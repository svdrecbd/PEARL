#!/usr/bin/env python3
"""Analyze the frozen data-exposure and conditional adapter-rescue estimands."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import hashlib
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


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric_index(
    root: Path,
    expected: dict[str, dict[str, Any]],
    receipt_hashes: dict[str, str],
) -> dict[str, float]:
    observed: dict[str, float] = {}
    for path in root.rglob("evaluation_report.json"):
        report = read_json(path)
        contract = report.get("contract") or {}
        source_sha = str(contract.get("source_run_contract_sha") or "")
        if source_sha not in expected:
            continue
        if report.get("status") != "complete" or not report.get("complete"):
            raise RuntimeError(f"incomplete expected evaluation: {path}")
        metric = report.get("holdout", {}).get("diagnostics", {}).get("per_residue", {}).get(
            "margin_delta_mean"
        )
        if not isinstance(metric, (int, float)) or not math.isfinite(float(metric)):
            raise RuntimeError(f"expected evaluation lacks primary endpoint: {path}")
        if source_sha in observed:
            raise RuntimeError(f"duplicate expected evaluation: {source_sha}")
        if sha256_file(path) != receipt_hashes[source_sha]:
            raise RuntimeError(f"evaluation differs from its audited receipt: {path}")
        observed[source_sha] = float(metric)
    if set(observed) != set(expected):
        raise RuntimeError(
            f"control evaluation matrix mismatch: missing={sorted(set(expected) - set(observed))}"
        )
    return observed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluations-root", required=True)
    parser.add_argument("--adapter-rescue-gate", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    launcher = load_script("launch_scaling_paradox_v1.py")
    helper = load_script("analyze_scaling_paradox_optimization.py")
    manager = load_script("manage_scaling_paradox_campaign.py")
    manifest = read_json(ROOT / "data/phase8_dpo/scaling_paradox_v1/dataset_manifest.json")
    configs = {
        "original": read_json(ROOT / "configs/experiments/scaling_paradox_v1.json"),
        "replication": read_json(
            ROOT / "configs/experiments/scaling_paradox_v1_replication.json"
        ),
    }
    gate = read_json(Path(args.adapter_rescue_gate))
    executor = read_json(ROOT / "configs/experiments/scaling_paradox_executor_v1.json")
    campaign_manifest = manager.build_manifest(executor)
    manager.validate_rescue_gate(
        manifest=campaign_manifest,
        state_dir=Path(args.state_dir),
        rescue_gate=gate,
    )
    expected: dict[str, dict[str, Any]] = {}
    plans: dict[tuple[str, str], dict[str, Any]] = {}
    stages = ["core", "data_exposure"] + (["adapter_rescue"] if gate.get("pass") else [])
    for cohort, config in configs.items():
        for stage in stages:
            plan = launcher.build_plan(config, manifest, stage)
            plans[(cohort, stage)] = plan
            for row in plan["runs"]:
                expected[row["run_contract_sha"]] = {"cohort": cohort, "stage": stage, **row}
    receipt_hashes: dict[str, str] = {}
    for source_sha, row in expected.items():
        receipt_path = Path(args.state_dir) / "receipts" / "evaluation" / f"{row['run_key']}.json"
        if not receipt_path.is_file():
            raise RuntimeError(f"missing audited evaluation receipt: {row['run_key']}")
        receipt = read_json(receipt_path)
        if (
            receipt.get("run_key") != row["run_key"]
            or not receipt.get("evaluation_terminal_valid")
            or receipt.get("run_contract_sha") != source_sha
        ):
            raise RuntimeError(f"invalid audited evaluation receipt: {row['run_key']}")
        receipt_hashes[source_sha] = str(receipt["evaluation_report_file_sha256"])
    values = metric_index(Path(args.evaluations_root), expected, receipt_hashes)
    data_rows: dict[str, list[dict[str, Any]]] = {"original": [], "replication": []}
    rescue_rows: dict[str, list[dict[str, Any]]] = {"original": [], "replication": []}
    for cohort, config in configs.items():
        core = plans[(cohort, "core")]["runs"]
        data = plans[(cohort, "data_exposure")]["runs"]
        for seed in config["training_seeds"]:
            core_row = next(
                row for row in core
                if row["model_tag"] == "qwen3p5-4b" and row["arm"] == "true"
                and int(row["training_seed"]) == int(seed)
            )
            one = next(row for row in data if row["tag"] == "d2p5-one-epoch" and int(row["training_seed"]) == int(seed))
            matched = next(row for row in data if row["tag"] == "d2p5-update-matched" and int(row["training_seed"]) == int(seed))
            data_rows[cohort].append(
                {
                    "training_seed": int(seed),
                    "update_exposure_matched_minus_one_epoch": values[matched["run_contract_sha"]] - values[one["run_contract_sha"]],
                    "data_diversity_d10_minus_d2p5_update_matched": values[core_row["run_contract_sha"]] - values[matched["run_contract_sha"]],
                }
            )
        if gate.get("pass"):
            rescue = plans[(cohort, "adapter_rescue")]["runs"]
            for seed in config["training_seeds"]:
                for model_tag in ("qwen3p5-9b", "qwen3p6-27b"):
                    fixed = next(row for row in core if row["model_tag"] == model_tag and row["arm"] == "true" and int(row["training_seed"]) == int(seed))
                    rank128 = next(row for row in rescue if row["model_tag"] == model_tag and int(row["training_seed"]) == int(seed))
                    rescue_rows[cohort].append(
                        {
                            "training_seed": int(seed), "model_tag": model_tag,
                            "rank128_minus_rank32_margin_delta": values[rank128["run_contract_sha"]] - values[fixed["run_contract_sha"]],
                        }
                    )

    def summarize(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
        return helper.mean_interval([float(row[field]) for row in rows])

    combined_data = data_rows["original"] + data_rows["replication"]
    payload: dict[str, Any] = {
        "contract": "pearl.scaling-paradox-controls-analysis/1",
        "analysis_unit": "independent_training_seed",
        "adapter_rescue_gate_sha256": gate["gate_sha256"],
        "campaign_manifest_sha256": campaign_manifest["manifest_sha256"],
        "evaluation_report_sha256s": sorted(receipt_hashes.values()),
        "data_exposure_estimands": {
            cohort: {
                "seed_level": rows,
                "update_exposure": summarize(rows, "update_exposure_matched_minus_one_epoch"),
                "data_diversity": summarize(rows, "data_diversity_d10_minus_d2p5_update_matched"),
            }
            for cohort, rows in {**data_rows, "combined": combined_data}.items()
        },
        "adapter_rescue": {"gate_passed": bool(gate.get("pass"))},
    }
    payload["data_exposure_estimands"]["combined"]["update_exposure_exact_sign_flip"] = (
        helper.exact_sign_flip_test(
            [row["update_exposure_matched_minus_one_epoch"] for row in combined_data]
        )
    )
    payload["data_exposure_estimands"]["combined"]["data_diversity_exact_sign_flip"] = (
        helper.exact_sign_flip_test(
            [row["data_diversity_d10_minus_d2p5_update_matched"] for row in combined_data]
        )
    )
    if gate.get("pass"):
        combined_rescue = rescue_rows["original"] + rescue_rows["replication"]
        payload["adapter_rescue"]["estimand"] = "rank128_minus_matched_rank32_true_preference_margin_delta"
        payload["adapter_rescue"]["cohorts"] = {}
        for cohort, rows in {**rescue_rows, "combined": combined_rescue}.items():
            payload["adapter_rescue"]["cohorts"][cohort] = {
                model_tag: {
                    "seed_level": [row for row in rows if row["model_tag"] == model_tag],
                    "summary": summarize(
                        [row for row in rows if row["model_tag"] == model_tag],
                        "rank128_minus_rank32_margin_delta",
                    ),
                }
                for model_tag in ("qwen3p5-9b", "qwen3p6-27b")
            }
        for model_tag in ("qwen3p5-9b", "qwen3p6-27b"):
            payload["adapter_rescue"]["cohorts"]["combined"][model_tag][
                "exact_sign_flip"
            ] = helper.exact_sign_flip_test(
                [
                    row["rank128_minus_rank32_margin_delta"]
                    for row in combined_rescue
                    if row["model_tag"] == model_tag
                ]
            )
    else:
        payload["adapter_rescue"]["status"] = "prospectively_skipped_without_substitution"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "complete", "gate_passed": bool(gate.get("pass"))}))


if __name__ == "__main__":
    main()
