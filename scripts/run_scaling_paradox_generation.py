#!/usr/bin/env python3
"""Generate one immutable, resumable scaling-paradox structural panel from Tinker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.esm_proxy import inspect_raw_sequence_text  # noqa: E402
from pearl.io_utils import atomic_write_json  # noqa: E402
from pearl.model_rendering import RendererContract, build_generation_input  # noqa: E402


DEFAULT_CONFIG = ROOT / "configs" / "experiments" / "scaling_paradox_structural_v1.json"
ALLOWED_ARMS = {"base", "true", "shuffled", "data_exposure", "adapter_rescue"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def source_training_identity(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.arm == "base":
        return None
    contract_arg = getattr(args, "source_run_contract", None)
    report_arg = getattr(args, "source_training_report", None)
    lineage_arg = getattr(args, "source_checkpoint_lineage", None)
    if not contract_arg or not report_arg or not lineage_arg:
        raise ValueError(
            "trained structural generation requires source run contract, terminal report, and checkpoint lineage"
        )
    contract_path = repo_path(contract_arg)
    report_path = repo_path(report_arg)
    lineage_path = repo_path(lineage_arg)
    contract = read_json(contract_path)
    report = read_json(report_path)
    lineage = read_json(lineage_path)
    if report.get("contract_sha") != contract.get("run_contract_sha"):
        raise RuntimeError("structural source report differs from its run contract")
    expected = {
        "model": args.model,
        "arm": args.arm,
        "training_seed": int(args.training_seed),
    }
    if any(contract.get(key) != value for key, value in expected.items()):
        raise RuntimeError("structural source cell differs from requested model/arm/seed")
    if lineage.get("contract_sha") != contract.get("run_contract_sha"):
        raise RuntimeError("structural source checkpoint lineage has the wrong contract")
    matches = [
        row for row in lineage.get("checkpoints", [])
        if int(row.get("step", -1)) == int(args.checkpoint_step)
        and row.get("state_path") == args.checkpoint_path
    ]
    if len(matches) != 1:
        raise RuntimeError("requested structural checkpoint is absent or non-unique in source lineage")
    if int(args.checkpoint_step) == int(contract["max_steps"]):
        if report.get("checkpoint_path") != args.checkpoint_path or not matches[0].get("terminal"):
            raise RuntimeError("terminal structural checkpoint differs from source report/lineage")
    return {
        "source_run_key": contract["run_key"],
        "source_run_contract_sha": contract["run_contract_sha"],
        "source_run_contract_file_sha256": sha256_file(contract_path),
        "source_training_report_file_sha256": sha256_file(report_path),
        "source_checkpoint_lineage_file_sha256": sha256_file(lineage_path),
    }


def message_text(message: Any) -> str:
    content = message.get("content", "") if isinstance(message, dict) else ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return str(content or "")


def build_contract(args: argparse.Namespace, config: dict[str, Any], panel_path: Path) -> dict[str, Any]:
    training_config = read_json(repo_path(config["training_config"]))
    model_rows = {str(row["model"]): row for row in training_config["models"]}
    if args.model not in model_rows:
        raise ValueError(f"model {args.model!r} is outside the frozen scaling-paradox model set")
    if args.arm not in ALLOWED_ARMS:
        raise ValueError(f"arm {args.arm!r} is not supported")
    all_steps = set(config["checkpoints"]["primary"]) | set(config["checkpoints"]["secondary_timecourse"])
    if args.checkpoint_step not in all_steps:
        raise ValueError(f"checkpoint step {args.checkpoint_step} is outside the frozen evaluation schedule")
    if args.arm == "base" and (args.checkpoint_step != 0 or args.checkpoint_path):
        raise ValueError("base evaluation requires checkpoint step 0 and no checkpoint path")
    if args.arm != "base" and (args.checkpoint_step == 0 or not args.checkpoint_path):
        raise ValueError("trained evaluation requires a nonzero checkpoint step and --checkpoint-path")
    renderer = str(training_config["common"]["renderer"])
    source_identity = source_training_identity(args)
    identity = {
        "campaign_id": config["campaign_id"],
        "structural_contract": config["contract"],
        "structural_config_sha256": sha256_file(repo_path(args.config)),
        "prompt_panel_sha256": sha256_file(panel_path),
        "model": args.model,
        "model_tag": model_rows[args.model]["tag"],
        "renderer": renderer,
        "renderer_contract_fingerprint": RendererContract(name=renderer, model_name=args.model).fingerprint(),
        "arm": args.arm,
        "training_seed": int(args.training_seed),
        "checkpoint_step": int(args.checkpoint_step),
        "checkpoint_path": args.checkpoint_path,
        "sampling": config["sampling"],
        "source_training": source_identity,
    }
    identity["generation_contract_sha"] = sha256_value(identity)
    identity["run_key"] = (
        f"struct-{model_rows[args.model]['tag']}-{args.arm}-seed{args.training_seed}-"
        f"step{args.checkpoint_step}-{identity['generation_contract_sha'][:10]}"
    )
    return identity


def validate_resume(payload: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("contract") != contract:
        raise RuntimeError("existing generation report belongs to a different immutable contract")
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        raise RuntimeError("existing generation report has invalid candidates")
    return [dict(row) for row in candidates if isinstance(row, dict) and row.get("candidate_id")]


def candidate_id(contract_sha: str, prompt_id: str, sample_seed: int) -> str:
    return "cand-" + hashlib.sha256(
        f"{contract_sha}\0{prompt_id}\0{sample_seed}".encode("utf-8")
    ).hexdigest()[:20]


def report_payload(
    *,
    contract: dict[str, Any],
    panel: list[dict[str, Any]],
    sample_seeds: list[int],
    candidates: list[dict[str, Any]],
    status: str,
) -> dict[str, Any]:
    expected = len(panel) * len(sample_seeds)
    valid = sum(bool(row.get("valid_sequence")) for row in candidates)
    return {
        "contract": contract,
        "status": status,
        "expected_candidate_count": expected,
        "completed_candidate_count": len(candidates),
        "valid_candidate_count": valid,
        "invalid_candidate_count": len(candidates) - valid,
        "complete": len(candidates) == expected,
        "candidates": candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--model", required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--training-seed", type=int, required=True)
    parser.add_argument("--checkpoint-step", type=int, required=True)
    parser.add_argument("--checkpoint-path")
    parser.add_argument("--source-run-contract")
    parser.add_argument("--source-training-report")
    parser.add_argument("--source-checkpoint-lineage")
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "scaling_paradox_v1" / "structural"))
    parser.add_argument("--shape-only", action="store_true")
    args = parser.parse_args()

    config = read_json(repo_path(args.config))
    panel_path = repo_path(config["prompt_panel"])
    panel = read_jsonl(panel_path)
    if len(panel) != int(config["prompt_count"]):
        raise RuntimeError("prompt panel count differs from the frozen structural config")
    if len({row["prompt_id"] for row in panel}) != len(panel):
        raise RuntimeError("prompt panel contains duplicate prompt IDs")
    contract = build_contract(args, config, panel_path)
    output_dir = repo_path(args.output_dir) / str(contract["run_key"])
    report_path = output_dir / "generation_report.json"
    contract_path = output_dir / "generation_contract.json"
    sample_seeds = [int(value) for value in config["sampling"]["sample_seeds"]]
    candidates: list[dict[str, Any]] = []
    if report_path.exists():
        candidates = validate_resume(read_json(report_path), contract)
    output_dir.mkdir(parents=True, exist_ok=True)
    if contract_path.exists() and read_json(contract_path) != contract:
        raise RuntimeError("generation contract path is already occupied by another contract")
    atomic_write_json(contract_path, contract)
    if args.shape_only:
        payload = report_payload(
            contract=contract,
            panel=panel,
            sample_seeds=sample_seeds,
            candidates=candidates,
            status="shape_validated",
        )
        atomic_write_json(report_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if not os.environ.get("TINKER_API_KEY"):
        raise SystemExit("TINKER_API_KEY is required for generation")

    import tinker
    from tinker import types
    from tinker_cookbook.tokenizer_utils import get_tokenizer

    service_client = tinker.ServiceClient(
        user_metadata={
            "pearl_task": "scaling_paradox_structural_generation",
            "campaign_id": str(contract["campaign_id"]),
            "run_key": str(contract["run_key"]),
            "contract_sha": str(contract["generation_contract_sha"]),
        }
    )
    sampling_client = service_client.create_sampling_client(
        model_path=args.checkpoint_path,
        base_model=args.model,
    )
    tokenizer = get_tokenizer(args.model)
    renderer_contract = RendererContract(name=str(contract["renderer"]), model_name=args.model)
    completed = {str(row["candidate_id"]) for row in candidates}
    observed_sequences = {str(row.get("sequence") or "") for row in candidates if row.get("sequence")}

    for prompt_row in panel:
        prompt_input, renderer = build_generation_input(str(prompt_row["prompt"]), tokenizer, renderer_contract)
        for sample_seed in sample_seeds:
            cid = candidate_id(str(contract["generation_contract_sha"]), str(prompt_row["prompt_id"]), sample_seed)
            if cid in completed:
                continue
            sampling_params = types.SamplingParams(
                max_tokens=int(config["sampling"]["max_tokens"]),
                seed=sample_seed,
                temperature=float(config["sampling"]["temperature"]),
                top_p=float(config["sampling"]["top_p"]),
                top_k=int(config["sampling"]["top_k"]),
                stop=renderer.get_stop_sequences() if renderer is not None else (["\n"] if config["sampling"]["stop_on_newline"] else []),
            )
            response = sampling_client.sample(
                prompt=prompt_input,
                num_samples=1,
                sampling_params=sampling_params,
            ).result()
            sampled = response.sequences[0]
            if renderer is not None:
                parsed, termination = renderer.parse_response(sampled.tokens)
                raw_text = message_text(parsed).strip()
                termination_reason = str(termination)
            else:
                raw_text = tokenizer.decode(sampled.tokens, skip_special_tokens=False).strip()
                termination_reason = "raw"
            inspection = inspect_raw_sequence_text(raw_text)
            sequence = str(inspection.get("sequence") or "")
            duplicate = bool(sequence and sequence in observed_sequences)
            valid = bool(sequence and not inspection.get("error") and not duplicate)
            row = {
                "candidate_id": cid,
                "prompt_id": prompt_row["prompt_id"],
                "target_length": prompt_row["target_length"],
                "length_bin": prompt_row["length_bin"],
                "sample_seed": sample_seed,
                "raw_text": raw_text,
                "sequence": sequence,
                "sequence_sha256": hashlib.sha256(sequence.encode("ascii")).hexdigest() if sequence else None,
                "sequence_length": len(sequence),
                "generation_error": inspection.get("error"),
                "duplicate_sequence": duplicate,
                "valid_sequence": valid,
                "termination_reason": termination_reason,
            }
            candidates.append(row)
            completed.add(cid)
            if sequence:
                observed_sequences.add(sequence)
            atomic_write_json(
                report_path,
                report_payload(
                    contract=contract,
                    panel=panel,
                    sample_seeds=sample_seeds,
                    candidates=candidates,
                    status="running",
                ),
            )
            print(json.dumps({"candidate_id": cid, "valid": valid, "completed": len(candidates)}), flush=True)

    payload = report_payload(
        contract=contract,
        panel=panel,
        sample_seeds=sample_seeds,
        candidates=candidates,
        status="complete",
    )
    atomic_write_json(report_path, payload)
    print(json.dumps({key: value for key, value in payload.items() if key != "candidates"}, indent=2))


if __name__ == "__main__":
    main()
