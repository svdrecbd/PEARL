#!/usr/bin/env python3
"""Build the one-job paid authority packet for frozen discovery-priority folding."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STOCK_IMAGE = (
    "docker.io/nvidia/cuda:13.0.2-cudnn-runtime-ubuntu24.04@"
    "sha256:14d94b039cb94bbd5da559f303b46bc4b0d5d6c24ab1a9d7b186e566ed3400dc"
)
LIST_RATE_PER_MINUTE_USD = 0.0666
EFFECTIVE_RATE_PER_MINUTE_USD = 0.04995
MAX_DURATION_MINUTES = 120
STAGING_BUCKET = "pearl-gmn-folding-packets-975049894429-20260823"
STAGING_PREFIX = "replication-salvage-discovery-priority-fp32-r1"
PROVIDER_COMMAND = (
    "bash -lc 'apt-get update && "
    "DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends "
    "ca-certificates curl python3 && rm -rf /var/lib/apt/lists/* && "
    "curl --fail --silent --show-error --location "
    "\"$PEARL_PACKET_URL\" --output /tmp/pearl-packet.tar.gz && "
    "echo \"$PEARL_PACKET_TAR_SHA256  /tmp/pearl-packet.tar.gz\" | sha256sum -c - && "
    "tar -xzf /tmp/pearl-packet.tar.gz && "
    "exec bash deploy/frontier_adaptation_v2/run_discovery_priority_folding_stock_image.sh'"
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--shard", required=True)
    args = parser.parse_args()

    discovery_path = ROOT / "reports/frontier_adaptation_v2_replication_salvage/discovery_funnel_esm3_repeat_filtered.json"
    shard_path = Path(args.shard).resolve()
    discovery = read_json(discovery_path)
    shard = read_json(shard_path)
    if shard.get("sequence_count") != 168 or shard.get("shard_count") != 1:
        raise RuntimeError("priority paid preflight requires exactly one 168-sequence shard")
    if shard.get("discovery_funnel_sha256") != discovery.get("funnel_sha256"):
        raise RuntimeError("priority shard is not bound to the corrected ESM3 funnel")
    role_counts = {
        role: sum(row.get("discovery_panel_roles") == [role] for row in shard["sequences"])
        for role in ("selected", "random_survivor", "random_audit")
    }
    if role_counts != {"selected": 96, "random_survivor": 24, "random_audit": 48}:
        raise RuntimeError(f"priority shard role counts changed: {role_counts}")

    context_sources = {
        "deploy/frontier_adaptation_v2/run_discovery_priority_folding_stock_image.sh": ROOT / "deploy/frontier_adaptation_v2/run_discovery_priority_folding_stock_image.sh",
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
        "packet/shard-0.json": shard_path,
    }
    missing = [str(path) for path in context_sources.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"priority packet sources missing: {missing}")

    calibration = read_json(ROOT / "configs/structure_gate_calibration.esmfold2.json")
    mean_minutes = (
        168 * float(calibration["fold_seconds_mean"])
        + float(calibration["model_load_seconds"])
    ) / 60
    p95_minutes = (
        168 * float(calibration["fold_seconds_p95"])
        + float(calibration["model_load_seconds"])
    ) / 60
    shard_file_sha = sha256_file(shard_path)
    payload = {
        "contract": "pearl.frontier-replication-salvage-discovery-priority-folding-preflight/1",
        "analysis_scope": "replication_only_salvage_exploratory_posthoc_repeat_filtered_discovery_priority",
        "approval": {
            "status": "explicit_user_approved",
            "approval_message": "ok then do it, remember were kinda cowboying this shit (non destructive from a science pov) this is really the only thing that matters to me",
            "approval_date": "2026-08-23",
            "approved_job_count": 1,
            "approved_chip_count": 1,
            "operational_ceiling_usd": 8.0,
        },
        "repository_head_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "execution": {
            "mission": "pearl-frontier-replication-salvage",
            "chip": "h100",
            "chip_count_per_job": 1,
            "job_count": 1,
            "stock_image": STOCK_IMAGE,
            "custom_image_build": False,
            "provider_context_upload": False,
            "clock_lock": True,
            "hf_cache": True,
            "resume": "checkpoint",
            "max_duration_minutes_per_job": MAX_DURATION_MINUTES,
            "list_rate_per_gpu_minute_usd": LIST_RATE_PER_MINUTE_USD,
            "effective_rate_per_gpu_minute_usd": EFFECTIVE_RATE_PER_MINUTE_USD,
            "hard_runtime_ceiling_at_list_rate_usd": round(MAX_DURATION_MINUTES * LIST_RATE_PER_MINUTE_USD, 3),
            "hard_runtime_ceiling_at_effective_rate_usd": round(MAX_DURATION_MINUTES * EFFECTIVE_RATE_PER_MINUTE_USD, 3),
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
            "total_unique_folds": 168,
            "mean_runtime_minutes": round(mean_minutes, 2),
            "p95_runtime_minutes": round(p95_minutes, 2),
            "p95_plus_20_percent_runtime_minutes": round(p95_minutes * 1.2, 2),
        },
        "frozen_panel": {
            "selected": 96,
            "random_survivor": 24,
            "random_audit": 48,
            "total": 168,
            "membership_changed": False,
            "scientific_contract_changed": False,
            "execution_priority_only": True,
        },
        "discovery_funnel_sha256": discovery["funnel_sha256"],
        "discovery_file_sha256": sha256_file(discovery_path),
        "source_file_sha256s": {
            relative: sha256_file(path) for relative, path in context_sources.items()
        },
        "jobs": [{
            "shard_index": 0,
            "sequence_count": 168,
            "estimated_work_units": shard["estimated_work_units"],
            "source_shard_path": str(shard_path.relative_to(ROOT)),
            "context_shard_path": "packet/shard-0.json",
            "shard_file_sha256": shard_file_sha,
            "idempotency_key": f"pearl-rep-discovery-priority-r1-{discovery['funnel_sha256'][:10]}-{shard_file_sha[:10]}",
            "provider_label": "pearl-rep-discovery-priority-fp32",
            "packet_object_key": f"{STAGING_PREFIX}/discovery-priority.tar.gz",
            "max_cost_at_list_rate_usd": round(MAX_DURATION_MINUTES * LIST_RATE_PER_MINUTE_USD, 3),
        }],
        "superseded_broad_wave": {
            "job_ids": ["job-wciip", "job-jxq3h", "job-i6x64", "job-rqrnr", "job-jdz4u", "job-hyumy"],
            "action": "canceled before discovery-priority relaunch",
            "source_shards_preserved": True,
            "partial_endpoint_artifacts_exported": False,
            "scientific_endpoint_values_inspected": False,
            "full_confirmatory_folding_status": "deferred_not_complete",
        },
        "source_checkpoint_deletion_authorized": False,
        "scientific_endpoint_inspection_performed": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
