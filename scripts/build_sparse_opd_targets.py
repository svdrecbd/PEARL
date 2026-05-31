#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.io_utils import atomic_write_json
from pearl.opd_lite import build_sparse_poe_target_row
from pearl.preference_distillation import load_jsonl, write_jsonl


def main() -> None:
    args = parse_args()
    trace_path = repo_path(args.teacher_trace_path)
    output_dir = repo_path(args.output_dir) / sanitize_name(args.name)
    output_dir.mkdir(parents=True, exist_ok=True)

    target_path = output_dir / "sparse_opd_targets.jsonl"
    manifest_path = output_dir / "manifest.json"
    raw_rows = load_jsonl(trace_path)
    if args.max_rows is not None:
        raw_rows = raw_rows[: args.max_rows]
    if not raw_rows:
        raise RuntimeError("No teacher trace rows were provided")

    targets: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for row_index, row in enumerate(raw_rows):
        try:
            target = build_sparse_poe_target_row(
                row,
                top_k=args.top_k,
                missing_logprob=args.missing_logprob,
                min_teacher_count=args.min_teacher_count,
            )
        except Exception as exc:  # noqa: BLE001 - this is a data-prep report.
            failures.append({"row_index": row_index, "error": str(exc)})
            if args.fail_fast:
                raise
            continue
        targets.append(target)

    if not targets:
        preview = "; ".join(f"{failure['row_index']}: {failure['error']}" for failure in failures[:5])
        raise RuntimeError(f"No sparse OPD targets were built. Failures: {preview}")

    write_jsonl(target_path, targets)
    manifest = build_manifest(
        args=args,
        trace_path=trace_path,
        target_path=target_path,
        raw_count=len(raw_rows),
        targets=targets,
        failures=failures,
    )
    atomic_write_json(manifest_path, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build sparse multi-teacher OPD distillation targets from teacher top-K traces. "
            "This does not require a full-logits API."
        )
    )
    parser.add_argument("--name", default="phase8-sparse-opd")
    parser.add_argument(
        "--teacher-trace-path",
        required=True,
        help="JSONL file containing one rollout row with top-K traces from each teacher.",
    )
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "opd_lite"))
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--missing-logprob", type=float, default=-30.0)
    parser.add_argument("--min-teacher-count", type=int, default=1)
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--fail-fast", action="store_true")
    return parser.parse_args()


def build_manifest(
    *,
    args: argparse.Namespace,
    trace_path: Path,
    target_path: Path,
    raw_count: int,
    targets: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    teacher_counter: Counter[str] = Counter()
    position_counts: list[int] = []
    disagreements: list[float] = []
    dropped_positions = 0
    for target in targets:
        consensus = target["consensus"]
        teacher_counter.update(consensus["teacher_names"])
        position_counts.append(int(consensus["position_count"]))
        dropped_positions += int(consensus["dropped_position_count"])
        disagreements.append(float(consensus["mean_sparse_disagreement"]))

    return {
        "name": args.name,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "trace_path": str(trace_path),
        "target_path": str(target_path),
        "raw_row_count": raw_count,
        "target_count": len(targets),
        "failure_count": len(failures),
        "failures_preview": failures[:10],
        "top_k": args.top_k,
        "missing_logprob": args.missing_logprob,
        "min_teacher_count": args.min_teacher_count,
        "teacher_trace_counts": dict(sorted(teacher_counter.items())),
        "position_count": {
            "min": min(position_counts, default=0),
            "mean": round(sum(position_counts) / max(1, len(position_counts)), 4),
            "max": max(position_counts, default=0),
            "dropped": dropped_positions,
        },
        "mean_sparse_disagreement": round(sum(disagreements) / max(1, len(disagreements)), 8),
        "ready_for_sparse_opd_smoke": bool(targets) and not failures,
        "blocked_exact_proteinopd_requirement": "full_vocab_student_and_teacher_logits",
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
    return sanitized or "phase8-sparse-opd"


if __name__ == "__main__":
    main()
