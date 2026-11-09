#!/usr/bin/env python3
"""Build an exact inventory from the v2 scientific-sampler attestation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


class InventoryError(RuntimeError):
    pass


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    value = json.loads(args.attestation.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise InventoryError("attestation is not a JSON object")
    if value.get("contract") != "pearl.frontier-v2-scientific-sampler-attestation/1":
        raise InventoryError("unsupported attestation contract")
    supplied = value.get("attestation_sha256")
    unsigned = {
        key: item for key, item in value.items() if key != "attestation_sha256"
    }
    if supplied != canonical_sha256(unsigned):
        raise InventoryError("attestation self-hash mismatch")
    if value.get("terminal_valid") is not True:
        raise InventoryError("attestation is not terminal-valid")
    mappings = value.get("mappings")
    if not isinstance(mappings, dict):
        raise InventoryError("attestation mappings are invalid")
    if len(mappings) != int(value.get("expected_mapping_count", -1)):
        raise InventoryError("attestation mapping count is incomplete")

    checkpoints = []
    for job_sha, entry in sorted(mappings.items()):
        provider = entry.get("provider_checkpoint")
        sampler_path = entry.get("sampler_path")
        if not isinstance(provider, dict) or not isinstance(sampler_path, str):
            raise InventoryError(f"incomplete sampler mapping: {job_sha}")
        if provider.get("checkpoint_type") != "sampler":
            raise InventoryError(f"mapping is not a sampler checkpoint: {job_sha}")
        required = (
            "source_checkpoint_path",
            "source_run_contract_sha",
            "checkpoint_step",
            "run_key",
            "model",
        )
        missing = [key for key in required if key not in entry]
        if missing:
            raise InventoryError(
                f"sampler mapping lacks {', '.join(missing)}: {job_sha}"
            )
        checkpoints.append(
            {
                **provider,
                "tinker_path": sampler_path,
                "preservation_job_sha": job_sha,
                "source_checkpoint_path": entry["source_checkpoint_path"],
                "source_run_contract_sha": entry["source_run_contract_sha"],
                "checkpoint_step": entry["checkpoint_step"],
                "run_key": entry["run_key"],
                "model": entry["model"],
            }
        )
    paths = [row["tinker_path"] for row in checkpoints]
    if len(paths) != len(set(paths)):
        raise InventoryError("sampler paths are not unique")
    output = {
        "contract": "pearl.attested-tinker-sampler-inventory/1",
        "source_attestation_sha256": supplied,
        "checkpoint_count": len(checkpoints),
        "provider_accounted_bytes": sum(
            int(row.get("size_bytes", 0)) for row in checkpoints
        ),
        "checkpoints": checkpoints,
    }
    output["inventory_sha256"] = canonical_sha256(output)
    atomic_json(args.output, output)
    print(json.dumps({key: output[key] for key in (
        "contract", "source_attestation_sha256", "checkpoint_count",
        "provider_accounted_bytes", "inventory_sha256"
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InventoryError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
