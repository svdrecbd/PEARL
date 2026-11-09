#!/usr/bin/env python3
"""Build a result-blind, model-homogeneous replication generation schedule."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "reports/frontier_adaptation_v2_structural_local_authority/structural_manifest.json"
DEFAULT_ATTESTATION = ROOT / "reports/frontier_adaptation_v2_structural_sampler_weight_attestation_v2.json"
DEFAULT_OUTPUT = ROOT / "reports/frontier_adaptation_v2_structural_local_authority/replication_duration_wave_plan.json"
EXPECTED_MANIFEST_SHA = "2cf37f0b1cd1e10848a55232916be59d34e7703fcd22f13681e221207aa6c788"
MODEL_ORDER = [
    ("thinkingmachines/Inkling-Small", "fast"),
    ("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16", "fast"),
    ("openai/gpt-oss-20b", "medium"),
    ("nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16", "medium"),
    ("openai/gpt-oss-120b", "medium_slow"),
    ("thinkingmachines/Inkling", "medium_slow"),
    ("nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16", "slow"),
    ("nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16", "slow"),
]


def sha256_value(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--attestation", type=Path, default=DEFAULT_ATTESTATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    manifest = read_json(args.manifest)
    manifest_sha = manifest.get("structural_manifest_sha")
    if manifest_sha != sha256_value(
        {key: value for key, value in manifest.items() if key != "structural_manifest_sha"}
    ) or manifest_sha != EXPECTED_MANIFEST_SHA:
        raise RuntimeError("structural manifest hash mismatch")
    attestation = read_json(args.attestation)
    attestation_sha = attestation.get("attestation_sha256")
    if (
        attestation_sha
        != sha256_value(
            {key: value for key, value in attestation.items() if key != "attestation_sha256"}
        )
        or attestation.get("structural_manifest_sha") != manifest_sha
        or attestation.get("terminal_valid") is not True
        or attestation.get("completed_mapping_count") != 48
    ):
        raise RuntimeError("sampler attestation is not terminal-valid")

    replication = [job for job in manifest["jobs"] if job.get("campaign") == "replication"]
    by_model = {
        model: [job for job in replication if job["model"] == model]
        for model, _latency in MODEL_ORDER
    }
    if len(replication) != 48 or any(len(rows) != 6 for rows in by_model.values()):
        raise RuntimeError("replication cohort is not eight exact six-cell model groups")
    mappings = attestation["mappings"]
    waves = []
    ordered_job_keys = []
    for index, (model, latency) in enumerate(MODEL_ORDER, start=1):
        rows = sorted(
            by_model[model], key=lambda row: (row["arm"], int(row["training_seed"]))
        )
        job_keys = [row["job_key"] for row in rows]
        if any(key not in mappings for key in job_keys):
            raise RuntimeError(f"model group lacks sampler attestations: {model}")
        ordered_job_keys.extend(job_keys)
        waves.append(
            {
                "wave_index": index,
                "model": model,
                "model_tag": rows[0]["model_tag"],
                "expected_latency_class": latency,
                "job_keys": job_keys,
            }
        )
    if len(ordered_job_keys) != 48 or len(set(ordered_job_keys)) != 48:
        raise RuntimeError("replication wave plan is incomplete or duplicate")

    packet = {
        "contract": "pearl.frontier-v2-replication-duration-wave-plan/1",
        "created_at": datetime.now(UTC).isoformat(),
        "structural_manifest_sha": manifest_sha,
        "sampler_attestation_sha256": attestation_sha,
        "campaign": "replication",
        "job_count": 48,
        "wave_count": 8,
        "maximum_concurrent_cells": 6,
        "grouping_policy": "one exact model per six-cell wave",
        "ordering_basis": (
            "result-blind expected provider latency from model identity, active scale, "
            "and prior base-cell operational throughput only"
        ),
        "ordered_job_keys": ordered_job_keys,
        "waves": waves,
        "scientific_contract_changes": [],
        "source_checkpoint_deletion_authorized": False,
        "generation_authorized_by_this_packet": False,
    }
    packet["wave_plan_sha256"] = sha256_value(packet)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "wave_plan_sha256": packet["wave_plan_sha256"],
                "wave_count": len(waves),
                "job_count": len(ordered_job_keys),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
