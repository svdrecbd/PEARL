#!/usr/bin/env python3
"""Export the completed local original cohort as result-blind supervisor evidence."""

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

from pearl.scaling_campaign import read_json, sha256_value, write_json  # noqa: E402


DEFAULT_EXECUTOR = ROOT / "configs" / "experiments" / "frontier_adaptation_v2_executor.json"
ORIGINAL_CAMPAIGN_ID = "pearl-frontier-adaptation-v2-original"
ORIGINAL_PLAN_SHA = "ce4fd33d9f5f8d62d42a4ddc383222adc18c48ba1399920073beaf44879842c6"


def load_script(name: str, filename: str) -> Any:
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validated_receipt(path: Path, *, run_key: str, valid_field: str) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"completion handoff is missing {path}")
    receipt = read_json(path)
    if receipt.get("receipt_sha256") != sha256_value(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    ):
        raise RuntimeError(f"completion handoff receipt SHA mismatch for {run_key}")
    if (
        receipt.get("run_key") != run_key
        or receipt.get(valid_field) is not True
        or receipt.get("scientific_values_omitted") is not True
    ):
        raise RuntimeError(f"completion handoff receipt is invalid for {run_key}")
    return receipt


def choose_receipt(
    *, bootstrap_dir: Path, completion_dir: Path, kind: str, run_key: str
) -> Path:
    local = completion_dir / "receipts" / kind / f"{run_key}.json"
    bootstrap = bootstrap_dir / "receipts" / kind / f"{run_key}.json"
    if local.is_file():
        return local
    return bootstrap


def export(args: argparse.Namespace) -> dict[str, Any]:
    state_dir = Path(args.state_dir).resolve()
    bootstrap_dir = Path(args.bootstrap_state_dir).resolve()
    completion_dir = state_dir / "original_completion"
    manager = load_script("frontier_handoff_manager", "manage_scaling_paradox_campaign.py")
    local = load_script("frontier_handoff_local", "manage_frontier_local_wave.py")
    executor = read_json(Path(args.executor_config).resolve())
    plans = manager.build_plans(executor)
    plan = plans[("original", "core")]
    if plan["launch_plan_contract_sha"] != ORIGINAL_PLAN_SHA:
        raise RuntimeError("original completion handoff has the wrong frozen plan")
    entries = {str(row["run_key"]): row for row in plan["runs"]}
    ordered_keys = [str(row["run_key"]) for row in plan["runs"]]
    if len(entries) != 48 or len(ordered_keys) != 48:
        raise RuntimeError("original completion handoff does not contain 48 unique cells")

    events = local.read_ledger(state_dir / "ledger.jsonl")
    terminal_events = [
        event for event in events if event.get("event_type") == "original_optimization_complete"
    ]
    if len(terminal_events) != 1:
        raise RuntimeError("original controller has not reached one exact hard stop")
    terminal = terminal_events[0]
    payload = terminal.get("payload") or {}
    if (
        payload.get("training_receipt_count") != 48
        or payload.get("evaluation_receipt_count") != 48
        or payload.get("hard_stop_reached") is not True
        or payload.get("replication_started") is not False
        or payload.get("analysis_started") is not False
    ):
        raise RuntimeError("original controller hard-stop event is invalid")

    gate = read_json(completion_dir / "original_completion_gate.json")
    if gate.get("gate_sha256") != sha256_value(
        {key: value for key, value in gate.items() if key != "gate_sha256"}
    ):
        raise RuntimeError("original completion gate SHA mismatch")
    if (
        gate.get("contract") != "pearl.scaling-paradox-wave-gate/1"
        or gate.get("campaign_id") != ORIGINAL_CAMPAIGN_ID
        or gate.get("run_keys") != ordered_keys
        or gate.get("terminal_valid") is not True
        or gate.get("scientific_values_omitted") is not True
        or gate.get("gate_sha256") != payload.get("completion_gate_sha256")
    ):
        raise RuntimeError("original completion gate differs from the hard-stop event")

    training: dict[str, dict[str, Any]] = {}
    evaluation: dict[str, dict[str, Any]] = {}
    for run_key in ordered_keys:
        training[run_key] = validated_receipt(
            choose_receipt(
                bootstrap_dir=bootstrap_dir,
                completion_dir=completion_dir,
                kind="training",
                run_key=run_key,
            ),
            run_key=run_key,
            valid_field="training_terminal_valid",
        )
        evaluation[run_key] = validated_receipt(
            choose_receipt(
                bootstrap_dir=bootstrap_dir,
                completion_dir=completion_dir,
                kind="evaluation",
                run_key=run_key,
            ),
            run_key=run_key,
            valid_field="evaluation_terminal_valid",
        )
        for receipt in (training[run_key], evaluation[run_key]):
            if (
                receipt.get("campaign_id") != ORIGINAL_CAMPAIGN_ID
                or receipt.get("run_contract_sha") != entries[run_key]["run_contract_sha"]
            ):
                raise RuntimeError(f"original completion receipt differs from plan for {run_key}")

    if gate["training_receipt_shas"] != [training[key]["receipt_sha256"] for key in ordered_keys]:
        raise RuntimeError("training receipts differ from original completion gate")
    if gate["evaluation_receipt_shas"] != [evaluation[key]["receipt_sha256"] for key in ordered_keys]:
        raise RuntimeError("evaluation receipts differ from original completion gate")
    armed = [event for event in events if event.get("event_type") == "original_completion_armed"]
    if len(armed) != 1:
        raise RuntimeError("original completion source arm is absent or ambiguous")

    handoff: dict[str, Any] = {
        "contract": "pearl.frontier-original-completion-handoff/1",
        "campaign_id": ORIGINAL_CAMPAIGN_ID,
        "plan_sha": ORIGINAL_PLAN_SHA,
        "run_keys": ordered_keys,
        "completion_gate": gate,
        "training_receipts": training,
        "evaluation_receipts": evaluation,
        "controller_source_commit": armed[0]["payload"]["controller_source_commit"],
        "local_ledger_head_sha256": terminal["event_sha256"],
        "scientific_values_omitted": True,
        "replication_started": False,
        "analysis_started": False,
    }
    handoff["handoff_sha256"] = sha256_value(handoff)
    write_json(Path(args.output).resolve(), handoff)
    return handoff


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--bootstrap-state-dir", required=True)
    parser.add_argument("--executor-config", default=str(DEFAULT_EXECUTOR))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    handoff = export(args)
    print(
        json.dumps(
            {
                "output": str(Path(args.output).resolve()),
                "handoff_sha256": handoff["handoff_sha256"],
                "training_receipts": len(handoff["training_receipts"]),
                "evaluation_receipts": len(handoff["evaluation_receipts"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
