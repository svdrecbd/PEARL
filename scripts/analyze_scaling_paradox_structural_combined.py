#!/usr/bin/env python3
"""Combine frozen original and replication structural analyses at the training-seed level."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str) -> Any:
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_value(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def cohort_capacity(analysis: dict[str, Any], config: dict[str, Any], cohort: str) -> list[dict[str, Any]]:
    if not analysis.get("matrix_complete"):
        raise RuntimeError(f"{cohort} structural matrix is incomplete")
    model_tags = {row["model"]: row["tag"] for row in config["models"]}
    rows = [
        row for row in analysis.get("seed_level_contrasts", [])
        if row.get("contrast") == "true_minus_shuffled"
    ]
    index = {
        (model_tags[row["model"]], int(row["training_seed"])): float(row["delta"])
        for row in rows
    }
    expected = {
        (tag, int(seed))
        for tag in ("qwen3p5-4b", "qwen3p5-9b", "qwen3p6-27b")
        for seed in config["training_seeds"]
    }
    if set(index) != expected:
        raise RuntimeError(f"{cohort} structural seed contrast matrix differs from the frozen design")
    return [
        {
            "cohort": cohort,
            "training_seed": int(seed),
            "clean_4b_minus_9b": index[("qwen3p5-4b", int(seed))]
            - index[("qwen3p5-9b", int(seed))],
            "extension_4b_minus_27b": index[("qwen3p5-4b", int(seed))]
            - index[("qwen3p6-27b", int(seed))],
        }
        for seed in config["training_seeds"]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-analysis", required=True)
    parser.add_argument("--replication-analysis", required=True)
    parser.add_argument("--structural-manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    helper = load_script("analyze_scaling_paradox_optimization.py")
    original_config = read_json(str(ROOT / "configs/experiments/scaling_paradox_v1.json"))
    replication_config = read_json(
        str(ROOT / "configs/experiments/scaling_paradox_v1_replication.json")
    )
    original_analysis = read_json(args.original_analysis)
    replication_analysis = read_json(args.replication_analysis)
    structural_manifest = read_json(args.structural_manifest)
    if structural_manifest.get("structural_manifest_sha") != sha256_value(
        {key: value for key, value in structural_manifest.items() if key != "structural_manifest_sha"}
    ):
        raise RuntimeError("combined analysis received a corrupt structural manifest")
    launcher = load_script("launch_scaling_paradox_v1.py")
    dataset = read_json(str(ROOT / original_config["dataset_manifest"]))
    expected = {
        "original": {
            "campaign_id": "pearl-scaling-paradox-v1",
            "structural_config_sha256": sha256_file(
                ROOT / "configs/experiments/scaling_paradox_structural_v1.json"
            ),
            "core_plan_sha": launcher.build_plan(original_config, dataset, "core")[
                "launch_plan_contract_sha"
            ],
        },
        "replication": {
            "campaign_id": "pearl-scaling-paradox-v1-replication",
            "structural_config_sha256": sha256_file(
                ROOT / "configs/experiments/scaling_paradox_structural_v1_replication.json"
            ),
            "core_plan_sha": launcher.build_plan(replication_config, dataset, "core")[
                "launch_plan_contract_sha"
            ],
        },
    }
    for cohort, analysis in (("original", original_analysis), ("replication", replication_analysis)):
        if analysis.get("contract") != "pearl.scaling-paradox-structural-analysis/1":
            raise RuntimeError(f"{cohort} structural analysis has the wrong contract")
        if any(analysis.get(key) != value for key, value in expected[cohort].items()):
            raise RuntimeError(f"{cohort} structural analysis differs from the frozen design")
        if analysis.get("structural_manifest_sha") != structural_manifest["structural_manifest_sha"]:
            raise RuntimeError(f"{cohort} structural analysis used another structural manifest")
    if original_analysis.get("campaign_id") != "pearl-scaling-paradox-v1":
        raise RuntimeError("original structural analysis has the wrong campaign")
    if replication_analysis.get("campaign_id") != "pearl-scaling-paradox-v1-replication":
        raise RuntimeError("replication structural analysis has the wrong campaign")
    if (
        len(original_analysis.get("shared_base_report_sha256s", [])) != 3
        or original_analysis.get("shared_base_report_sha256s")
        != replication_analysis.get("shared_base_report_sha256s")
    ):
        raise RuntimeError("replication did not reuse the exact three original base reports")
    original = cohort_capacity(original_analysis, original_config, "original")
    replication = cohort_capacity(
        replication_analysis, replication_config, "replication"
    )
    combined = original + replication
    payload = {
        "contract": "pearl.scaling-paradox-structural-combined-analysis/1",
        "primary_endpoint": "seed_level_true_minus_shuffled_full_gate_yield",
        "analysis_unit": "independent_training_seed",
        "candidate_observations_are_nested_not_replicates": True,
        "structural_manifest_sha": structural_manifest["structural_manifest_sha"],
        "original_analysis_file_sha256": sha256_file(args.original_analysis),
        "replication_analysis_file_sha256": sha256_file(args.replication_analysis),
        "original": {
            "capacity_contrasts": original,
            "clean_4b_minus_9b": helper.mean_interval([row["clean_4b_minus_9b"] for row in original]),
            "extension_4b_minus_27b": helper.mean_interval([row["extension_4b_minus_27b"] for row in original]),
        },
        "replication": {
            "capacity_contrasts": replication,
            "clean_4b_minus_9b": helper.mean_interval([row["clean_4b_minus_9b"] for row in replication]),
            "extension_4b_minus_27b": helper.mean_interval([row["extension_4b_minus_27b"] for row in replication]),
        },
        "combined": {
            "capacity_contrasts": combined,
            "clean_4b_minus_9b": helper.mean_interval([row["clean_4b_minus_9b"] for row in combined]),
            "extension_4b_minus_27b": helper.mean_interval([row["extension_4b_minus_27b"] for row in combined]),
            "clean_exact_sign_flip": helper.exact_sign_flip_test(
                [row["clean_4b_minus_9b"] for row in combined]
            ),
            "extension_exact_sign_flip": helper.exact_sign_flip_test(
                [row["extension_4b_minus_27b"] for row in combined]
            ),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "complete", "seed_units": len(combined)}))


if __name__ == "__main__":
    main()
