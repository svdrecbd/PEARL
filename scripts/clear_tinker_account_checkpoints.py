#!/usr/bin/env python3
"""Create and execute a fail-closed Tinker checkpoint deletion plan.

The source inventory is immutable evidence. Execution requires the exact plan
SHA-256, verifies the authenticated Tinker identity and every live checkpoint
field, records each completed deletion atomically, and never modifies API keys.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLAN_CONTRACT = "pearl.tinker-checkpoint-deletion-plan/1"
RECEIPT_CONTRACT = "pearl.tinker-checkpoint-deletion-receipt/1"


class ClearanceError(RuntimeError):
    """Raised when a checkpoint-clearance invariant does not hold."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def checkpoint_time(value: Any) -> datetime:
    """Parse an ISO-8601 checkpoint time into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ClearanceError("checkpoint time is not a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ClearanceError("checkpoint time has no timezone")
    return parsed.astimezone(timezone.utc)


def canonical_sha256(value: dict[str, Any], hash_field: str) -> str:
    payload = {key: item for key, item in value.items() if key != hash_field}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ClearanceError(f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def validate_inventory(value: dict[str, Any]) -> None:
    if value.get("contract") != "pearl.tinker-account-checkpoint-inventory/1":
        raise ClearanceError("source inventory has the wrong contract")
    if value.get("inventory_sha256") != canonical_sha256(value, "inventory_sha256"):
        raise ClearanceError("source inventory SHA-256 mismatch")
    checkpoints = value.get("checkpoints")
    if not isinstance(checkpoints, list):
        raise ClearanceError("source inventory checkpoints are invalid")
    paths = [row.get("tinker_path") for row in checkpoints]
    if any(not isinstance(path, str) for path in paths) or len(paths) != len(set(paths)):
        raise ClearanceError("source inventory checkpoint paths are missing or duplicate")


def build_plan(inventory: dict[str, Any], checkpoint_type: str) -> dict[str, Any]:
    validate_inventory(inventory)
    targets = [
        {
            "checkpoint_id": row["checkpoint_id"],
            "checkpoint_type": row["checkpoint_type"],
            "size_bytes": int(row["size_bytes"]),
            "time": row["time"],
            "tinker_path": row["tinker_path"],
        }
        for row in inventory["checkpoints"]
        if checkpoint_type == "all" or row["checkpoint_type"] == checkpoint_type
    ]
    targets.sort(key=lambda row: row["tinker_path"])
    if not targets:
        raise ClearanceError("deletion plan contains no targets")
    plan = {
        "contract": PLAN_CONTRACT,
        "created_at": utc_now(),
        "source_inventory_sha256": inventory["inventory_sha256"],
        "identity": inventory["identity"],
        "selection": {"checkpoint_type": checkpoint_type},
        "target_count": len(targets),
        "target_bytes": sum(row["size_bytes"] for row in targets),
        "targets": targets,
        "api_key_mutation_authorized": False,
        "checkpoint_deletion_authorized": True,
    }
    plan["plan_sha256"] = canonical_sha256(plan, "plan_sha256")
    return plan


def validate_plan(value: dict[str, Any]) -> None:
    if value.get("contract") != PLAN_CONTRACT:
        raise ClearanceError("deletion plan has the wrong contract")
    if value.get("plan_sha256") != canonical_sha256(value, "plan_sha256"):
        raise ClearanceError("deletion plan SHA-256 mismatch")
    if value.get("api_key_mutation_authorized") is not False:
        raise ClearanceError("deletion plan does not protect API keys")
    if value.get("checkpoint_deletion_authorized") is not True:
        raise ClearanceError("deletion plan is not authorized")


def list_live_checkpoints(rest: Any) -> list[dict[str, Any]]:
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
    return rows


def execute(plan: dict[str, Any], confirm_sha: str, receipt_path: Path) -> dict[str, Any]:
    validate_plan(plan)
    if confirm_sha != plan["plan_sha256"]:
        raise ClearanceError("--confirm-plan-sha does not match the exact plan")
    api_key = os.environ.get("TINKER_API_KEY")
    if not api_key:
        raise ClearanceError("TINKER_API_KEY is required")

    import tinker

    rest = tinker.ServiceClient(api_key=api_key).create_rest_client()
    identity = rest.whoami().result(timeout=60).model_dump(mode="json")
    if identity != plan["identity"]:
        raise ClearanceError("authenticated Tinker identity does not match the plan")

    if receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt.get("contract") != RECEIPT_CONTRACT:
            raise ClearanceError("existing deletion receipt has the wrong contract")
        if receipt.get("plan_sha256") != plan["plan_sha256"]:
            raise ClearanceError("existing deletion receipt belongs to another plan")
    else:
        receipt = {
            "contract": RECEIPT_CONTRACT,
            "started_at": utc_now(),
            "plan_sha256": plan["plan_sha256"],
            "identity": identity,
            "deleted": {},
            "api_key_modified": False,
            "terminal_valid": False,
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt, "receipt_sha256")
        atomic_json(receipt_path, receipt)

    live = {row["tinker_path"]: row for row in list_live_checkpoints(rest)}
    for target in plan["targets"]:
        path = target["tinker_path"]
        observed = live.get(path)
        if path in receipt["deleted"]:
            if observed is not None:
                raise ClearanceError(f"recorded deletion is live again: {path}")
            continue
        if observed is None:
            raise ClearanceError(f"unrecorded planned checkpoint is absent: {path}")
        for field in ("checkpoint_id", "checkpoint_type", "size_bytes"):
            if observed[field] != target[field]:
                raise ClearanceError(f"live checkpoint {field} mismatch: {path}")
        if checkpoint_time(observed["time"]) != checkpoint_time(target["time"]):
            raise ClearanceError(f"live checkpoint time mismatch: {path}")

    for index, target in enumerate(plan["targets"], start=1):
        path = target["tinker_path"]
        if path in receipt["deleted"]:
            print(f"[{index}/{len(plan['targets'])}] RECORDED {path}", flush=True)
            continue
        rest.delete_checkpoint_from_tinker_path(path).result(timeout=120)
        receipt["deleted"][path] = {
            "deleted_at": utc_now(),
            "checkpoint_id": target["checkpoint_id"],
            "checkpoint_type": target["checkpoint_type"],
            "size_bytes": target["size_bytes"],
        }
        receipt["receipt_sha256"] = canonical_sha256(receipt, "receipt_sha256")
        atomic_json(receipt_path, receipt)
        print(f"[{index}/{len(plan['targets'])}] DELETED {path}", flush=True)

    remaining = {row["tinker_path"] for row in list_live_checkpoints(rest)}
    undeleted = sorted({row["tinker_path"] for row in plan["targets"]} & remaining)
    if undeleted:
        raise ClearanceError(f"provider still reports {len(undeleted)} planned checkpoints")
    receipt["completed_at"] = utc_now()
    receipt["deleted_count"] = len(receipt["deleted"])
    receipt["deleted_bytes"] = sum(
        int(row["size_bytes"]) for row in receipt["deleted"].values()
    )
    receipt["terminal_valid"] = receipt["deleted_count"] == plan["target_count"]
    receipt["receipt_sha256"] = canonical_sha256(receipt, "receipt_sha256")
    atomic_json(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--checkpoint-type", choices=("training", "sampler", "all"))
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-plan-sha")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()

    try:
        if args.execute:
            if not args.plan or not args.confirm_plan_sha or not args.receipt:
                raise ClearanceError("execution requires --plan, --confirm-plan-sha, and --receipt")
            receipt = execute(
                read_json(args.plan.resolve()),
                args.confirm_plan_sha,
                args.receipt.resolve(),
            )
            print(json.dumps(receipt, indent=2, sort_keys=True))
            return 0

        if not args.inventory or not args.checkpoint_type or not args.plan_output:
            raise ClearanceError(
                "planning requires --inventory, --checkpoint-type, and --plan-output"
            )
        plan = build_plan(read_json(args.inventory.resolve()), args.checkpoint_type)
        atomic_json(args.plan_output.resolve(), plan)
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    except (ClearanceError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
