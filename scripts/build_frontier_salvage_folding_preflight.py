#!/usr/bin/env python3
"""Build the exact six-job paid packet for replication-salvage FP32 folding."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STOCK_IMAGE = (
    "docker.io/nvidia/cuda:13.0.2-cudnn-runtime-ubuntu24.04@"
    "sha256:14d94b039cb94bbd5da559f303b46bc4b0d5d6c24ab1a9d7b186e566ed3400dc"
)
RATE_PER_MINUTE_USD = 0.0666
MAX_DURATION_MINUTES = 225
SHARD_COUNT = 6
STAGING_BUCKET = "pearl-gmn-folding-packets-975049894429-20260823"
STAGING_PREFIX = "replication-salvage-fp32-r5"
PROVIDER_COMMAND = (
    "bash -lc 'apt-get update && "
    "DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends "
    "ca-certificates curl python3 && rm -rf /var/lib/apt/lists/* && "
    "curl --fail --silent --show-error --location "
    "\"$PEARL_PACKET_URL\" --output /tmp/pearl-packet.tar.gz && "
    "echo \"$PEARL_PACKET_TAR_SHA256  /tmp/pearl-packet.tar.gz\" | sha256sum -c - && "
    "tar -xzf /tmp/pearl-packet.tar.gz && "
    "exec bash deploy/frontier_adaptation_v2/run_salvage_folding_shard_stock_image.sh'"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    discovery_path = ROOT / "reports/frontier_adaptation_v2_replication_salvage/discovery_funnel_esm3_repeat_filtered.json"
    shard_root = ROOT / "reports/frontier_adaptation_v2_replication_salvage/folding_shards_esm3_repeat_filtered"
    shard_index_path = shard_root / "shard-index.json"
    discovery = read_json(discovery_path)
    shard_index = read_json(shard_index_path)
    if discovery.get("funnel_sha256") != shard_index.get("discovery_funnel_sha256"):
        raise RuntimeError("shard index is not bound to the corrected ESM3 funnel")
    if int(shard_index.get("shard_count", -1)) != SHARD_COUNT:
        raise RuntimeError("paid preflight requires exactly six shards")

    context_sources = {
        "deploy/frontier_adaptation_v2/run_salvage_folding_shard_stock_image.sh": ROOT / "deploy/frontier_adaptation_v2/run_salvage_folding_shard_stock_image.sh",
        "scripts/run_frontier_structural_folding_shard.py": ROOT / "scripts/run_frontier_structural_folding_shard.py",
        "src/pearl/__init__.py": ROOT / "src/pearl/__init__.py",
        "src/pearl/esmfold2_contract.py": ROOT / "src/pearl/esmfold2_contract.py",
        "src/pearl/family.py": ROOT / "src/pearl/family.py",
        "src/pearl/io_utils.py": ROOT / "src/pearl/io_utils.py",
        "src/pearl/structure_gate.py": ROOT / "src/pearl/structure_gate.py",
        "configs/esmfold2_runtime_lock.json": ROOT / "configs/esmfold2_runtime_lock.json",
        "configs/structure_gate_calibration.esmfold2.json": ROOT / "configs/structure_gate_calibration.esmfold2.json",
        "configs/experiments/frontier_adaptation_structural_v2_replication.json": ROOT / "configs/experiments/frontier_adaptation_structural_v2_replication.json",
        "configs/experiments/frontier_adaptation_structural_v2_replication_fp32_folding.json": ROOT / "configs/experiments/frontier_adaptation_structural_v2_replication_fp32_folding.json",
        "packet/discovery_funnel_esm3_repeat_filtered.json": discovery_path,
    }
    missing = [str(path) for path in context_sources.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"paid packet source files missing: {missing}")

    jobs = []
    for shard_index_value in range(SHARD_COUNT):
        shard_path = shard_root / f"shard-{shard_index_value}.json"
        shard = read_json(shard_path)
        file_sha = sha256_file(shard_path)
        indexed = shard_index[f"shard_{shard_index_value}"]
        if file_sha != indexed["sha256"] or shard["shard_index"] != shard_index_value:
            raise RuntimeError(f"shard {shard_index_value} differs from its index")
        jobs.append(
            {
                "shard_index": shard_index_value,
                "sequence_count": shard["sequence_count"],
                "estimated_work_units": shard["estimated_work_units"],
                "source_shard_path": str(shard_path.relative_to(ROOT)),
                "context_shard_path": f"packet/shard-{shard_index_value}.json",
                "shard_file_sha256": file_sha,
                "idempotency_key": (
                    f"pearl-rep-salvage-fp32-r5-s{shard_index_value}-"
                    f"{discovery['funnel_sha256'][:10]}-{file_sha[:10]}"
                ),
                "provider_label": f"pearl-rep-salvage-fp32-shard-{shard_index_value}",
                "packet_object_key": f"{STAGING_PREFIX}/shard-{shard_index_value}.tar.gz",
                "max_cost_at_list_rate_usd": round(
                    MAX_DURATION_MINUTES * RATE_PER_MINUTE_USD, 3
                ),
            }
        )

    calibration = read_json(ROOT / "configs/structure_gate_calibration.esmfold2.json")
    fold_seconds_mean = float(calibration["fold_seconds_mean"])
    fold_seconds_p95 = float(calibration["fold_seconds_p95"])
    model_load_seconds = float(calibration["model_load_seconds"])
    total_folds = int(shard_index["total_sequences"])
    mean_gpu_hours = (total_folds * fold_seconds_mean + SHARD_COUNT * model_load_seconds) / 3600
    p95_gpu_hours = (total_folds * fold_seconds_p95 + SHARD_COUNT * model_load_seconds) / 3600
    list_hourly = RATE_PER_MINUTE_USD * 60
    hard_ceiling = SHARD_COUNT * MAX_DURATION_MINUTES * RATE_PER_MINUTE_USD
    if not math.isclose(hard_ceiling, 89.91, abs_tol=1e-9):
        raise RuntimeError("paid ceiling calculation changed")

    payload = {
        "contract": "pearl.frontier-replication-salvage-folding-preflight/5",
        "analysis_scope": "replication_only_salvage_exploratory_posthoc_repeat_filtered",
        "approval": {
            "status": "explicit_user_approved",
            "approval_message": "I agree on 6 independent jobs, get it done",
            "approval_date": "2026-08-23",
            "approved_job_count": SHARD_COUNT,
            "operational_ceiling_usd": 90.0,
        },
        "repository_head_sha": (
            __import__("subprocess")
            .check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)
            .strip()
        ),
        "execution": {
            "mission": "pearl-frontier-replication-salvage",
            "chip": "h100",
            "chip_count_per_job": 1,
            "job_count": SHARD_COUNT,
            "stock_image": STOCK_IMAGE,
            "custom_image_build": False,
            "provider_context_upload": False,
            "clock_lock": True,
            "hf_cache": True,
            "resume": "checkpoint",
            "max_duration_minutes_per_job": MAX_DURATION_MINUTES,
            "list_rate_per_gpu_minute_usd": RATE_PER_MINUTE_USD,
            "list_rate_per_gpu_hour_usd": list_hourly,
            "hard_six_job_runtime_ceiling_usd": round(hard_ceiling, 2),
            "provider_command": PROVIDER_COMMAND,
        },
        "staging": {
            "service": "Amazon S3",
            "bucket": STAGING_BUCKET,
            "prefix": STAGING_PREFIX,
            "public_access": "blocked",
            "server_side_encryption": "AES256",
            "transport": "HTTPS presigned GET in protected job environment",
            "presigned_url_expires_seconds": 604800,
        },
        "projection": {
            "total_unique_folds": total_folds,
            "mean_gpu_hours": round(mean_gpu_hours, 3),
            "mean_cost_at_list_rate_usd": round(mean_gpu_hours * list_hourly, 2),
            "p95_gpu_hours": round(p95_gpu_hours, 3),
            "p95_cost_at_list_rate_usd": round(p95_gpu_hours * list_hourly, 2),
            "p95_plus_20_percent_cost_at_list_rate_usd": round(
                p95_gpu_hours * 1.2 * list_hourly, 2
            ),
        },
        "discovery_funnel_sha256": discovery["funnel_sha256"],
        "discovery_file_sha256": sha256_file(discovery_path),
        "shard_index_file_sha256": sha256_file(shard_index_path),
        "source_file_sha256s": {
            relative: sha256_file(path) for relative, path in context_sources.items()
        },
        "jobs": jobs,
        "source_checkpoint_deletion_authorized": False,
        "scientific_endpoint_inspection_performed": False,
        "superseded_failed_submissions": {
            "job_ids": [
                "job-8ukhg", "job-s7cfi", "job-kca54", "job-q695w", "job-qxnv4", "job-kgucn",
                "job-d9m26", "job-zf8kx",
            ],
            "failures": [
                "initial command assumed curl was present in the stock runtime image",
                "r2 command assumed python3 was present in the stock runtime image",
                "r3 bootstrap installed curl but runtime validation required python3 before the full runtime install",
            ],
            "common_boundary": "all jobs exited before packet extraction or model loading",
            "scientific_results_produced": False,
        },
        "superseded_checkpoint_declaration_cancellations": {
            "job_ids": [
                "job-8u46h", "job-tx5sa", "job-e8gw9",
                "job-f5nv8", "job-xvcq4", "job-h63nc",
            ],
            "failure": (
                "the installed CLI omitted resume=checkpoint, so the metadata "
                "checkpoint endpoint returned HTTP 403"
            ),
            "action": "all six jobs canceled before relaunch through the raw provider API",
            "partial_endpoint_artifacts_exported": False,
            "scientific_endpoint_values_inspected": False,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
