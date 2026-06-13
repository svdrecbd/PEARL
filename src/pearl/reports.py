from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io_utils import atomic_write_json


@dataclass(frozen=True)
class ReportContext:
    init_state_path: str | None
    eval_only: bool
    prompt_variant: str
    candidate_sample_count: int
    second_stage_top_k: int
    esm_pll_gate_percentile: float
    second_stage_esm_weight: float
    second_stage_motif_weight: float
    second_stage_geometry_weight: float
    second_stage_template_weight: float
    skip_stage2_esm: bool
    prompts_path: str | None


def build_report_payload(
    *,
    requested_model_name: str,
    base_model: str,
    supported_models: list[str],
    checkpoint_name: str,
    checkpoint_path: str | None,
    reference_records_path: Path | None,
    prompts: list[str],
    step_records: list[dict[str, object]],
    context: ReportContext,
) -> dict[str, Any]:
    average_reward = 0.0
    if step_records:
        average_reward = sum(float(record["reward"]) for record in step_records) / len(step_records)
    return {
        "requested_model_name": requested_model_name,
        "base_model": base_model,
        "supported_models": supported_models,
        "checkpoint_name": checkpoint_name,
        "checkpoint_path": checkpoint_path,
        "init_state_path": context.init_state_path,
        "eval_only": context.eval_only,
        "steps": len(step_records),
        "prompt_count": len(prompts),
        "prompts_path": context.prompts_path,
        "reference_records_path": str(reference_records_path) if reference_records_path is not None else None,
        "prompt_variant": context.prompt_variant,
        "candidate_sample_count": context.candidate_sample_count,
        "second_stage_top_k": context.second_stage_top_k,
        "esm_pll_gate_percentile": context.esm_pll_gate_percentile,
        "second_stage_esm_weight": context.second_stage_esm_weight,
        "second_stage_motif_weight": context.second_stage_motif_weight,
        "second_stage_geometry_weight": context.second_stage_geometry_weight,
        "second_stage_template_weight": context.second_stage_template_weight,
        "skip_stage2_esm": context.skip_stage2_esm,
        "average_reward": average_reward,
        "records": step_records,
    }


def build_candidate_audit_payload(
    *,
    checkpoint_name: str,
    checkpoint_path: str | None,
    candidate_audit_records: list[dict[str, object]],
    context: ReportContext,
) -> dict[str, Any]:
    return {
        "checkpoint_name": checkpoint_name,
        "checkpoint_path": checkpoint_path,
        "init_state_path": context.init_state_path,
        "eval_only": context.eval_only,
        "prompt_variant": context.prompt_variant,
        "candidate_sample_count": context.candidate_sample_count,
        "second_stage_top_k": context.second_stage_top_k,
        "esm_pll_gate_percentile": context.esm_pll_gate_percentile,
        "second_stage_esm_weight": context.second_stage_esm_weight,
        "second_stage_motif_weight": context.second_stage_motif_weight,
        "second_stage_geometry_weight": context.second_stage_geometry_weight,
        "second_stage_template_weight": context.second_stage_template_weight,
        "skip_stage2_esm": context.skip_stage2_esm,
        "records": candidate_audit_records,
    }


def persist_progress(
    *,
    report_path: Path,
    candidate_audit_path: Path | None,
    requested_model_name: str,
    base_model: str,
    supported_models: list[str],
    checkpoint_name: str,
    checkpoint_path: str | None,
    reference_records_path: Path | None,
    prompts: list[str],
    step_records: list[dict[str, object]],
    candidate_audit_records: list[dict[str, object]],
    context: ReportContext,
) -> dict[str, Any]:
    report = build_report_payload(
        requested_model_name=requested_model_name,
        base_model=base_model,
        supported_models=supported_models,
        checkpoint_name=checkpoint_name,
        checkpoint_path=checkpoint_path,
        reference_records_path=reference_records_path,
        prompts=prompts,
        step_records=step_records,
        context=context,
    )
    atomic_write_json(report_path, report)
    if candidate_audit_path is not None:
        atomic_write_json(
            candidate_audit_path,
            build_candidate_audit_payload(
                checkpoint_name=checkpoint_name,
                checkpoint_path=checkpoint_path,
                candidate_audit_records=candidate_audit_records,
                context=context,
            ),
        )
    return report


def extract_contiguous_step_records(*, raw_records: Any, prompt_count: int) -> list[dict[str, object]]:
    if not isinstance(raw_records, list):
        return []
    by_step: dict[int, dict[str, object]] = {}
    for record in raw_records:
        if not isinstance(record, dict):
            continue
        step_value = record.get("step")
        try:
            step = int(step_value)
        except (TypeError, ValueError):
            continue
        if step < 0 or step >= prompt_count:
            continue
        by_step[step] = record

    contiguous: list[dict[str, object]] = []
    for step in range(prompt_count):
        record = by_step.get(step)
        if record is None:
            break
        contiguous.append(record)
    return contiguous


def validate_optional_weight(*, report_path: Path, payload: dict[str, Any], field: str, expected: float) -> None:
    observed = payload.get(field)
    if observed is None:
        return
    if not math.isclose(float(observed), expected, abs_tol=1e-9):
        raise RuntimeError(
            f"Resume report {field} mismatch for {report_path}: expected {expected}, observed {observed}"
        )


def validate_resume_report_payload(
    *,
    report_payload: dict[str, Any],
    prompts: list[str],
    report_path: Path,
    context: ReportContext,
) -> None:
    expected_prompt_count = len(prompts)
    observed_prompt_count = report_payload.get("prompt_count")
    if int(observed_prompt_count or -1) != expected_prompt_count:
        raise RuntimeError(
            f"Resume report prompt_count mismatch for {report_path}: "
            f"expected {expected_prompt_count}, observed {observed_prompt_count}"
        )

    observed_eval_only = bool(report_payload.get("eval_only"))
    if observed_eval_only != context.eval_only:
        raise RuntimeError(
            f"Resume report eval_only mismatch for {report_path}: expected {context.eval_only}, observed {observed_eval_only}"
        )

    observed_init_state_path = report_payload.get("init_state_path")
    if observed_init_state_path is not None and str(observed_init_state_path) != str(context.init_state_path):
        raise RuntimeError(
            f"Resume report init_state_path mismatch for {report_path}: "
            f"expected {context.init_state_path}, observed {observed_init_state_path}"
        )

    observed_prompt_variant = report_payload.get("prompt_variant")
    if observed_prompt_variant is not None and str(observed_prompt_variant) != context.prompt_variant:
        raise RuntimeError(
            f"Resume report prompt_variant mismatch for {report_path}: "
            f"expected {context.prompt_variant}, observed {observed_prompt_variant}"
        )

    observed_candidate_count = report_payload.get("candidate_sample_count")
    if observed_candidate_count is not None and int(observed_candidate_count) != context.candidate_sample_count:
        raise RuntimeError(
            f"Resume report candidate_sample_count mismatch for {report_path}: "
            f"expected {context.candidate_sample_count}, observed {observed_candidate_count}"
        )

    observed_top_k = report_payload.get("second_stage_top_k")
    if observed_top_k is not None and int(observed_top_k) != context.second_stage_top_k:
        raise RuntimeError(
            f"Resume report second_stage_top_k mismatch for {report_path}: "
            f"expected {context.second_stage_top_k}, observed {observed_top_k}"
        )

    observed_percentile = report_payload.get("esm_pll_gate_percentile")
    if observed_percentile is not None and not math.isclose(
        float(observed_percentile), context.esm_pll_gate_percentile, abs_tol=1e-9
    ):
        raise RuntimeError(
            f"Resume report esm_pll_gate_percentile mismatch for {report_path}: "
            f"expected {context.esm_pll_gate_percentile}, observed {observed_percentile}"
        )

    validate_optional_weight(
        report_path=report_path,
        payload=report_payload,
        field="second_stage_esm_weight",
        expected=context.second_stage_esm_weight,
    )
    validate_optional_weight(
        report_path=report_path,
        payload=report_payload,
        field="second_stage_motif_weight",
        expected=context.second_stage_motif_weight,
    )
    validate_optional_weight(
        report_path=report_path,
        payload=report_payload,
        field="second_stage_geometry_weight",
        expected=context.second_stage_geometry_weight,
    )
    validate_optional_weight(
        report_path=report_path,
        payload=report_payload,
        field="second_stage_template_weight",
        expected=context.second_stage_template_weight,
    )

    observed_prompts_path = report_payload.get("prompts_path")
    if observed_prompts_path and context.prompts_path:
        expected_path = str(Path(context.prompts_path).expanduser().resolve())
        observed_path = str(Path(str(observed_prompts_path)).expanduser().resolve())
        if observed_path != expected_path:
            raise RuntimeError(
                f"Resume report prompts_path mismatch for {report_path}: "
                f"expected {expected_path}, observed {observed_path}"
            )
