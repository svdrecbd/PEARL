#!/usr/bin/env python3
"""Combine the two frozen frontier structural cohorts without pooling architecture families."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import statistics
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mean_interval(values: list[float]) -> dict[str, Any]:
    mean = statistics.fmean(values)
    critical = 2.5705818356 if len(values) == 6 else 1.9599639845
    half = critical * statistics.stdev(values) / math.sqrt(len(values))
    return {
        "n_independent_training_seeds": len(values),
        "mean": mean,
        "mean_t_95ci": [mean - half, mean + half],
        "positive_seed_count": sum(value > 0 for value in values),
    }


def exact_sign_flip(values: list[float]) -> dict[str, Any]:
    observed = abs(statistics.fmean(values))
    draws = [
        abs(statistics.fmean(sign * value for sign, value in zip(signs, values, strict=True)))
        for signs in itertools.product((-1.0, 1.0), repeat=len(values))
    ]
    return {
        "permutation_count": len(draws),
        "two_sided_p_value": sum(draw >= observed - 1e-15 for draw in draws) / len(draws),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True)
    parser.add_argument("--replication", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    original_path = Path(args.original)
    replication_path = Path(args.replication)
    original = read_json(original_path)
    replication = read_json(replication_path)
    expected_contract = "pearl.frontier-adaptation-structural-analysis/2"
    if original.get("contract") != expected_contract or replication.get("contract") != expected_contract:
        raise RuntimeError("combined analysis requires two frontier structural analyses")
    if not original.get("matrix_complete") or not replication.get("matrix_complete"):
        raise RuntimeError("combined analysis requires two complete matrices")
    if original.get("structural_manifest_sha") != replication.get("structural_manifest_sha"):
        raise RuntimeError("cohorts are not bound to the same structural manifest")
    if original.get("shared_base_report_sha256s") != replication.get("shared_base_report_sha256s"):
        raise RuntimeError("replication did not reuse the exact original base reports")
    if original.get("campaign_id") != "pearl-frontier-adaptation-v2-original":
        raise RuntimeError("wrong original structural campaign")
    if replication.get("campaign_id") != "pearl-frontier-adaptation-v2-replication":
        raise RuntimeError("wrong replication structural campaign")
    comparisons: dict[str, Any] = {}
    if set(original["capacity_contrasts"]) != set(replication["capacity_contrasts"]):
        raise RuntimeError("cohorts have different frozen family contrasts")
    for name in original["capacity_contrasts"]:
        values = [
            float(row["value"])
            for cohort in (original, replication)
            for row in cohort["capacity_contrasts"][name]["seed_level"]
        ]
        if len(values) != 6:
            raise RuntimeError(f"combined structural contrast {name} is not six-seed complete")
        comparisons[name] = {
            "summary": mean_interval(values),
            "exact_sign_flip": exact_sign_flip(values),
            "direction": original["capacity_contrasts"][name]["direction"],
        }
    payload = {
        "contract": "pearl.frontier-adaptation-structural-combined-analysis/2",
        "structural_manifest_sha": original["structural_manifest_sha"],
        "shared_base_report_sha256s": original["shared_base_report_sha256s"],
        "within_family_scaling_contrasts": comparisons,
        "original_core_plan_sha": original["core_plan_sha"],
        "replication_core_plan_sha": replication["core_plan_sha"],
        "original_structural_config_sha256": original["structural_config_sha256"],
        "replication_structural_config_sha256": replication["structural_config_sha256"],
        "original_analysis_file_sha256": sha256_file(original_path),
        "replication_analysis_file_sha256": sha256_file(replication_path),
        "architecture_families_are_not_pooled": True,
        "candidate_rows_are_nested_not_independent_replicates": True,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "complete", "comparisons": len(comparisons)}))


if __name__ == "__main__":
    main()
