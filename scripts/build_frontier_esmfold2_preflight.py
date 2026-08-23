#!/usr/bin/env python3
"""Build the exact no-launch runtime and spend packet after ESMFold2 calibration."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pearl.esmfold2_contract import validate_fp32_folding_config  # noqa: E402
from pearl.io_utils import atomic_write_json  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", required=True)
    parser.add_argument(
        "--original-config",
        default="configs/experiments/frontier_adaptation_structural_v2_original_fp32_folding.json",
    )
    parser.add_argument(
        "--replication-config",
        default="configs/experiments/frontier_adaptation_structural_v2_replication_fp32_folding.json",
    )
    parser.add_argument("--stock-image-digest", required=True)
    parser.add_argument("--quoted-hourly-usd", required=True, type=float)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config_paths = [ROOT / args.original_config, ROOT / args.replication_config]
    configs = [read_json(path) for path in config_paths]
    calibration_path = Path(args.calibration)
    calibration = read_json(calibration_path)
    for config in configs:
        gate = config["structure_gate"]
        generation_config_path = ROOT / config["generation_config"]
        validate_fp32_folding_config(
            config,
            read_json(generation_config_path),
            generation_config_sha256=sha256_file(generation_config_path),
            runtime_lock=read_json(ROOT / gate["runtime_lock"]),
            calibration=calibration,
        )
        if sha256_file(ROOT / gate["calibration"]) != sha256_file(calibration_path):
            raise RuntimeError("preflight calibration differs from the folding config")
    if configs[1].get("shared_base_config") != args.original_config:
        raise RuntimeError("replication folding config has the wrong shared-base successor")
    executor_path = ROOT / "configs/experiments/frontier_adaptation_v2_executor.json"
    executor = read_json(executor_path)
    cells = int(executor["structural_scope"]["total_structural_cells"])
    candidates_per_cell = int(executor["structural_scope"]["candidates_per_cell"])
    folds = cells * candidates_per_cell
    conservative_fold_seconds = float(calibration["fold_seconds_p95"])
    startup_seconds = float(calibration["model_load_seconds"])
    raw_seconds = folds * conservative_fold_seconds + cells * startup_seconds
    contingency = 1.20
    projected_gpu_hours = raw_seconds * contingency / 3600.0
    projected_cost = projected_gpu_hours * args.quoted_hourly_usd
    ceiling = float(executor["max_authorized_givemeanode_usd"])
    payload = {
        "contract": "pearl.frontier-esmfold2-paid-preflight/2",
        "action": "approval_required_no_launch",
        "folding_config_sha256s": {
            "original": sha256_file(config_paths[0]),
            "replication": sha256_file(config_paths[1]),
        },
        "generation_config_sha256s": {
            "original": configs[0]["generation_config_sha256"],
            "replication": configs[1]["generation_config_sha256"],
        },
        "executor_sha256": sha256_file(executor_path),
        "calibration_sha256": sha256_file(calibration_path),
        "calibration_contract_sha": calibration["calibration_contract"]["calibration_contract_sha"],
        "stock_image_digest": args.stock_image_digest,
        "quoted_hourly_usd": args.quoted_hourly_usd,
        "cell_count": cells,
        "candidate_slots_per_cell": candidates_per_cell,
        "total_candidate_slots": folds,
        "conservative_fold_seconds": conservative_fold_seconds,
        "per_job_model_load_seconds": startup_seconds,
        "contingency_multiplier": contingency,
        "projected_gpu_hours": round(projected_gpu_hours, 3),
        "projected_cost_usd": round(projected_cost, 2),
        "authorized_ceiling_usd": ceiling,
        "within_authorized_ceiling": math.isfinite(projected_cost) and projected_cost <= ceiling,
        "source_checkpoint_deletion_authorized": False,
        "scientific_endpoint_inspection_performed": False,
    }
    atomic_write_json(Path(args.output), payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
