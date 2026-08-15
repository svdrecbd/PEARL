#!/usr/bin/env python3
"""Write a sanitized provider-identity receipt for one frozen scaling-paradox cell."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.scaling_campaign import audit_provider_identity, write_json  # noqa: E402


def load_launcher() -> Any:
    path = ROOT / "scripts" / "launch_scaling_paradox_v1.py"
    spec = importlib.util.spec_from_file_location("scaling_paradox_launcher", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load scaling-paradox launcher")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def quarantined_provider_ids(executor: dict[str, Any], run_key: str) -> list[str]:
    claims = executor.get("redundant_training_continuation_quarantine", {})
    if not isinstance(claims, dict):
        raise RuntimeError("redundant continuation quarantine is malformed")
    actions_ids: set[int] = set()
    provider_ids: set[str] = set()
    result: list[str] = []
    for actions_id_text, claim in claims.items():
        if not isinstance(claim, dict) or claim.get("contract") != (
            "pearl.frontier-redundant-continuation-quarantine/1"
        ):
            raise RuntimeError("redundant continuation quarantine contract is invalid")
        actions_id = int(actions_id_text)
        provider_id = str(claim.get("redundant_provider_training_run_id") or "")
        if actions_id <= 0 or actions_id in actions_ids or not provider_id:
            raise RuntimeError("redundant continuation quarantine identity is invalid")
        if provider_id in provider_ids:
            raise RuntimeError("redundant provider identity is quarantined more than once")
        actions_ids.add(actions_id)
        provider_ids.add(provider_id)
        if claim.get("run_key") == run_key:
            result.append(provider_id)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-contract", required=True)
    parser.add_argument("--checkpoint-lineage")
    parser.add_argument(
        "--executor-config",
        help="Executor config containing exact redundant-provider quarantine claims",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--provider-json", help="Offline provider-list fixture; otherwise query Tinker")
    args = parser.parse_args()
    contract = json.loads(Path(args.run_contract).read_text(encoding="utf-8"))
    if args.provider_json:
        payload = json.loads(Path(args.provider_json).read_text(encoding="utf-8"))
        rows = payload.get("runs", payload) if isinstance(payload, dict) else payload
    else:
        rows = load_launcher().provider_runs()
    if not isinstance(rows, list):
        raise RuntimeError("provider run listing has an invalid shape")
    lineage = (
        json.loads(Path(args.checkpoint_lineage).read_text(encoding="utf-8"))
        if args.checkpoint_lineage
        else None
    )
    quarantined = (
        quarantined_provider_ids(
            json.loads(Path(args.executor_config).read_text(encoding="utf-8")),
            str(contract["run_key"]),
        )
        if args.executor_config
        else []
    )
    receipt = audit_provider_identity(
        plan_entry=contract,
        provider_rows=rows,
        checkpoint_lineage=lineage,
        quarantined_provider_ids=quarantined,
    )
    write_json(Path(args.output), receipt)
    print(json.dumps({"provider_identity_valid": True, "run_key": contract["run_key"]}))


if __name__ == "__main__":
    main()
