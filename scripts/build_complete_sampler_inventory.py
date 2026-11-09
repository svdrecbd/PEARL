#!/usr/bin/env python3
"""Build a complete sampler-only inventory from a base inventory and attestation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class InventoryError(RuntimeError):
    """Raised when an input or union invariant does not hold."""


def canonical_sha256(value: dict[str, Any], omitted: str) -> str:
    payload = {key: item for key, item in value.items() if key != omitted}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise InventoryError(f"expected JSON object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-inventory", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    base = read_object(args.base_inventory)
    if base.get("contract") != "pearl.tinker-account-checkpoint-inventory/1":
        raise InventoryError("base inventory has the wrong contract")
    if base.get("inventory_sha256") != canonical_sha256(base, "inventory_sha256"):
        raise InventoryError("base inventory SHA-256 mismatch")

    attestation = read_object(args.attestation)
    if attestation.get("contract") != "pearl.frontier-v2-scientific-sampler-attestation/1":
        raise InventoryError("attestation has the wrong contract")
    if attestation.get("attestation_sha256") != canonical_sha256(
        attestation, "attestation_sha256"
    ):
        raise InventoryError("attestation SHA-256 mismatch")
    if attestation.get("terminal_valid") is not True:
        raise InventoryError("attestation is not terminal-valid")
    mappings = attestation.get("mappings")
    if not isinstance(mappings, dict) or len(mappings) != int(
        attestation.get("expected_mapping_count", -1)
    ):
        raise InventoryError("attestation mappings are incomplete")

    checkpoints: dict[str, dict[str, Any]] = {}
    for row in base.get("checkpoints", []):
        if row.get("checkpoint_type") != "sampler":
            continue
        path = row.get("tinker_path")
        if not isinstance(path, str) or path in checkpoints:
            raise InventoryError("base sampler paths are missing or duplicate")
        checkpoints[path] = dict(row)

    for entry in mappings.values():
        provider = entry.get("provider_checkpoint")
        path = entry.get("sampler_path")
        if not isinstance(provider, dict) or not isinstance(path, str):
            raise InventoryError("attestation mapping is incomplete")
        if provider.get("checkpoint_type") != "sampler":
            raise InventoryError(f"attested checkpoint is not a sampler: {path}")
        row = {
            "checkpoint_id": provider["checkpoint_id"],
            "checkpoint_type": "sampler",
            "expires_at": provider.get("expires_at"),
            "public": bool(provider.get("public", False)),
            "size_bytes": int(provider["size_bytes"]),
            "time": provider.get("time") or provider.get("created_at"),
            "tinker_path": path,
        }
        prior = checkpoints.get(path)
        if prior is not None:
            for field in ("checkpoint_id", "checkpoint_type", "size_bytes"):
                if prior.get(field) != row[field]:
                    raise InventoryError(f"base/attestation {field} mismatch: {path}")
        else:
            checkpoints[path] = row

    rows = sorted(checkpoints.values(), key=lambda row: row["tinker_path"])
    total_bytes = sum(int(row["size_bytes"]) for row in rows)
    output = {
        "contract": "pearl.tinker-account-checkpoint-inventory/1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "identity": base["identity"],
        "checkpoint_count": len(rows),
        "checkpoint_bytes": total_bytes,
        "by_type": {"sampler": {"count": len(rows), "bytes": total_bytes}},
        "checkpoints": rows,
        "api_key_stored_separately": True,
        "deletion_authorized": False,
        "source_base_inventory_sha256": base["inventory_sha256"],
        "source_attestation_sha256": attestation["attestation_sha256"],
    }
    output["inventory_sha256"] = canonical_sha256(output, "inventory_sha256")
    atomic_json(args.output, output)
    print(
        json.dumps(
            {
                "checkpoint_count": output["checkpoint_count"],
                "checkpoint_bytes": output["checkpoint_bytes"],
                "inventory_sha256": output["inventory_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InventoryError, KeyError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
