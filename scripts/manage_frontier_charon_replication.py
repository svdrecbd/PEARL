#!/usr/bin/env python3
"""Run the frozen post-sentinel Frontier v2 replication cohort on Charon."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.scaling_campaign import (  # noqa: E402
    audit_evaluation_artifact,
    audit_training_artifact,
    build_wave_gate,
    read_json,
    sha256_file,
    sha256_value,
)
from pearl.tinker_dpo import pair_rows_fingerprint  # noqa: E402


DEFAULT_EXECUTOR = ROOT / "configs" / "experiments" / "frontier_adaptation_v2_executor.json"
REPLICATION_CAMPAIGN_ID = "pearl-frontier-adaptation-v2-replication"
REPLICATION_PLAN_SHA = "85660f7b99193e34a546f9eb50dfe18ff10fe42d3127232686be9b5ee7fd2593"
TERMINAL_STEP = 2250
RUN_COUNT = 48
POST_SENTINEL_COUNT = 47
TIER_PREFIXES = (12, 24, 47)


class SafetyStop(RuntimeError):
    """An expected fail-closed Charon boundary."""


def load_script(name: str, filename: str) -> Any:
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def signed(payload: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(payload)
    result[field] = sha256_value(result)
    return result


def validate_signed(payload: dict[str, Any], field: str) -> str:
    observed = str(payload.get(field) or "")
    if observed != sha256_value({key: value for key, value in payload.items() if key != field}):
        raise SafetyStop(f"{field} is invalid")
    return observed


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise SafetyStop("operational timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise SafetyStop("operational timestamp lacks a timezone")
    return parsed.astimezone(UTC)


def frozen_context(args: argparse.Namespace) -> tuple[Any, Any, Any, dict[str, Any], dict[str, Any], list[str]]:
    manager = load_script("charon_campaign_manager", "manage_scaling_paradox_campaign.py")
    launcher = load_script("charon_launcher", "launch_scaling_paradox_v1.py")
    local = load_script("charon_local_ledger", "manage_frontier_local_wave.py")
    executor = read_json(Path(args.executor_config).resolve())
    controller_contract = executor.get("charon_replication_controller") or {}
    if (
        executor.get("contract") != "pearl.frontier-adaptation-executor/8"
        or controller_contract.get("contract") != "pearl.frontier-charon-controller/1"
        or controller_contract.get("replication_plan_sha256") != REPLICATION_PLAN_SHA
        or controller_contract.get("capacity_tier_prefixes") != list(TIER_PREFIXES)
        or controller_contract.get("post_sentinel_training_count") != POST_SENTINEL_COUNT
        or controller_contract.get("post_sentinel_terminal_step") != TERMINAL_STEP
        or controller_contract.get("github_post_sentinel_hold") != "charon_local_takeover"
        or controller_contract.get("scientific_values_consulted") is not False
        or controller_contract.get("analysis_authorized") is not False
        or controller_contract.get("structural_authorized") is not False
    ):
        raise SafetyStop("Charon controller metadata differs from executor contract v8")
    plans = manager.build_plans(executor)
    plan = plans[("replication", "core")]
    if plan["launch_plan_contract_sha"] != REPLICATION_PLAN_SHA:
        raise SafetyStop("Charon replication plan SHA differs from the frozen plan")
    entries = {str(row["run_key"]): row for row in plan["runs"]}
    ordered = [str(row["run_key"]) for row in plan["runs"]]
    if len(entries) != RUN_COUNT or len(ordered) != RUN_COUNT or len(set(ordered)) != RUN_COUNT:
        raise SafetyStop("Charon replication plan is not the exact 48-cell cohort")
    return manager, launcher, local, executor, plan, ordered


def existing_events(events: list[dict[str, Any]], event_type: str) -> dict[str, dict[str, Any]]:
    return {
        str(event["payload"]["run_key"]): event
        for event in events
        if event.get("event_type") == event_type and (event.get("payload") or {}).get("run_key")
    }


def valid_receipt(path: Path, *, run_key: str, valid_field: str) -> dict[str, Any]:
    if not path.is_file():
        raise SafetyStop(f"required receipt is absent: {path}")
    receipt = read_json(path)
    if receipt.get("receipt_sha256") != sha256_value(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    ):
        raise SafetyStop(f"receipt SHA mismatch for {run_key}")
    if (
        receipt.get("run_key") != run_key
        or receipt.get(valid_field) is not True
        or receipt.get("scientific_values_omitted") is not True
    ):
        raise SafetyStop(f"receipt is invalid for {run_key}")
    return receipt


def validate_bootstrap(
    *, args: argparse.Namespace, manager: Any, executor: dict[str, Any], plan: dict[str, Any], ordered: list[str]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    bootstrap_dir = Path(args.bootstrap_dir).resolve()
    bootstrap = read_json(bootstrap_dir / "charon_bootstrap.json")
    validate_signed(bootstrap, "bootstrap_sha256")
    sentinel = ordered[0]
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if (
        bootstrap.get("contract") != "pearl.frontier-charon-bootstrap/1"
        or bootstrap.get("source_commit") != source_commit
        or bootstrap.get("replication_plan_sha") != REPLICATION_PLAN_SHA
        or bootstrap.get("replication_sentinel_run_key") != sentinel
        or bootstrap.get("post_sentinel_hold_reason")
        != "replication_sentinel_complete_pending_charon_takeover"
        or bootstrap.get("scientific_values_omitted") is not True
        or bootstrap.get("analysis_authorized") is not False
    ):
        raise SafetyStop("Charon bootstrap differs from the frozen handoff")
    source_spec = executor.get("external_completion_handoff") or {}
    if (
        source_spec.get("contract") != "pearl.frontier-external-completion-handoff-source/1"
        or bootstrap.get("original_completion_handoff_file_sha256") != source_spec.get("sha256")
    ):
        raise SafetyStop("Charon bootstrap is not bound to the original completion handoff")
    validation_state = bootstrap_dir / "validated_original_state"
    imported = manager.import_external_completion_handoff(
        executor=executor,
        plans=manager.build_plans(executor),
        state_dir=validation_state,
    )
    if imported != {"training": 48, "evaluation": 48} and imported != {"training": 0, "evaluation": 0}:
        raise SafetyStop("original completion handoff import is incomplete")
    training = valid_receipt(
        bootstrap_dir / "sentinel" / "training_receipt.json",
        run_key=sentinel,
        valid_field="training_terminal_valid",
    )
    evaluation = valid_receipt(
        bootstrap_dir / "sentinel" / "evaluation_receipt.json",
        run_key=sentinel,
        valid_field="evaluation_terminal_valid",
    )
    entry = {str(row["run_key"]): row for row in plan["runs"]}[sentinel]
    if (
        training.get("campaign_id") != REPLICATION_CAMPAIGN_ID
        or evaluation.get("campaign_id") != REPLICATION_CAMPAIGN_ID
        or training.get("run_contract_sha") != entry["run_contract_sha"]
        or evaluation.get("run_contract_sha") != entry["run_contract_sha"]
        or evaluation.get("source_training_actions_run_id") != training.get("source_actions_run_id")
        or bootstrap.get("sentinel_training_receipt_sha256") != training["receipt_sha256"]
        or bootstrap.get("sentinel_evaluation_receipt_sha256") != evaluation["receipt_sha256"]
    ):
        raise SafetyStop("Charon bootstrap sentinel evidence differs from the frozen cell")
    hold_run_id = int(bootstrap.get("hold_supervisor_actions_run_id", 0))
    hold_run = manager.gh_json(
        ["gh", "run", "view", str(hold_run_id), "--json", "status,conclusion,workflowName,headSha"]
    )
    if (
        hold_run.get("status") != "completed"
        or hold_run.get("conclusion") != "success"
        or hold_run.get("workflowName") != executor["supervisor_workflow_name"]
        or hold_run.get("headSha") != bootstrap["source_commit"]
    ):
        raise SafetyStop("Charon bootstrap hold is not bound to a successful supervisor")
    return bootstrap, training, evaluation


def fresh_provider_snapshot(manager: Any, plans: dict[tuple[str, str], dict[str, Any]], output: Path) -> dict[str, Any]:
    snapshot = manager.build_provider_snapshot(plans)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return snapshot


def validate_prelaunch_provider(
    *, snapshot: dict[str, Any], plan: dict[str, Any], ordered: list[str]
) -> None:
    entries = {str(row["run_key"]): row for row in plan["runs"]}
    replication_rows = [
        row for row in snapshot["runs"] if row["campaign_id"] == REPLICATION_CAMPAIGN_ID
    ]
    by_key: dict[str, list[dict[str, Any]]] = {}
    for row in replication_rows:
        by_key.setdefault(str(row["run_key"]), []).append(row)
    sentinel = ordered[0]
    if not by_key.get(sentinel):
        raise SafetyStop("provider has no replication sentinel lineage")
    if any(row["run_contract_sha"] != entries[sentinel]["run_contract_sha"] for row in by_key[sentinel]):
        raise SafetyStop("provider sentinel lineage differs from the frozen contract")
    unexpected = sorted(set(by_key) - {sentinel})
    if unexpected:
        raise SafetyStop("provider already contains post-sentinel replication ownership: " + ", ".join(unexpected))


def build_takeover_authorization(
    *,
    bootstrap: dict[str, Any],
    plan: dict[str, Any],
    ordered: list[str],
    provider_sha: str,
    source_commit: str,
    estimated_evaluation_cost_usd: float,
) -> dict[str, Any]:
    entries = {str(row["run_key"]): row for row in plan["runs"]}
    keys = ordered[1:]
    training_cost = round(
        sum(float(entries[key]["cost_estimate"]["estimated_training_cost_usd"]) for key in keys),
        4,
    )
    return signed(
        {
            "contract": "pearl.frontier-charon-replication-authorization/1",
            "action": "complete_post_sentinel_replication",
            "campaign": "replication",
            "campaign_id": REPLICATION_CAMPAIGN_ID,
            "stage": "core",
            "plan_sha": REPLICATION_PLAN_SHA,
            "replication_sentinel_run_key": ordered[0],
            "authorized_run_keys": keys,
            "run_contract_shas": {key: entries[key]["run_contract_sha"] for key in keys},
            "segment_end_steps": {key: TERMINAL_STEP for key in keys},
            "capacity_tier_prefixes": list(TIER_PREFIXES),
            "capacity_observation_minutes": 20,
            "max_provider_staleness_minutes": 15,
            "max_active_after_dispatch": POST_SENTINEL_COUNT,
            "estimated_training_cost_usd": training_cost,
            "estimated_evaluation_cost_usd": estimated_evaluation_cost_usd,
            "estimated_total_cost_usd": round(training_cost + estimated_evaluation_cost_usd, 4),
            "provider_snapshot_sha256": provider_sha,
            "bootstrap_sha256": bootstrap["bootstrap_sha256"],
            "controller_source_commit": source_commit,
            "scientific_contract_changed": False,
            "analysis_authorized": False,
        },
        "authorization_sha256",
    )


def prepare(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir).resolve()
    mirror_dir = Path(args.mirror_dir).resolve()
    if state_dir.exists() and any(state_dir.iterdir()):
        raise SafetyStop("Charon state directory is not empty")
    if not os.environ.get("TINKER_API_KEY"):
        raise SafetyStop("TINKER_API_KEY is unavailable")
    manager, launcher, local, executor, plan, ordered = frozen_context(args)
    source_commit = local.tracked_source_is_clean()
    bootstrap, _, _ = validate_bootstrap(
        args=args, manager=manager, executor=executor, plan=plan, ordered=ordered
    )
    if bootstrap["source_commit"] != source_commit:
        raise SafetyStop("Charon source differs from the bootstrap commit")
    if local.github_nonterminal_runs():
        raise SafetyStop("GitHub frontier ownership is nonterminal")
    local.require_supervisor_disabled()
    if shutil.disk_usage(ROOT).free < args.minimum_free_bytes:
        raise SafetyStop("free disk is below the Charon safety floor")
    plans = manager.build_plans(executor)
    snapshot_path = state_dir / "provider_snapshot_at_takeover.json"
    snapshot = fresh_provider_snapshot(manager, plans, snapshot_path)
    validate_prelaunch_provider(snapshot=snapshot, plan=plan, ordered=ordered)
    entries = {str(row["run_key"]): row for row in plan["runs"]}
    manifest = manager.build_manifest(executor)
    replication_phase = next(
        phase for phase in manifest["phases"] if phase["phase"] == "replication:core"
    )
    evaluation_cost_by_key = {
        run_key: float(wave["estimated_checkpoint_evaluation_cost_by_run_key"][run_key])
        for wave in replication_phase["waves"]
        for run_key in wave["run_keys"]
    }
    post_sentinel_evaluation_cost = round(
        sum(evaluation_cost_by_key[key] for key in ordered[1:]), 4
    )
    authorization = build_takeover_authorization(
        bootstrap=bootstrap,
        plan=plan,
        ordered=ordered,
        provider_sha=snapshot["snapshot_sha256"],
        source_commit=source_commit,
        estimated_evaluation_cost_usd=post_sentinel_evaluation_cost,
    )
    expected_post_sentinel_training_cost = round(
        sum(
            float(entries[key]["cost_estimate"]["estimated_training_cost_usd"])
            for key in ordered[1:]
        ),
        4,
    )
    expected_post_sentinel_total = round(
        expected_post_sentinel_training_cost + post_sentinel_evaluation_cost,
        4,
    )
    if (
        authorization["estimated_training_cost_usd"] != expected_post_sentinel_training_cost
        or authorization["estimated_total_cost_usd"] != expected_post_sentinel_total
    ):
        raise SafetyStop("Charon authorization does not equal the exact 47-cell cost estimate")
    if authorization["estimated_total_cost_usd"] > float(executor["planned_total_with_recovery_ceiling_usd"]):
        raise SafetyStop("Charon authorization exceeds the frozen campaign ceiling")
    local.atomic_json(state_dir / "authorization.json", authorization)
    local.atomic_json(mirror_dir / "authorization.json", authorization)
    local.append_ledger(
        state_dir,
        mirror_dir,
        "charon_takeover_prepared",
        {
            "authorization_sha256": authorization["authorization_sha256"],
            "controller_source_commit": source_commit,
            "authorized_count": POST_SENTINEL_COUNT,
            "capacity_tier_prefixes": list(TIER_PREFIXES),
            "replication_sentinel_complete": True,
            "analysis_authorized": False,
        },
    )
    print(json.dumps({"prepared": True, "authorization_sha256": authorization["authorization_sha256"]}, indent=2))


def process_alive(run_key: str, *, evaluation: bool = False) -> bool:
    script = "run_frontier_local_evaluation.py" if evaluation else "run_tinker_dpo_smoke.py"
    result = subprocess.run(
        ["pgrep", "-f", f"{script}.*--run-key {run_key}"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def training_receipt_path(state_dir: Path, run_key: str) -> Path:
    return state_dir / "receipts" / "training" / f"{run_key}.json"


def evaluation_receipt_path(state_dir: Path, run_key: str) -> Path:
    return state_dir / "receipts" / "evaluation" / f"{run_key}.json"


def audit_finished_training(
    *, state_dir: Path, mirror_dir: Path, local: Any, entries: dict[str, dict[str, Any]], started_keys: list[str]
) -> None:
    events = local.read_ledger(state_dir / "ledger.jsonl")
    audited = existing_events(events, "charon_training_audited")
    for run_key in started_keys:
        if run_key in audited or process_alive(run_key):
            continue
        try:
            receipt = audit_training_artifact(
                plan_entry=entries[run_key],
                run_dir=ROOT / "reports" / "frontier_adaptation_v2_replication" / "runs" / run_key,
            )
        except Exception as error:
            raise SafetyStop(f"Charon trainer ended without a valid terminal artifact: {run_key}") from error
        local.atomic_json(training_receipt_path(state_dir, run_key), receipt)
        local.append_ledger(
            state_dir,
            mirror_dir,
            "charon_training_audited",
            {"run_key": run_key, "training_receipt_sha256": receipt["receipt_sha256"]},
        )


def launch_keys(
    *,
    args: argparse.Namespace,
    state_dir: Path,
    mirror_dir: Path,
    launcher: Any,
    local: Any,
    plan: dict[str, Any],
    entries: dict[str, dict[str, Any]],
    authorization: dict[str, Any],
    keys: list[str],
    tier: int,
) -> None:
    events = local.read_ledger(state_dir / "ledger.jsonl")
    intents = existing_events(events, "charon_training_launch_intent")
    starts = existing_events(events, "charon_training_started")
    if local.github_nonterminal_runs():
        raise SafetyStop("GitHub frontier ownership reappeared during Charon launch")
    local.require_supervisor_disabled()
    for run_key in keys:
        if run_key in intents and run_key not in starts:
            raise SafetyStop(f"ambiguous Charon launch intent without start record: {run_key}")
        if run_key in starts:
            continue
        intent = local.append_ledger(
            state_dir,
            mirror_dir,
            "charon_training_launch_intent",
            {
                "run_key": run_key,
                "tier_prefix": tier,
                "authorization_sha256": authorization["authorization_sha256"],
                "segment_end_step": TERMINAL_STEP,
            },
        )
        run_dir = ROOT / "reports" / "frontier_adaptation_v2_replication" / "runs" / run_key
        run_dir.mkdir(parents=True, exist_ok=True)
        local_receipt = signed(
            {
                "contract": "pearl.frontier-charon-training-authorization-receipt/1",
                "run_key": run_key,
                "run_contract_sha": entries[run_key]["run_contract_sha"],
                "authorization_sha256": authorization["authorization_sha256"],
                "launch_intent_event_sha256": intent["event_sha256"],
                "tier_prefix": tier,
                "segment_end_step": TERMINAL_STEP,
                "scientific_contract_changed": False,
            },
            "receipt_sha256",
        )
        local.atomic_json(run_dir / "charon_authorization_receipt.json", local_receipt)
        try:
            pid, returncode = launcher.launch_one(
                entries[run_key],
                plan,
                ROOT / "reports" / "frontier_adaptation_v2_replication",
                resume=False,
                wait=False,
                segment_end_step=TERMINAL_STEP,
            )
            if returncode is not None:
                raise RuntimeError("Charon trainer returned synchronously")
        except Exception as error:
            local.append_ledger(
                state_dir,
                mirror_dir,
                "charon_training_launch_failed",
                {"run_key": run_key, "failure": f"{type(error).__name__}: {error}"},
            )
            raise SafetyStop(f"Charon training launch failed for {run_key}") from error
        local.append_ledger(
            state_dir,
            mirror_dir,
            "charon_training_started",
            {
                "run_key": run_key,
                "pid": pid,
                "tier_prefix": tier,
                "authorization_sha256": authorization["authorization_sha256"],
            },
        )


def wait_for_capacity_gate(
    *,
    args: argparse.Namespace,
    state_dir: Path,
    mirror_dir: Path,
    manager: Any,
    local: Any,
    plans: dict[tuple[str, str], dict[str, Any]],
    entries: dict[str, dict[str, Any]],
    prefix_keys: list[str],
    next_limit: int,
) -> None:
    event_type = f"charon_capacity_gate_{next_limit}_opened"
    if any(event.get("event_type") == event_type for event in local.read_ledger(state_dir / "ledger.jsonl")):
        return
    while True:
        events = local.read_ledger(state_dir / "ledger.jsonl")
        starts = existing_events(events, "charon_training_started")
        audit_finished_training(
            state_dir=state_dir,
            mirror_dir=mirror_dir,
            local=local,
            entries=entries,
            started_keys=list(starts),
        )
        events = local.read_ledger(state_dir / "ledger.jsonl")
        audited = existing_events(events, "charon_training_audited")
        starts = existing_events(events, "charon_training_started")
        observation = timedelta(minutes=args.capacity_observation_minutes)
        waiting_for_age = any(
            run_key not in audited
            and run_key in starts
            and datetime.now(UTC) - parse_time(starts[run_key]["observed_at_utc"]) < observation
            for run_key in prefix_keys
        )
        if waiting_for_age:
            time.sleep(args.poll_seconds)
            continue
        snapshot = fresh_provider_snapshot(
            manager,
            plans,
            state_dir / "capacity_snapshots" / f"tier-{next_limit}-latest.json",
        )
        observed_at = parse_time(snapshot["observed_at_utc"])
        provider_by_key: dict[str, list[dict[str, Any]]] = {}
        for row in snapshot["runs"]:
            if row["campaign_id"] == REPLICATION_CAMPAIGN_ID:
                provider_by_key.setdefault(str(row["run_key"]), []).append(row)
        evidence: list[dict[str, Any]] = []
        healthy = True
        for run_key in prefix_keys:
            if run_key in audited:
                receipt = valid_receipt(
                    training_receipt_path(state_dir, run_key),
                    run_key=run_key,
                    valid_field="training_terminal_valid",
                )
                evidence.append(
                    {"run_key": run_key, "evidence": "audited_terminal_training", "receipt_sha256": receipt["receipt_sha256"]}
                )
                continue
            start = starts.get(run_key)
            if start is None or not process_alive(run_key):
                healthy = False
                break
            if observed_at - parse_time(start["observed_at_utc"]) < timedelta(
                minutes=args.capacity_observation_minutes
            ):
                healthy = False
                break
            rows = provider_by_key.get(run_key, [])
            if (
                len(rows) != 1
                or rows[0]["run_contract_sha"] != entries[run_key]["run_contract_sha"]
                or rows[0]["corrupted"] is not False
            ):
                healthy = False
                break
            latest = parse_time(rows[0]["last_request_time"])
            if observed_at - latest > timedelta(minutes=args.max_provider_staleness_minutes):
                healthy = False
                break
            evidence.append(
                {
                    "run_key": run_key,
                    "evidence": "sustained_uncorrupted_provider_progress",
                    "provider_training_run_id": rows[0]["provider_training_run_id"],
                    "observed_minutes": args.capacity_observation_minutes,
                }
            )
        if healthy and len(evidence) == len(prefix_keys):
            gate = signed(
                {
                    "contract": "pearl.frontier-charon-capacity-gate/1",
                    "campaign": "replication",
                    "plan_sha": REPLICATION_PLAN_SHA,
                    "minimum_started_cells": len(prefix_keys),
                    "authorized_max_active_cells": next_limit,
                    "provider_snapshot_sha256": snapshot["snapshot_sha256"],
                    "operational_evidence": evidence,
                    "scientific_values_omitted": True,
                },
                "gate_sha256",
            )
            local.atomic_json(state_dir / "capacity_gates" / f"tier-{next_limit}.json", gate)
            local.append_ledger(
                state_dir,
                mirror_dir,
                event_type,
                {"gate_sha256": gate["gate_sha256"], "authorized_max_active_cells": next_limit},
            )
            return
        time.sleep(args.poll_seconds)


def wait_for_all_training(
    *, args: argparse.Namespace, state_dir: Path, mirror_dir: Path, local: Any, entries: dict[str, dict[str, Any]], keys: list[str]
) -> None:
    while True:
        events = local.read_ledger(state_dir / "ledger.jsonl")
        starts = existing_events(events, "charon_training_started")
        if set(starts) != set(keys):
            raise SafetyStop("Charon did not start the exact 47 post-sentinel cells")
        audit_finished_training(
            state_dir=state_dir,
            mirror_dir=mirror_dir,
            local=local,
            entries=entries,
            started_keys=keys,
        )
        audited = existing_events(local.read_ledger(state_dir / "ledger.jsonl"), "charon_training_audited")
        if set(audited) == set(keys):
            return
        if not any(process_alive(key) for key in keys if key not in audited):
            raise SafetyStop("Charon training state is incomplete without a live owner")
        time.sleep(args.poll_seconds)


def raw_provider_snapshot(launcher: Any, output: Path) -> list[dict[str, Any]]:
    rows = launcher.provider_runs()
    payload: dict[str, Any] = {
        "contract": "pearl.frontier-charon-raw-provider-snapshot/1",
        "observed_at_utc": now_utc(),
        "runs": rows,
    }
    payload["snapshot_sha256"] = sha256_value(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return rows


def partition_contracts(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    launcher = load_script("charon_partition_launcher", "launch_scaling_paradox_v1.py")
    result: dict[str, dict[str, Any]] = {}
    for name in ("holdout", "challenge"):
        rows = launcher.load_jsonl(ROOT / entry[f"{name}_path"])
        result[name] = {"pair_count": len(rows), "pair_fingerprint": pair_rows_fingerprint(rows)}
    return result


def build_evaluation_authorization(
    *,
    state_dir: Path,
    entries: dict[str, dict[str, Any]],
    keys: list[str],
    training: dict[str, dict[str, Any]],
    provider_sha: str,
    source_commit: str,
    estimated_cost_usd: float,
) -> dict[str, Any]:
    return signed(
        {
            "contract": "pearl.frontier-local-evaluation-authorization/1",
            "action": "evaluate_charon_replication_endpoints",
            "campaign": "replication",
            "stage": "core",
            "plan_sha": REPLICATION_PLAN_SHA,
            "authorized_run_keys": keys,
            "run_contract_shas": {key: entries[key]["run_contract_sha"] for key in keys},
            "training_receipt_shas": {key: training[key]["receipt_sha256"] for key in keys},
            "provider_snapshot_sha256": provider_sha,
            "controller_source_commit": source_commit,
            "evaluator_sha256": sha256_file(ROOT / "scripts" / "evaluate_scaling_paradox_checkpoint.py"),
            "evaluation_worker_sha256": sha256_file(ROOT / "scripts" / "run_frontier_local_evaluation.py"),
            "max_active_after_dispatch": len(keys),
            "estimated_cost_usd": estimated_cost_usd,
            "replication_authorized": True,
            "analysis_authorized": False,
            "scientific_contract_changed": False,
        },
        "authorization_sha256",
    )


def run_evaluations(
    *,
    args: argparse.Namespace,
    state_dir: Path,
    mirror_dir: Path,
    local: Any,
    entries: dict[str, dict[str, Any]],
    keys: list[str],
    training: dict[str, dict[str, Any]],
    authorization: dict[str, Any],
) -> None:
    auth_path = state_dir / "evaluation_authorization.json"
    provider_json = state_dir / "provider_snapshot_before_evaluation.json"
    output_root = state_dir / "evaluation_artifacts"
    while True:
        events = local.read_ledger(state_dir / "ledger.jsonl")
        intents = existing_events(events, "charon_evaluation_launch_intent")
        starts = existing_events(events, "charon_evaluation_started")
        audited = existing_events(events, "charon_evaluation_audited")
        for run_key in keys:
            if run_key in audited:
                continue
            if run_key in intents and run_key not in starts:
                raise SafetyStop(f"ambiguous Charon evaluation intent without start: {run_key}")
            if run_key in starts:
                continue
            output_dir = output_root / run_key
            if output_dir.exists() and any(output_dir.iterdir()):
                raise SafetyStop(f"unowned Charon evaluation directory exists: {run_key}")
            intent = local.append_ledger(
                state_dir,
                mirror_dir,
                "charon_evaluation_launch_intent",
                {"run_key": run_key, "authorization_sha256": authorization["authorization_sha256"]},
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            local.atomic_json(
                output_dir / "charon_evaluation_authorization_receipt.json",
                signed(
                    {
                        "contract": "pearl.frontier-charon-evaluation-authorization-receipt/1",
                        "run_key": run_key,
                        "run_contract_sha": entries[run_key]["run_contract_sha"],
                        "authorization_sha256": authorization["authorization_sha256"],
                        "launch_intent_event_sha256": intent["event_sha256"],
                        "scientific_contract_changed": False,
                    },
                    "receipt_sha256",
                ),
            )
            run_dir = ROOT / "reports" / "frontier_adaptation_v2_replication" / "runs" / run_key
            command = [
                sys.executable,
                str(ROOT / "scripts" / "run_frontier_local_evaluation.py"),
                "--authorization",
                str(auth_path),
                "--run-key",
                run_key,
                "--run-contract",
                str(run_dir / "run_contract.json"),
                "--training-report",
                str(run_dir / "report.json"),
                "--checkpoint-lineage",
                str(run_dir / "checkpoint_lineage.json"),
                "--provider-json",
                str(provider_json),
                "--executor-config",
                str(Path(args.executor_config).resolve()),
                "--output-dir",
                str(output_dir),
            ]
            with (output_dir / "evaluator.log").open("a", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    env=os.environ.copy(),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            local.append_ledger(
                state_dir,
                mirror_dir,
                "charon_evaluation_started",
                {"run_key": run_key, "pid": process.pid, "authorization_sha256": authorization["authorization_sha256"]},
            )
        events = local.read_ledger(state_dir / "ledger.jsonl")
        audited = existing_events(events, "charon_evaluation_audited")
        for run_key in keys:
            if run_key in audited or process_alive(run_key, evaluation=True):
                continue
            try:
                receipt = audit_evaluation_artifact(
                    plan_entry=entries[run_key],
                    evaluation_dir=output_root / run_key,
                    training_receipt=training[run_key],
                    partition_contracts=partition_contracts(entries[run_key]),
                )
            except Exception as error:
                raise SafetyStop(f"Charon evaluation ended without a valid artifact: {run_key}") from error
            local.atomic_json(evaluation_receipt_path(state_dir, run_key), receipt)
            local.append_ledger(
                state_dir,
                mirror_dir,
                "charon_evaluation_audited",
                {"run_key": run_key, "evaluation_receipt_sha256": receipt["receipt_sha256"]},
            )
        audited = existing_events(local.read_ledger(state_dir / "ledger.jsonl"), "charon_evaluation_audited")
        if set(audited) == set(keys):
            return
        if not any(process_alive(key, evaluation=True) for key in keys if key not in audited):
            raise SafetyStop("Charon evaluation state is incomplete without a live owner")
        time.sleep(args.poll_seconds)


def run_controller(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir).resolve()
    mirror_dir = Path(args.mirror_dir).resolve()
    manager, launcher, local, executor, plan, ordered = frozen_context(args)
    authorization = read_json(state_dir / "authorization.json")
    validate_signed(authorization, "authorization_sha256")
    events = local.read_ledger(state_dir / "ledger.jsonl")
    prepared = [event for event in events if event.get("event_type") == "charon_takeover_prepared"]
    if len(prepared) != 1 or prepared[0]["payload"]["authorization_sha256"] != authorization["authorization_sha256"]:
        raise SafetyStop("Charon controller lacks one exact prepared takeover")
    if local.tracked_source_is_clean() != authorization["controller_source_commit"]:
        raise SafetyStop("Charon source differs from the prepared authorization")
    if local.github_nonterminal_runs():
        raise SafetyStop("GitHub frontier ownership reappeared")
    local.require_supervisor_disabled()
    entries = {str(row["run_key"]): row for row in plan["runs"]}
    keys = ordered[1:]
    tier_slices = (
        (12, keys[:12]),
        (24, keys[12:24]),
        (47, keys[24:]),
    )
    for tier, launch_slice in tier_slices:
        launch_keys(
            args=args,
            state_dir=state_dir,
            mirror_dir=mirror_dir,
            launcher=launcher,
            local=local,
            plan=plan,
            entries=entries,
            authorization=authorization,
            keys=launch_slice,
            tier=tier,
        )
        if tier < 47:
            wait_for_capacity_gate(
                args=args,
                state_dir=state_dir,
                mirror_dir=mirror_dir,
                manager=manager,
                local=local,
                plans=manager.build_plans(executor),
                entries=entries,
                prefix_keys=keys[:tier],
                next_limit=24 if tier == 12 else 47,
            )
    local.append_ledger(
        state_dir,
        mirror_dir,
        "charon_full_cohort_exposed",
        {"post_sentinel_started_count": 47, "max_active_cells": 47},
    )
    wait_for_all_training(
        args=args,
        state_dir=state_dir,
        mirror_dir=mirror_dir,
        local=local,
        entries=entries,
        keys=keys,
    )
    training = {
        key: valid_receipt(training_receipt_path(state_dir, key), run_key=key, valid_field="training_terminal_valid")
        for key in keys
    }
    rows = raw_provider_snapshot(launcher, state_dir / "provider_snapshot_before_evaluation.json")
    forbidden = {
        "scaling_paradox_checkpoint_evaluation",
        "scaling_paradox_reference_evaluation",
    }
    existing_evaluations = {
        str((row.get("user_metadata") or {}).get("run_key") or "")
        for row in rows
        if (row.get("user_metadata") or {}).get("campaign_id") == REPLICATION_CAMPAIGN_ID
        and (row.get("user_metadata") or {}).get("pearl_task") in forbidden
        and str((row.get("user_metadata") or {}).get("run_key") or "") in keys
    }
    if existing_evaluations:
        raise SafetyStop("provider already contains post-sentinel evaluation ownership")
    evaluation_auth_path = state_dir / "evaluation_authorization.json"
    if evaluation_auth_path.is_file():
        evaluation_authorization = read_json(evaluation_auth_path)
        validate_signed(evaluation_authorization, "authorization_sha256")
    else:
        evaluation_authorization = build_evaluation_authorization(
            state_dir=state_dir,
            entries=entries,
            keys=keys,
            training=training,
            provider_sha=read_json(state_dir / "provider_snapshot_before_evaluation.json")["snapshot_sha256"],
            source_commit=authorization["controller_source_commit"],
            estimated_cost_usd=float(authorization["estimated_evaluation_cost_usd"]),
        )
        local.atomic_json(evaluation_auth_path, evaluation_authorization)
        local.append_ledger(
            state_dir,
            mirror_dir,
            "charon_evaluation_authorized",
            {"authorization_sha256": evaluation_authorization["authorization_sha256"], "authorized_count": 47},
        )
    run_evaluations(
        args=args,
        state_dir=state_dir,
        mirror_dir=mirror_dir,
        local=local,
        entries=entries,
        keys=keys,
        training=training,
        authorization=evaluation_authorization,
    )
    bootstrap_dir = Path(args.bootstrap_dir).resolve()
    all_training = {
        ordered[0]: valid_receipt(
            bootstrap_dir / "sentinel" / "training_receipt.json",
            run_key=ordered[0],
            valid_field="training_terminal_valid",
        ),
        **training,
    }
    all_evaluation = {
        ordered[0]: valid_receipt(
            bootstrap_dir / "sentinel" / "evaluation_receipt.json",
            run_key=ordered[0],
            valid_field="evaluation_terminal_valid",
        ),
        **{
            key: valid_receipt(evaluation_receipt_path(state_dir, key), run_key=key, valid_field="evaluation_terminal_valid")
            for key in keys
        },
    }
    gate = build_wave_gate(
        campaign_id=REPLICATION_CAMPAIGN_ID,
        wave_name="frontier-v2-replication-complete",
        expected_run_keys=ordered,
        training_receipts=[all_training[key] for key in ordered],
        evaluation_receipts=[all_evaluation[key] for key in ordered],
    )
    local.atomic_json(state_dir / "replication_completion_gate.json", gate)
    local.append_ledger(
        state_dir,
        mirror_dir,
        "charon_replication_complete",
        {
            "training_receipt_count": 48,
            "evaluation_receipt_count": 48,
            "completion_gate_sha256": gate["gate_sha256"],
            "analysis_started": False,
            "hard_stop_reached": True,
        },
    )


def status(args: argparse.Namespace) -> None:
    local = load_script("charon_status_local", "manage_frontier_local_wave.py")
    state_dir = Path(args.state_dir).resolve()
    events = local.read_ledger(state_dir / "ledger.jsonl")
    counts: dict[str, int] = {}
    for event in events:
        counts[event["event_type"]] = counts.get(event["event_type"], 0) + 1
    step_counts: dict[str, int] = {}
    runs_dir = ROOT / "reports" / "frontier_adaptation_v2_replication" / "runs"
    for metadata in runs_dir.glob("*/checkpoint_meta.json"):
        payload = read_json(metadata)
        step_counts[metadata.parent.name] = int(payload.get("completed_steps", 0))
    print(
        json.dumps(
            {
                "event_count": len(events),
                "event_type_counts": counts,
                "step_counts": step_counts,
                "last_event": events[-1] if events else None,
            },
            indent=2,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor-config", default=str(DEFAULT_EXECUTOR))
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "_run"):
        child = subparsers.add_parser(command)
        child.add_argument("--state-dir", required=True)
        child.add_argument("--mirror-dir", required=True)
        child.add_argument("--bootstrap-dir", required=True)
        child.add_argument("--poll-seconds", type=int, default=15)
        child.add_argument("--capacity-observation-minutes", type=int, default=20)
        child.add_argument("--max-provider-staleness-minutes", type=int, default=15)
        child.add_argument("--minimum-free-bytes", type=int, default=20 * 1024**3)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--state-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "status":
        status(args)
        return
    try:
        if args.command == "prepare":
            prepare(args)
        else:
            run_controller(args)
    except SafetyStop as error:
        state_dir = Path(args.state_dir).resolve()
        mirror_dir = Path(args.mirror_dir).resolve()
        local = load_script("charon_block_local", "manage_frontier_local_wave.py")
        if (state_dir / "ledger.jsonl").is_file():
            events = local.read_ledger(state_dir / "ledger.jsonl")
            if not events or events[-1].get("event_type") != "charon_replication_blocked":
                local.append_ledger(
                    state_dir,
                    mirror_dir,
                    "charon_replication_blocked",
                    {"reason": str(error), "automatic_retry_authorized": False},
                )
        print(json.dumps({"status": "blocked", "reason": str(error)}), file=sys.stderr)


if __name__ == "__main__":
    main()
