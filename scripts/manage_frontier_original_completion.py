#!/usr/bin/env python3
"""Finish and evaluate the frozen frontier-v2 original cohort, then stop."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
SCRIPTS_ROOT = ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from pearl.scaling_campaign import (  # noqa: E402
    audit_evaluation_artifact,
    audit_provider_identity,
    audit_training_artifact,
    audit_training_continuation_artifact,
    build_wave_gate,
    read_json,
    sha256_file,
    sha256_value,
)
from pearl.preference_distillation import load_jsonl  # noqa: E402
from pearl.tinker_dpo import pair_rows_fingerprint  # noqa: E402

from manage_frontier_local_wave import (  # noqa: E402
    append_ledger,
    artifact_manifest,
    atomic_json,
    github_nonterminal_runs,
    load_script,
    read_ledger,
    require_supervisor_disabled,
    tracked_source_is_clean,
)


ORIGINAL_CAMPAIGN_ID = "pearl-frontier-adaptation-v2-original"
ORIGINAL_PLAN_SHA = "ce4fd33d9f5f8d62d42a4ddc383222adc18c48ba1399920073beaf44879842c6"
ORIGINAL_RUN_COUNT = 48
TERMINAL_STEP = 2250
COMPLETION_CONTRACT = "pearl.frontier-original-completion-authorization/1"
EVALUATION_CONTRACT = "pearl.frontier-local-evaluation-authorization/1"
LAUNCH_AGENT_LABEL = "org.pearl.frontier-original-completion"


class SafetyStop(RuntimeError):
    """A fail-closed condition that must not enter an automatic restart loop."""


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def signed(payload: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(payload)
    result[field] = sha256_value(result)
    return result


def validate_signed(payload: dict[str, Any], field: str) -> str:
    unsigned = dict(payload)
    observed = str(unsigned.pop(field, ""))
    if not observed or observed != sha256_value(unsigned):
        raise SafetyStop(f"{field} does not match its canonical payload")
    return observed


def valid_receipt(path: Path, *, run_key: str, valid_field: str) -> dict[str, Any]:
    receipt = read_json(path)
    validate_signed(receipt, "receipt_sha256")
    if receipt.get("run_key") != run_key or receipt.get(valid_field) is not True:
        raise SafetyStop(f"invalid {valid_field} receipt for {run_key}")
    return receipt


def process_alive(script_name: str, run_key: str) -> bool:
    result = subprocess.run(
        ["pgrep", "-f", f"{script_name}.*--run-key {run_key}"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def phase_wave_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    matches = [
        phase
        for phase in manifest["phases"]
        if phase["campaign"] == "original" and phase["stage"] == "core"
    ]
    if len(matches) != 1:
        raise SafetyStop("frozen manifest lacks one original core phase")
    result: dict[str, dict[str, Any]] = {}
    for wave in matches[0]["waves"]:
        for key in wave["run_keys"]:
            if key in result:
                raise SafetyStop("original run key appears in multiple manifest waves")
            result[key] = wave
    return result


def frozen_context(args: argparse.Namespace) -> tuple[Any, Any, dict[str, Any], dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    executor = read_json(Path(args.executor_config).resolve())
    if int(executor.get("global_max_active_paid_cells", -1)) != 47:
        raise SafetyStop("frontier global active-cell cap differs from the frozen value")
    manager = load_script("frontier_completion_manager", "manage_scaling_paradox_campaign.py")
    launcher = load_script("frontier_completion_launcher", "launch_scaling_paradox_v1.py")
    plans = manager.build_plans(executor)
    plan = plans[("original", "core")]
    if (
        plan["launch_plan_contract_sha"] != ORIGINAL_PLAN_SHA
        or plan["campaign_id"] != ORIGINAL_CAMPAIGN_ID
        or len(plan["runs"]) != ORIGINAL_RUN_COUNT
        or any(int(row["max_steps"]) != TERMINAL_STEP for row in plan["runs"])
    ):
        raise SafetyStop("regenerated original core plan differs from the frozen contract")
    entries = {str(row["run_key"]): row for row in plan["runs"]}
    if len(entries) != ORIGINAL_RUN_COUNT:
        raise SafetyStop("original plan run keys are not unique")
    manifest = manager.build_manifest(executor)
    waves = phase_wave_index(manifest)
    if set(waves) != set(entries):
        raise SafetyStop("manifest and original plan run keys differ")
    return manager, launcher, executor, plan, entries, waves


def current_wave_boundary(
    state_dir: Path,
    entries: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str], list[str]]:
    current = read_json(state_dir / "authorization.json")
    keys = list(current.get("authorized_run_keys") or [])
    if (
        current.get("campaign") != "original"
        or current.get("stage") != "core"
        or current.get("plan_sha") != ORIGINAL_PLAN_SHA
        or len(keys) != 35
        or len(set(keys)) != 35
        or not set(keys) <= set(entries)
    ):
        raise SafetyStop("current local wave is not the expected 35-cell original authorization")
    events = read_ledger(state_dir / "ledger.jsonl")
    terminals = [event for event in events if event["event_type"] == "local_wave_terminal"]
    if not terminals:
        raise LookupError("current local wave is still running")
    terminal = terminals[-1]["payload"]
    if (
        terminal.get("authorization_sha256") != current.get("authorization_sha256")
        or int(terminal.get("started_count", -1)) != 35
        or int(terminal.get("valid_segment_count", -1)) != 35
        or terminal.get("failed_run_keys") != []
        or terminal.get("launch_prefix_complete") is not True
    ):
        raise SafetyStop("current local wave did not terminate as an exact valid 35-cell wave")
    for key in keys:
        valid_receipt(
            state_dir / "local_segment_receipts" / f"{key}.json",
            run_key=key,
            valid_field="segment_valid",
        )
    terminal_keys = [key for key in keys if int(current["segment_end_steps"][key]) == TERMINAL_STEP]
    continuation_keys = [key for key in keys if int(current["segment_end_steps"][key]) < TERMINAL_STEP]
    if len(terminal_keys) != 9 or len(continuation_keys) != 26:
        raise SafetyStop("current wave does not have the frozen 9-terminal/26-continuation shape")
    return current, terminal_keys, continuation_keys


def backup_intermediate(
    state_dir: Path,
    plan_dir: Path,
    key: str,
    entry: dict[str, Any],
    expected_steps: int,
) -> dict[str, Any]:
    run_dir = plan_dir / "runs" / key
    audit = audit_training_continuation_artifact(plan_entry=entry, run_dir=run_dir)
    if int(audit["completed_steps"]) != expected_steps:
        raise SafetyStop(f"current continuation boundary differs for {key}")
    destination = state_dir / "original_completion" / "terminal_source_artifacts" / key
    if destination.exists():
        if artifact_manifest(destination) != artifact_manifest(run_dir):
            raise SafetyStop(f"immutable terminal-source backup differs for {key}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(run_dir, destination)
    receipt = signed(
        {
            "contract": "pearl.frontier-original-terminal-source-backup/1",
            "run_key": key,
            "completed_steps": expected_steps,
            "continuation_audit_sha256": audit["receipt_sha256"],
            "artifact_manifest_sha256": sha256_value(artifact_manifest(destination)),
            "scientific_values_omitted": True,
        },
        "receipt_sha256",
    )
    atomic_json(state_dir / "original_completion" / "backup_receipts" / f"{key}.json", receipt)
    return receipt


def provider_rows(launcher: Any, output: Path) -> list[dict[str, Any]]:
    rows = launcher.provider_runs()
    if not isinstance(rows, list):
        raise SafetyStop("provider snapshot has invalid shape")
    payload = signed(
        {
            "contract": "pearl.frontier-local-raw-provider-snapshot/1",
            "observed_at_utc": now_utc(),
            "runs": rows,
            "scientific_values_omitted": True,
        },
        "snapshot_sha256",
    )
    atomic_json(output, payload)
    return rows


def quarantine_ids(provider_auditor: Any, executor: dict[str, Any], key: str) -> list[str]:
    return provider_auditor.quarantined_provider_ids(executor, key)


def audit_live_lineage(
    *,
    rows: list[dict[str, Any]],
    keys: list[str],
    entries: dict[str, dict[str, Any]],
    plan_dir: Path,
    executor: dict[str, Any],
) -> dict[str, str]:
    provider_auditor = load_script("frontier_completion_provider_auditor", "audit_scaling_paradox_provider.py")
    result: dict[str, str] = {}
    for key in keys:
        receipt = audit_provider_identity(
            plan_entry=entries[key],
            provider_rows=rows,
            checkpoint_lineage=read_json(plan_dir / "runs" / key / "checkpoint_lineage.json"),
            quarantined_provider_ids=quarantine_ids(provider_auditor, executor, key),
        )
        result[key] = receipt["receipt_sha256"]
    return result


def build_terminal_authorization(
    *,
    current: dict[str, Any],
    keys: list[str],
    entries: dict[str, dict[str, Any]],
    waves: dict[str, dict[str, Any]],
    manager: Any,
    provider_snapshot_sha: str,
    backup_shas: dict[str, str],
    provider_audit_shas: dict[str, str],
    controller_source_commit: str,
) -> dict[str, Any]:
    completed = {key: int(current["segment_end_steps"][key]) for key in keys}
    cost = round(
        sum(
            manager.estimated_segment_cost(
                wave=waves[key], run_key=key, start_step=completed[key], end_step=TERMINAL_STEP
            )
            for key in keys
        ),
        4,
    )
    return signed(
        {
            "contract": COMPLETION_CONTRACT,
            "action": "complete_remaining_original_trajectories",
            "campaign": "original",
            "stage": "core",
            "plan_sha": ORIGINAL_PLAN_SHA,
            "source_authorization_sha256": current["authorization_sha256"],
            "authorized_run_keys": keys,
            "run_contract_shas": {key: entries[key]["run_contract_sha"] for key in keys},
            "completed_steps": completed,
            "segment_end_steps": {key: TERMINAL_STEP for key in keys},
            "source_backup_receipt_shas": backup_shas,
            "provider_identity_receipt_shas": provider_audit_shas,
            "provider_snapshot_sha256": provider_snapshot_sha,
            "controller_source_commit": controller_source_commit,
            "estimated_cost_usd": cost,
            "max_active_after_dispatch": len(keys),
            "replication_authorized": False,
            "analysis_authorized": False,
            "scientific_contract_changed": False,
        },
        "authorization_sha256",
    )


def existing_events(events: list[dict[str, Any]], event_type: str) -> dict[str, dict[str, Any]]:
    return {
        str(event["payload"].get("run_key")): event
        for event in events
        if event["event_type"] == event_type and event["payload"].get("run_key")
    }


def run_training_to_terminal(
    *,
    args: argparse.Namespace,
    state_dir: Path,
    mirror_dir: Path,
    launcher: Any,
    plan: dict[str, Any],
    entries: dict[str, dict[str, Any]],
    authorization: dict[str, Any],
) -> None:
    keys = list(authorization["authorized_run_keys"])
    plan_dir = ROOT / "reports/frontier_adaptation_v2_original"
    while True:
        events = read_ledger(state_dir / "ledger.jsonl")
        intents = existing_events(events, "terminal_training_launch_intent")
        starts = existing_events(events, "terminal_training_started")
        finished = existing_events(events, "terminal_training_audited")
        for key in keys:
            if key in finished:
                continue
            if key in intents and key not in starts:
                raise SafetyStop(f"ambiguous terminal-training intent without start record: {key}")
            if key not in starts:
                intent = append_ledger(
                    state_dir,
                    mirror_dir,
                    "terminal_training_launch_intent",
                    {
                        "run_key": key,
                        "authorization_sha256": authorization["authorization_sha256"],
                        "completed_steps": authorization["completed_steps"][key],
                        "segment_end_step": TERMINAL_STEP,
                    },
                )
                local_receipt = signed(
                    {
                        "contract": "pearl.frontier-local-terminal-authorization-receipt/1",
                        "run_key": key,
                        "run_contract_sha": entries[key]["run_contract_sha"],
                        "authorization_sha256": authorization["authorization_sha256"],
                        "launch_intent_event_sha256": intent["event_sha256"],
                        "completed_steps": authorization["completed_steps"][key],
                        "segment_end_step": TERMINAL_STEP,
                        "scientific_contract_changed": False,
                    },
                    "receipt_sha256",
                )
                atomic_json(plan_dir / "runs" / key / "local_terminal_authorization_receipt.json", local_receipt)
                try:
                    pid, returncode = launcher.launch_one(
                        entries[key], plan, plan_dir, resume=True, wait=False, segment_end_step=TERMINAL_STEP
                    )
                    if returncode is not None:
                        raise RuntimeError("terminal trainer returned synchronously")
                except Exception as error:
                    append_ledger(
                        state_dir,
                        mirror_dir,
                        "terminal_training_launch_failed",
                        {"run_key": key, "failure": f"{type(error).__name__}: {error}"},
                    )
                    raise SafetyStop(f"terminal training launch failed for {key}") from error
                append_ledger(
                    state_dir,
                    mirror_dir,
                    "terminal_training_started",
                    {"run_key": key, "pid": pid, "authorization_sha256": authorization["authorization_sha256"]},
                )

        active = False
        events = read_ledger(state_dir / "ledger.jsonl")
        finished = existing_events(events, "terminal_training_audited")
        for key in keys:
            if key in finished:
                continue
            if process_alive("run_tinker_dpo_smoke.py", key):
                active = True
                continue
            try:
                receipt = audit_training_artifact(plan_entry=entries[key], run_dir=plan_dir / "runs" / key)
            except Exception as error:
                raise SafetyStop(f"terminal training process ended without a valid artifact for {key}") from error
            atomic_json(
                state_dir / "original_completion" / "receipts" / "training" / f"{key}.json",
                receipt,
            )
            append_ledger(
                state_dir,
                mirror_dir,
                "terminal_training_audited",
                {"run_key": key, "training_receipt_sha256": receipt["receipt_sha256"]},
            )
        if len(existing_events(read_ledger(state_dir / "ledger.jsonl"), "terminal_training_audited")) >= len(keys):
            return
        if not active:
            raise SafetyStop("terminal-training completion state is internally inconsistent")
        time.sleep(args.poll_seconds)


def write_all_training_receipts(
    *, state_dir: Path, bootstrap_dir: Path, plan_dir: Path, entries: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    destination = state_dir / "original_completion" / "receipts" / "training"
    result: dict[str, dict[str, Any]] = {}
    for key, entry in entries.items():
        bootstrap = bootstrap_dir / "receipts" / "training" / f"{key}.json"
        if bootstrap.is_file():
            receipt = valid_receipt(bootstrap, run_key=key, valid_field="training_terminal_valid")
        else:
            receipt = audit_training_artifact(plan_entry=entry, run_dir=plan_dir / "runs" / key)
            atomic_json(destination / f"{key}.json", receipt)
        result[key] = receipt
    if len(result) != ORIGINAL_RUN_COUNT:
        raise SafetyStop("training receipts do not cover the exact original cohort")
    return result


def assert_no_prior_evaluation(rows: list[dict[str, Any]], keys: list[str], entries: dict[str, dict[str, Any]]) -> None:
    forbidden = {"scaling_paradox_checkpoint_evaluation", "scaling_paradox_reference_evaluation"}
    matches: list[str] = []
    for row in rows:
        metadata = row.get("user_metadata") or {}
        key = str(metadata.get("run_key") or "")
        if (
            key in keys
            and metadata.get("campaign_id") == ORIGINAL_CAMPAIGN_ID
            and metadata.get("contract_sha") == entries[key]["run_contract_sha"]
            and metadata.get("pearl_task") in forbidden
        ):
            matches.append(key)
    if matches:
        raise SafetyStop("provider already contains evaluation ownership for: " + ", ".join(sorted(set(matches))))


def build_evaluation_authorization(
    *, keys: list[str], entries: dict[str, dict[str, Any]], waves: dict[str, dict[str, Any]],
    training: dict[str, dict[str, Any]], provider_snapshot_sha: str,
    controller_source_commit: str,
) -> dict[str, Any]:
    return signed(
        {
            "contract": EVALUATION_CONTRACT,
            "action": "evaluate_missing_original_endpoints",
            "campaign": "original",
            "stage": "core",
            "plan_sha": ORIGINAL_PLAN_SHA,
            "authorized_run_keys": keys,
            "run_contract_shas": {key: entries[key]["run_contract_sha"] for key in keys},
            "training_receipt_shas": {key: training[key]["receipt_sha256"] for key in keys},
            "provider_snapshot_sha256": provider_snapshot_sha,
            "controller_source_commit": controller_source_commit,
            "evaluator_sha256": sha256_file(ROOT / "scripts" / "evaluate_scaling_paradox_checkpoint.py"),
            "evaluation_worker_sha256": sha256_file(ROOT / "scripts" / "run_frontier_local_evaluation.py"),
            "estimated_cost_usd": round(
                sum(float(waves[key]["estimated_checkpoint_evaluation_cost_by_run_key"][key]) for key in keys), 4
            ),
            "max_active_after_dispatch": len(keys),
            "replication_authorized": False,
            "analysis_authorized": False,
            "scientific_contract_changed": False,
        },
        "authorization_sha256",
    )


def run_evaluations(
    *, args: argparse.Namespace, state_dir: Path, mirror_dir: Path,
    authorization: dict[str, Any], entries: dict[str, dict[str, Any]],
    training: dict[str, dict[str, Any]], partition_evidence: dict[str, dict[str, Any]],
) -> None:
    keys = list(authorization["authorized_run_keys"])
    plan_dir = ROOT / "reports/frontier_adaptation_v2_original"
    evaluation_root = state_dir / "original_completion" / "evaluation_artifacts"
    provider_json = state_dir / "original_completion" / "provider_snapshot_before_evaluation.json"
    auth_path = state_dir / "original_completion" / "evaluation_authorization.json"
    while True:
        events = read_ledger(state_dir / "ledger.jsonl")
        intents = existing_events(events, "original_evaluation_launch_intent")
        starts = existing_events(events, "original_evaluation_started")
        finished = existing_events(events, "original_evaluation_audited")
        for key in keys:
            if key in finished:
                continue
            if key in intents and key not in starts:
                raise SafetyStop(f"ambiguous evaluation intent without start record: {key}")
            if key not in starts:
                output_dir = evaluation_root / key
                if output_dir.exists() and any(output_dir.iterdir()):
                    raise SafetyStop(f"unowned evaluation artifact directory already exists for {key}")
                intent = append_ledger(
                    state_dir,
                    mirror_dir,
                    "original_evaluation_launch_intent",
                    {"run_key": key, "authorization_sha256": authorization["authorization_sha256"]},
                )
                output_dir.mkdir(parents=True, exist_ok=True)
                receipt = signed(
                    {
                        "contract": "pearl.frontier-local-evaluation-authorization-receipt/1",
                        "run_key": key,
                        "run_contract_sha": entries[key]["run_contract_sha"],
                        "authorization_sha256": authorization["authorization_sha256"],
                        "launch_intent_event_sha256": intent["event_sha256"],
                        "scientific_contract_changed": False,
                    },
                    "receipt_sha256",
                )
                atomic_json(output_dir / "local_evaluation_authorization_receipt.json", receipt)
                run_dir = plan_dir / "runs" / key
                command = [
                    sys.executable,
                    str(ROOT / "scripts" / "run_frontier_local_evaluation.py"),
                    "--authorization", str(auth_path), "--run-key", key,
                    "--run-contract", str(run_dir / "run_contract.json"),
                    "--training-report", str(run_dir / "report.json"),
                    "--checkpoint-lineage", str(run_dir / "checkpoint_lineage.json"),
                    "--provider-json", str(provider_json),
                    "--executor-config", str(Path(args.executor_config).resolve()),
                    "--output-dir", str(output_dir),
                ]
                log_path = output_dir / "evaluator.log"
                try:
                    with log_path.open("a", encoding="utf-8") as log:
                        process = subprocess.Popen(
                            command, cwd=ROOT, env=os.environ.copy(), stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True,
                        )
                except Exception as error:
                    append_ledger(
                        state_dir, mirror_dir, "original_evaluation_launch_failed",
                        {"run_key": key, "failure": f"{type(error).__name__}: {error}"},
                    )
                    raise SafetyStop(f"evaluation launch failed for {key}") from error
                append_ledger(
                    state_dir, mirror_dir, "original_evaluation_started",
                    {"run_key": key, "pid": process.pid, "authorization_sha256": authorization["authorization_sha256"]},
                )

        active = False
        events = read_ledger(state_dir / "ledger.jsonl")
        finished = existing_events(events, "original_evaluation_audited")
        for key in keys:
            if key in finished:
                continue
            if process_alive("run_frontier_local_evaluation.py", key):
                active = True
                continue
            try:
                receipt = audit_evaluation_artifact(
                    plan_entry=entries[key],
                    evaluation_dir=evaluation_root / key,
                    training_receipt=training[key],
                    partition_contracts=partition_evidence,
                )
            except Exception as error:
                raise SafetyStop(f"evaluation process ended without a valid artifact for {key}") from error
            atomic_json(
                state_dir / "original_completion" / "receipts" / "evaluation" / f"{key}.json",
                receipt,
            )
            append_ledger(
                state_dir, mirror_dir, "original_evaluation_audited",
                {"run_key": key, "evaluation_receipt_sha256": receipt["receipt_sha256"]},
            )
        if len(existing_events(read_ledger(state_dir / "ledger.jsonl"), "original_evaluation_audited")) >= len(keys):
            return
        if not active:
            raise SafetyStop("evaluation completion state is internally inconsistent")
        time.sleep(args.poll_seconds)


def partition_contracts(entries: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    exemplar = next(iter(entries.values()))
    result: dict[str, dict[str, Any]] = {}
    for name in ("holdout", "challenge"):
        rows = load_jsonl(ROOT / exemplar[f"{name}_path"])
        result[name] = {"pair_count": len(rows), "pair_fingerprint": pair_rows_fingerprint(rows)}
    return result


def complete_original(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir).resolve()
    mirror_dir = Path(args.mirror_dir).resolve()
    bootstrap_dir = Path(args.bootstrap_state_dir).resolve()
    completion_dir = state_dir / "original_completion"
    events = read_ledger(state_dir / "ledger.jsonl")
    if any(event["event_type"] == "original_optimization_complete" for event in events):
        return
    if any(event["event_type"] == "original_completion_blocked" for event in events):
        return
    armed = [event for event in events if event["event_type"] == "original_completion_armed"]
    if len(armed) != 1:
        raise SafetyStop("original completion controller lacks one immutable arm event")
    armed_commit = str(armed[0]["payload"]["controller_source_commit"])
    source_commit = tracked_source_is_clean()
    if source_commit != armed_commit:
        raise SafetyStop("controller source commit differs from the armed commit")
    if not os.environ.get("TINKER_API_KEY"):
        raise SafetyStop("TINKER_API_KEY is unavailable")
    manager, launcher, executor, plan, entries, waves = frozen_context(args)

    while True:
        try:
            current, _terminal_keys, continuation_keys = current_wave_boundary(state_dir, entries)
            break
        except LookupError:
            time.sleep(args.poll_seconds)
    if github_nonterminal_runs():
        raise SafetyStop("GitHub frontier ownership reappeared")
    require_supervisor_disabled()
    if shutil.disk_usage(ROOT).free < args.minimum_free_bytes:
        raise SafetyStop("free disk is below the frozen safety floor")

    plan_dir = ROOT / str(current["plan_dir"])
    terminal_auth_path = completion_dir / "terminal_training_authorization.json"
    if terminal_auth_path.is_file():
        terminal_auth = read_json(terminal_auth_path)
        validate_signed(terminal_auth, "authorization_sha256")
    else:
        if tracked_source_is_clean() != armed_commit:
            raise SafetyStop("source changed before terminal-training authorization")
        backup_shas: dict[str, str] = {}
        for key in continuation_keys:
            receipt = backup_intermediate(
                state_dir, plan_dir, key, entries[key], int(current["segment_end_steps"][key])
            )
            backup_shas[key] = receipt["receipt_sha256"]
        terminal_snapshot_path = completion_dir / "provider_snapshot_before_terminal_training.json"
        rows = provider_rows(launcher, terminal_snapshot_path)
        provider_audits = audit_live_lineage(
            rows=rows, keys=continuation_keys, entries=entries, plan_dir=plan_dir, executor=executor
        )
        terminal_auth = build_terminal_authorization(
            current=current, keys=continuation_keys, entries=entries, waves=waves,
            manager=manager, provider_snapshot_sha=read_json(terminal_snapshot_path)["snapshot_sha256"],
            backup_shas=backup_shas, provider_audit_shas=provider_audits,
            controller_source_commit=armed_commit,
        )
        atomic_json(terminal_auth_path, terminal_auth)
        append_ledger(
            state_dir, mirror_dir, "terminal_training_authorized",
            {"authorization_sha256": terminal_auth["authorization_sha256"], "authorized_count": 26,
             "estimated_cost_usd": terminal_auth["estimated_cost_usd"], "replication_authorized": False},
        )
    validate_signed(terminal_auth, "authorization_sha256")
    if set(terminal_auth["authorized_run_keys"]) != set(continuation_keys):
        raise SafetyStop("terminal authorization differs from the exact 26 continuation keys")
    if terminal_auth.get("controller_source_commit") != armed_commit:
        raise SafetyStop("terminal authorization is bound to another source commit")
    if tracked_source_is_clean() != armed_commit:
        raise SafetyStop("source changed before terminal-training launch")
    run_training_to_terminal(
        args=args, state_dir=state_dir, mirror_dir=mirror_dir, launcher=launcher,
        plan=plan, entries=entries, authorization=terminal_auth,
    )

    training = write_all_training_receipts(
        state_dir=state_dir, bootstrap_dir=bootstrap_dir, plan_dir=plan_dir, entries=entries
    )
    bootstrap_eval_keys = {
        path.stem for path in (bootstrap_dir / "receipts" / "evaluation").glob("core-*.json")
    }
    missing_eval_keys = [str(row["run_key"]) for row in plan["runs"] if str(row["run_key"]) not in bootstrap_eval_keys]
    if set(missing_eval_keys) != set(current["authorized_run_keys"]) or len(missing_eval_keys) != 35:
        raise SafetyStop("missing original evaluations are not the exact current-wave 35 cells")
    if github_nonterminal_runs():
        raise SafetyStop("GitHub frontier ownership reappeared before evaluation")
    require_supervisor_disabled()
    evaluation_auth_path = completion_dir / "evaluation_authorization.json"
    if evaluation_auth_path.is_file():
        evaluation_auth = read_json(evaluation_auth_path)
        validate_signed(evaluation_auth, "authorization_sha256")
    else:
        if tracked_source_is_clean() != armed_commit:
            raise SafetyStop("source changed before evaluation authorization")
        evaluation_snapshot_path = completion_dir / "provider_snapshot_before_evaluation.json"
        eval_rows = provider_rows(launcher, evaluation_snapshot_path)
        assert_no_prior_evaluation(eval_rows, missing_eval_keys, entries)
        audit_live_lineage(
            rows=eval_rows, keys=missing_eval_keys, entries=entries, plan_dir=plan_dir, executor=executor
        )
        evaluation_auth = build_evaluation_authorization(
            keys=missing_eval_keys, entries=entries, waves=waves, training=training,
            provider_snapshot_sha=read_json(evaluation_snapshot_path)["snapshot_sha256"],
            controller_source_commit=armed_commit,
        )
        atomic_json(evaluation_auth_path, evaluation_auth)
        append_ledger(
            state_dir, mirror_dir, "original_evaluation_authorized",
            {"authorization_sha256": evaluation_auth["authorization_sha256"], "authorized_count": 35,
             "estimated_cost_usd": evaluation_auth["estimated_cost_usd"], "replication_authorized": False},
        )
    if evaluation_auth.get("controller_source_commit") != armed_commit:
        raise SafetyStop("evaluation authorization is bound to another source commit")
    if tracked_source_is_clean() != armed_commit:
        raise SafetyStop("source changed before evaluation launch")
    run_evaluations(
        args=args, state_dir=state_dir, mirror_dir=mirror_dir,
        authorization=evaluation_auth, entries=entries, training=training,
        partition_evidence=partition_contracts(entries),
    )

    evaluations: dict[str, dict[str, Any]] = {}
    for key in entries:
        bootstrap = bootstrap_dir / "receipts" / "evaluation" / f"{key}.json"
        local = completion_dir / "receipts" / "evaluation" / f"{key}.json"
        path = bootstrap if bootstrap.is_file() else local
        evaluations[key] = valid_receipt(path, run_key=key, valid_field="evaluation_terminal_valid")
    gate = build_wave_gate(
        campaign_id=ORIGINAL_CAMPAIGN_ID,
        wave_name="frontier-v2-original-complete",
        expected_run_keys=[str(row["run_key"]) for row in plan["runs"]],
        training_receipts=[training[str(row["run_key"])] for row in plan["runs"]],
        evaluation_receipts=[evaluations[str(row["run_key"])] for row in plan["runs"]],
    )
    atomic_json(completion_dir / "original_completion_gate.json", gate)
    append_ledger(
        state_dir, mirror_dir, "original_optimization_complete",
        {"campaign": "original", "training_receipt_count": 48, "evaluation_receipt_count": 48,
         "completion_gate_sha256": gate["gate_sha256"], "replication_started": False,
         "analysis_started": False, "hard_stop_reached": True},
    )


def install(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir).resolve()
    mirror_dir = Path(args.mirror_dir).resolve()
    if not os.environ.get("TINKER_API_KEY"):
        raise RuntimeError("TINKER_API_KEY is required to arm original completion")
    commit = tracked_source_is_clean()
    _, _, executor, _, entries, _ = frozen_context(args)
    if int(executor["global_max_active_paid_cells"]) != 47 or len(entries) != 48:
        raise RuntimeError("frozen original capacity or cohort size differs")
    if github_nonterminal_runs():
        raise RuntimeError("GitHub frontier ownership is not idle")
    require_supervisor_disabled()
    events = read_ledger(state_dir / "ledger.jsonl")
    if any(event["event_type"] == "original_completion_armed" for event in events):
        raise RuntimeError("original completion is already armed")
    append_ledger(
        state_dir, mirror_dir, "original_completion_armed",
        {"controller_source_commit": commit, "scope": "remaining_original_training_and_evaluation_only",
         "original_plan_sha": ORIGINAL_PLAN_SHA, "terminal_step": TERMINAL_STEP,
         "expected_training_receipts": 48, "expected_evaluation_receipts": 48,
         "replication_authorized": False, "analysis_authorized": False},
    )
    print(json.dumps({"armed": True, "controller_source_commit": commit, "launch_agent_label": LAUNCH_AGENT_LABEL}, indent=2))


def status(args: argparse.Namespace) -> None:
    events = read_ledger(Path(args.state_dir).resolve() / "ledger.jsonl")
    counts: dict[str, int] = {}
    for event in events:
        counts[event["event_type"]] = counts.get(event["event_type"], 0) + 1
    print(json.dumps({"event_count": len(events), "event_type_counts": counts, "last_event": events[-1] if events else None}, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "_run", "status"):
        child = sub.add_parser(name)
        child.add_argument("--state-dir", required=True)
        if name != "status":
            child.add_argument("--mirror-dir", required=True)
            child.add_argument("--bootstrap-state-dir", required=True)
            child.add_argument("--executor-config", required=True)
            child.add_argument("--poll-seconds", type=int, default=30)
            child.add_argument("--minimum-free-bytes", type=int, default=5 * 1024**3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "install":
        install(args)
    elif args.command == "status":
        status(args)
    else:
        state_dir = Path(args.state_dir).resolve()
        mirror_dir = Path(args.mirror_dir).resolve()
        try:
            complete_original(args)
        except SafetyStop as error:
            events = read_ledger(state_dir / "ledger.jsonl")
            if not any(event["event_type"] == "original_completion_blocked" for event in events):
                append_ledger(
                    state_dir, mirror_dir, "original_completion_blocked",
                    {"reason": f"{type(error).__name__}: {error}", "automatic_retry": False,
                     "replication_started": False, "analysis_started": False},
                )
            print(str(error), file=sys.stderr)
            return


if __name__ == "__main__":
    main()
