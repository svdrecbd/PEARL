#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.io_utils import atomic_write_json
from pearl.preference_distillation import load_jsonl, write_jsonl
from pearl.tinker_teacher_traces import (
    TeacherTraceSpec,
    build_teacher_trace_row,
    extract_sequence_topk_positions,
    parse_teacher_spec,
)


def main() -> None:
    args = parse_args()
    rollouts_path = repo_path(args.rollouts_path)
    output_dir = repo_path(args.output_dir) / sanitize_name(args.name)
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_path = output_dir / "teacher_traces.jsonl"
    manifest_path = output_dir / "manifest.json"

    rollouts = load_jsonl(rollouts_path)
    if args.max_rollouts is not None:
        rollouts = rollouts[: args.max_rollouts]
    if not rollouts:
        raise RuntimeError("No rollout rows were provided")
    teacher_specs = [parse_teacher_spec(value) for value in args.teacher]
    validate_rollouts(rollouts)

    if args.shape_only:
        manifest = build_manifest(
            args=args,
            rollouts_path=rollouts_path,
            trace_path=trace_path,
            rollouts=rollouts,
            teacher_specs=teacher_specs,
            traced_count=0,
            status="shape_validated",
        )
        atomic_write_json(manifest_path, manifest)
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return

    import tinker
    from tinker import types

    service_client = tinker.ServiceClient(user_metadata={"pearl_task": "teacher_topk_trace_collection"})
    clients = {
        spec.name: service_client.create_sampling_client(model_path=spec.model_path, base_model=spec.base_model)
        for spec in teacher_specs
    }
    tokenizer = clients[teacher_specs[0].name].get_tokenizer()

    trace_rows: list[dict[str, Any]] = []
    for rollout_index, rollout in enumerate(rollouts):
        prompt = str(rollout.get("prompt") or "")
        sequence = str(rollout.get("sequence") or rollout.get("completion") or "").strip()
        prompt_tokens = tokenizer.encode(prompt, add_special_tokens=False)
        sequence_tokens = tokenizer.encode(sequence, add_special_tokens=False)
        if not prompt_tokens or not sequence_tokens:
            raise RuntimeError(f"rollout {rollout_index} tokenized to an empty prompt or sequence")
        full_tokens = prompt_tokens + sequence_tokens
        model_input = types.ModelInput.from_ints(full_tokens)
        sampling_params = types.SamplingParams(max_tokens=1, temperature=1.0, top_p=1.0)

        teacher_traces: list[dict[str, Any]] = []
        for spec in teacher_specs:
            response = clients[spec.name].sample(
                prompt=model_input,
                num_samples=1,
                sampling_params=sampling_params,
                include_prompt_logprobs=True,
                topk_prompt_logprobs=args.top_k,
            ).result()
            if response.topk_prompt_logprobs is None:
                raise RuntimeError(f"teacher {spec.name!r} did not return top-k prompt logprobs")
            positions = extract_sequence_topk_positions(
                full_topk_prompt_logprobs=response.topk_prompt_logprobs,
                prompt_token_count=len(prompt_tokens),
                sequence_token_count=len(sequence_tokens),
                teacher_name=spec.name,
            )
            teacher_traces.append(
                {
                    "name": spec.name,
                    "weight": spec.weight,
                    "temperature": spec.temperature,
                    "model_path": spec.model_path,
                    "base_model": spec.base_model,
                    "positions": positions,
                }
            )

        trace_rows.append(build_teacher_trace_row(rollout=rollout, teacher_traces=teacher_traces))
        if (rollout_index + 1) % args.progress_every == 0:
            print(json.dumps({"traced_rollouts": rollout_index + 1}), flush=True)

    write_jsonl(trace_path, trace_rows)
    manifest = build_manifest(
        args=args,
        rollouts_path=rollouts_path,
        trace_path=trace_path,
        rollouts=rollouts,
        teacher_specs=teacher_specs,
        traced_count=len(trace_rows),
        status="traced",
    )
    atomic_write_json(manifest_path, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect teacher-forced top-K prompt logprob traces for sparse OPD target building."
    )
    parser.add_argument("--name", default="phase8-teacher-traces")
    parser.add_argument("--rollouts-path", required=True, help="JSONL rows with prompt and sequence/completion fields.")
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "opd_lite"))
    parser.add_argument(
        "--teacher",
        action="append",
        required=True,
        help=(
            "Teacher spec. Format: name=fold,path=tinker://...,weight=0.35,temperature=0.7 "
            "or name=base,base_model=moonshotai/Kimi-K2.6,weight=1.0"
        ),
    )
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--max-rollouts", type=int)
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--shape-only", action="store_true")
    return parser.parse_args()


def validate_rollouts(rollouts: list[dict[str, Any]]) -> None:
    issues: list[str] = []
    for index, rollout in enumerate(rollouts):
        if not isinstance(rollout.get("prompt"), str) or not str(rollout.get("prompt")).strip():
            issues.append(f"row {index}: missing non-empty prompt")
        sequence = rollout.get("sequence") if "sequence" in rollout else rollout.get("completion")
        if not isinstance(sequence, str) or not sequence.strip():
            issues.append(f"row {index}: missing non-empty sequence/completion")
    if issues:
        preview = "; ".join(issues[:10])
        suffix = "" if len(issues) <= 10 else f"; plus {len(issues) - 10} more"
        raise RuntimeError(f"Teacher trace rollout validation failed: {preview}{suffix}")


def build_manifest(
    *,
    args: argparse.Namespace,
    rollouts_path: Path,
    trace_path: Path,
    rollouts: list[dict[str, Any]],
    teacher_specs: list[TeacherTraceSpec],
    traced_count: int,
    status: str,
) -> dict[str, Any]:
    return {
        "name": args.name,
        "status": status,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "rollouts_path": str(rollouts_path),
        "trace_path": str(trace_path),
        "rollout_count": len(rollouts),
        "traced_count": traced_count,
        "top_k": args.top_k,
        "teacher_count": len(teacher_specs),
        "teachers": [
            {
                "name": spec.name,
                "weight": spec.weight,
                "temperature": spec.temperature,
                "model_path": spec.model_path,
                "base_model": spec.base_model,
            }
            for spec in teacher_specs
        ],
        "ready_for_sparse_target_build": status == "traced" and traced_count == len(rollouts),
    }


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path


def sanitize_name(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "-" for char in value]
    sanitized = "".join(chars).strip("-")
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized or "phase8-teacher-traces"


if __name__ == "__main__":
    main()
