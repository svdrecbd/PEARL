#!/usr/bin/env python3
"""Fail-closed terminal structural analysis for the scaling-paradox confirmatory matrix."""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "experiments" / "scaling_paradox_structural_v1.json"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float]:
    if total <= 0:
        return [0.0, 0.0]
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)) / denominator
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def load_terminal_reports(reports_dir: Path, *, terminal_step: int) -> dict[tuple[str, str, int], dict[str, Any]]:
    cells: dict[tuple[str, str, int], dict[str, Any]] = {}
    for path in sorted(reports_dir.rglob("structure_report.json")):
        report = read_json(path)
        if report.get("status") != "complete" or not report.get("complete"):
            raise RuntimeError(f"incomplete structural report: {path}")
        generation = report["contract"]
        source_contract_path = path.with_name("generation_contract.json")
        if source_contract_path.exists():
            source = read_json(source_contract_path)
        else:
            source = None
            generation_report_path = path.with_name("generation_report.json")
            if generation_report_path.exists():
                source = read_json(generation_report_path).get("contract")
        if source is None:
            run_key = str(generation["generation_run_key"])
            candidates = list(reports_dir.rglob(f"{run_key}/generation_contract.json"))
            if len(candidates) == 1:
                source = read_json(candidates[0])
        if source is None:
            raise RuntimeError(f"missing generation contract for {path}")
        step = int(source["checkpoint_step"])
        if step not in (0, terminal_step):
            continue
        key = (str(source["model"]), str(source["arm"]), int(source["training_seed"]))
        if key in cells:
            raise RuntimeError(f"duplicate terminal structural cell {key}")
        cells[key] = {"path": str(path), "source": source, "report": report}
    return cells


def validate_matrix(cells: dict[tuple[str, str, int], dict[str, Any]], training: dict[str, Any]) -> None:
    models = [str(row["model"]) for row in training["models"]]
    seeds = [int(value) for value in training["training_seeds"]]
    required = {(model, "base", 0) for model in models}
    required |= {(model, arm, seed) for model in models for arm in ("true", "shuffled") for seed in seeds}
    missing = sorted(required - set(cells))
    unexpected = sorted(set(cells) - required)
    if missing or unexpected:
        raise RuntimeError(f"terminal structural matrix mismatch: missing={missing}, unexpected={unexpected}")


def summarize_cell(cell: dict[str, Any]) -> dict[str, Any]:
    report = cell["report"]
    total = int(report["expected_candidate_count"])
    completed = int(report["completed_candidate_count"])
    if completed != total:
        raise RuntimeError(f"cell is not fully observed: {cell['path']}")
    passes = int(report["full_structural_gate_passes"])
    results = report.get("results", [])
    return {
        "model": cell["source"]["model"],
        "arm": cell["source"]["arm"],
        "training_seed": int(cell["source"]["training_seed"]),
        "checkpoint_step": int(cell["source"]["checkpoint_step"]),
        "attempts": total,
        "passes": passes,
        "yield": passes / total,
        "yield_wilson_95ci": wilson_interval(passes, total),
        "invalid_generations": sum(not bool(row.get("valid_generation")) for row in results),
        "duplicate_generations": sum(bool(row.get("duplicate_sequence")) for row in results),
        "source_report": cell["path"],
    }


def hierarchical_seed_bootstrap(
    contrasts: list[dict[str, Any]], *, seeds: list[int], samples: int = 10_000, seed: int = 20260811
) -> dict[str, Any]:
    rng = random.Random(seed)
    by_model: dict[str, dict[int, float]] = {}
    for row in contrasts:
        by_model.setdefault(str(row["model"]), {})[int(row["training_seed"])] = float(row["delta"])
    draws: list[float] = []
    for _ in range(samples):
        model_means: list[float] = []
        for model in sorted(by_model):
            sampled_seeds = rng.choices(seeds, k=len(seeds))
            model_means.append(statistics.fmean(by_model[model][value] for value in sampled_seeds))
        draws.append(statistics.fmean(model_means))
    observed = statistics.fmean(row["delta"] for row in contrasts)
    return {
        "mean_delta": observed,
        "hierarchical_seed_bootstrap_95ci": [percentile(draws, 0.025), percentile(draws, 0.975)],
        "bootstrap_samples": samples,
        "bootstrap_seed": seed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--reports-dir", default=str(ROOT / "reports" / "scaling_paradox_v1" / "structural"))
    parser.add_argument("--output", default=str(ROOT / "reports" / "scaling_paradox_v1" / "structural_analysis.json"))
    args = parser.parse_args()
    config = read_json(repo_path(args.config))
    training = read_json(repo_path(config["training_config"]))
    terminal_step = max(int(value) for value in config["checkpoints"]["primary"])
    cells = load_terminal_reports(repo_path(args.reports_dir), terminal_step=terminal_step)
    validate_matrix(cells, training)
    summaries = [summarize_cell(cells[key]) for key in sorted(cells)]
    index = {(row["model"], row["arm"], row["training_seed"]): row for row in summaries}
    seeds = [int(value) for value in training["training_seeds"]]
    contrasts: list[dict[str, Any]] = []
    for model in [str(row["model"]) for row in training["models"]]:
        base = index[(model, "base", 0)]["yield"]
        for seed in seeds:
            true_yield = index[(model, "true", seed)]["yield"]
            shuffled_yield = index[(model, "shuffled", seed)]["yield"]
            contrasts.extend(
                [
                    {"model": model, "training_seed": seed, "contrast": "true_minus_base", "delta": true_yield - base},
                    {"model": model, "training_seed": seed, "contrast": "shuffled_minus_base", "delta": shuffled_yield - base},
                    {"model": model, "training_seed": seed, "contrast": "true_minus_shuffled", "delta": true_yield - shuffled_yield},
                ]
            )
    inference = {
        name: hierarchical_seed_bootstrap(
            [row for row in contrasts if row["contrast"] == name],
            seeds=seeds,
        )
        for name in ("true_minus_base", "shuffled_minus_base", "true_minus_shuffled")
    }
    payload = {
        "contract": "pearl.scaling-paradox-structural-analysis/1",
        "analysis_unit": config["analysis"]["experimental_unit"],
        "candidate_observations_are_nested": True,
        "matrix_complete": True,
        "cells": summaries,
        "seed_level_contrasts": contrasts,
        "inference": inference,
    }
    output = repo_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "cells"}, indent=2))


if __name__ == "__main__":
    main()
