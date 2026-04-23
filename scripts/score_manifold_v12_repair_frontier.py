#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

ROOT_PATH = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT_PATH / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.paths import resolve_repo_path


ScoreFn = Callable[[list[str]], list[float]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score a v1.2 repair frontier with the local ESM proxy")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--esm-threshold", type=float, default=85.0)
    parser.add_argument("--batch-size", type=int, default=32)
    return parser.parse_args()


def resolved(value: str) -> Path:
    path = resolve_repo_path(value)
    if path is None or path.startswith("tinker://"):
        raise ValueError(f"could not resolve local path: {value}")
    return Path(path)


def read_jsonl(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def score_rows(
    rows: list[dict[str, Any]],
    *,
    score_fn: ScoreFn,
    esm_threshold: float,
    batch_size: int,
) -> list[dict[str, Any]]:
    scored_rows: list[dict[str, Any]] = []
    batch_size = max(1, int(batch_size))
    for start in range(0, len(rows), batch_size):
        batch_rows = rows[start : start + batch_size]
        scores = score_fn([str(row["sequence"]) for row in batch_rows])
        for row, score in zip(batch_rows, scores, strict=True):
            payload = dict(row)
            payload["esm_score"] = round(float(score), 4)
            payload["needs_esm_score"] = False
            payload["esm_gate_pass"] = float(score) >= float(esm_threshold)
            payload["v12_ready_candidate"] = bool(
                payload.get("strict_trainable_candidate")
                and payload.get("passes_core_screen")
                and payload["esm_gate_pass"]
            )
            scored_rows.append(payload)
    return scored_rows


def numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "mean": None, "max": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "mean": round(sum(values) / len(values), 4),
        "max": round(max(values), 4),
    }


def summarize(scored_rows: list[dict[str, Any]], *, esm_threshold: float) -> dict[str, Any]:
    scores = [float(row["esm_score"]) for row in scored_rows]
    ready_rows = [row for row in scored_rows if bool(row.get("v12_ready_candidate"))]
    by_lane = Counter(str(row.get("source_lane")) for row in scored_rows)
    ready_by_lane = Counter(str(row.get("source_lane")) for row in ready_rows)
    by_operation = Counter(str(row.get("operation")) for row in scored_rows)
    ready_by_operation = Counter(str(row.get("operation")) for row in ready_rows)
    return {
        "scored_candidates": len(scored_rows),
        "esm_threshold": float(esm_threshold),
        "score_summary": numeric_summary(scores),
        "esm_ge_85": sum(score >= 85.0 for score in scores),
        "esm_ge_90": sum(score >= 90.0 for score in scores),
        "esm_ge_95": sum(score >= 95.0 for score in scores),
        "v12_ready_candidates": len(ready_rows),
        "scored_by_lane": dict(sorted(by_lane.items())),
        "ready_by_lane": dict(sorted(ready_by_lane.items())),
        "scored_by_operation": dict(sorted(by_operation.items())),
        "ready_by_operation": dict(sorted(ready_by_operation.items())),
        "top_candidates": [
            {
                "candidate_id": row.get("candidate_id"),
                "source_lane": row.get("source_lane"),
                "operation": row.get("operation"),
                "esm_score": row.get("esm_score"),
                "mutation_count": row.get("mutation_count"),
                "length": row.get("length"),
                "prompt_length_delta": row.get("prompt_length_delta"),
            }
            for row in sorted(scored_rows, key=lambda item: float(item.get("esm_score") or 0.0), reverse=True)[:20]
        ],
    }


def score_frontier(args: argparse.Namespace) -> dict[str, Any]:
    from pearl.esm_proxy import get_esm2_plddt_scores, prewarm_esm2_model

    input_path = resolved(args.input_path)
    output_path = resolved(args.output_path)
    summary_path = resolved(args.summary_path)
    started = datetime.now(UTC)
    rows = read_jsonl(input_path, limit=args.limit)
    esm_info = prewarm_esm2_model()
    scored_rows = score_rows(
        rows,
        score_fn=get_esm2_plddt_scores,
        esm_threshold=float(args.esm_threshold),
        batch_size=int(args.batch_size),
    )
    write_jsonl(output_path, scored_rows)
    summary = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "duration_seconds": round((datetime.now(UTC) - started).total_seconds(), 3),
        "input_path": str(input_path),
        "output_path": str(output_path),
        "summary_path": str(summary_path),
        "limit": args.limit,
        "batch_size": int(args.batch_size),
        "esm_info": esm_info,
        **summarize(scored_rows, esm_threshold=float(args.esm_threshold)),
        "next_step": "If v12_ready_candidates is nonzero, run diversity selection before any paid gate.",
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    args = parse_args()
    print(json.dumps(score_frontier(args), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
