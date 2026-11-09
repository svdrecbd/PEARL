#!/usr/bin/env python3
"""Capture a signed, deletion-disabled inventory of one Tinker account."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTRACT = "pearl.tinker-account-checkpoint-inventory/1"


class InventoryError(RuntimeError):
    """Raised when an inventory invariant does not hold."""


def canonical_sha256(value: dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "inventory_sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def list_checkpoints(rest: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    total: int | None = None
    while total is None or offset < total:
        page = rest.list_user_checkpoints(limit=100, offset=offset).result(timeout=120)
        rows.extend(row.model_dump(mode="json") for row in page.checkpoints)
        total = int(page.cursor.total_count) if page.cursor else len(rows)
        if not page.checkpoints:
            break
        offset += len(page.checkpoints)
    return sorted(rows, key=lambda row: row["tinker_path"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        api_key = os.environ.get("TINKER_API_KEY")
        if not api_key:
            raise InventoryError("TINKER_API_KEY is required")

        import tinker

        rest = tinker.ServiceClient(api_key=api_key).create_rest_client()
        identity = rest.whoami().result(timeout=60).model_dump(mode="json")
        checkpoints = list_checkpoints(rest)
        paths = [row.get("tinker_path") for row in checkpoints]
        if any(not isinstance(path, str) for path in paths):
            raise InventoryError("checkpoint path is missing")
        if len(paths) != len(set(paths)):
            raise InventoryError("checkpoint paths are duplicate")

        by_type: dict[str, dict[str, int]] = {}
        for row in checkpoints:
            kind = row["checkpoint_type"]
            summary = by_type.setdefault(kind, {"bytes": 0, "count": 0})
            summary["bytes"] += int(row["size_bytes"])
            summary["count"] += 1

        inventory = {
            "contract": CONTRACT,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "identity": identity,
            "checkpoint_count": len(checkpoints),
            "checkpoint_bytes": sum(int(row["size_bytes"]) for row in checkpoints),
            "by_type": by_type,
            "checkpoints": checkpoints,
            "deletion_authorized": False,
            "api_key_stored_separately": True,
        }
        inventory["inventory_sha256"] = canonical_sha256(inventory)
        atomic_json(args.output.resolve(), inventory)
        print(
            json.dumps(
                {
                    "output": str(args.output.resolve()),
                    "identity": identity,
                    "checkpoint_count": inventory["checkpoint_count"],
                    "checkpoint_bytes": inventory["checkpoint_bytes"],
                    "by_type": by_type,
                    "inventory_sha256": inventory["inventory_sha256"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (InventoryError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
