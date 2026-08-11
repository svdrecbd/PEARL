#!/usr/bin/env python3
"""Run the frozen original, replication, and combined scaling-paradox optimization analysis."""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import statistics
import hashlib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXECUTOR = ROOT / "configs" / "experiments" / "scaling_paradox_executor_v1.json"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_value(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_launcher() -> Any:
    path = ROOT / "scripts" / "launch_scaling_paradox_v1.py"
    spec = importlib.util.spec_from_file_location("scaling_paradox_launcher", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the frozen scaling-paradox launcher")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def core_plan(config_path: Path) -> dict[str, Any]:
    launcher = load_launcher()
    config = read_json(config_path)
    manifest = read_json(repo_path(config["dataset_manifest"]))
    return launcher.build_plan(config, manifest, "core")


def mean_interval(values: list[float]) -> dict[str, Any]:
    if not values:
        raise RuntimeError("cannot summarize an empty contrast")
    mean = statistics.fmean(values)
    if len(values) == 1:
        interval = [mean, mean]
    else:
        critical = {3: 4.3026527297, 6: 2.5705818356}.get(len(values), 1.9599639845)
        half = critical * statistics.stdev(values) / math.sqrt(len(values))
        interval = [mean - half, mean + half]
    return {
        "n_training_seeds": len(values),
        "mean": mean,
        "mean_t_95ci": interval,
        "positive_seed_count": sum(value > 0.0 for value in values),
        "zero_seed_count": sum(value == 0.0 for value in values),
    }


def exact_sign_flip_test(values: list[float]) -> dict[str, Any]:
    if not values:
        raise RuntimeError("sign-flip test requires observations")
    observed = abs(statistics.fmean(values))
    draws = [
        abs(statistics.fmean(sign * value for sign, value in zip(signs, values, strict=True)))
        for signs in itertools.product((-1.0, 1.0), repeat=len(values))
    ]
    extreme = sum(draw >= observed - 1e-15 for draw in draws)
    return {
        "test": "exact_two_sided_sign_flip_of_seed_level_contrasts",
        "observed_absolute_mean": observed,
        "permutation_count": len(draws),
        "two_sided_p_value": extreme / len(draws),
    }


def load_evaluations(
    root: Path, plans: dict[str, dict[str, Any]]
) -> dict[tuple[str, str, str, int], dict[str, Any]]:
    expected_by_sha: dict[str, tuple[str, dict[str, Any]]] = {}
    for cohort, plan in plans.items():
        for row in plan["runs"]:
            expected_by_sha[str(row["run_contract_sha"])] = (cohort, row)
    cells: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    for path in sorted(root.rglob("evaluation_report.json")):
        report = read_json(path)
        if report.get("status") != "complete" or not report.get("complete"):
            raise RuntimeError(f"incomplete checkpoint evaluation: {path}")
        contract = report.get("contract") or {}
        source_sha = str(contract.get("source_run_contract_sha") or "")
        if source_sha not in expected_by_sha:
            continue
        cohort, plan_entry = expected_by_sha[source_sha]
        if contract.get("source_run_key") != plan_entry["run_key"]:
            raise RuntimeError(f"evaluation run key mismatch: {path}")
        metric = (
            report.get("holdout", {})
            .get("diagnostics", {})
            .get("per_residue", {})
            .get("margin_delta_mean")
        )
        if not isinstance(metric, (int, float)) or not math.isfinite(float(metric)):
            raise RuntimeError(f"evaluation lacks the primary per-residue endpoint: {path}")
        key = (
            cohort,
            str(plan_entry["model_tag"]),
            str(plan_entry["arm"]),
            int(plan_entry["training_seed"]),
        )
        if key in cells:
            raise RuntimeError(f"duplicate checkpoint evaluation for {key}")
        cells[key] = {
            "cohort": cohort,
            "model_tag": plan_entry["model_tag"],
            "model": plan_entry["model"],
            "arm": plan_entry["arm"],
            "training_seed": int(plan_entry["training_seed"]),
            "run_key": plan_entry["run_key"],
            "run_contract_sha": source_sha,
            "holdout_per_residue_margin_delta_mean": float(metric),
            "source_evaluation_report": str(path),
            "source_evaluation_report_sha256": sha256_file(path),
        }
    expected_count = sum(int(plan["run_count"]) for plan in plans.values())
    if len(cells) != expected_count:
        raise RuntimeError(f"core evaluation matrix is incomplete: expected {expected_count}, observed {len(cells)}")
    return cells


def cohort_contrasts(
    cells: dict[tuple[str, str, str, int], dict[str, Any]],
    cohort: str,
    seeds: list[int],
) -> dict[str, Any]:
    arm_effects: list[dict[str, Any]] = []
    capacity: list[dict[str, Any]] = []
    for seed in seeds:
        effects: dict[str, float] = {}
        for model_tag in ("qwen3p5-4b", "qwen3p5-9b", "qwen3p6-27b"):
            true_value = cells[(cohort, model_tag, "true", seed)][
                "holdout_per_residue_margin_delta_mean"
            ]
            shuffled_value = cells[(cohort, model_tag, "shuffled", seed)][
                "holdout_per_residue_margin_delta_mean"
            ]
            effects[model_tag] = true_value - shuffled_value
            arm_effects.append(
                {
                    "cohort": cohort,
                    "training_seed": seed,
                    "model_tag": model_tag,
                    "contrast": "true_minus_shuffled",
                    "value": effects[model_tag],
                }
            )
        capacity.append(
            {
                "cohort": cohort,
                "training_seed": seed,
                "clean_4b_minus_9b": effects["qwen3p5-4b"] - effects["qwen3p5-9b"],
                "extension_4b_minus_27b": effects["qwen3p5-4b"] - effects["qwen3p6-27b"],
                "effect_4b": effects["qwen3p5-4b"],
                "effect_9b": effects["qwen3p5-9b"],
                "effect_27b": effects["qwen3p6-27b"],
            }
        )
    return {
        "arm_effects": arm_effects,
        "capacity_contrasts": capacity,
        "summaries": {
            "clean_4b_minus_9b": mean_interval([row["clean_4b_minus_9b"] for row in capacity]),
            "extension_4b_minus_27b": mean_interval(
                [row["extension_4b_minus_27b"] for row in capacity]
            ),
            "effect_4b": mean_interval([row["effect_4b"] for row in capacity]),
            "effect_9b": mean_interval([row["effect_9b"] for row in capacity]),
            "effect_27b": mean_interval([row["effect_27b"] for row in capacity]),
        },
    }


def evaluate_rescue_gate(
    original: dict[str, Any], replication: dict[str, Any], gate: dict[str, Any]
) -> dict[str, Any]:
    combined = original["capacity_contrasts"] + replication["capacity_contrasts"]
    predicates = {
        "original_clean_mean_positive": original["summaries"]["clean_4b_minus_9b"]["mean"] > 0.0,
        "original_clean_positive_seeds": original["summaries"]["clean_4b_minus_9b"][
            "positive_seed_count"
        ]
        >= int(gate["original_clean_positive_seed_count_minimum"]),
        "replication_clean_mean_positive": replication["summaries"]["clean_4b_minus_9b"]["mean"]
        > 0.0,
        "replication_clean_positive_seeds": replication["summaries"]["clean_4b_minus_9b"][
            "positive_seed_count"
        ]
        >= int(gate["replication_clean_positive_seed_count_minimum"]),
        "combined_4b_effect_mean_positive": statistics.fmean(row["effect_4b"] for row in combined)
        > 0.0,
        "combined_clean_positive_seeds": sum(row["clean_4b_minus_9b"] > 0.0 for row in combined)
        >= int(gate["combined_clean_4b_minus_9b_positive_seed_count_minimum"]),
        "combined_extension_positive_seeds": sum(
            row["extension_4b_minus_27b"] > 0.0 for row in combined
        )
        >= int(gate["combined_extension_4b_minus_27b_positive_seed_count_minimum"]),
    }
    return {
        "contract": "pearl.scaling-paradox-adapter-rescue-gate/1",
        "gate_id": gate["id"],
        "predicates": predicates,
        "pass": all(predicates.values()),
        "pass_action": "run_both_frozen_adapter_rescue_stages",
        "failure_action": gate["failure_action"],
        "no_parameter_tuning_or_substitution": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor-config", default=str(DEFAULT_EXECUTOR))
    parser.add_argument("--evaluations-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--gate-output", required=True)
    args = parser.parse_args()
    executor = read_json(repo_path(args.executor_config))
    campaign_configs = {
        name: repo_path(row["config"])
        for name, row in executor["campaigns"].items()
        if name in {"original", "replication"}
    }
    plans = {name: core_plan(path) for name, path in campaign_configs.items()}
    for name, plan in plans.items():
        expected_sha = executor["campaigns"][name]["stages"]["core"]["plan_sha"]
        if plan["launch_plan_contract_sha"] != expected_sha:
            raise RuntimeError(f"{name} core plan SHA differs from the executor contract")
    cells = load_evaluations(repo_path(args.evaluations_root), plans)
    original_config = read_json(campaign_configs["original"])
    replication_config = read_json(campaign_configs["replication"])
    original = cohort_contrasts(cells, "original", [int(x) for x in original_config["training_seeds"]])
    replication = cohort_contrasts(
        cells,
        "replication",
        [int(x) for x in replication_config["training_seeds"]],
    )
    combined_capacity = original["capacity_contrasts"] + replication["capacity_contrasts"]
    combined = {
        "clean_4b_minus_9b": mean_interval(
            [row["clean_4b_minus_9b"] for row in combined_capacity]
        ),
        "extension_4b_minus_27b": mean_interval(
            [row["extension_4b_minus_27b"] for row in combined_capacity]
        ),
        "clean_exact_sign_flip": exact_sign_flip_test(
            [row["clean_4b_minus_9b"] for row in combined_capacity]
        ),
        "extension_exact_sign_flip": exact_sign_flip_test(
            [row["extension_4b_minus_27b"] for row in combined_capacity]
        ),
        "cohort_block_retained": True,
    }
    gate_receipt = evaluate_rescue_gate(original, replication, executor["adapter_rescue_gate"])
    gate_receipt.update(
        {
            "analyzer_sha256": sha256_file(Path(__file__).resolve()),
            "executor_config_sha256": sha256_file(repo_path(args.executor_config)),
            "original_core_plan_sha": plans["original"]["launch_plan_contract_sha"],
            "replication_core_plan_sha": plans["replication"]["launch_plan_contract_sha"],
            "complete_matrix_cell_count": len(cells),
            "evaluation_report_sha256s": sorted(
                row["source_evaluation_report_sha256"] for row in cells.values()
            ),
        }
    )
    payload = {
        "contract": "pearl.scaling-paradox-optimization-analysis/1",
        "primary_endpoint": "heldout_per_residue_margin_delta_true_minus_shuffled",
        "analysis_unit": "independent_training_seed",
        "candidate_or_pair_rows_are_not_replicates": True,
        "original": original,
        "replication": replication,
        "combined": combined,
        "cells": [cells[key] for key in sorted(cells)],
        "adapter_rescue_gate": gate_receipt,
    }
    output = repo_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    gate_receipt["source_analysis_sha256"] = sha256_file(output)
    gate_receipt["gate_sha256"] = sha256_value(gate_receipt)
    gate_output = repo_path(args.gate_output)
    gate_output.parent.mkdir(parents=True, exist_ok=True)
    gate_output.write_text(json.dumps(gate_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "complete", "matrix_cells": len(cells), "gate_written": True}))


if __name__ == "__main__":
    main()
