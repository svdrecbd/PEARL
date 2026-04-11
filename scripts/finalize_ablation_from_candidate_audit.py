from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from src.pearl.io_utils import atomic_write_json


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize a stage1-only ablation by rescoring stage2 candidates")
    parser.add_argument("--ablation-dir", required=True)
    parser.add_argument("--esm2-device", default=os.environ.get("ESM2_DEVICE", "cuda"))
    parser.add_argument("--skip-finalized", action="store_true", default=True)
    parser.add_argument("--no-skip-finalized", action="store_false", dest="skip_finalized")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ablation_dir = Path(args.ablation_dir).expanduser().resolve()
    result = finalize_ablation_dir(
        ablation_dir=ablation_dir,
        esm2_device=args.esm2_device,
        skip_finalized=args.skip_finalized,
    )
    print(json.dumps(result, indent=2))


def finalize_ablation_dir(
    *,
    ablation_dir: Path,
    esm2_device: str,
    skip_finalized: bool = True,
) -> dict[str, Any]:
    metadata_path = ablation_dir / "metadata.json"
    report_path = ablation_dir / "report.json"
    summary_path = ablation_dir / "summary.json"
    candidate_audit_path = ablation_dir / "candidate_audit.json"

    if not metadata_path.exists():
        raise RuntimeError(f"Missing metadata.json in {ablation_dir}")
    if not candidate_audit_path.exists():
        raise RuntimeError(f"Missing candidate_audit.json in {ablation_dir}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    candidate_audit_payload = json.loads(candidate_audit_path.read_text(encoding="utf-8"))
    existing_report = load_json_if_exists(report_path)

    if (
        skip_finalized
        and summary_path.exists()
        and existing_report is not None
        and not bool(existing_report.get("skip_stage2_esm"))
    ):
        return {
            "status": "skipped",
            "reason": "already_finalized",
            "ablation_dir": str(ablation_dir),
            "summary_path": str(summary_path),
            "report_path": str(report_path),
        }

    configure_runtime_env(
        metadata=metadata,
        candidate_audit_payload=candidate_audit_payload,
        esm2_device=esm2_device,
    )

    local_proxy = importlib.import_module("local_proxy")
    tinker_main = importlib.import_module("main")
    run_ablation = importlib.import_module("scripts.run_ablation")
    petase_family = importlib.import_module("petase_family")

    records = candidate_audit_payload.get("records")
    if not isinstance(records, list):
        raise RuntimeError(f"candidate_audit.json in {ablation_dir} is missing a records list")

    top_k = int(candidate_audit_payload.get("second_stage_top_k") or metadata.get("second_stage_top_k") or 16)
    candidate_sample_count = int(
        candidate_audit_payload.get("candidate_sample_count") or metadata.get("candidate_sample_count") or 0
    )
    prompts_path = str(metadata.get("subset_path") or metadata.get("source_prompts_path") or "")
    reference_records_path = str(metadata.get("reference_records_path") or "")

    print(
        json.dumps(
            {
                "event": "finalize_start",
                "ablation_dir": str(ablation_dir),
                "record_count": len(records),
                "top_k": top_k,
                "esm2_device": esm2_device,
            }
        ),
        flush=True,
    )
    print(json.dumps({"event": "prewarm_esm2", **local_proxy.prewarm_esm2_model()}), flush=True)

    rescored_records = finalize_candidate_audit_records(
        records=records,
        top_k=top_k,
        candidate_sample_count=candidate_sample_count,
        tinker_main=tinker_main,
        petase_family=petase_family,
        local_proxy=local_proxy,
    )

    step_records = [record["step_record"] for record in rescored_records]
    updated_candidate_audit_records = [record["candidate_audit_record"] for record in rescored_records]

    report_payload = build_report_payload(
        metadata=metadata,
        candidate_audit_payload=candidate_audit_payload,
        existing_report=existing_report,
        prompts_path=prompts_path,
        reference_records_path=reference_records_path,
        step_records=step_records,
    )
    atomic_write_json(report_path, report_payload)

    candidate_audit_payload["skip_stage2_esm"] = False
    candidate_audit_payload["rescored_esm_device"] = esm2_device
    candidate_audit_payload["rescored_at_epoch"] = int(time.time())
    candidate_audit_payload["records"] = updated_candidate_audit_records
    atomic_write_json(candidate_audit_path, candidate_audit_payload)

    summary_payload = run_ablation.summarize_report(report_payload)
    summary_payload["name"] = str(metadata["name"])
    summary_payload["variant"] = str(metadata["variant"])
    summary_payload["model"] = str(metadata["model"])
    summary_payload["init_state_path"] = metadata.get("init_state_path")
    summary_payload["eval_only"] = bool(metadata.get("eval_only"))
    summary_payload["stage1_only"] = False
    summary_payload["prompt_count"] = int(metadata["prompt_count"])
    summary_payload["candidate_sample_count"] = candidate_sample_count
    summary_payload["second_stage_top_k"] = top_k
    summary_payload["plddt_gate_threshold"] = float(candidate_audit_payload.get("plddt_gate_threshold") or 85.0)
    summary_payload["second_stage_esm_weight"] = float(candidate_audit_payload.get("second_stage_esm_weight") or 0.0)
    summary_payload["second_stage_motif_weight"] = float(candidate_audit_payload.get("second_stage_motif_weight") or 0.0)
    summary_payload["second_stage_geometry_weight"] = float(
        candidate_audit_payload.get("second_stage_geometry_weight") or 0.0
    )
    summary_payload["second_stage_template_weight"] = float(
        candidate_audit_payload.get("second_stage_template_weight") or 0.0
    )
    summary_payload["seed"] = int(metadata["seed"])
    summary_payload["subset_path"] = prompts_path
    summary_payload["report_path"] = str(report_path)
    summary_payload["candidate_audit_path"] = str(candidate_audit_path)
    atomic_write_json(summary_path, summary_payload)

    return {
        "status": "finalized",
        "ablation_dir": str(ablation_dir),
        "summary_path": str(summary_path),
        "report_path": str(report_path),
        "candidate_audit_path": str(candidate_audit_path),
        "records": len(step_records),
        "average_reward": report_payload["average_reward"],
        "functional_bridge_steps": summary_payload["functional_bridge_steps"],
        "family_faithful_bridge_steps": summary_payload["family_faithful_bridge_steps"],
    }


def finalize_candidate_audit_records(
    *,
    records: list[dict[str, Any]],
    top_k: int,
    candidate_sample_count: int,
    tinker_main: Any,
    petase_family: Any,
    local_proxy: Any,
) -> list[dict[str, Any]]:
    stage2_sequences: list[str] = []
    for record in records:
        for candidate in select_stage2_candidates(record.get("candidates"), top_k=top_k):
            sequence = str(candidate.get("extracted_sequence") or "")
            if sequence:
                stage2_sequences.append(sequence)

    score_map = score_sequences(stage2_sequences=stage2_sequences, local_proxy=local_proxy)
    rescored_records: list[dict[str, Any]] = []
    for record in records:
        rescored_records.append(
            recompute_record(
                record=record,
                score_map=score_map,
                top_k=top_k,
                candidate_sample_count=candidate_sample_count,
                tinker_main=tinker_main,
                petase_family=petase_family,
            )
        )
    return rescored_records


def score_sequences(*, stage2_sequences: list[str], local_proxy: Any) -> dict[str, float]:
    unique_sequences = list(dict.fromkeys(sequence for sequence in stage2_sequences if sequence))
    if not unique_sequences:
        return {}
    scores = local_proxy.get_esm2_plddt_scores(unique_sequences)
    return {sequence: float(score) for sequence, score in zip(unique_sequences, scores)}


def recompute_record(
    *,
    record: dict[str, Any],
    score_map: dict[str, float],
    top_k: int,
    candidate_sample_count: int,
    tinker_main: Any,
    petase_family: Any,
) -> dict[str, Any]:
    step = int(record.get("step", 0))
    prompt = str(record.get("prompt") or "")
    sequence_prompt = str(record.get("sequence_prompt") or "")
    candidates = normalize_candidates(record.get("candidates"))
    if not candidates:
        raise RuntimeError(f"Step {step} is missing candidates")

    stage2_candidates = select_stage2_candidates(candidates, top_k=top_k)
    stage2_by_rank: dict[int, dict[str, Any]] = {int(candidate["stage1_rank"]): candidate for candidate in stage2_candidates}

    updated_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate = dict(candidate)
        candidate["in_stage2_pool"] = False
        candidate["stage2_rank"] = None
        candidate["stage2_score"] = 0.0
        candidate["raw_esm_score"] = 0.0
        updated_candidates.append(candidate)

    for candidate in updated_candidates:
        stage2_candidate = stage2_by_rank.get(int(candidate["stage1_rank"]))
        if stage2_candidate is None:
            continue
        sequence = str(stage2_candidate.get("extracted_sequence") or "")
        raw_esm_score = float(score_map.get(sequence, 0.0))
        candidate["in_stage2_pool"] = True
        candidate["raw_esm_score"] = raw_esm_score
        candidate["stage2_score"] = float(
            tinker_main.compute_second_stage_score(
                raw_esm_score=raw_esm_score,
                motif_strength=float(candidate["sequence_quality"]["motif_strength"]),
                geometry_score=float(candidate["sequence_quality"]["geometry_score"]),
                template_penalty=float(candidate["sequence_quality"]["template_penalty"]),
            )
        )

    rescored_stage2 = [candidate for candidate in updated_candidates if candidate["in_stage2_pool"]]
    rescored_stage2.sort(
        key=lambda candidate: (
            float(candidate["stage2_score"] or 0.0),
            float(candidate["stage1_score"] or 0.0),
        ),
        reverse=True,
    )
    for rank, candidate in enumerate(rescored_stage2, start=1):
        candidate["stage2_rank"] = rank

    selected = (
        next(
            (
                candidate
                for candidate in rescored_stage2
                if candidate["sequence_quality"]["is_trainable"]
                and float(candidate["raw_esm_score"]) >= float(tinker_main.PLDDT_GATE_THRESHOLD)
            ),
            None,
        )
        or next((candidate for candidate in rescored_stage2 if candidate["sequence_quality"]["is_trainable"]), None)
        or rescored_stage2[0]
    )

    selection_metadata = {
        "stage1_rank": int(selected["stage1_rank"]),
        "stage2_rank": int(selected["stage2_rank"]) if selected["stage2_rank"] is not None else None,
        "stage2_pool_size": len(rescored_stage2),
        "stage2_score": round(float(selected["stage2_score"] or 0.0), 4),
    }

    updated_candidates_payload: list[dict[str, Any]] = []
    for candidate in updated_candidates:
        updated_candidates_payload.append(
            build_rescored_candidate_audit_entry(
                candidate=candidate,
                is_selected=candidate is selected,
                tinker_main=tinker_main,
            )
        )

    step_record = build_step_record(
        step=step,
        prompt=prompt,
        selected=selected,
        selection_metadata=selection_metadata,
        candidate_sample_count=candidate_sample_count,
        tinker_main=tinker_main,
        petase_family=petase_family,
    )

    return {
        "candidate_audit_record": {
            "step": step,
            "prompt": prompt,
            "sequence_prompt": sequence_prompt,
            "selection_metadata": selection_metadata,
            "candidates": updated_candidates_payload,
        },
        "step_record": step_record,
    }


def build_step_record(
    *,
    step: int,
    prompt: str,
    selected: dict[str, Any],
    selection_metadata: dict[str, Any],
    candidate_sample_count: int,
    tinker_main: Any,
    petase_family: Any,
) -> dict[str, Any]:
    quality = selected["sequence_quality"]
    family_evaluation = selected["family_evaluation"]
    raw_esm_score = float(selected["raw_esm_score"])
    family_reward_info = (
        petase_family.compute_family_reward(family_evaluation)
        if family_evaluation is not None
        else {"family_reward": 0.0, "family_reward_components": {}}
    )
    reward_info = tinker_main.compute_training_reward(
        step=step,
        raw_esm_score=raw_esm_score,
        quality=quality,
        family_evaluation=family_evaluation,
    )
    reward = float(reward_info["reward"])
    eligible_for_training = bool(
        quality["is_trainable"]
        and int(selected.get("sample_token_count") or 0) > 0
        and reward > 0.0
    )
    return {
        "step": step,
        "prompt": prompt,
        "sample_text": selected["sample_text"],
        "extracted_sequence": selected["extracted_sequence"],
        "reward": reward,
        "selection_metadata": selection_metadata,
        "reward_components": {
            "reward_mode": reward_info["reward_mode"],
            "esm_reward": raw_esm_score,
            "esm_gate_pass": reward_info["esm_gate_pass"],
            "functional_bridge_passes": reward_info["functional_bridge_passes"],
            "family_faithful_bridge_passes": reward_info["family_faithful_bridge_passes"],
            "family_reward": family_reward_info["family_reward"],
            "rl_family_reward": reward_info["rl_family_reward"],
            "dense_family_reward": reward_info["dense_family_reward"],
            "dense_reward_components": reward_info["dense_reward_components"],
            "template_penalty": reward_info["template_penalty"],
            "motif_spam_penalty": reward_info["motif_spam_penalty"],
            "tandem_repeat_penalty": reward_info["tandem_repeat_penalty"],
            "local_entropy_penalty": reward_info["local_entropy_penalty"],
            "kmer_uniqueness_ratio": reward_info["kmer_uniqueness_ratio"],
            "motif_count": reward_info["motif_count"],
            "max_tandem_repeat_similarity": reward_info["max_tandem_repeat_similarity"],
            "min_local_window_entropy": reward_info["min_local_window_entropy"],
            "family_reward_components": family_reward_info["family_reward_components"],
        },
        "sample_token_count": int(selected.get("sample_token_count") or 0),
        "sample_attempts": candidate_sample_count,
        "sequence_quality": quality,
        "family_evaluation": family_evaluation,
        "training_skipped": not eligible_for_training,
        "update_performed": False,
    }


def build_rescored_candidate_audit_entry(*, candidate: dict[str, Any], is_selected: bool, tinker_main: Any) -> dict[str, Any]:
    quality = candidate["sequence_quality"]
    family_evaluation = candidate["family_evaluation"]
    catalytic_geometry = family_evaluation["catalytic_geometry"] if family_evaluation is not None else None
    raw_esm_score = float(candidate["raw_esm_score"])
    bridge_flags = tinker_main.compute_bridge_flags(
        quality=quality,
        family_evaluation=family_evaluation,
        raw_esm_score=raw_esm_score,
    )
    return {
        "selected": is_selected,
        "sample_text": candidate["sample_text"],
        "extracted_sequence": candidate["extracted_sequence"],
        "sample_token_count": int(candidate.get("sample_token_count") or 0),
        "stage1_rank": int(candidate["stage1_rank"]),
        "stage1_score": round(float(candidate["stage1_score"]), 4),
        "in_stage2_pool": bool(candidate["in_stage2_pool"]),
        "stage2_rank": int(candidate["stage2_rank"]) if candidate["stage2_rank"] is not None else None,
        "stage2_score": round(float(candidate["stage2_score"] or 0.0), 4),
        "hard_gate_pass": bool(quality["hard_gate_pass"]),
        "soft_floor_pass": bool(quality["soft_floor_pass"]),
        "is_trainable": bool(quality["is_trainable"]),
        "trainability_reason": str(quality.get("trainability_reason", "")),
        "soft_score": float(quality["soft_score"]),
        "soft_trainability_threshold": float(quality["soft_trainability_threshold"]),
        "soft_trainability_margin": float(quality["soft_trainability_margin"]),
        "length": int(quality["length"]),
        "aa_only_ratio": float(quality["aa_only_ratio"]),
        "entropy": float(quality["entropy"]),
        "unique_residues": int(quality["unique_residues"]),
        "dominant_residue_fraction": float(quality["dominant_residue_fraction"]),
        "kmer_uniqueness_ratio": float(quality["kmer_uniqueness_ratio"]),
        "min_local_window_entropy": float(quality["min_local_window_entropy"]),
        "max_tandem_repeat_similarity": float(quality["max_tandem_repeat_similarity"]),
        "template_penalty": float(quality["template_penalty"]),
        "motif_count": int(quality["motif_count"]),
        "motif_strength": float(quality["motif_strength"]),
        "dyad_strength": float(quality["dyad_strength"]),
        "ser_asp_strength": float(quality["ser_asp_strength"]),
        "ser_his_strength": float(quality["ser_his_strength"]),
        "geometry_score": float(quality["geometry_score"]),
        "raw_esm_score": raw_esm_score,
        "sequence_quality": quality,
        "family_evaluation": family_evaluation,
        **bridge_flags,
        "best_gap_error": family_evaluation["catalytic_geometry"]["best_gap_error"] if family_evaluation else None,
        "ser_asp_gap_error": catalytic_geometry["ser_asp_gap_error"] if catalytic_geometry else None,
        "asp_his_gap_error": catalytic_geometry["asp_his_gap_error"] if catalytic_geometry else None,
        "ser_his_gap_error": catalytic_geometry["ser_his_gap_error"] if catalytic_geometry else None,
        "ser_asp_dyad_passes": catalytic_geometry["ser_asp_dyad_passes"] if catalytic_geometry else False,
        "ser_his_dyad_passes": catalytic_geometry["ser_his_dyad_passes"] if catalytic_geometry else False,
        "passes_core_screen": bool(family_evaluation["passes_core_screen"]) if family_evaluation else False,
    }


def normalize_candidates(raw_candidates: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_candidates, list):
        return []
    normalized: list[dict[str, Any]] = []
    for candidate in raw_candidates:
        if not isinstance(candidate, dict):
            continue
        sequence_quality = candidate.get("sequence_quality")
        family_evaluation = candidate.get("family_evaluation")
        if not isinstance(sequence_quality, dict):
            raise RuntimeError("Candidate audit entry is missing sequence_quality; regenerate with full-candidate audit patch")
        normalized.append(
            {
                "sample_text": str(candidate.get("sample_text") or ""),
                "extracted_sequence": str(candidate.get("extracted_sequence") or ""),
                "sample_token_count": int(candidate.get("sample_token_count") or 0),
                "stage1_rank": int(candidate.get("stage1_rank") or 0),
                "stage1_score": float(candidate.get("stage1_score") or 0.0),
                "sequence_quality": sequence_quality,
                "family_evaluation": family_evaluation if isinstance(family_evaluation, dict) else None,
            }
        )
    normalized.sort(key=lambda candidate: int(candidate["stage1_rank"]) or 10**9)
    return normalized


def select_stage2_candidates(raw_candidates: Any, *, top_k: int) -> list[dict[str, Any]]:
    candidates = normalize_candidates(raw_candidates)
    stage2_candidates = [
        candidate
        for candidate in candidates
        if candidate["sequence_quality"]["hard_gate_pass"]
        and candidate["sequence_quality"]["soft_floor_pass"]
        and candidate["extracted_sequence"]
    ][:top_k]
    if not stage2_candidates:
        stage2_candidates = candidates[:1]
    return stage2_candidates


def build_report_payload(
    *,
    metadata: dict[str, Any],
    candidate_audit_payload: dict[str, Any],
    existing_report: dict[str, Any] | None,
    prompts_path: str,
    reference_records_path: str,
    step_records: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = dict(existing_report or {})
    payload.setdefault("requested_model_name", "Qwen/Qwen3-8B")
    payload["base_model"] = str(metadata["model"])
    payload.setdefault("supported_models", [])
    payload["checkpoint_name"] = sanitize_name(str(metadata["name"]))
    payload["checkpoint_path"] = metadata.get("init_state_path")
    payload["init_state_path"] = metadata.get("init_state_path")
    payload["eval_only"] = bool(metadata.get("eval_only"))
    payload["steps"] = len(step_records)
    payload["prompt_count"] = int(metadata["prompt_count"])
    payload["prompts_path"] = prompts_path
    payload["reference_records_path"] = reference_records_path
    payload["prompt_variant"] = str(metadata["variant"])
    payload["candidate_sample_count"] = int(candidate_audit_payload.get("candidate_sample_count") or metadata["candidate_sample_count"])
    payload["second_stage_top_k"] = int(candidate_audit_payload.get("second_stage_top_k") or 0)
    payload["plddt_gate_threshold"] = float(candidate_audit_payload.get("plddt_gate_threshold") or 0.0)
    payload["second_stage_esm_weight"] = float(candidate_audit_payload.get("second_stage_esm_weight") or 0.0)
    payload["second_stage_motif_weight"] = float(candidate_audit_payload.get("second_stage_motif_weight") or 0.0)
    payload["second_stage_geometry_weight"] = float(candidate_audit_payload.get("second_stage_geometry_weight") or 0.0)
    payload["second_stage_template_weight"] = float(candidate_audit_payload.get("second_stage_template_weight") or 0.0)
    payload["skip_stage2_esm"] = False
    payload["average_reward"] = (
        sum(float(record["reward"]) for record in step_records) / len(step_records) if step_records else 0.0
    )
    payload["records"] = step_records
    return payload


def configure_runtime_env(
    *,
    metadata: dict[str, Any],
    candidate_audit_payload: dict[str, Any],
    esm2_device: str,
) -> None:
    os.environ["ESM2_BACKEND"] = "torch"
    os.environ["ESM2_DEVICE"] = esm2_device
    os.environ["TINKER_SECOND_STAGE_ESM_WEIGHT"] = str(candidate_audit_payload.get("second_stage_esm_weight") or 0.0)
    os.environ["TINKER_SECOND_STAGE_MOTIF_WEIGHT"] = str(candidate_audit_payload.get("second_stage_motif_weight") or 0.0)
    os.environ["TINKER_SECOND_STAGE_GEOMETRY_WEIGHT"] = str(candidate_audit_payload.get("second_stage_geometry_weight") or 0.0)
    os.environ["TINKER_SECOND_STAGE_TEMPLATE_WEIGHT"] = str(
        candidate_audit_payload.get("second_stage_template_weight") or 0.0
    )
    os.environ["TINKER_SECOND_STAGE_TOP_K"] = str(candidate_audit_payload.get("second_stage_top_k") or 0)
    os.environ["TINKER_PLDDT_GATE_THRESHOLD"] = str(candidate_audit_payload.get("plddt_gate_threshold") or 85.0)
    os.environ["PROMPT_VARIANT"] = str(metadata.get("variant") or "baseline")
    os.environ["TINKER_INIT_STATE_PATH"] = str(metadata.get("init_state_path") or "")


def load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def sanitize_name(value: str) -> str:
    chars: list[str] = []
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("-")
    sanitized = "".join(chars).strip("-")
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized or "run"


if __name__ == "__main__":
    main()
