from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_analyzer():
    path = ROOT / "scripts" / "analyze_tinker_dpo_performance.py"
    spec = importlib.util.spec_from_file_location(
        "analyze_tinker_dpo_performance", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(clock: int, *, pipelined: bool = False) -> dict:
    payload = {
        "epoch": 0,
        "batch_index": clock,
        "forward_backward_metrics": {"clock_cycle:unique": float(clock)},
        "optim_step_metrics": {},
    }
    if pipelined:
        payload["performance"] = {
            "contract": "pearl.dpo-step-performance/1",
            "request_schedule": "custom_backward_then_optimizer_before_result",
            "client_step_wall_seconds": 2.0,
            "client_submission_wall_seconds": 1.0,
            "client_result_wait_wall_seconds": 1.0,
        }
    return payload


def test_analyzer_requires_exact_history_and_measures_clock_gap_speedup(
    tmp_path: Path,
) -> None:
    analyzer = load_analyzer()
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    baseline = [row(clock) for clock in (10, 16, 22, 28)]
    candidate = baseline + [row(clock, pipelined=True) for clock in (31, 34, 37, 40)]
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    report = analyzer.analyze(
        baseline_path=baseline_path,
        candidate_path=candidate_path,
        baseline_start_step=1,
        baseline_end_step=4,
        candidate_start_step=5,
        candidate_end_step=8,
    )

    assert report["baseline"]["clock_gap_median"] == 6.0
    assert report["candidate"]["clock_gap_median"] == 3.0
    assert report["clock_gap_median_speedup"] == 2.0
    assert report["clock_gap_median_reduction_fraction"] == 0.5
    assert report["candidate"]["client_step_wall_seconds_median"] == 2.0


def test_analyzer_rejects_a_changed_historical_prefix(tmp_path: Path) -> None:
    analyzer = load_analyzer()
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    baseline = [row(clock) for clock in (10, 16, 22)]
    candidate = [row(clock) for clock in (10, 17, 22)] + [row(25, pipelined=True)]
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

    with pytest.raises(RuntimeError, match="exact baseline prefix"):
        analyzer.analyze(
            baseline_path=baseline_path,
            candidate_path=candidate_path,
            baseline_start_step=1,
            baseline_end_step=3,
            candidate_start_step=4,
            candidate_end_step=4,
        )
