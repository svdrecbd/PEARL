from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TeacherTraceSpec:
    name: str
    weight: float
    temperature: float
    model_path: str | None = None
    base_model: str | None = None


def parse_teacher_spec(value: str) -> TeacherTraceSpec:
    fields: dict[str, str] = {}
    for part in value.split(","):
        if not part.strip():
            continue
        if "=" not in part:
            raise ValueError(f"teacher spec part {part!r} is missing '='")
        key, raw_value = part.split("=", 1)
        fields[key.strip()] = raw_value.strip()

    name = fields.get("name")
    if not name:
        raise ValueError("teacher spec is missing name=...")
    model_path = fields.get("path") or fields.get("model_path")
    base_model = fields.get("base_model")
    if not model_path and not base_model:
        raise ValueError(f"teacher {name!r} must provide path=... or base_model=...")
    weight = as_float(fields.get("weight"), default=1.0)
    temperature = as_float(fields.get("temperature"), default=1.0)
    if weight < 0:
        raise ValueError(f"teacher {name!r} weight must be >= 0")
    if temperature <= 0:
        raise ValueError(f"teacher {name!r} temperature must be > 0")
    return TeacherTraceSpec(
        name=name,
        model_path=model_path,
        base_model=base_model,
        weight=weight,
        temperature=temperature,
    )


def extract_sequence_topk_positions(
    *,
    full_topk_prompt_logprobs: list[Any],
    prompt_token_count: int,
    sequence_token_count: int,
    teacher_name: str,
) -> list[dict[str, list[float] | list[int]]]:
    start = prompt_token_count
    end = prompt_token_count + sequence_token_count
    if len(full_topk_prompt_logprobs) < end:
        raise ValueError(
            f"teacher {teacher_name!r} returned {len(full_topk_prompt_logprobs)} prompt top-k positions, "
            f"but {end} are required for prompt+sequence"
        )

    positions: list[dict[str, list[float] | list[int]]] = []
    for relative_position, topk_position in enumerate(full_topk_prompt_logprobs[start:end]):
        if topk_position is None:
            raise ValueError(f"teacher {teacher_name!r} returned no top-k data for sequence position {relative_position}")
        token_ids: list[int] = []
        logprobs: list[float] = []
        for item in topk_position:
            if isinstance(item, dict):
                token_id = item.get("token_id") if "token_id" in item else item.get("token")
                logprob = item.get("logprob")
            else:
                token_id, logprob = item
            token_ids.append(int(token_id))
            logprobs.append(float(logprob))
        positions.append({"token_ids": token_ids, "logprobs": logprobs})
    return positions


def build_teacher_trace_row(
    *,
    rollout: dict[str, Any],
    teacher_traces: list[dict[str, Any]],
) -> dict[str, Any]:
    sample_id = str(
        rollout.get("sample_id")
        or rollout.get("rollout_id")
        or rollout.get("candidate_id")
        or rollout.get("id")
        or ""
    )
    return {
        "sample_id": sample_id,
        "prompt": str(rollout.get("prompt") or ""),
        "sequence": str(rollout.get("sequence") or rollout.get("completion") or "").strip(),
        "teachers": {trace["name"]: trace for trace in teacher_traces},
        "source_rollout": {
            key: value
            for key, value in rollout.items()
            if key not in {"prompt", "sequence", "completion"}
        },
    }


def as_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
