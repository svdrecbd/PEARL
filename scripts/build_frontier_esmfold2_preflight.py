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

from pearl.esmfold2_contract import validate_complete_calibration  # noqa: E402
from pearl.io_utils import atomic_write_json  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", required=True)
    parser.add_argument("--container-image-digest", required=True)
    parser.add_argument("--quoted-hourly-usd", required=True, type=float)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config_path = ROOT / "configs/experiments/frontier_adaptation_structural_v2_original.json"
    config = read_json(config_path)
    gate = config["structure_gate"]
    calibration_path = Path(args.calibration)
    calibration = read_json(calibration_path)
    validate_complete_calibration(calibration, gate)
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
        "contract": "pearl.frontier-esmfold2-paid-preflight/1",
        "action": "approval_required_no_launch",
        "structural_config_sha256": sha256_file(config_path),
        "executor_sha256": sha256_file(executor_path),
        "calibration_sha256": sha256_file(calibration_path),
        "calibration_contract_sha": calibration["calibration_contract"]["calibration_contract_sha"],
        "container_image_digest": args.container_image_digest,
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
