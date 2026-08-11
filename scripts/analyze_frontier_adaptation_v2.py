#!/usr/bin/env python3
"""Fail-closed family-stratified analysis of the frozen frontier-adaptation v2 matrix."""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import statistics
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXECUTOR = ROOT / "configs/experiments/frontier_adaptation_v2_executor.json"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_value(value: Any) -> str:
    import hashlib

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_manager() -> Any:
    path = ROOT / "scripts/manage_scaling_paradox_campaign.py"
    spec = importlib.util.spec_from_file_location("frontier_campaign_manager", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load frozen campaign manager")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mean_interval(values: list[float]) -> dict[str, Any]:
    if not values:
        raise RuntimeError("cannot summarize an empty contrast")
    mean = statistics.fmean(values)
    critical = {3: 4.3026527297, 6: 2.5705818356}.get(len(values), 1.9599639845)
    half = 0.0 if len(values) == 1 else critical * statistics.stdev(values) / math.sqrt(len(values))
    return {
        "n_independent_training_seeds": len(values),
        "mean": mean,
        "mean_t_95ci": [mean - half, mean + half],
        "positive_seed_count": sum(value > 0.0 for value in values),
        "negative_seed_count": sum(value < 0.0 for value in values),
        "zero_seed_count": sum(value == 0.0 for value in values),
    }


def exact_sign_flip(values: list[float]) -> dict[str, Any]:
    observed = abs(statistics.fmean(values))
    draws = [
        abs(statistics.fmean(sign * value for sign, value in zip(signs, values, strict=True)))
        for signs in itertools.product((-1.0, 1.0), repeat=len(values))
    ]
    return {
        "test": "exact_two_sided_sign_flip_of_seed_level_contrasts",
        "permutation_count": len(draws),
        "observed_absolute_mean": observed,
        "two_sided_p_value": sum(draw >= observed - 1e-15 for draw in draws) / len(draws),
    }


def endpoint_value(report: dict[str, Any], partition: str) -> float:
    value = (
        report.get(partition, {})
        .get("diagnostics", {})
        .get("per_residue", {})
        .get("margin_delta_mean")
    )
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise RuntimeError(f"evaluation lacks finite {partition} per-residue margin delta")
    return float(value)


def load_cells(
    evaluations_root: Path,
    state_dir: Path,
    plans: dict[tuple[str, str], dict[str, Any]],
) -> dict[tuple[str, str, str, int], dict[str, Any]]:
    expected = {
        str(row["run_contract_sha"]): (cohort, row)
        for (cohort, stage), plan in plans.items()
        if stage == "core"
        for row in plan["runs"]
    }
    cells: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    seen_run_keys: set[str] = set()
    for path in sorted(evaluations_root.rglob("evaluation_report.json")):
        report = read_json(path)
        contract = report.get("contract") or {}
        source_sha = str(contract.get("source_run_contract_sha") or "")
        if source_sha not in expected:
            continue
        cohort, entry = expected[source_sha]
        run_key = str(entry["run_key"])
        if run_key in seen_run_keys:
            raise RuntimeError(f"duplicate evaluation report for {run_key}")
        if (
            report.get("status") != "complete"
            or not report.get("complete")
            or contract.get("source_run_key") != run_key
        ):
            raise RuntimeError(f"incomplete or contract-mismatched evaluation: {path}")
        receipt_path = state_dir / "receipts/evaluation" / f"{run_key}.json"
        if not receipt_path.is_file():
            raise RuntimeError(f"missing audited evaluation receipt for {run_key}")
        receipt = read_json(receipt_path)
        if (
            not receipt.get("evaluation_terminal_valid")
            or receipt.get("run_key") != run_key
            or receipt.get("evaluation_report_file_sha256") != sha256_file(path)
            or receipt.get("receipt_sha256")
            != sha256_value({key: value for key, value in receipt.items() if key != "receipt_sha256"})
        ):
            raise RuntimeError(f"evaluation report is not bound to its audit receipt: {run_key}")
        key = (cohort, str(entry["model_tag"]), str(entry["arm"]), int(entry["training_seed"]))
        if key in cells:
            raise RuntimeError(f"duplicate matrix cell {key}")
        cells[key] = {
            "cohort": cohort,
            "model_tag": entry["model_tag"],
            "model": entry["model"],
            "model_family": entry["model_family"],
            "model_generation": entry["model_generation"],
            "total_parameters_b": entry["total_parameters_b"],
            "active_parameters_b": entry["active_parameters_b"],
            "arm": entry["arm"],
            "training_seed": int(entry["training_seed"]),
            "run_key": run_key,
            "run_contract_sha": source_sha,
            "holdout_margin_delta_per_residue": endpoint_value(report, "holdout"),
            "challenge_margin_delta_per_residue": endpoint_value(report, "challenge"),
            "evaluation_report_sha256": sha256_file(path),
            "evaluation_receipt_sha256": receipt["receipt_sha256"],
        }
        seen_run_keys.add(run_key)
    if len(cells) != 96 or seen_run_keys != {row[1]["run_key"] for row in expected.values()}:
        raise RuntimeError(f"frontier evaluation matrix is incomplete: expected 96, observed {len(cells)}")
    return cells


def analyze_endpoint(
    cells: dict[tuple[str, str, str, int], dict[str, Any]],
    configs: dict[str, dict[str, Any]],
    executor: dict[str, Any],
    field: str,
) -> dict[str, Any]:
    effects: dict[tuple[str, str, int], float] = {}
    arm_rows: list[dict[str, Any]] = []
    for cohort, config in configs.items():
        for model in config["models"]:
            tag = str(model["tag"])
            for seed in config["training_seeds"]:
                value = cells[(cohort, tag, "true", int(seed))][field] - cells[
                    (cohort, tag, "shuffled", int(seed))
                ][field]
                effects[(cohort, tag, int(seed))] = value
                arm_rows.append(
                    {
                        "cohort": cohort,
                        "model_tag": tag,
                        "training_seed": int(seed),
                        "contrast": "true_minus_shuffled",
                        "value": value,
                    }
                )
    comparisons: dict[str, Any] = {}
    for small, large in executor["analysis_contract"]["primary_pairs"]:
        name = f"{small}_minus_{large}"
        by_cohort: dict[str, Any] = {}
        combined: list[float] = []
        for cohort, config in configs.items():
            values = [
                effects[(cohort, small, int(seed))] - effects[(cohort, large, int(seed))]
                for seed in config["training_seeds"]
            ]
            by_cohort[cohort] = {"summary": mean_interval(values), "exact_sign_flip": exact_sign_flip(values)}
            combined.extend(values)
        comparisons[name] = {
            "direction": "positive_means_smaller_model_has_larger_true_minus_shuffled_effect",
            "cohorts": by_cohort,
            "combined": {"summary": mean_interval(combined), "exact_sign_flip": exact_sign_flip(combined)},
        }
    release_controls: dict[str, Any] = {}
    for older, newer in executor["analysis_contract"]["release_controls"]:
        values_by_cohort: dict[str, Any] = {}
        combined = []
        for cohort, config in configs.items():
            values = [
                effects[(cohort, newer, int(seed))] - effects[(cohort, older, int(seed))]
                for seed in config["training_seeds"]
            ]
            values_by_cohort[cohort] = mean_interval(values)
            combined.extend(values)
        release_controls[f"{newer}_minus_{older}"] = {
            "direction": "positive_means_new_release_has_larger_true_minus_shuffled_effect_at_matched_capacity",
            "cohorts": values_by_cohort,
            "combined": mean_interval(combined),
        }
    return {
        "arm_effects": arm_rows,
        "within_family_scaling_contrasts": comparisons,
        "matched_capacity_release_controls": release_controls,
        "architecture_families_are_not_pooled": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor-config", default=str(DEFAULT_EXECUTOR))
    parser.add_argument("--evaluations-root", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    executor = read_json(repo_path(args.executor_config))
    manager = load_manager()
    plans = manager.build_plans(executor)
    configs = {
        cohort: read_json(ROOT / campaign["config"])
        for cohort, campaign in executor["campaigns"].items()
    }
    cells = load_cells(repo_path(args.evaluations_root), repo_path(args.state_dir), plans)
    payload = {
        "contract": "pearl.frontier-adaptation-optimization-analysis/2",
        "matrix_cell_count": len(cells),
        "primary_endpoint": "holdout_per_residue_margin_delta_true_minus_shuffled",
        "secondary_endpoint": "real_failure_challenge_per_residue_margin_delta_true_minus_shuffled",
        "experimental_unit": "independent_training_seed",
        "candidate_or_pair_rows_are_not_replicates": True,
        "model_sizes_are_categorical_within_family": True,
        "pooled_raw_parameter_regression_performed": False,
        "holdout": analyze_endpoint(cells, configs, executor, "holdout_margin_delta_per_residue"),
        "real_failure_challenge": analyze_endpoint(
            cells, configs, executor, "challenge_margin_delta_per_residue"
        ),
        "cells": [cells[key] for key in sorted(cells)],
        "source_plan_shas": {
            cohort: plans[(cohort, "core")]["launch_plan_contract_sha"] for cohort in configs
        },
        "executor_config_sha256": sha256_file(repo_path(args.executor_config)),
    }
    output = repo_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "complete", "matrix_cells": len(cells)}))


if __name__ == "__main__":
    main()
