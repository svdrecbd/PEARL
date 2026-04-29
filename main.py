from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import tinker
from tinker import types

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.checkpoints import load_sampler_checkpoint_map, persist_sampler_checkpoint_mapping
from pearl.io_utils import load_json_object
from pearl.openai_compat_sampler import OpenAICompatibleSamplingClient
from pearl.reports import (
    ReportContext,
    extract_contiguous_step_records,
    persist_progress,
    validate_resume_report_payload,
)
from pearl.run_records import build_candidate_audit_record, build_step_record

from pearl.esm_proxy import (
    extract_amino_acid_sequence,
    get_esm2_plddt_score,
    inspect_raw_sequence_text,
    prewarm_esm2_model,
)
from pearl.family import (
    NOVELTY_IDENTITY_THRESHOLD,
    compute_family_reward,
    compute_family_stats,
    evaluate_candidate,
    load_reference_records,
)


def parse_optional_int_env(name: str) -> int | None:
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        return None
    return int(raw_value)


REQUESTED_MODEL_NAME = "Qwen/Qwen3-8B"
FALLBACK_MODEL_NAMES = (
    "Qwen/Qwen3-4B-Instruct-2507",
    "Qwen/Qwen3-8B-Base",
    "meta-llama/Llama-3.2-1B",
)
SAMPLER_BACKEND = os.environ.get("PEARL_SAMPLER_BACKEND", "tinker").strip().lower() or "tinker"
OPENAI_BASE_URL = os.environ.get("PEARL_OPENAI_BASE_URL", "").strip()
OPENAI_API_KEY = os.environ.get("PEARL_OPENAI_API_KEY", "").strip()
OPENAI_MODEL_NAME = os.environ.get("PEARL_OPENAI_MODEL", "").strip()
OPENAI_TOKENIZER_NAME = os.environ.get("PEARL_OPENAI_TOKENIZER", "").strip()
OPENAI_TIMEOUT_SECONDS = float(os.environ.get("PEARL_OPENAI_TIMEOUT_SECONDS", "120.0"))
OPENAI_MAX_RETRIES = max(1, int(os.environ.get("PEARL_OPENAI_MAX_RETRIES", "3")))
OPENAI_TRUST_REMOTE_CODE = os.environ.get("PEARL_OPENAI_TRUST_REMOTE_CODE", "1").strip().lower() not in {"0", "false", "no"}
CHECKPOINT_NAME = os.environ.get("CHECKPOINT_NAME", "dry_run_lora_v1")
REPORT_PATH = os.environ.get("REPORT_PATH")
CANDIDATE_AUDIT_PATH = os.environ.get("CANDIDATE_AUDIT_PATH")
PROMPTS_PATH = os.environ.get("PROMPTS_PATH")
REFERENCE_RECORDS_PATH = os.environ.get("REFERENCE_RECORDS_PATH")
INIT_STATE_PATH = os.environ.get("TINKER_INIT_STATE_PATH")
EVAL_ONLY = os.environ.get("TINKER_EVAL_ONLY", "0") == "1"
RESUME_PROGRESS = os.environ.get("TINKER_RESUME_PROGRESS", "0") == "1"
PROMPT_COUNT = int(os.environ.get("DRY_RUN_PROMPT_COUNT", "10"))
MAX_TOKENS = int(os.environ.get("TINKER_MAX_TOKENS", "320"))
CANDIDATE_SAMPLE_COUNT = int(os.environ.get("TINKER_CANDIDATE_SAMPLE_COUNT", "8"))
SECOND_STAGE_TOP_K = int(os.environ.get("TINKER_SECOND_STAGE_TOP_K", "4"))
SECOND_STAGE_ESM_WEIGHT = float(os.environ.get("TINKER_SECOND_STAGE_ESM_WEIGHT", "0.2"))
SECOND_STAGE_MOTIF_WEIGHT = float(os.environ.get("TINKER_SECOND_STAGE_MOTIF_WEIGHT", "0.2"))
SECOND_STAGE_GEOMETRY_WEIGHT = float(os.environ.get("TINKER_SECOND_STAGE_GEOMETRY_WEIGHT", "0.6"))
SECOND_STAGE_TEMPLATE_WEIGHT = float(os.environ.get("TINKER_SECOND_STAGE_TEMPLATE_WEIGHT", "0.15"))
PLDDT_GATE_THRESHOLD = float(os.environ.get("TINKER_PLDDT_GATE_THRESHOLD", "85.0"))
SAMPLING_TEMPERATURE = float(os.environ.get("SAMPLING_TEMPERATURE", "0.4"))
SAMPLING_TOP_P = float(os.environ.get("SAMPLING_TOP_P", "0.95"))
SAMPLING_TOP_K = int(os.environ.get("SAMPLING_TOP_K", "50"))
SAMPLING_SEED_BASE = parse_optional_int_env("TINKER_SAMPLING_SEED")
RL_LEARNING_RATE = float(os.environ.get("RL_LEARNING_RATE", "1e-4"))
RL_LOSS_FN = os.environ.get("TINKER_RL_LOSS_FN", "importance_sampling")
RL_REWARD_MODE = os.environ.get("TINKER_RL_REWARD_MODE", "dense_family")
PPO_CLIP_LOW_THRESHOLD = float(os.environ.get("TINKER_PPO_CLIP_LOW_THRESHOLD", "0.9"))
PPO_CLIP_HIGH_THRESHOLD = float(os.environ.get("TINKER_PPO_CLIP_HIGH_THRESHOLD", "1.1"))
BRIDGE_TIER2_REWARD = float(os.environ.get("TINKER_BRIDGE_TIER2_REWARD", "1.0"))
BRIDGE_TIER1_BONUS = float(os.environ.get("TINKER_BRIDGE_TIER1_BONUS", "5.0"))
KMER_DIVERSITY_K = int(os.environ.get("KMER_DIVERSITY_K", "4"))
MOTIF_SPAM_ALLOWED_COUNT = int(os.environ.get("MOTIF_SPAM_ALLOWED_COUNT", "1"))
MOTIF_SPAM_PENALTY_FLOOR = float(os.environ.get("MOTIF_SPAM_PENALTY_FLOOR", "0.05"))
MOTIF_SPAM_PENALTY_EXPONENT = float(os.environ.get("MOTIF_SPAM_PENALTY_EXPONENT", "1.35"))
TANDEM_REPEAT_BLOCK_MIN = int(os.environ.get("TANDEM_REPEAT_BLOCK_MIN", "16"))
TANDEM_REPEAT_BLOCK_MAX = int(os.environ.get("TANDEM_REPEAT_BLOCK_MAX", "24"))
TANDEM_REPEAT_BLOCK_STEP = int(os.environ.get("TANDEM_REPEAT_BLOCK_STEP", "4"))
TANDEM_REPEAT_MAX_GAP = int(os.environ.get("TANDEM_REPEAT_MAX_GAP", "6"))
TANDEM_REPEAT_SIMILARITY_THRESHOLD = float(os.environ.get("TANDEM_REPEAT_SIMILARITY_THRESHOLD", "0.85"))
TANDEM_REPEAT_PENALTY_FLOOR = float(os.environ.get("TANDEM_REPEAT_PENALTY_FLOOR", "0.05"))
LOCAL_ENTROPY_WINDOW = int(os.environ.get("LOCAL_ENTROPY_WINDOW", "20"))
LOCAL_ENTROPY_MIN_THRESHOLD = float(os.environ.get("LOCAL_ENTROPY_MIN_THRESHOLD", "2.7"))
LOCAL_ENTROPY_PENALTY_FLOOR = float(os.environ.get("LOCAL_ENTROPY_PENALTY_FLOOR", "0.2"))
DENSE_MOTIF_REWARD_WEIGHT = float(os.environ.get("DENSE_MOTIF_REWARD_WEIGHT", "1.0"))
DENSE_SER_ASP_REWARD_WEIGHT = float(os.environ.get("DENSE_SER_ASP_REWARD_WEIGHT", "3.0"))
DENSE_SER_HIS_REWARD_WEIGHT = float(os.environ.get("DENSE_SER_HIS_REWARD_WEIGHT", "0.75"))
DENSE_TRIAD_REWARD_WEIGHT = float(os.environ.get("DENSE_TRIAD_REWARD_WEIGHT", "10.0"))
DENSE_ASPARTATE_PRESENCE_WEIGHT = float(os.environ.get("DENSE_ASPARTATE_PRESENCE_WEIGHT", "2.0"))
DENSE_INCOMPLETE_TRIAD_PENALTY_WEIGHT = float(os.environ.get("DENSE_INCOMPLETE_TRIAD_PENALTY_WEIGHT", "1.5"))
TEMPLATE_PENALTY_SCORE_WEIGHT = float(os.environ.get("TEMPLATE_PENALTY_SCORE_WEIGHT", "120.0"))
SER_ASP_DYAD_SCORE_SCALE = float(os.environ.get("SER_ASP_DYAD_SCORE_SCALE", "18.0"))
SER_HIS_DYAD_SCORE_SCALE = float(os.environ.get("SER_HIS_DYAD_SCORE_SCALE", "18.0"))
TRIAD_SCORE_SCALE = float(os.environ.get("TRIAD_SCORE_SCALE", "12.0"))
PROMPT_VARIANT = os.environ.get("PROMPT_VARIANT", "baseline")
PROMPT_MOTIF_HINT_COUNT = int(os.environ.get("PROMPT_MOTIF_HINT_COUNT", "4"))
CONTROL_TARGET_TAG = os.environ.get("CONTROL_TARGET_TAG", "").strip()
CONTROL_BLUEPRINT_TAG = os.environ.get("CONTROL_BLUEPRINT_TAG", "").strip()
CONTROL_BLUEPRINT_RATIOS = os.environ.get("CONTROL_BLUEPRINT_RATIOS", "").strip()
TIMING_ENABLED = os.environ.get("TINKER_TIMING", "0") == "1"
PREWARM_ESM2 = os.environ.get("TINKER_PREWARM_ESM2", "1") == "1"
SKIP_STAGE2_ESM = os.environ.get("TINKER_SKIP_STAGE2_ESM", "0") == "1"
SAMPLER_CHECKPOINT_MAP_PATH = Path(
    os.environ.get("TINKER_SAMPLER_CHECKPOINT_MAP_PATH", ".tinker_sampler_checkpoint_map.json")
)
REPORT_CONTEXT = ReportContext(
    init_state_path=INIT_STATE_PATH,
    eval_only=EVAL_ONLY,
    prompt_variant=PROMPT_VARIANT,
    candidate_sample_count=CANDIDATE_SAMPLE_COUNT,
    second_stage_top_k=SECOND_STAGE_TOP_K,
    plddt_gate_threshold=PLDDT_GATE_THRESHOLD,
    second_stage_esm_weight=SECOND_STAGE_ESM_WEIGHT,
    second_stage_motif_weight=SECOND_STAGE_MOTIF_WEIGHT,
    second_stage_geometry_weight=SECOND_STAGE_GEOMETRY_WEIGHT,
    second_stage_template_weight=SECOND_STAGE_TEMPLATE_WEIGHT,
    skip_stage2_esm=SKIP_STAGE2_ESM,
    prompts_path=PROMPTS_PATH,
)
MIN_VALID_SEQUENCE_LENGTH = 120
MAX_VALID_SEQUENCE_LENGTH = 360
MIN_SEQUENCE_ENTROPY = 3.4
MAX_DOMINANT_RESIDUE_FRACTION = 0.3
MIN_UNIQUE_RESIDUES = 16
MIN_AA_ONLY_RATIO = 0.98
SOFT_ENTROPY_FLOOR = 3.05
SOFT_UNIQUE_RESIDUES_FLOOR = 11
SOFT_MAX_DOMINANT_RESIDUE_FRACTION = 0.26
SOFT_TRAINABILITY_BASE_THRESHOLD = 88.0
SOFT_TRAINABILITY_FLOOR = 60.0
ENTROPY_DEFICIT_WEIGHT = 35.0
UNIQUE_RESIDUE_DEFICIT_WEIGHT = 6.0
DOMINANT_RESIDUE_EXCESS_WEIGHT = 180.0
MOTIF_STRENGTH_DISCOUNT_WEIGHT = 12.0
GEOMETRY_SCORE_DISCOUNT_WEIGHT = 20.0
MAX_NORMALIZED_SCORE = 1.0
MAX_PERCENT_SCORE = 100.0
QUALITY_SCORE_LENGTH_TARGET = 200
QUALITY_SCORE_AA_RATIO_WEIGHT = 100.0
QUALITY_SCORE_ENTROPY_WEIGHT = 10.0
QUALITY_SCORE_UNIQUE_RESIDUES_WEIGHT = 2.0
QUALITY_SCORE_DOMINANT_RESIDUE_WEIGHT = 50.0
QUALITY_SCORE_INVALID_SEQUENCE_PENALTY = 250.0
MERGE_SCORE_VALID_AMINO_ACIDS_BONUS = 40.0
MERGE_SCORE_LENGTH_BAND_BONUS = 45.0
MERGE_SCORE_FAMILY_MOTIF_BONUS = 90.0
MERGE_SCORE_GEOMETRY_BONUS = 140.0
MERGE_SCORE_NOVELTY_BONUS = 35.0
MERGE_SCORE_PER_SERINE_MOTIF_BONUS = 5.0
MERGE_SCORE_SERINE_MOTIF_BONUS_CAP = 4
MERGE_SCORE_GAP_ALIGNMENT_BONUS_CAP = 25.0
MERGE_SCORE_STRONG_NOVELTY_THRESHOLD = 0.9
MERGE_SCORE_STRONG_NOVELTY_PENALTY = 60.0
MERGE_SCORE_SOFT_NOVELTY_PENALTY_SCALE = 100.0
MERGE_SCORE_DYAD_WEIGHT = 50.0
MERGE_SCORE_SER_ASP_WEIGHT = 35.0
MERGE_SCORE_ASPARTATE_HIT_BONUS = 12.0
MERGE_SCORE_SER_HIS_STRENGTH_THRESHOLD = 0.45
MERGE_SCORE_SER_ASP_WEAK_THRESHOLD = 0.15
MERGE_SCORE_SER_HIS_MISALIGNMENT_PENALTY = 35.0
SECOND_STAGE_ESM_SCORE_NORMALIZER = 100.0
MOTIF_STRENGTH_NON_FAMILY_BASE = 0.45
MOTIF_STRENGTH_REPEAT_DECAY_WEIGHT = 0.75
GEOMETRY_SCORE_WINDOW_HIT_WEIGHT = 0.05
GEOMETRY_SCORE_SER_ASP_WEIGHT = 0.4
GEOMETRY_SCORE_SER_HIS_WEIGHT = 0.1
GEOMETRY_SCORE_TRIAD_WEIGHT = 0.45
DYAD_SCORE_SER_ASP_WEIGHT = 0.75
DYAD_SCORE_SER_HIS_WEIGHT = 0.25
BASELINE_SEQUENCE_PROMPT_TEMPLATE = """<protein_design>
Request: {request}
Constraint: output exactly one sequence in uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY
Constraint: output only the raw amino acid sequence with no markdown, whitespace, punctuation, or explanation
Constraint: produce a complete full-length protein close to the requested length and do not stop early with a partial fragment
Constraint: avoid tandem repeats and low-complexity residue patterns
Format: SEQUENCE=<sequence>
SEQUENCE="""

MOTIF_PRIOR_SEQUENCE_PROMPT_TEMPLATE = """<protein_design>
Request: {request}
Constraint: output exactly one sequence in uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY
Constraint: output only the raw amino acid sequence with no markdown, whitespace, punctuation, or explanation
Constraint: produce a complete full-length protein close to the requested length and do not stop early with a partial fragment
Constraint: avoid tandem repeats and low-complexity residue patterns
Constraint: prefer a PETase/cutinase-like nucleophile motif chosen from {motif_hint}
Constraint: place catalytic serine around {serine_window}, aspartate around {aspartate_window}, and histidine around {histidine_window} of sequence length
Format: SEQUENCE=<sequence>
SEQUENCE="""

SOFT_MOTIF_PRIOR_SEQUENCE_PROMPT_TEMPLATE = """<protein_design>
Request: {request}
Constraint: output exactly one sequence in uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY
Constraint: output only the raw amino acid sequence with no markdown, whitespace, punctuation, or explanation
Constraint: produce a complete full-length protein close to the requested length and do not stop early with a partial fragment
Constraint: avoid tandem repeats and low-complexity residue patterns
Constraint: keep the sequence protein-like and naturally diverse across its full length
Hint: PETase/cutinase-family proteins often include a nucleophile motif such as {motif_hint}
Hint: if using a serine motif, prefer a single plausible family-like motif rather than repeated copies
Format: SEQUENCE=<sequence>
SEQUENCE="""

SOFT_MOTIF_PRIOR_CONTROLLED_SEQUENCE_PROMPT_TEMPLATE = """<protein_design>
Request: {request}
Constraint: output exactly one sequence in uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY
Constraint: output only the raw amino acid sequence with no markdown, whitespace, punctuation, or explanation
Constraint: produce a complete full-length protein close to the requested length and do not stop early with a partial fragment
Constraint: avoid tandem repeats and low-complexity residue patterns
Constraint: keep the sequence protein-like and naturally diverse across its full length
Constraint: if the request includes a [Target: ...] control tag, follow it exactly
Constraint: if the request includes a [Blueprint: ...] tag, satisfy those residue positions as closely as possible
Hint: PETase/cutinase-family proteins often include a nucleophile motif such as {motif_hint}
Format: SEQUENCE=<sequence>
SEQUENCE="""


def emit_timing_event(
    *,
    phase: str,
    status: str,
    started_at: float | None = None,
    step: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    if not TIMING_ENABLED:
        return

    payload: dict[str, Any] = {
        "timing": True,
        "phase": phase,
        "status": status,
    }
    if step is not None:
        payload["step"] = step
    if started_at is not None:
        payload["elapsed_seconds"] = round(time.perf_counter() - started_at, 4)
    if extra:
        payload.update(extra)
    print(json.dumps(payload), flush=True)


def main() -> None:
    startup_started_at = time.perf_counter()
    service_client: tinker.ServiceClient | None = None
    if using_openai_compatible_sampler():
        phase_started_at = time.perf_counter()
        emit_timing_event(phase="resolve_base_model", status="start")
        base_model, supported_models = resolve_local_base_model()
        emit_timing_event(
            phase="resolve_base_model",
            status="end",
            started_at=phase_started_at,
            extra={"supported_model_count": len(supported_models), "sampler_backend": SAMPLER_BACKEND},
        )
    else:
        phase_started_at = time.perf_counter()
        emit_timing_event(phase="service_client_init", status="start")
        service_client = tinker.ServiceClient()
        emit_timing_event(phase="service_client_init", status="end", started_at=phase_started_at)

        phase_started_at = time.perf_counter()
        emit_timing_event(phase="resolve_base_model", status="start")
        base_model, supported_models = resolve_base_model(service_client)
        emit_timing_event(
            phase="resolve_base_model",
            status="end",
            started_at=phase_started_at,
            extra={"supported_model_count": len(supported_models)},
        )
    runtime = initialize_runtime(
        service_client=service_client,
        base_model=base_model,
    )
    training_client = runtime["training_client"]
    sampling_client = runtime["sampling_client"]
    tokenizer = runtime["tokenizer"]

    phase_started_at = time.perf_counter()
    emit_timing_event(phase="load_prompts", status="start")
    prompts = load_prompts()
    emit_timing_event(phase="load_prompts", status="end", started_at=phase_started_at, extra={"prompt_count": len(prompts)})

    phase_started_at = time.perf_counter()
    emit_timing_event(phase="resolve_reference_records_path", status="start")
    reference_records_path = resolve_reference_records_path()
    emit_timing_event(phase="resolve_reference_records_path", status="end", started_at=phase_started_at)
    reference_records: list[dict[str, Any]] = []
    family_stats: dict[str, Any] | None = None
    if reference_records_path is not None:
        phase_started_at = time.perf_counter()
        emit_timing_event(phase="load_reference_records", status="start")
        reference_records = load_reference_records(reference_records_path)
        emit_timing_event(
            phase="load_reference_records",
            status="end",
            started_at=phase_started_at,
            extra={"reference_record_count": len(reference_records)},
        )

        phase_started_at = time.perf_counter()
        emit_timing_event(phase="compute_family_stats", status="start")
        family_stats = compute_family_stats(reference_records)
        emit_timing_event(phase="compute_family_stats", status="end", started_at=phase_started_at)

    if PREWARM_ESM2 and SECOND_STAGE_TOP_K > 0 and not SKIP_STAGE2_ESM:
        phase_started_at = time.perf_counter()
        emit_timing_event(phase="prewarm_esm2_model", status="start")
        esm2_info = prewarm_esm2_model()
        emit_timing_event(
            phase="prewarm_esm2_model",
            status="end",
            started_at=phase_started_at,
            extra=esm2_info,
        )
    adam_params = types.AdamParams(learning_rate=RL_LEARNING_RATE, beta1=0.9, beta2=0.95, eps=1e-8)
    print(
        json.dumps(
            {
                "base_model": base_model,
                "prompt_count": len(prompts),
                "prompts_path": PROMPTS_PATH,
                "reference_records_path": str(reference_records_path) if reference_records_path is not None else None,
                "candidate_sample_count": CANDIDATE_SAMPLE_COUNT,
                "second_stage_top_k": SECOND_STAGE_TOP_K,
                "plddt_gate_threshold": PLDDT_GATE_THRESHOLD,
                "skip_stage2_esm": SKIP_STAGE2_ESM,
                "rl_learning_rate": RL_LEARNING_RATE,
                "rl_loss_fn": RL_LOSS_FN,
                "rl_reward_mode": RL_REWARD_MODE,
                "init_state_path": INIT_STATE_PATH,
                "eval_only": EVAL_ONLY,
                "prompt_variant": PROMPT_VARIANT,
            }
        ),
        flush=True,
    )

    report_path = Path(REPORT_PATH) if REPORT_PATH else Path(f"{CHECKPOINT_NAME}_report.json")
    candidate_audit_path = Path(CANDIDATE_AUDIT_PATH) if CANDIDATE_AUDIT_PATH else None
    (
        step_records,
        candidate_audit_records,
        resume_start_step,
    ) = maybe_load_eval_resume_state(
        report_path=report_path,
        candidate_audit_path=candidate_audit_path,
        prompts=prompts,
    )
    phase_started_at = time.perf_counter()
    emit_timing_event(phase="persist_progress_initial", status="start")
    persist_progress(
        report_path=report_path,
        candidate_audit_path=candidate_audit_path,
        requested_model_name=REQUESTED_MODEL_NAME,
        base_model=base_model,
        supported_models=supported_models,
        checkpoint_name=CHECKPOINT_NAME,
        checkpoint_path=INIT_STATE_PATH,
        reference_records_path=reference_records_path,
        prompts=prompts,
        step_records=step_records,
        candidate_audit_records=candidate_audit_records,
        context=REPORT_CONTEXT,
    )
    emit_timing_event(phase="persist_progress_initial", status="end", started_at=phase_started_at)
    emit_timing_event(phase="startup_total", status="end", started_at=startup_started_at)
    sampling_client_needs_refresh = training_client is not None and sampling_client is None
    for step, prompt in enumerate(prompts[resume_start_step:], start=resume_start_step):
        sequence_prompt = build_sequence_prompt(prompt, family_stats)
        sampling_seed = None if SAMPLING_SEED_BASE is None else SAMPLING_SEED_BASE + step
        sampling_params = types.SamplingParams(
            max_tokens=resolve_max_tokens(prompt),
            seed=sampling_seed,
            temperature=SAMPLING_TEMPERATURE,
            top_p=SAMPLING_TOP_P,
            top_k=SAMPLING_TOP_K,
            stop=["\n"],
        )
        if training_client is not None:
            sampling_client = prepare_sampling_client(
                training_client=training_client,
                sampling_client=sampling_client,
                refresh=sampling_client_needs_refresh,
                step=step,
            )
            sampling_client_needs_refresh = False
        assert sampling_client is not None
        (
            sampled_text,
            extracted_sequence,
            sampled_sequence,
            quality,
            family_evaluation,
            raw_esm_score,
            selection_metadata,
            candidate_audit,
            attempts,
        ) = sample_valid_sequence(
            step=step,
            tokenizer=tokenizer,
            sampling_client=sampling_client,
            sampling_params=sampling_params,
            sequence_prompt=sequence_prompt,
            reference_records=reference_records,
            family_stats=family_stats,
        )
        phase_started_at = time.perf_counter()
        emit_timing_event(phase="encode_prompt_input", status="start", step=step)
        prompt_input = types.ModelInput.from_ints(
            tokenizer.encode(sequence_prompt, add_special_tokens=False)
        )
        emit_timing_event(phase="encode_prompt_input", status="end", started_at=phase_started_at, step=step)
        family_reward_info = compute_family_reward(family_evaluation) if family_evaluation is not None else {
            "family_reward": 0.0,
            "family_reward_components": {},
        }
        reward_info = compute_training_reward(
            step=step,
            raw_esm_score=raw_esm_score,
            quality=quality,
            family_evaluation=family_evaluation,
        )
        reward = reward_info["reward"]
        print(
            json.dumps(
                {
                    "step": step,
                    "max_tokens": sampling_params.max_tokens,
                    "length": quality["length"],
                    "combined_score": quality["combined_score"],
                    "soft_score": quality["soft_score"],
                    "soft_threshold": quality["soft_trainability_threshold"],
                    "hard_gate_pass": quality["hard_gate_pass"],
                    "soft_floor_pass": quality["soft_floor_pass"],
                    "is_trainable": quality["is_trainable"],
                    "stage1_rank": selection_metadata["stage1_rank"],
                    "stage2_rank": selection_metadata["stage2_rank"],
                    "stage2_pool_size": selection_metadata["stage2_pool_size"],
                    "stage2_score": selection_metadata["stage2_score"],
                    "has_family_serine_motif": (
                        family_evaluation["has_family_serine_motif"] if family_evaluation is not None else None
                    ),
                    "catalytic_geometry_passes": (
                        family_evaluation["catalytic_geometry"]["passes"] if family_evaluation is not None else None
                    ),
                    "raw_esm_score": raw_esm_score,
                    "esm_gate_pass": reward_info["esm_gate_pass"],
                    "family_reward": family_reward_info["family_reward"],
                    "rl_family_reward": reward_info["rl_family_reward"],
                    "dense_family_reward": reward_info["dense_family_reward"],
                    "template_penalty": reward_info["template_penalty"],
                    "motif_spam_penalty": reward_info["motif_spam_penalty"],
                    "tandem_repeat_penalty": reward_info["tandem_repeat_penalty"],
                    "local_entropy_penalty": reward_info["local_entropy_penalty"],
                    "reward": reward,
                }
            ),
            flush=True,
        )
        if CANDIDATE_AUDIT_PATH:
            candidate_audit_records.append(
                build_candidate_audit_record(
                    step=step,
                    prompt=prompt,
                    sequence_prompt=sequence_prompt,
                    selection_metadata=selection_metadata,
                    candidate_audit=candidate_audit,
                )
            )
        eligible_for_training = bool(quality["is_trainable"] and sampled_sequence.tokens and reward > 0.0)
        if not eligible_for_training:
            step_records.append(
                build_step_record(
                    step=step,
                    prompt=prompt,
                    sampled_text=sampled_text,
                    extracted_sequence=extracted_sequence,
                    reward=reward,
                    selection_metadata=selection_metadata,
                    raw_esm_score=raw_esm_score,
                    reward_info=reward_info,
                    family_reward_info=family_reward_info,
                    quality=quality,
                    family_evaluation=family_evaluation,
                    sample_token_count=len(sampled_sequence.tokens),
                    sample_attempts=attempts,
                    training_skipped=True,
                    update_performed=False,
                )
            )
            persist_progress(
                report_path=report_path,
                candidate_audit_path=candidate_audit_path,
                requested_model_name=REQUESTED_MODEL_NAME,
                base_model=base_model,
                supported_models=supported_models,
                checkpoint_name=CHECKPOINT_NAME,
                checkpoint_path=INIT_STATE_PATH,
                reference_records_path=reference_records_path,
                prompts=prompts,
                step_records=step_records,
                candidate_audit_records=candidate_audit_records,
                context=REPORT_CONTEXT,
            )
            continue

        if EVAL_ONLY:
            step_records.append(
                build_step_record(
                    step=step,
                    prompt=prompt,
                    sampled_text=sampled_text,
                    extracted_sequence=extracted_sequence,
                    reward=reward,
                    selection_metadata=selection_metadata,
                    raw_esm_score=raw_esm_score,
                    reward_info=reward_info,
                    family_reward_info=family_reward_info,
                    quality=quality,
                    family_evaluation=family_evaluation,
                    sample_token_count=len(sampled_sequence.tokens),
                    sample_attempts=attempts,
                    training_skipped=False,
                    update_performed=False,
                )
            )
            persist_progress(
                report_path=report_path,
                candidate_audit_path=candidate_audit_path,
                requested_model_name=REQUESTED_MODEL_NAME,
                base_model=base_model,
                supported_models=supported_models,
                checkpoint_name=CHECKPOINT_NAME,
                checkpoint_path=INIT_STATE_PATH,
                reference_records_path=reference_records_path,
                prompts=prompts,
                step_records=step_records,
                candidate_audit_records=candidate_audit_records,
                context=REPORT_CONTEXT,
            )
            continue

        datum = build_policy_gradient_datum(
            prompt_input=prompt_input,
            sampled_tokens=sampled_sequence.tokens,
            sampled_logprobs=sampled_sequence.logprobs,
            reward=scale_reward_for_loss(reward),
        )

        forward_backward_future = training_client.forward_backward(
            [datum],
            loss_fn=RL_LOSS_FN,
            loss_fn_config=build_loss_fn_config(),
        )
        optim_step_future = training_client.optim_step(adam_params)
        forward_backward_result = forward_backward_future.result()
        optim_step_result = optim_step_future.result()

        step_records.append(
            build_step_record(
                step=step,
                prompt=prompt,
                sampled_text=sampled_text,
                extracted_sequence=extracted_sequence,
                reward=reward,
                selection_metadata=selection_metadata,
                raw_esm_score=raw_esm_score,
                reward_info=reward_info,
                family_reward_info=family_reward_info,
                quality=quality,
                family_evaluation=family_evaluation,
                sample_token_count=len(sampled_sequence.tokens),
                sample_attempts=attempts,
                training_skipped=False,
                update_performed=True,
                forward_backward_metrics=forward_backward_result.metrics,
                optim_step_metrics=optim_step_result.metrics,
            )
        )
        persist_progress(
            report_path=report_path,
            candidate_audit_path=candidate_audit_path,
            requested_model_name=REQUESTED_MODEL_NAME,
            base_model=base_model,
            supported_models=supported_models,
            checkpoint_name=CHECKPOINT_NAME,
            checkpoint_path=INIT_STATE_PATH,
            reference_records_path=reference_records_path,
            prompts=prompts,
            step_records=step_records,
            candidate_audit_records=candidate_audit_records,
            context=REPORT_CONTEXT,
        )
        sampling_client_needs_refresh = True

    checkpoint_path = INIT_STATE_PATH
    if not EVAL_ONLY:
        assert training_client is not None
        save_result = training_client.save_state(CHECKPOINT_NAME).result()
        checkpoint_path = save_result.path
    report = persist_progress(
        report_path=report_path,
        candidate_audit_path=candidate_audit_path,
        requested_model_name=REQUESTED_MODEL_NAME,
        base_model=base_model,
        supported_models=supported_models,
        checkpoint_name=CHECKPOINT_NAME,
        checkpoint_path=checkpoint_path,
        reference_records_path=reference_records_path,
        prompts=prompts,
        step_records=step_records,
        candidate_audit_records=candidate_audit_records,
        context=REPORT_CONTEXT,
    )
    print(
        json.dumps(
            {
                "checkpoint_path": checkpoint_path,
                "average_reward": report["average_reward"],
                "steps": report["steps"],
                "report_path": str(report_path),
            }
        ),
        flush=True,
    )


def create_training_client(
    *,
    service_client: tinker.ServiceClient,
    base_model: str,
) -> tinker.TrainingClient:
    if INIT_STATE_PATH:
        return service_client.create_training_client_from_state(path=INIT_STATE_PATH)
    return service_client.create_lora_training_client(base_model=base_model, rank=8)


def initialize_runtime(
    *,
    service_client: tinker.ServiceClient | None,
    base_model: str,
) -> dict[str, tinker.TrainingClient | tinker.SamplingClient | object | None]:
    if using_openai_compatible_sampler():
        if not EVAL_ONLY:
            raise RuntimeError("PEARL_SAMPLER_BACKEND=openai_compatible only supports eval-only runs")
        phase_started_at = time.perf_counter()
        emit_timing_event(phase="create_eval_sampling_client", status="start")
        sampling_client = OpenAICompatibleSamplingClient(
            base_url=OPENAI_BASE_URL,
            model_name=base_model,
            tokenizer_name=OPENAI_TOKENIZER_NAME or base_model,
            api_key=OPENAI_API_KEY or None,
            timeout_seconds=OPENAI_TIMEOUT_SECONDS,
            max_retries=OPENAI_MAX_RETRIES,
            trust_remote_code=OPENAI_TRUST_REMOTE_CODE,
        )
        emit_timing_event(
            phase="create_eval_sampling_client",
            status="end",
            started_at=phase_started_at,
            extra={"source": "openai_compatible", "base_url": OPENAI_BASE_URL},
        )
        tokenizer = sampling_client.get_tokenizer()
        return {
            "training_client": None,
            "sampling_client": sampling_client,
            "tokenizer": tokenizer,
        }

    if EVAL_ONLY:
        assert service_client is not None
        sampling_client = create_eval_sampling_client(
            service_client=service_client,
            base_model=base_model,
        )
        if sampling_client is not None:
            tokenizer = get_sampling_tokenizer(sampling_client=sampling_client)
            return {
                "training_client": None,
                "sampling_client": sampling_client,
                "tokenizer": tokenizer,
            }

    phase_started_at = time.perf_counter()
    emit_timing_event(phase="create_training_client", status="start")
    assert service_client is not None
    training_client = create_training_client(service_client=service_client, base_model=base_model)
    emit_timing_event(phase="create_training_client", status="end", started_at=phase_started_at)
    tokenizer = get_training_tokenizer(training_client=training_client)
    return {
        "training_client": training_client,
        "sampling_client": None,
        "tokenizer": tokenizer,
    }


def create_eval_sampling_client(
    *,
    service_client: tinker.ServiceClient,
    base_model: str,
) -> tinker.SamplingClient | None:
    sampling_target = resolve_eval_sampling_target(
        service_client=service_client,
        base_model=base_model,
    )
    if sampling_target is None:
        return None

    phase_started_at = time.perf_counter()
    emit_timing_event(phase="create_eval_sampling_client", status="start")
    sampling_client = service_client.create_sampling_client(
        model_path=sampling_target["model_path"],
        base_model=sampling_target["base_model"],
    )
    emit_timing_event(
        phase="create_eval_sampling_client",
        status="end",
        started_at=phase_started_at,
        extra={"source": sampling_target["source"]},
    )
    return sampling_client


def resolve_eval_sampling_target(
    *,
    service_client: tinker.ServiceClient,
    base_model: str,
) -> dict[str, str | None] | None:
    if not INIT_STATE_PATH:
        emit_timing_event(
            phase="resolve_eval_sampling_target",
            status="end",
            extra={"source": "base_model"},
        )
        return {
            "model_path": None,
            "base_model": base_model,
            "source": "base_model",
        }

    parsed_path = types.ParsedCheckpointTinkerPath.from_tinker_path(INIT_STATE_PATH)
    if parsed_path.checkpoint_type == "sampler":
        emit_timing_event(
            phase="resolve_eval_sampling_target",
            status="end",
            extra={"source": "sampler_checkpoint"},
        )
        return {
            "model_path": INIT_STATE_PATH,
            "base_model": None,
            "source": "sampler_checkpoint",
        }

    mapped_sampler_path = get_mapped_sampler_checkpoint_path(
        service_client=service_client,
        training_checkpoint_path=INIT_STATE_PATH,
    )
    if mapped_sampler_path is not None:
        emit_timing_event(
            phase="resolve_eval_sampling_target",
            status="end",
            extra={"source": "sampler_checkpoint_map"},
        )
        return {
            "model_path": mapped_sampler_path,
            "base_model": None,
            "source": "sampler_checkpoint_map",
        }

    phase_started_at = time.perf_counter()
    emit_timing_event(phase="resolve_eval_sampling_target", status="start")
    expected_sampler_path = INIT_STATE_PATH.replace("/weights/", "/sampler_weights/", 1)
    rest_client = service_client.create_rest_client()
    try:
        checkpoints = rest_client.list_checkpoints(parsed_path.training_run_id).result().checkpoints
    except Exception:
        # Public cross-account checkpoints can be loaded by exact path without
        # granting permission to list the owning training run.
        matching_sampler_checkpoint = None
    else:
        matching_sampler_checkpoint = next(
            (
                checkpoint
                for checkpoint in checkpoints
                if checkpoint.checkpoint_type == "sampler" and checkpoint.tinker_path == expected_sampler_path
            ),
            None,
        )
    if matching_sampler_checkpoint is None:
        created_sampler_path = create_matching_sampler_checkpoint(
            service_client=service_client,
            base_model=base_model,
            training_checkpoint_path=INIT_STATE_PATH,
            expected_sampler_path=expected_sampler_path,
        )
        persist_sampler_checkpoint_mapping(
            SAMPLER_CHECKPOINT_MAP_PATH,
            training_checkpoint_path=INIT_STATE_PATH,
            sampler_checkpoint_path=created_sampler_path,
        )
        emit_timing_event(
            phase="resolve_eval_sampling_target",
            status="end",
            started_at=phase_started_at,
            extra={"source": "created_sampler_checkpoint", "found_sampler_checkpoint": True},
        )
        return {
            "model_path": created_sampler_path,
            "base_model": None,
            "source": "created_sampler_checkpoint",
        }

    emit_timing_event(
        phase="resolve_eval_sampling_target",
        status="end",
        started_at=phase_started_at,
        extra={"source": "matching_sampler_checkpoint", "found_sampler_checkpoint": True},
    )
    return {
        "model_path": matching_sampler_checkpoint.tinker_path,
        "base_model": None,
        "source": "matching_sampler_checkpoint",
    }


def get_mapped_sampler_checkpoint_path(
    *,
    service_client: tinker.ServiceClient,
    training_checkpoint_path: str,
) -> str | None:
    checkpoint_map = load_sampler_checkpoint_map(SAMPLER_CHECKPOINT_MAP_PATH)
    sampler_checkpoint_path = checkpoint_map.get(training_checkpoint_path)
    if sampler_checkpoint_path is None:
        return None
    if sampler_checkpoint_exists(
        service_client=service_client,
        sampler_checkpoint_path=sampler_checkpoint_path,
    ):
        return sampler_checkpoint_path
    return None


def sampler_checkpoint_exists(
    *,
    service_client: tinker.ServiceClient,
    sampler_checkpoint_path: str,
) -> bool:
    parsed_path = types.ParsedCheckpointTinkerPath.from_tinker_path(sampler_checkpoint_path)
    if parsed_path.checkpoint_type != "sampler":
        return False
    rest_client = service_client.create_rest_client()
    try:
        checkpoints = rest_client.list_checkpoints(parsed_path.training_run_id).result().checkpoints
    except Exception:
        # The checkpoint map may point at a private sampler checkpoint from a
        # different account; treat inaccessible mappings as stale.
        return False
    return any(
        checkpoint.checkpoint_type == "sampler" and checkpoint.tinker_path == sampler_checkpoint_path
        for checkpoint in checkpoints
    )


def create_matching_sampler_checkpoint(
    *,
    service_client: tinker.ServiceClient,
    base_model: str,
    training_checkpoint_path: str,
    expected_sampler_path: str,
) -> str:
    parsed_path = types.ParsedCheckpointTinkerPath.from_tinker_path(training_checkpoint_path)
    sampler_checkpoint_name = parsed_path.checkpoint_id.split("/", 1)[1]
    phase_started_at = time.perf_counter()
    emit_timing_event(
        phase="create_matching_sampler_checkpoint",
        status="start",
        extra={"expected_sampler_path": expected_sampler_path},
    )
    training_client = create_training_client(service_client=service_client, base_model=base_model)
    save_result = training_client.save_weights_for_sampler(sampler_checkpoint_name).result()
    emit_timing_event(
        phase="create_matching_sampler_checkpoint",
        status="end",
        started_at=phase_started_at,
        extra={"sampler_checkpoint_path": save_result.path},
    )
    return save_result.path


def get_sampling_tokenizer(
    *,
    sampling_client: tinker.SamplingClient,
) -> object:
    phase_started_at = time.perf_counter()
    emit_timing_event(phase="get_tokenizer", status="start")
    tokenizer = sampling_client.get_tokenizer()
    emit_timing_event(phase="get_tokenizer", status="end", started_at=phase_started_at)
    return tokenizer


def get_training_tokenizer(
    *,
    training_client: tinker.TrainingClient,
) -> object:
    phase_started_at = time.perf_counter()
    emit_timing_event(phase="get_tokenizer", status="start")
    tokenizer = training_client.get_tokenizer()
    emit_timing_event(phase="get_tokenizer", status="end", started_at=phase_started_at)
    return tokenizer


def prepare_sampling_client(
    *,
    training_client: tinker.TrainingClient,
    sampling_client: tinker.SamplingClient | None,
    refresh: bool,
    step: int,
) -> tinker.SamplingClient:
    phase_started_at = time.perf_counter()
    emit_timing_event(
        phase="prepare_sampling_client",
        status="start",
        step=step,
        extra={"refresh": refresh},
    )
    if not refresh and sampling_client is not None:
        emit_timing_event(
            phase="prepare_sampling_client",
            status="end",
            started_at=phase_started_at,
            step=step,
            extra={"refresh": False, "reused": True},
        )
        return sampling_client

    refresh_started_at = time.perf_counter()
    emit_timing_event(phase="save_weights_and_get_sampling_client", status="start", step=step)
    refreshed_sampling_client = training_client.save_weights_and_get_sampling_client()
    emit_timing_event(
        phase="save_weights_and_get_sampling_client",
        status="end",
        started_at=refresh_started_at,
        step=step,
    )
    emit_timing_event(
        phase="prepare_sampling_client",
        status="end",
        started_at=phase_started_at,
        step=step,
        extra={"refresh": True, "reused": False},
    )
    return refreshed_sampling_client


def resolve_base_model(service_client: tinker.ServiceClient) -> tuple[str, list[str]]:
    capabilities = service_client.get_server_capabilities()
    supported_models = [model.model_name for model in capabilities.supported_models]
    explicit_override = os.environ.get("TINKER_BASE_MODEL")
    if explicit_override:
        if explicit_override not in supported_models:
            raise RuntimeError(
                f"TINKER_BASE_MODEL={explicit_override!r} is not supported by this backend"
            )
        return explicit_override, supported_models

    if REQUESTED_MODEL_NAME in supported_models:
        return REQUESTED_MODEL_NAME, supported_models

    for candidate in FALLBACK_MODEL_NAMES:
        if candidate in supported_models:
            return candidate, supported_models

    raise RuntimeError("No supported fallback base model is available for the dry run")


def using_openai_compatible_sampler() -> bool:
    return SAMPLER_BACKEND in {"openai", "openai_compatible", "local_openai"}


def resolve_local_base_model() -> tuple[str, list[str]]:
    if not OPENAI_BASE_URL:
        raise RuntimeError("PEARL_OPENAI_BASE_URL is required for PEARL_SAMPLER_BACKEND=openai_compatible")
    base_model = OPENAI_MODEL_NAME or os.environ.get("TINKER_BASE_MODEL", "").strip() or REQUESTED_MODEL_NAME
    return base_model, [base_model]


def load_prompts() -> list[str]:
    if not PROMPTS_PATH:
        return ["Generate thermophilic PETase sequence:"] * PROMPT_COUNT

    prompts: list[str] = []
    with Path(PROMPTS_PATH).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            prompt = record.get("prompt")
            if isinstance(prompt, str) and prompt:
                prompts.append(prompt)
            if len(prompts) >= PROMPT_COUNT:
                break

    if not prompts:
        raise RuntimeError(f"PROMPTS_PATH={PROMPTS_PATH!r} did not yield any prompts")
    return prompts


def resolve_reference_records_path() -> Path | None:
    if REFERENCE_RECORDS_PATH:
        return Path(REFERENCE_RECORDS_PATH)
    if PROMPTS_PATH:
        prompt_path = Path(PROMPTS_PATH)
        sibling_records = prompt_path.with_name("petase_records.jsonl")
        if sibling_records.exists():
            return sibling_records
    default_records = Path("data/petase_family/petase_records.jsonl")
    if default_records.exists():
        return default_records
    return None


def resolve_max_tokens(prompt: str) -> int:
    length_hint = extract_length_hint(prompt)
    if length_hint is None:
        return MAX_TOKENS
    return max(160, min(MAX_TOKENS, int(length_hint * 0.78)))


def extract_length_hint(prompt: str) -> int | None:
    match = re.search(r"(?:near|around|about)\s+(\d+)\s*(?:aa|amino acids?)", prompt, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def combine_reward_scores(esm_reward: float, family_reward: float) -> float:
    return round((0.4 * esm_reward) + (0.6 * family_reward), 2)


def maybe_load_eval_resume_state(
    *,
    report_path: Path,
    candidate_audit_path: Path | None,
    prompts: list[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    if not RESUME_PROGRESS:
        return [], [], 0
    if not EVAL_ONLY:
        raise RuntimeError("TINKER_RESUME_PROGRESS is only supported for eval-only runs")
    if not report_path.exists():
        return [], [], 0

    report_payload = load_json_object(report_path)
    if report_payload is None:
        raise RuntimeError(f"Could not parse resume report: {report_path}")
    validate_resume_report_payload(
        report_payload=report_payload,
        prompts=prompts,
        report_path=report_path,
        context=REPORT_CONTEXT,
    )
    step_records = extract_contiguous_step_records(
        raw_records=report_payload.get("records"),
        prompt_count=len(prompts),
    )

    candidate_audit_records: list[dict[str, object]] = []
    if candidate_audit_path is not None and candidate_audit_path.exists():
        candidate_audit_payload = load_json_object(candidate_audit_path)
        if candidate_audit_payload is not None:
            candidate_audit_records = extract_contiguous_step_records(
                raw_records=candidate_audit_payload.get("records"),
                prompt_count=len(prompts),
            )
    if candidate_audit_records:
        candidate_audit_records = candidate_audit_records[: len(step_records)]

    print(
        json.dumps(
            {
                "resume_progress": True,
                "resumed_step_count": len(step_records),
                "prompt_count": len(prompts),
                "report_path": str(report_path),
            }
        ),
        flush=True,
    )
    return step_records, candidate_audit_records, len(step_records)
def sample_valid_sequence(
    *,
    step: int | None,
    tokenizer: object,
    sampling_client: Any,
    sampling_params: types.SamplingParams,
    sequence_prompt: str,
    reference_records: list[dict[str, Any]],
    family_stats: dict[str, Any] | None,
) -> tuple[
    str,
    str,
    types.SampledSequence,
    dict[str, float | int | bool],
    dict[str, Any] | None,
    float,
    dict[str, float | int | bool | None],
    list[dict[str, Any]],
    int,
]:
    candidates: list[dict[str, Any]] = []
    phase_started_at = time.perf_counter()
    emit_timing_event(phase="sample_prepare_prompt_input", status="start", step=step)
    prompt_input = None
    if not isinstance(sampling_client, OpenAICompatibleSamplingClient):
        prompt_input = types.ModelInput.from_ints(
            tokenizer.encode(sequence_prompt, add_special_tokens=False)
        )
    emit_timing_event(phase="sample_prepare_prompt_input", status="end", started_at=phase_started_at, step=step)

    phase_started_at = time.perf_counter()
    emit_timing_event(phase="sample_remote_sequences", status="start", step=step)
    if isinstance(sampling_client, OpenAICompatibleSamplingClient):
        sample_result = sampling_client.sample_text(
            prompt=sequence_prompt,
            num_samples=CANDIDATE_SAMPLE_COUNT,
            sampling_params=sampling_params,
        ).result()
    else:
        assert prompt_input is not None
        sample_result = sampling_client.sample(
            prompt=prompt_input,
            num_samples=CANDIDATE_SAMPLE_COUNT,
            sampling_params=sampling_params,
        ).result()
    emit_timing_event(
        phase="sample_remote_sequences",
        status="end",
        started_at=phase_started_at,
        step=step,
        extra={"sampled_sequence_count": len(sample_result.sequences), "sampler_backend": SAMPLER_BACKEND},
    )

    phase_started_at = time.perf_counter()
    emit_timing_event(phase="evaluate_stage1_candidates", status="start", step=step)
    for sampled_sequence in sample_result.sequences:
        if sampled_sequence.logprobs is None and not EVAL_ONLY:
            raise RuntimeError("Tinker sampling response did not include token logprobs")

        sampled_text = tokenizer.decode(sampled_sequence.tokens, skip_special_tokens=False).strip()

        # Aggressive extraction for 'chatty' or 'thinking' models
        if "SEQUENCE=" in sampled_text:
            sampled_text = sampled_text.split("SEQUENCE=")[-1].strip()
        elif "<think>" in sampled_text and "</think>" in sampled_text:
            # If think tags are present but SEQUENCE= is missing (e.g. truncated), try to extract from what remains
            import re
            sampled_text = re.sub(r"<think>.*?</think>", "", sampled_text, flags=re.DOTALL).strip()

        extracted_sequence = extract_amino_acid_sequence(sampled_text)
        quality = assess_sequence_quality(sampled_text, extracted_sequence)
        family_evaluation = (
            evaluate_candidate(
                sequence=extracted_sequence,
                family_stats=family_stats,
                reference_records=reference_records,
            )
            if family_stats is not None and reference_records and extracted_sequence
            else None
        )
        quality = merge_candidate_quality(quality, family_evaluation)
        candidates.append(
            {
                "sampled_text": sampled_text,
                "extracted_sequence": extracted_sequence,
                "sampled_sequence": sampled_sequence,
                "quality": quality,
                "family_evaluation": family_evaluation,
                "stage1_score": float(quality["combined_score"]),
                "raw_esm_score": 0.0,
                "stage2_score": None,
                "stage1_rank": None,
                "stage2_rank": None,
                "in_stage2_pool": False,
            }
        )
    emit_timing_event(
        phase="evaluate_stage1_candidates",
        status="end",
        started_at=phase_started_at,
        step=step,
        extra={"candidate_count": len(candidates)},
    )

    if not candidates:
        raise RuntimeError("Tinker sampling response did not include any sequences")

    phase_started_at = time.perf_counter()
    emit_timing_event(phase="rank_stage1_candidates", status="start", step=step)
    sorted_stage1 = sorted(candidates, key=lambda candidate: candidate["stage1_score"], reverse=True)
    for rank, candidate in enumerate(sorted_stage1, start=1):
        candidate["stage1_rank"] = rank
    emit_timing_event(phase="rank_stage1_candidates", status="end", started_at=phase_started_at, step=step)

    stage2_candidates = [
        candidate
        for candidate in sorted_stage1
        if candidate["quality"]["hard_gate_pass"]
        and candidate["quality"]["soft_floor_pass"]
        and candidate["extracted_sequence"]
    ][:SECOND_STAGE_TOP_K]
    if not stage2_candidates:
        stage2_candidates = sorted_stage1[:1]
    for candidate in stage2_candidates:
        candidate["in_stage2_pool"] = True

    phase_started_at = time.perf_counter()
    emit_timing_event(
        phase="score_stage2_esm",
        status="start",
        step=step,
        extra={"stage2_candidate_count": len(stage2_candidates), "skip_stage2_esm": SKIP_STAGE2_ESM},
    )
    for candidate in stage2_candidates:
        raw_esm_score = 0.0
        if (
            not SKIP_STAGE2_ESM
            and candidate["extracted_sequence"]
            and candidate["quality"]["hard_gate_pass"]
            and candidate["quality"]["soft_floor_pass"]
        ):
            raw_esm_score = get_esm2_plddt_score(candidate["extracted_sequence"])
        candidate["raw_esm_score"] = raw_esm_score
        candidate["stage2_score"] = compute_second_stage_score(
            raw_esm_score=raw_esm_score,
            motif_strength=float(candidate["quality"]["motif_strength"]),
            geometry_score=float(candidate["quality"]["geometry_score"]),
            template_penalty=float(candidate["quality"]["template_penalty"]),
        )
    emit_timing_event(phase="score_stage2_esm", status="end", started_at=phase_started_at, step=step)

    phase_started_at = time.perf_counter()
    emit_timing_event(phase="select_final_candidate", status="start", step=step)
    sorted_stage2 = sorted(
        stage2_candidates,
        key=lambda candidate: (
            float(candidate["stage2_score"] or 0.0),
            float(candidate["stage1_score"]),
        ),
        reverse=True,
    )
    for rank, candidate in enumerate(sorted_stage2, start=1):
        candidate["stage2_rank"] = rank

    selected = (
        next(
            (
                candidate
                for candidate in sorted_stage2
                if candidate["quality"]["is_trainable"] and candidate["raw_esm_score"] >= PLDDT_GATE_THRESHOLD
            ),
            None,
        )
        or next(
            (candidate for candidate in sorted_stage2 if candidate["quality"]["is_trainable"]),
            None,
        )
        or sorted_stage2[0]
    )
    selection_metadata = {
        "stage1_rank": selected["stage1_rank"],
        "stage2_rank": selected["stage2_rank"],
        "stage2_pool_size": len(stage2_candidates),
        "stage2_score": round(float(selected["stage2_score"] or 0.0), 4),
    }
    candidate_audit = [
        build_candidate_audit_entry(candidate, selected is candidate)
        for candidate in sorted_stage1
    ]
    emit_timing_event(phase="select_final_candidate", status="end", started_at=phase_started_at, step=step)
    return (
        selected["sampled_text"],
        selected["extracted_sequence"],
        selected["sampled_sequence"],
        selected["quality"],
        selected["family_evaluation"],
        float(selected["raw_esm_score"]),
        selection_metadata,
        candidate_audit,
        CANDIDATE_SAMPLE_COUNT,
    )


def build_candidate_audit_entry(candidate: dict[str, Any], is_selected: bool) -> dict[str, Any]:
    quality = candidate["quality"]
    family_evaluation = candidate["family_evaluation"]
    raw_esm_score = float(candidate["raw_esm_score"])
    catalytic_geometry = family_evaluation["catalytic_geometry"] if family_evaluation is not None else None
    bridge_flags = compute_bridge_flags(
        quality=quality,
        family_evaluation=family_evaluation,
        raw_esm_score=raw_esm_score,
    )
    return {
        "selected": is_selected,
        "sample_text": candidate["sampled_text"],
        "extracted_sequence": candidate["extracted_sequence"],
        "sample_token_count": len(candidate["sampled_sequence"].tokens),
        "stage1_rank": candidate["stage1_rank"],
        "stage1_score": round(float(candidate["stage1_score"]), 4),
        "in_stage2_pool": bool(candidate["in_stage2_pool"]),
        "stage2_rank": candidate["stage2_rank"],
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
        "best_gap_error": (
            family_evaluation["catalytic_geometry"]["best_gap_error"] if family_evaluation is not None else None
        ),
        "ser_asp_gap_error": catalytic_geometry["ser_asp_gap_error"] if catalytic_geometry is not None else None,
        "asp_his_gap_error": catalytic_geometry["asp_his_gap_error"] if catalytic_geometry is not None else None,
        "ser_his_gap_error": catalytic_geometry["ser_his_gap_error"] if catalytic_geometry is not None else None,
        "ser_asp_dyad_passes": catalytic_geometry["ser_asp_dyad_passes"] if catalytic_geometry is not None else False,
        "ser_his_dyad_passes": catalytic_geometry["ser_his_dyad_passes"] if catalytic_geometry is not None else False,
        "passes_core_screen": (
            bool(family_evaluation["passes_core_screen"]) if family_evaluation is not None else False
        ),
    }


def build_sequence_prompt(request: str, family_stats: dict[str, Any] | None) -> str:
    request = maybe_append_control_target_tag(request)
    request = maybe_append_control_blueprint_tag(request, family_stats)
    if PROMPT_VARIANT == "baseline" or family_stats is None:
        return BASELINE_SEQUENCE_PROMPT_TEMPLATE.format(request=request.strip())
    if PROMPT_VARIANT == "motif_prior_v1":
        motif_hint = ", ".join(family_stats["top_serine_motifs"][:PROMPT_MOTIF_HINT_COUNT])
        if not motif_hint:
            motif_hint = "GYSQG, GFSQG, GYSLG, GHSMG"
        return MOTIF_PRIOR_SEQUENCE_PROMPT_TEMPLATE.format(
            request=request.strip(),
            motif_hint=motif_hint,
            serine_window=format_position_window(family_stats["serine_position_range"]),
            aspartate_window=format_position_window(family_stats["aspartate_position_range"]),
            histidine_window=format_position_window(family_stats["histidine_position_range"]),
        )
    if PROMPT_VARIANT == "motif_prior_soft_v2":
        motif_hint = ", ".join(family_stats["top_serine_motifs"][:2])
        if not motif_hint:
            motif_hint = "GYSQG, GFSQG"
        if "[Target:" in request:
            return SOFT_MOTIF_PRIOR_CONTROLLED_SEQUENCE_PROMPT_TEMPLATE.format(
                request=request.strip(),
                motif_hint=motif_hint,
            )
        return SOFT_MOTIF_PRIOR_SEQUENCE_PROMPT_TEMPLATE.format(
            request=request.strip(),
            motif_hint=motif_hint,
        )
    raise RuntimeError(f"Unsupported PROMPT_VARIANT={PROMPT_VARIANT!r}")


def format_position_window(position_range: tuple[float, float]) -> str:
    start, end = position_range
    return f"{round(start * 100):d}-{round(end * 100):d}%"


def maybe_append_control_target_tag(request: str) -> str:
    stripped = request.strip()
    if not CONTROL_TARGET_TAG or "[Target:" in stripped:
        return stripped
    return f"{stripped}\n{CONTROL_TARGET_TAG}"


def maybe_append_control_blueprint_tag(request: str, family_stats: dict[str, Any] | None) -> str:
    stripped = request.strip()
    if "[Blueprint:" in stripped:
        return stripped
    if CONTROL_BLUEPRINT_TAG:
        return f"{stripped}\n{CONTROL_BLUEPRINT_TAG}"
    if not CONTROL_BLUEPRINT_RATIOS:
        return stripped
    ratios = parse_control_blueprint_ratios(CONTROL_BLUEPRINT_RATIOS)
    if ratios is None:
        return stripped
    length_hint = extract_length_hint(stripped)
    if length_hint is None:
        if family_stats is None:
            return stripped
        length_hint = int(family_stats["length_median"])
    serine_pos = max(1, int(round(length_hint * ratios[0])))
    aspartate_pos = max(serine_pos + 1, int(round(length_hint * ratios[1])))
    histidine_pos = max(aspartate_pos + 1, int(round(length_hint * ratios[2])))
    blueprint_tag = (
        f"[Blueprint: S_motif@{serine_pos}, D@{aspartate_pos}, H@{histidine_pos}]"
    )
    return f"{stripped}\n{blueprint_tag}"


def parse_control_blueprint_ratios(value: str) -> tuple[float, float, float] | None:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        return None
    try:
        ratios = tuple(float(part) for part in parts)
    except ValueError:
        return None
    if not (0.0 < ratios[0] < ratios[1] < ratios[2] < 1.0):
        return None
    return ratios


def assess_sequence_quality(
    raw_text: str,
    sequence: str,
) -> dict[str, float | int | bool]:
    raw_inspection = inspect_raw_sequence_text(raw_text)
    alpha_chars = [char for char in raw_text.upper() if char.isalpha()]
    aa_only_ratio = 0.0 if not alpha_chars else len(sequence) / len(alpha_chars)
    counts = Counter(sequence)
    entropy = 0.0
    dominant_fraction = 1.0
    if sequence:
        dominant_fraction = max(counts.values()) / len(sequence)
        entropy = -sum(
            (count / len(sequence)) * math.log2(count / len(sequence))
            for count in counts.values()
        )
    min_local_window_entropy = compute_min_local_window_entropy(sequence, LOCAL_ENTROPY_WINDOW)
    max_tandem_repeat_similarity = compute_max_tandem_repeat_similarity(sequence)

    hard_gate_pass = (
        MIN_VALID_SEQUENCE_LENGTH <= len(sequence) <= MAX_VALID_SEQUENCE_LENGTH
        and aa_only_ratio >= MIN_AA_ONLY_RATIO
        and bool(sequence)
        and not bool(raw_inspection["formatting_xml_tag"])
        and not bool(raw_inspection["invalid_alphabet"])
    )
    soft_floor_pass = (
        len(counts) >= SOFT_UNIQUE_RESIDUES_FLOOR
        and entropy >= SOFT_ENTROPY_FLOOR
        and dominant_fraction <= SOFT_MAX_DOMINANT_RESIDUE_FRACTION
    )
    soft_score = MAX_PERCENT_SCORE
    soft_score -= max(0.0, MIN_SEQUENCE_ENTROPY - entropy) * ENTROPY_DEFICIT_WEIGHT
    soft_score -= max(0, MIN_UNIQUE_RESIDUES - len(counts)) * UNIQUE_RESIDUE_DEFICIT_WEIGHT
    soft_score -= max(0.0, dominant_fraction - MAX_DOMINANT_RESIDUE_FRACTION) * DOMINANT_RESIDUE_EXCESS_WEIGHT
    soft_score = max(0.0, min(MAX_PERCENT_SCORE, soft_score))
    is_valid = hard_gate_pass and soft_floor_pass and soft_score >= SOFT_TRAINABILITY_BASE_THRESHOLD
    quality_score = (
        len(sequence)
        + aa_only_ratio * QUALITY_SCORE_AA_RATIO_WEIGHT
        + entropy * QUALITY_SCORE_ENTROPY_WEIGHT
        + len(counts) * QUALITY_SCORE_UNIQUE_RESIDUES_WEIGHT
        - dominant_fraction * QUALITY_SCORE_DOMINANT_RESIDUE_WEIGHT
        - abs(len(sequence) - QUALITY_SCORE_LENGTH_TARGET)
    )
    if not (hard_gate_pass and soft_floor_pass):
        quality_score -= QUALITY_SCORE_INVALID_SEQUENCE_PENALTY
    return {
        "is_valid": is_valid,
        "hard_gate_pass": hard_gate_pass,
        "soft_floor_pass": soft_floor_pass,
        "formatting_xml_tag": bool(raw_inspection["formatting_xml_tag"]),
        "invalid_alphabet": bool(raw_inspection["invalid_alphabet"]),
        "length": len(sequence),
        "aa_only_ratio": round(aa_only_ratio, 4),
        "unique_residues": len(counts),
        "entropy": round(entropy, 4),
        "dominant_residue_fraction": round(dominant_fraction, 4),
        "kmer_uniqueness_ratio": round(compute_kmer_uniqueness_ratio(sequence, KMER_DIVERSITY_K), 4),
        "min_local_window_entropy": round(min_local_window_entropy, 4),
        "max_tandem_repeat_similarity": round(max_tandem_repeat_similarity, 4),
        "template_penalty": 1.0,
        "motif_count": 0,
        "soft_score": round(soft_score, 4),
        "soft_trainability_base_threshold": SOFT_TRAINABILITY_BASE_THRESHOLD,
        "quality_score": round(quality_score, 4),
    }


def merge_candidate_quality(
    quality: dict[str, float | int | bool],
    family_evaluation: dict[str, Any] | None,
) -> dict[str, float | int | bool]:
    combined_score = float(quality["quality_score"])
    hard_gate_pass = bool(quality["hard_gate_pass"])
    soft_floor_pass = bool(quality["soft_floor_pass"])
    soft_score = float(quality["soft_score"])
    motif_strength = 0.0
    dyad_strength = 0.0
    ser_asp_strength = 0.0
    ser_his_strength = 0.0
    geometry_score = 0.0
    template_penalty = 1.0
    motif_count = 0
    trainability_reason = "soft_threshold"
    adjusted_soft_threshold = SOFT_TRAINABILITY_BASE_THRESHOLD
    is_trainable = hard_gate_pass and soft_floor_pass and soft_score >= adjusted_soft_threshold

    if family_evaluation is not None:
        if family_evaluation["valid_amino_acids"]:
            combined_score += MERGE_SCORE_VALID_AMINO_ACIDS_BONUS
        if family_evaluation["length_in_family_band"]:
            combined_score += MERGE_SCORE_LENGTH_BAND_BONUS
        if family_evaluation["has_family_serine_motif"]:
            combined_score += MERGE_SCORE_FAMILY_MOTIF_BONUS
        if family_evaluation["catalytic_geometry"]["passes"]:
            combined_score += MERGE_SCORE_GEOMETRY_BONUS
        if family_evaluation["novelty"]["passes_novelty_threshold"]:
            combined_score += MERGE_SCORE_NOVELTY_BONUS

        serine_motif_count = len(family_evaluation["serine_motifs"])
        combined_score += min(serine_motif_count, MERGE_SCORE_SERINE_MOTIF_BONUS_CAP) * MERGE_SCORE_PER_SERINE_MOTIF_BONUS

        best_gap_error = family_evaluation["catalytic_geometry"]["best_gap_error"]
        if isinstance(best_gap_error, int):
            combined_score += max(0.0, MERGE_SCORE_GAP_ALIGNMENT_BONUS_CAP - float(best_gap_error))

        closest_identity = float(family_evaluation["novelty"]["closest_edit_identity"])
        if closest_identity >= MERGE_SCORE_STRONG_NOVELTY_THRESHOLD:
            combined_score -= MERGE_SCORE_STRONG_NOVELTY_PENALTY
        elif closest_identity >= NOVELTY_IDENTITY_THRESHOLD:
            combined_score -= (closest_identity - NOVELTY_IDENTITY_THRESHOLD) * MERGE_SCORE_SOFT_NOVELTY_PENALTY_SCALE

        motif_strength = compute_motif_strength(family_evaluation)
        motif_count = len(family_evaluation["serine_motifs"])
        ser_asp_strength = compute_ser_asp_strength(family_evaluation)
        ser_his_strength = compute_ser_his_strength(family_evaluation)
        dyad_strength = compute_dyad_strength(family_evaluation)
        geometry_score = compute_geometry_score(family_evaluation)
        template_penalty = compute_targeted_diversity_penalty(
            quality=quality,
            family_evaluation=family_evaluation,
        )["template_penalty"]
        combined_score += MERGE_SCORE_DYAD_WEIGHT * dyad_strength
        combined_score += MERGE_SCORE_SER_ASP_WEIGHT * ser_asp_strength
        if family_evaluation["catalytic_geometry"]["aspartate_hits"]:
            combined_score += MERGE_SCORE_ASPARTATE_HIT_BONUS
        if (
            ser_his_strength > MERGE_SCORE_SER_HIS_STRENGTH_THRESHOLD
            and ser_asp_strength < MERGE_SCORE_SER_ASP_WEAK_THRESHOLD
        ):
            combined_score -= MERGE_SCORE_SER_HIS_MISALIGNMENT_PENALTY
        combined_score -= TEMPLATE_PENALTY_SCORE_WEIGHT * (1.0 - template_penalty)
        adjusted_soft_threshold = max(
            SOFT_TRAINABILITY_FLOOR,
            SOFT_TRAINABILITY_BASE_THRESHOLD
            - (MOTIF_STRENGTH_DISCOUNT_WEIGHT * motif_strength)
            - (GEOMETRY_SCORE_DISCOUNT_WEIGHT * geometry_score),
        )
        if bool(quality.get("formatting_xml_tag")):
            hard_gate_pass = False
            is_trainable = False
            trainability_reason = "formatting_xml_tag"
        elif bool(quality.get("invalid_alphabet")):
            hard_gate_pass = False
            is_trainable = False
            trainability_reason = "invalid_alphabet"
        elif motif_count == 0:
            hard_gate_pass = False
            is_trainable = False
            trainability_reason = "missing_catalytic_motif"
        elif motif_count > 1:
            hard_gate_pass = False
            is_trainable = False
            trainability_reason = "motif_spam_rejected"
        elif not hard_gate_pass:
            is_trainable = False
            trainability_reason = "hard_gate"
        elif not soft_floor_pass:
            is_trainable = False
            trainability_reason = "soft_floor"
        elif not family_evaluation["valid_amino_acids"]:
            is_trainable = False
            trainability_reason = "invalid_amino_acids"
        else:
            is_trainable = soft_score >= adjusted_soft_threshold
            trainability_reason = "ok" if is_trainable else "soft_threshold"
    else:
        if bool(quality.get("formatting_xml_tag")):
            is_trainable = False
            trainability_reason = "formatting_xml_tag"
        elif bool(quality.get("invalid_alphabet")):
            is_trainable = False
            trainability_reason = "invalid_alphabet"
        elif not hard_gate_pass:
            is_trainable = False
            trainability_reason = "hard_gate"
        elif not soft_floor_pass:
            is_trainable = False
            trainability_reason = "soft_floor"
        else:
            trainability_reason = "ok" if is_trainable else "soft_threshold"

    merged = dict(quality)
    merged["combined_score"] = round(combined_score, 4)
    merged["hard_gate_pass"] = hard_gate_pass
    merged["motif_strength"] = round(motif_strength, 4)
    merged["dyad_strength"] = round(dyad_strength, 4)
    merged["ser_asp_strength"] = round(ser_asp_strength, 4)
    merged["ser_his_strength"] = round(ser_his_strength, 4)
    merged["geometry_score"] = round(geometry_score, 4)
    merged["template_penalty"] = round(template_penalty, 4)
    merged["motif_count"] = int(motif_count)
    merged["soft_trainability_threshold"] = round(adjusted_soft_threshold, 4)
    merged["soft_trainability_margin"] = round(soft_score - adjusted_soft_threshold, 4)
    merged["is_trainable"] = is_trainable
    merged["trainability_reason"] = trainability_reason
    return merged


def compute_second_stage_score(
    *,
    raw_esm_score: float,
    motif_strength: float,
    geometry_score: float,
    template_penalty: float,
) -> float:
    normalized_esm_score = max(0.0, min(MAX_NORMALIZED_SCORE, raw_esm_score / SECOND_STAGE_ESM_SCORE_NORMALIZER))
    return round(
        (SECOND_STAGE_ESM_WEIGHT * normalized_esm_score)
        + (SECOND_STAGE_MOTIF_WEIGHT * motif_strength)
        + (SECOND_STAGE_GEOMETRY_WEIGHT * geometry_score),
        4,
    ) + round(SECOND_STAGE_TEMPLATE_WEIGHT * template_penalty, 4)


def compute_training_reward(
    *,
    step: int,
    raw_esm_score: float,
    quality: dict[str, float | int | bool],
    family_evaluation: dict[str, Any] | None,
) -> dict[str, Any]:
    bridge_flags = compute_bridge_flags(
        quality=quality,
        family_evaluation=family_evaluation,
        raw_esm_score=raw_esm_score,
    )
    dense_reward_info = compute_dense_family_reward(quality=quality, family_evaluation=family_evaluation)
    dense_family_reward = dense_reward_info["dense_family_reward"]
    kmer_uniqueness_ratio = float(quality.get("kmer_uniqueness_ratio", 0.0))
    template_penalty_info = compute_targeted_diversity_penalty(
        quality=quality,
        family_evaluation=family_evaluation,
    )
    rl_family_reward = round(dense_family_reward * template_penalty_info["template_penalty"], 2)
    if RL_REWARD_MODE == "bridge_tiers":
        if not quality["is_trainable"] or family_evaluation is None:
            reward = 0.0
        elif not bridge_flags["functional_bridge_passes"]:
            reward = 0.0
        elif bridge_flags["family_faithful_bridge_passes"]:
            reward = BRIDGE_TIER2_REWARD + BRIDGE_TIER1_BONUS
        else:
            reward = BRIDGE_TIER2_REWARD
        return build_reward_metadata(
            reward=reward,
            bridge_flags=bridge_flags,
            dense_reward_info=dense_reward_info,
            dense_family_reward=dense_family_reward,
            rl_family_reward=rl_family_reward,
            template_penalty_info=template_penalty_info,
            kmer_uniqueness_ratio=kmer_uniqueness_ratio,
        )
    if not quality["is_trainable"] or family_evaluation is None or not bridge_flags["esm_gate_pass"]:
        return build_reward_metadata(
            reward=0.0,
            bridge_flags=bridge_flags,
            dense_reward_info=dense_reward_info,
            dense_family_reward=dense_family_reward,
            rl_family_reward=rl_family_reward,
            template_penalty_info=template_penalty_info,
            kmer_uniqueness_ratio=kmer_uniqueness_ratio,
        )
    return build_reward_metadata(
        reward=rl_family_reward,
        bridge_flags=bridge_flags,
        dense_reward_info=dense_reward_info,
        dense_family_reward=dense_family_reward,
        rl_family_reward=rl_family_reward,
        template_penalty_info=template_penalty_info,
        kmer_uniqueness_ratio=kmer_uniqueness_ratio,
    )


def build_reward_metadata(
    *,
    reward: float,
    bridge_flags: dict[str, bool],
    dense_reward_info: dict[str, Any],
    dense_family_reward: float,
    rl_family_reward: float,
    template_penalty_info: dict[str, Any],
    kmer_uniqueness_ratio: float,
) -> dict[str, Any]:
    return {
        "reward": reward,
        "reward_mode": RL_REWARD_MODE,
        **bridge_flags,
        "dense_family_reward": dense_family_reward,
        "rl_family_reward": rl_family_reward,
        "dense_reward_components": dense_reward_info["dense_reward_components"],
        "template_penalty": template_penalty_info["template_penalty"],
        "motif_spam_penalty": template_penalty_info["motif_spam_penalty"],
        "tandem_repeat_penalty": template_penalty_info["tandem_repeat_penalty"],
        "local_entropy_penalty": template_penalty_info["local_entropy_penalty"],
        "kmer_uniqueness_ratio": kmer_uniqueness_ratio,
        "motif_count": template_penalty_info["motif_count"],
        "max_tandem_repeat_similarity": template_penalty_info["max_tandem_repeat_similarity"],
        "min_local_window_entropy": template_penalty_info["min_local_window_entropy"],
    }


def compute_bridge_flags(
    *,
    quality: dict[str, float | int | bool],
    family_evaluation: dict[str, Any] | None,
    raw_esm_score: float,
) -> dict[str, bool]:
    has_family_serine_motif = bool(
        family_evaluation is not None and family_evaluation["has_family_serine_motif"]
    )
    geometry_passes = bool(
        family_evaluation is not None and family_evaluation["catalytic_geometry"]["passes"]
    )
    esm_gate_pass = raw_esm_score >= PLDDT_GATE_THRESHOLD
    functional_bridge_passes = bool(quality["motif_count"] == 1 and geometry_passes and esm_gate_pass)
    family_faithful_bridge_passes = bool(functional_bridge_passes and has_family_serine_motif)
    return {
        "esm_gate_pass": esm_gate_pass,
        "has_family_serine_motif": has_family_serine_motif,
        "geometry_passes": geometry_passes,
        "functional_bridge_passes": functional_bridge_passes,
        "family_faithful_bridge_passes": family_faithful_bridge_passes,
    }


def compute_motif_strength(family_evaluation: dict[str, Any]) -> float:
    motif_count = len(family_evaluation["serine_motifs"])
    if motif_count == 0:
        return 0.0

    base_strength = 1.0 if family_evaluation["has_family_serine_motif"] else MOTIF_STRENGTH_NON_FAMILY_BASE
    spam_factor = 1.0 / (1.0 + (MOTIF_STRENGTH_REPEAT_DECAY_WEIGHT * max(0, motif_count - 1)))
    return base_strength * spam_factor


def compute_geometry_score(family_evaluation: dict[str, Any]) -> float:
    catalytic_geometry = family_evaluation["catalytic_geometry"]
    window_hits = sum(
        bool(catalytic_geometry[key])
        for key in ("serine_hits", "aspartate_hits", "histidine_hits")
    )
    window_score = window_hits / 3.0
    ser_asp_strength = compute_ser_asp_strength(family_evaluation)
    ser_his_strength = compute_ser_his_strength(family_evaluation)
    triad_strength = compute_triad_strength(family_evaluation)
    return min(
        MAX_NORMALIZED_SCORE,
        (GEOMETRY_SCORE_WINDOW_HIT_WEIGHT * window_score)
        + (GEOMETRY_SCORE_SER_ASP_WEIGHT * ser_asp_strength)
        + (GEOMETRY_SCORE_SER_HIS_WEIGHT * ser_his_strength)
        + (GEOMETRY_SCORE_TRIAD_WEIGHT * triad_strength),
    )


def compute_ser_asp_strength(family_evaluation: dict[str, Any]) -> float:
    catalytic_geometry = family_evaluation["catalytic_geometry"]
    return compute_gap_alignment_strength(
        catalytic_geometry.get("ser_asp_gap_error"),
        SER_ASP_DYAD_SCORE_SCALE,
    )


def compute_ser_his_strength(family_evaluation: dict[str, Any]) -> float:
    catalytic_geometry = family_evaluation["catalytic_geometry"]
    return compute_gap_alignment_strength(
        catalytic_geometry.get("ser_his_gap_error"),
        SER_HIS_DYAD_SCORE_SCALE,
    )


def compute_dyad_strength(family_evaluation: dict[str, Any]) -> float:
    ser_asp_strength = compute_ser_asp_strength(family_evaluation)
    ser_his_strength = compute_ser_his_strength(family_evaluation)
    return min(
        MAX_NORMALIZED_SCORE,
        (DYAD_SCORE_SER_ASP_WEIGHT * ser_asp_strength) + (DYAD_SCORE_SER_HIS_WEIGHT * ser_his_strength),
    )


def compute_triad_strength(family_evaluation: dict[str, Any]) -> float:
    catalytic_geometry = family_evaluation["catalytic_geometry"]
    return compute_gap_alignment_strength(
        catalytic_geometry.get("best_gap_error"),
        TRIAD_SCORE_SCALE,
    )


def compute_gap_alignment_strength(gap_error: Any, scale: float) -> float:
    if not isinstance(gap_error, int):
        return 0.0
    return math.exp(-float(gap_error) / scale)


def compute_dense_family_reward(
    *,
    quality: dict[str, float | int | bool],
    family_evaluation: dict[str, Any] | None,
) -> dict[str, float | dict[str, float]]:
    if family_evaluation is None:
        return {
            "dense_family_reward": 0.0,
            "dense_reward_components": {
                "motif_component": 0.0,
                "ser_asp_component": 0.0,
                "ser_his_component": 0.0,
                "aspartate_presence_component": 0.0,
                "triad_component": 0.0,
                "incomplete_triad_penalty": 0.0,
            },
        }

    catalytic_geometry = family_evaluation["catalytic_geometry"]
    ser_asp_strength = compute_ser_asp_strength(family_evaluation)
    ser_his_strength = compute_ser_his_strength(family_evaluation)
    triad_strength = compute_triad_strength(family_evaluation)
    motif_component = DENSE_MOTIF_REWARD_WEIGHT * float(quality.get("motif_strength", 0.0))
    ser_asp_component = DENSE_SER_ASP_REWARD_WEIGHT * ser_asp_strength
    ser_his_component = DENSE_SER_HIS_REWARD_WEIGHT * ser_his_strength
    aspartate_presence_component = (
        DENSE_ASPARTATE_PRESENCE_WEIGHT
        if catalytic_geometry["aspartate_hits"]
        else 0.0
    )
    triad_component = DENSE_TRIAD_REWARD_WEIGHT * triad_strength
    incomplete_triad_penalty = DENSE_INCOMPLETE_TRIAD_PENALTY_WEIGHT * max(0.0, ser_his_strength - ser_asp_strength)
    max_reward = (
        DENSE_MOTIF_REWARD_WEIGHT
        + DENSE_SER_ASP_REWARD_WEIGHT
        + DENSE_SER_HIS_REWARD_WEIGHT
        + DENSE_ASPARTATE_PRESENCE_WEIGHT
        + DENSE_TRIAD_REWARD_WEIGHT
    )
    dense_family_reward = round(
        MAX_PERCENT_SCORE
        * max(
            0.0,
            (
                motif_component
                + ser_asp_component
                + ser_his_component
                + aspartate_presence_component
                + triad_component
                - incomplete_triad_penalty
            )
            / max_reward,
        ),
        2,
    )
    return {
        "dense_family_reward": dense_family_reward,
        "dense_reward_components": {
            "motif_component": round(motif_component, 4),
            "ser_asp_component": round(ser_asp_component, 4),
            "ser_his_component": round(ser_his_component, 4),
            "aspartate_presence_component": round(aspartate_presence_component, 4),
            "triad_component": round(triad_component, 4),
            "incomplete_triad_penalty": round(incomplete_triad_penalty, 4),
        },
    }


def compute_kmer_uniqueness_ratio(sequence: str, k: int) -> float:
    if len(sequence) < k or k <= 0:
        return 1.0 if sequence else 0.0
    kmers = [sequence[idx : idx + k] for idx in range(len(sequence) - k + 1)]
    return len(set(kmers)) / len(kmers)


def compute_targeted_diversity_penalty(
    *,
    quality: dict[str, float | int | bool],
    family_evaluation: dict[str, Any] | None,
) -> dict[str, float | int]:
    motif_count = len(family_evaluation["serine_motifs"]) if family_evaluation is not None else 0
    motif_spam_penalty = compute_motif_spam_penalty(motif_count)
    max_tandem_repeat_similarity = float(quality.get("max_tandem_repeat_similarity", 0.0))
    tandem_repeat_penalty = compute_tandem_repeat_penalty(max_tandem_repeat_similarity)
    min_local_window_entropy = float(quality.get("min_local_window_entropy", 0.0))
    local_entropy_penalty = compute_local_entropy_penalty(min_local_window_entropy)
    template_penalty = min(
        motif_spam_penalty,
        tandem_repeat_penalty,
        local_entropy_penalty,
    )
    return {
        "template_penalty": round(template_penalty, 4),
        "motif_spam_penalty": round(motif_spam_penalty, 4),
        "tandem_repeat_penalty": round(tandem_repeat_penalty, 4),
        "local_entropy_penalty": round(local_entropy_penalty, 4),
        "motif_count": motif_count,
        "max_tandem_repeat_similarity": round(max_tandem_repeat_similarity, 4),
        "min_local_window_entropy": round(min_local_window_entropy, 4),
    }


def compute_min_local_window_entropy(sequence: str, window_size: int) -> float:
    if not sequence:
        return 0.0
    if window_size <= 1 or len(sequence) <= window_size:
        return compute_shannon_entropy(sequence)
    min_entropy = math.inf
    for start in range(len(sequence) - window_size + 1):
        window = sequence[start : start + window_size]
        min_entropy = min(min_entropy, compute_shannon_entropy(window))
    return 0.0 if min_entropy is math.inf else min_entropy


def compute_shannon_entropy(sequence: str) -> float:
    if not sequence:
        return 0.0
    counts = Counter(sequence)
    length = len(sequence)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def compute_max_tandem_repeat_similarity(sequence: str) -> float:
    if not sequence:
        return 0.0
    best_similarity = 0.0
    for block_size in range(TANDEM_REPEAT_BLOCK_MIN, TANDEM_REPEAT_BLOCK_MAX + 1, TANDEM_REPEAT_BLOCK_STEP):
        if len(sequence) < (block_size * 2):
            continue
        max_start = len(sequence) - (2 * block_size)
        for start in range(max_start + 1):
            left = sequence[start : start + block_size]
            for gap in range(TANDEM_REPEAT_MAX_GAP + 1):
                right_start = start + block_size + gap
                if right_start + block_size > len(sequence):
                    break
                right = sequence[right_start : right_start + block_size]
                matches = sum([left_char == right_char for left_char, right_char in zip(left, right)])
                best_similarity = max(best_similarity, matches / block_size)
    return best_similarity


def compute_motif_spam_penalty(motif_count: int) -> float:
    if motif_count <= MOTIF_SPAM_ALLOWED_COUNT:
        return 1.0
    extra_motifs = motif_count - MOTIF_SPAM_ALLOWED_COUNT
    return max(
        MOTIF_SPAM_PENALTY_FLOOR,
        1.0 / ((1.0 + extra_motifs) ** MOTIF_SPAM_PENALTY_EXPONENT),
    )


def compute_tandem_repeat_penalty(max_tandem_repeat_similarity: float) -> float:
    if max_tandem_repeat_similarity <= TANDEM_REPEAT_SIMILARITY_THRESHOLD:
        return 1.0
    similarity_excess = (max_tandem_repeat_similarity - TANDEM_REPEAT_SIMILARITY_THRESHOLD) / max(
        1e-6,
        1.0 - TANDEM_REPEAT_SIMILARITY_THRESHOLD,
    )
    return max(TANDEM_REPEAT_PENALTY_FLOOR, 1.0 - (0.95 * similarity_excess))


def compute_local_entropy_penalty(min_local_window_entropy: float) -> float:
    if min_local_window_entropy >= LOCAL_ENTROPY_MIN_THRESHOLD:
        return 1.0
    if LOCAL_ENTROPY_MIN_THRESHOLD <= 0.0:
        return 1.0
    return max(
        LOCAL_ENTROPY_PENALTY_FLOOR,
        min_local_window_entropy / LOCAL_ENTROPY_MIN_THRESHOLD,
    )


def build_policy_gradient_datum(
    prompt_input: types.ModelInput,
    sampled_tokens: list[int],
    sampled_logprobs: list[float],
    reward: float,
) -> types.Datum:
    if not sampled_tokens:
        raise RuntimeError("Sampling returned an empty completion")

    observed_prompt_length = prompt_input.length - 1
    model_input = (
        prompt_input
        if len(sampled_tokens) == 1
        else prompt_input.append(types.EncodedTextChunk(tokens=sampled_tokens[:-1]))
    )
    target_tokens = np.asarray([0] * observed_prompt_length + sampled_tokens, dtype=np.int64)
    padded_logprobs = np.asarray(
        [0.0] * observed_prompt_length + sampled_logprobs,
        dtype=np.float32,
    )
    padded_advantages = np.asarray(
        [0.0] * observed_prompt_length + [reward] * (model_input.length - observed_prompt_length),
        dtype=np.float32,
    )

    if not (
        model_input.length
        == len(target_tokens)
        == len(padded_logprobs)
        == len(padded_advantages)
    ):
        raise RuntimeError("Importance-sampling tensors are not aligned")

    return types.Datum(
        model_input=model_input,
        loss_fn_inputs={
            "target_tokens": target_tokens,
            "logprobs": padded_logprobs,
            "advantages": padded_advantages,
        },
    )


def scale_reward_for_loss(reward: float) -> float:
    if RL_REWARD_MODE == "bridge_tiers":
        return reward
    return reward / MAX_PERCENT_SCORE


def build_loss_fn_config() -> dict[str, float] | None:
    if RL_LOSS_FN == "ppo":
        return {
            "clip_low_threshold": PPO_CLIP_LOW_THRESHOLD,
            "clip_high_threshold": PPO_CLIP_HIGH_THRESHOLD,
        }
    return None


if __name__ == "__main__":
    main()
