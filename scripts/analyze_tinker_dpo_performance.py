#!/usr/bin/env python3
"""Compare clock-cycle and client timing evidence across two DPO continuation segments."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_batches(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"{path} is not a nonempty batch history")
    if not all(isinstance(row, dict) for row in payload):
        raise RuntimeError(f"{path} contains a non-object batch row")
    return payload


def nearest_rank(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def segment_summary(
    rows: list[dict[str, Any]],
    *,
    start_step: int,
    end_step: int,
) -> dict[str, Any]:
    if not (1 <= start_step < end_step <= len(rows)):
        raise RuntimeError(
            "segment bounds must identify at least two recorded optimizer steps"
        )
    segment = rows[start_step - 1 : end_step]
    clocks: list[float] = []
    client_seconds: list[float] = []
    schedule: str | None = None
    for step, row in enumerate(segment, start=start_step):
        metrics = row.get("forward_backward_metrics")
        if not isinstance(metrics, dict) or "clock_cycle:unique" not in metrics:
            raise RuntimeError(f"step {step} has no backend clock-cycle metric")
        clocks.append(float(metrics["clock_cycle:unique"]))
        performance = row.get("performance")
        if performance is not None:
            if not isinstance(performance, dict):
                raise RuntimeError(f"step {step} has malformed performance evidence")
            if performance.get("contract") != "pearl.dpo-step-performance/1":
                raise RuntimeError(f"step {step} has the wrong performance contract")
            row_schedule = str(performance.get("request_schedule") or "")
            if not row_schedule:
                raise RuntimeError(f"step {step} has no request schedule")
            if schedule is not None and row_schedule != schedule:
                raise RuntimeError("segment mixes request schedules")
            schedule = row_schedule
            client_seconds.append(float(performance["client_step_wall_seconds"]))
    gaps = [current - previous for previous, current in zip(clocks, clocks[1:])]
    if any(gap <= 0 for gap in gaps):
        raise RuntimeError("backend clock-cycle sequence is not strictly increasing")
    return {
        "start_step": start_step,
        "end_step": end_step,
        "optimizer_updates": len(segment),
        "clock_gap_observations": len(gaps),
        "clock_gap_mean": statistics.mean(gaps),
        "clock_gap_median": statistics.median(gaps),
        "clock_gap_p90": nearest_rank(gaps, 0.9),
        "clock_gap_min": min(gaps),
        "clock_gap_max": max(gaps),
        "request_schedule": schedule,
        "client_step_wall_seconds_mean": (
            statistics.mean(client_seconds)
            if len(client_seconds) == len(segment)
            else None
        ),
        "client_step_wall_seconds_median": (
            statistics.median(client_seconds)
            if len(client_seconds) == len(segment)
            else None
        ),
    }


def analyze(
    *,
    baseline_path: Path,
    candidate_path: Path,
    baseline_start_step: int,
    baseline_end_step: int,
    candidate_start_step: int,
    candidate_end_step: int,
) -> dict[str, Any]:
    baseline_rows = load_batches(baseline_path)
    candidate_rows = load_batches(candidate_path)
    if len(candidate_rows) <= len(baseline_rows):
        raise RuntimeError(
            "candidate history does not extend the baseline continuation"
        )
    if candidate_rows[: len(baseline_rows)] != baseline_rows:
        raise RuntimeError(
            "candidate history does not preserve the exact baseline prefix"
        )
    if candidate_start_step <= len(baseline_rows):
        raise RuntimeError("candidate segment overlaps the baseline history")

    baseline = segment_summary(
        baseline_rows,
        start_step=baseline_start_step,
        end_step=baseline_end_step,
    )
    candidate = segment_summary(
        candidate_rows,
        start_step=candidate_start_step,
        end_step=candidate_end_step,
    )
    baseline_median = float(baseline["clock_gap_median"])
    candidate_median = float(candidate["clock_gap_median"])
    return {
        "contract": "pearl.dpo-performance-comparison/1",
        "scientific_values_omitted": True,
        "baseline_batch_history_sha256": sha256_file(baseline_path),
        "candidate_batch_history_sha256": sha256_file(candidate_path),
        "baseline": baseline,
        "candidate": candidate,
        "clock_gap_median_speedup": baseline_median / candidate_median,
        "clock_gap_median_reduction_fraction": 1.0
        - (candidate_median / baseline_median),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-batches", type=Path, required=True)
    parser.add_argument("--candidate-batches", type=Path, required=True)
    parser.add_argument("--baseline-start-step", type=int, required=True)
    parser.add_argument("--baseline-end-step", type=int, required=True)
    parser.add_argument("--candidate-start-step", type=int, required=True)
    parser.add_argument("--candidate-end-step", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze(
        baseline_path=args.baseline_batches,
        candidate_path=args.candidate_batches,
        baseline_start_step=args.baseline_start_step,
        baseline_end_step=args.baseline_end_step,
        candidate_start_step=args.candidate_start_step,
        candidate_end_step=args.candidate_end_step,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
