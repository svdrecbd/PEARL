from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class SparseTeacherTrace:
    name: str
    weight: float
    positions: tuple[dict[int, float], ...]
    temperature: float = 1.0


def build_sparse_poe_target_row(
    row: dict[str, Any],
    *,
    top_k: int = 20,
    missing_logprob: float = -30.0,
    min_teacher_count: int = 1,
) -> dict[str, Any]:
    traces = parse_teacher_traces(row)
    if not traces:
        raise ValueError("row does not contain any teacher traces")
    if top_k <= 0:
        raise ValueError("top_k must be > 0")
    if min_teacher_count <= 0:
        raise ValueError("min_teacher_count must be > 0")

    position_count = len(traces[0].positions)
    if any(len(trace.positions) != position_count for trace in traces):
        lengths = {trace.name: len(trace.positions) for trace in traces}
        raise ValueError(f"teacher traces have inconsistent position counts: {lengths}")

    teacher_weights = normalize_weights({trace.name: trace.weight for trace in traces})
    target_token_ids: list[list[int]] = []
    target_weights: list[list[float]] = []
    position_diagnostics: list[dict[str, Any]] = []
    dropped_position_count = 0

    for position_index in range(position_count):
        token_ids, weights, diagnostics = sparse_poe_position(
            traces,
            position_index=position_index,
            teacher_weights=teacher_weights,
            top_k=top_k,
            missing_logprob=missing_logprob,
            min_teacher_count=min_teacher_count,
        )
        if not token_ids:
            dropped_position_count += 1
            token_ids = [0]
            weights = [0.0]
        target_token_ids.append(token_ids)
        target_weights.append(weights)
        position_diagnostics.append(diagnostics)

    sample_id = str(row.get("sample_id") or row.get("rollout_id") or row.get("candidate_id") or "")
    prompt = str(row.get("prompt") or "")
    sequence = str(row.get("sequence") or row.get("completion") or "")
    teacher_names = [trace.name for trace in traces]
    mean_disagreement = mean_float(
        [diagnostic["sparse_disagreement"] for diagnostic in position_diagnostics if diagnostic.get("active")]
    )
    return {
        "sample_id": sample_id,
        "prompt": prompt,
        "sequence": sequence,
        "target_token_ids": target_token_ids,
        "target_weights": target_weights,
        "consensus": {
            "method": "sparse_weighted_product_of_experts",
            "top_k": top_k,
            "missing_logprob": missing_logprob,
            "min_teacher_count": min_teacher_count,
            "teacher_weights": teacher_weights,
            "teacher_names": teacher_names,
            "position_count": position_count,
            "dropped_position_count": dropped_position_count,
            "mean_sparse_disagreement": mean_disagreement,
        },
        "position_diagnostics": position_diagnostics,
    }


def sparse_poe_position(
    traces: tuple[SparseTeacherTrace, ...] | list[SparseTeacherTrace],
    *,
    position_index: int,
    teacher_weights: dict[str, float],
    top_k: int,
    missing_logprob: float,
    min_teacher_count: int,
) -> tuple[list[int], list[float], dict[str, Any]]:
    coverage: dict[int, int] = {}
    union_tokens: set[int] = set()
    scaled_positions: dict[str, dict[int, float]] = {}
    for trace in traces:
        position = trace.positions[position_index]
        scaled = temperature_scale_logprobs(position, trace.temperature)
        scaled_positions[trace.name] = scaled
        for token_id in scaled:
            union_tokens.add(token_id)
            coverage[token_id] = coverage.get(token_id, 0) + 1

    candidate_tokens = sorted(token_id for token_id in union_tokens if coverage.get(token_id, 0) >= min_teacher_count)
    if not candidate_tokens:
        return [], [], {
            "position": position_index,
            "active": False,
            "candidate_count": 0,
            "sparse_disagreement": 0.0,
            "mean_teacher_coverage": 0.0,
        }

    combined_logprobs: dict[int, float] = {}
    for token_id in candidate_tokens:
        combined = 0.0
        for trace in traces:
            teacher_logprob = scaled_positions[trace.name].get(token_id, missing_logprob)
            combined += teacher_weights[trace.name] * teacher_logprob
        combined_logprobs[token_id] = combined

    ranked = sorted(combined_logprobs.items(), key=lambda item: (-item[1], item[0]))[:top_k]
    retained_tokens = [token_id for token_id, _ in ranked]
    retained_logits = [logprob for _, logprob in ranked]
    normalizer = logsumexp(retained_logits)
    weights = [math.exp(logit - normalizer) for logit in retained_logits]
    mean_coverage = sum(coverage[token_id] for token_id in retained_tokens) / max(1, len(retained_tokens))
    return retained_tokens, weights, {
        "position": position_index,
        "active": True,
        "candidate_count": len(candidate_tokens),
        "retained_count": len(retained_tokens),
        "sparse_log_normalizer": round(normalizer, 8),
        "sparse_disagreement": round(max(0.0, -normalizer), 8),
        "mean_teacher_coverage": round(mean_coverage, 6),
        "max_teacher_coverage": max(coverage[token_id] for token_id in retained_tokens),
    }


def parse_teacher_traces(row: dict[str, Any]) -> tuple[SparseTeacherTrace, ...]:
    teachers = row.get("teachers")
    if isinstance(teachers, dict):
        traces = [
            parse_teacher_trace(name=str(name), payload=payload)
            for name, payload in teachers.items()
            if isinstance(payload, dict)
        ]
    else:
        teacher_topk = row.get("teacher_topk") or row.get("teacher_traces")
        if not isinstance(teacher_topk, list):
            return ()
        traces = [
            parse_teacher_trace(name=str(payload.get("name") or payload.get("teacher") or f"teacher_{index}"), payload=payload)
            for index, payload in enumerate(teacher_topk, start=1)
            if isinstance(payload, dict)
        ]
    return tuple(trace for trace in traces if trace.positions)


def parse_teacher_trace(*, name: str, payload: dict[str, Any]) -> SparseTeacherTrace:
    positions_payload = payload.get("positions") or payload.get("topk_prompt_logprobs")
    if not isinstance(positions_payload, list):
        raise ValueError(f"teacher {name!r} is missing positions")
    positions = tuple(parse_position(position, teacher_name=name) for position in positions_payload)
    weight = as_float(payload.get("weight"), default=1.0)
    temperature = as_float(payload.get("temperature"), default=1.0)
    if weight < 0:
        raise ValueError(f"teacher {name!r} has negative weight")
    if temperature <= 0:
        raise ValueError(f"teacher {name!r} temperature must be > 0")
    return SparseTeacherTrace(name=name, weight=weight, positions=positions, temperature=temperature)


def parse_position(position: Any, *, teacher_name: str) -> dict[int, float]:
    if isinstance(position, dict):
        token_ids = position.get("token_ids") or position.get("tokens")
        logprobs = position.get("logprobs")
        if isinstance(token_ids, list) and isinstance(logprobs, list):
            if len(token_ids) != len(logprobs):
                raise ValueError(f"teacher {teacher_name!r} has mismatched token/logprob lengths")
            return {int(token_id): float(logprob) for token_id, logprob in zip(token_ids, logprobs, strict=True)}
    if isinstance(position, list):
        parsed: dict[int, float] = {}
        for item in position:
            if isinstance(item, dict):
                token_id = item.get("token_id") if "token_id" in item else item.get("token")
                logprob = item.get("logprob")
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                token_id, logprob = item
            else:
                continue
            if token_id is None or logprob is None:
                continue
            parsed[int(token_id)] = float(logprob)
        return parsed
    raise ValueError(f"teacher {teacher_name!r} has unsupported position payload")


def temperature_scale_logprobs(logprobs: dict[int, float], temperature: float) -> dict[int, float]:
    if not logprobs:
        return {}
    scaled_values = {token_id: logprob / temperature for token_id, logprob in logprobs.items()}
    normalizer = logsumexp(scaled_values.values())
    return {token_id: value - normalizer for token_id, value in scaled_values.items()}


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(weight)) for weight in weights.values())
    if total <= 0:
        raise ValueError("at least one teacher weight must be positive")
    return {name: max(0.0, float(weight)) / total for name, weight in weights.items()}


def build_sparse_cross_entropy_datum(target_row: dict[str, Any], tokenizer: Any) -> Any:
    from tinker import types

    prompt = str(target_row["prompt"])
    sequence = str(target_row["sequence"])
    prompt_tokens = tokenizer.encode(prompt, add_special_tokens=False)
    sequence_tokens = tokenizer.encode(sequence, add_special_tokens=False)
    if not prompt_tokens:
        raise RuntimeError("OPD prompt tokenized to zero input tokens")
    if not sequence_tokens:
        raise RuntimeError("OPD sequence tokenized to zero target tokens")

    target_token_rows = target_row["target_token_ids"]
    target_weight_rows = target_row["target_weights"]
    if len(target_token_rows) != len(sequence_tokens) or len(target_weight_rows) != len(sequence_tokens):
        raise RuntimeError("Sparse OPD target length does not match tokenized sequence length")

    k = max(len(row) for row in target_token_rows)
    student_input = prompt_tokens + sequence_tokens[:-1]
    gen_start = len(prompt_tokens) - 1
    target_tokens = np.zeros((len(student_input), k), dtype=np.int64)
    weights = np.zeros((len(student_input), k), dtype=np.float32)
    for position_index, (token_ids, token_weights) in enumerate(
        zip(target_token_rows, target_weight_rows, strict=True)
    ):
        if len(token_ids) != len(token_weights):
            raise RuntimeError(f"Sparse OPD row {position_index} has mismatched target ids and weights")
        target_position = gen_start + position_index
        target_tokens[target_position, : len(token_ids)] = np.asarray(token_ids, dtype=np.int64)
        weights[target_position, : len(token_weights)] = np.asarray(token_weights, dtype=np.float32)

    return types.Datum(
        model_input=types.ModelInput.from_ints(student_input),
        loss_fn_inputs={
            "target_tokens": target_tokens,
            "weights": weights,
        },
    )


def validate_sparse_target_rows(target_rows: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[str] = []
    position_counts: list[int] = []
    active_position_counts: list[int] = []
    max_k = 0
    for row_index, row in enumerate(target_rows):
        row_issue_count = len(issues)
        for field_name in ("prompt", "sequence", "target_token_ids", "target_weights"):
            if field_name not in row:
                issues.append(f"row {row_index}: missing {field_name!r}")
        if len(issues) > row_issue_count:
            continue
        token_rows = row["target_token_ids"]
        weight_rows = row["target_weights"]
        if not isinstance(token_rows, list) or not isinstance(weight_rows, list):
            issues.append(f"row {row_index}: target_token_ids and target_weights must be lists")
            continue
        if len(token_rows) != len(weight_rows):
            issues.append(f"row {row_index}: position count mismatch")
            continue
        position_counts.append(len(token_rows))
        active_count = 0
        for position_index, (tokens, weights) in enumerate(zip(token_rows, weight_rows, strict=True)):
            if not isinstance(tokens, list) or not isinstance(weights, list):
                issues.append(f"row {row_index} position {position_index}: tokens and weights must be lists")
                continue
            if len(tokens) != len(weights):
                issues.append(f"row {row_index} position {position_index}: token/weight count mismatch")
                continue
            if not tokens:
                issues.append(f"row {row_index} position {position_index}: empty target set")
                continue
            max_k = max(max_k, len(tokens))
            weight_sum = sum(float(weight) for weight in weights)
            if weight_sum > 0:
                active_count += 1
                if abs(weight_sum - 1.0) > 1e-3:
                    issues.append(f"row {row_index} position {position_index}: weights sum to {weight_sum:.6f}")
        active_position_counts.append(active_count)

    if issues:
        preview = "; ".join(issues[:10])
        suffix = "" if len(issues) <= 10 else f"; plus {len(issues) - 10} more"
        raise RuntimeError(f"Sparse OPD target shape validation failed: {preview}{suffix}")

    return {
        "target_count": len(target_rows),
        "position_count_min": min(position_counts, default=0),
        "position_count_mean": round(sum(position_counts) / max(1, len(position_counts)), 4),
        "position_count_max": max(position_counts, default=0),
        "active_position_count_min": min(active_position_counts, default=0),
        "active_position_count_mean": round(sum(active_position_counts) / max(1, len(active_position_counts)), 4),
        "active_position_count_max": max(active_position_counts, default=0),
        "max_sparse_k": max_k,
    }


def logsumexp(values: Any) -> float:
    values = list(values)
    if not values:
        return float("-inf")
    max_value = max(values)
    if math.isinf(max_value):
        return max_value
    return max_value + math.log(sum(math.exp(value - max_value) for value in values))


def mean_float(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 8)


def as_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
