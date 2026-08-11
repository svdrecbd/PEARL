#!/usr/bin/env python3
"""Summarize paired structure-gate controls and generated campaign panels."""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_results(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("complete"):
        raise ValueError(f"Incomplete structure report: {path}")
    results = [row for row in payload.get("results", []) if "mean_plddt" in row]
    if len(results) != payload.get("target_count"):
        raise ValueError(f"Missing folds in {path}: {len(results)}/{payload.get('target_count')}")
    return results


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def arm_summary(rows: list[dict]) -> dict:
    plddt = [float(row["mean_plddt"]) for row in rows]
    return {
        "n": len(rows),
        "mean_plddt": round(statistics.fmean(plddt), 3),
        "median_plddt": round(statistics.median(plddt), 3),
        "plddt_p05": round(percentile(plddt, 0.05), 3),
        "plddt_p95": round(percentile(plddt, 0.95), 3),
        "plddt_gate_passes": sum(value >= 70.0 for value in plddt),
        "triad_passes": sum(bool(row.get("triad", {}).get("passes")) for row in rows),
        "structural_gate_passes": sum(bool(row.get("structural_gate_pass")) for row in rows),
    }


def exact_sign_test(differences: list[float]) -> float:
    nonzero = [value for value in differences if value != 0.0]
    positives = sum(value > 0.0 for value in nonzero)
    tail = min(positives, len(nonzero) - positives)
    probability = sum(math.comb(len(nonzero), index) for index in range(tail + 1)) / (2 ** len(nonzero))
    return min(1.0, 2.0 * probability)


def bootstrap_mean_ci(values: list[float], *, seed: int, samples: int = 10_000) -> list[float]:
    rng = random.Random(seed)
    means = [statistics.fmean(rng.choices(values, k=len(values))) for _ in range(samples)]
    return [round(percentile(means, 0.025), 3), round(percentile(means, 0.975), 3)]


def auc(positive: list[float], negative: list[float]) -> float:
    wins = 0.0
    for pos in positive:
        for neg in negative:
            wins += 1.0 if pos > neg else 0.5 if pos == neg else 0.0
    return wins / (len(positive) * len(negative))


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float]:
    proportion = successes / total
    denominator = 1.0 + (z * z / total)
    center = (proportion + (z * z / (2.0 * total))) / denominator
    margin = (
        z
        * math.sqrt((proportion * (1.0 - proportion) / total) + (z * z / (4.0 * total * total)))
        / denominator
    )
    return [round(center - margin, 4), round(center + margin, 4)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT / "reports" / "methods_evaluation" / "structure-gate-controls-v1" / "h100-esmfold"
    generated = ROOT / "reports" / "methods_evaluation" / "phase8-methods-matched-v1" / "h100-esmfold"
    parser.add_argument("--positive", type=Path, default=base / "positive-structure-gate.json")
    parser.add_argument("--negative", type=Path, default=base / "negative-structure-gate.json")
    parser.add_argument("--reference", type=Path, default=generated / "reference-structure-gate.json")
    parser.add_argument("--trained", type=Path, default=generated / "trained-structure-gate.json")
    parser.add_argument("--output", type=Path, default=base / "control-analysis.json")
    args = parser.parse_args()

    positive = load_results(args.positive)
    negative = load_results(args.negative)
    if len(positive) != len(negative):
        raise ValueError("Positive and negative control reports are not paired")
    positive_plddt = [float(row["mean_plddt"]) for row in positive]
    negative_plddt = [float(row["mean_plddt"]) for row in negative]
    differences = [pos - neg for pos, neg in zip(positive_plddt, negative_plddt, strict=True)]

    positive_passes = sum(bool(row.get("structural_gate_pass")) for row in positive)
    negative_passes = sum(bool(row.get("structural_gate_pass")) for row in negative)
    summary = {
        "contract": "pearl.structure-gate-control-analysis/1",
        "positive": arm_summary(positive),
        "negative": arm_summary(negative),
        "paired": {
            "mean_plddt_difference": round(statistics.fmean(differences), 3),
            "median_plddt_difference": round(statistics.median(differences), 3),
            "mean_difference_bootstrap_95ci": bootstrap_mean_ci(differences, seed=20260808),
            "positive_higher_pairs": sum(value > 0.0 for value in differences),
            "exact_sign_test_p": exact_sign_test(differences),
            "plddt_auc": round(auc(positive_plddt, negative_plddt), 4),
        },
        "gate_classification": {
            "sensitivity": round(positive_passes / len(positive), 4),
            "sensitivity_wilson_95ci": wilson_interval(positive_passes, len(positive)),
            "specificity": round((len(negative) - negative_passes) / len(negative), 4),
            "specificity_wilson_95ci": wilson_interval(len(negative) - negative_passes, len(negative)),
        },
    }
    generated_plddt: dict[str, list[float]] = {}
    for arm, path in (("reference_generated", args.reference), ("trained_generated", args.trained)):
        if path.exists():
            rows = load_results(path)
            summary[arm] = arm_summary(rows)
            generated_plddt[arm] = [float(row["mean_plddt"]) for row in rows]
    if generated_plddt:
        summary["distribution_comparisons"] = {
            arm: {
                "natural_over_generated_plddt_auc": round(auc(positive_plddt, values), 4),
                "generated_over_hard_negative_plddt_auc": round(auc(values, negative_plddt), 4),
            }
            for arm, values in generated_plddt.items()
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
