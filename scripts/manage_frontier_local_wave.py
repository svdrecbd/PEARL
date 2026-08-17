#!/usr/bin/env python3
"""Prepare and run one exact frontier-v2 authorization from a local controller."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.scaling_campaign import (  # noqa: E402
    audit_training_artifact,
    audit_training_continuation_artifact,
    canonical_json,
    read_json,
    sha256_file,
    sha256_value,
    write_json,
)


DEFAULT_EXECUTOR = ROOT / "configs/experiments/frontier_adaptation_v2_executor.json"
SUPERVISOR_WORKFLOW = "frontier-adaptation-v2-supervisor.yml"
PAID_WORKFLOWS = (
    "frontier-adaptation-v2.yml",
    "frontier-adaptation-v2-checkpoint-evaluation.yml",
)
LEDGER_CONTRACT = "pearl.frontier-local-controller-ledger/1"
LOCAL_RECEIPT_CONTRACT = "pearl.frontier-local-controller-authorization/1"


def load_script(name: str, filename: str) -> Any:
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def now_utc() -> str:
    return datetime.now(UTC).isoformat()


def run_json(command: list[str]) -> Any:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def tracked_source_is_clean() -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        raise RuntimeError("tracked worktree is dirty; local paid execution is not source-pinned")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def authorization_hash(authorization: dict[str, Any]) -> str:
    payload = dict(authorization)
    observed = str(payload.pop("authorization_sha256", ""))
    computed = sha256_value(payload)
    if observed != computed:
        raise RuntimeError("authorization SHA does not match its canonical payload")
    return observed


def semantic_authorization_payload(authorization: dict[str, Any]) -> dict[str, Any]:
    """Remove only live-snapshot attestation hashes, never a dispatch decision field."""

    payload = json.loads(json.dumps(authorization))
    payload.pop("authorization_sha256", None)
    payload.pop("capacity_gate_sha256", None)
    gate = payload.get("capacity_gate")
    if isinstance(gate, dict):
        gate.pop("gate_sha256", None)
        gate.pop("provider_snapshot_sha256", None)
    return payload


def validate_authorization(
    authorization: dict[str, Any],
    *,
    executor: dict[str, Any],
    manager: Any,
) -> dict[str, dict[str, Any]]:
    auth_sha = authorization_hash(authorization)
    if authorization.get("contract") != "pearl.scaling-paradox-authorization/1":
        raise RuntimeError("authorization contract is invalid")
    if authorization.get("action") != "dispatch_training_resume":
        raise RuntimeError("local takeover currently permits one exact training-resume authorization")
    if authorization.get("campaign") not in {"original", "replication"}:
        raise RuntimeError("authorization campaign is invalid")
    if authorization.get("stage") != "core":
        raise RuntimeError("local takeover is restricted to the frozen frontier core")

    keys = list(authorization.get("authorized_run_keys") or [])
    if not keys or len(keys) != len(set(keys)):
        raise RuntimeError("authorization run keys are empty or non-unique")
    maximum = int(executor["global_max_active_paid_cells"])
    if len(keys) > maximum or int(authorization.get("max_active_after_dispatch", -1)) > maximum:
        raise RuntimeError("authorization exceeds the frozen active-cell cap")

    plans = manager.build_plans(executor)
    plan = plans[(str(authorization["campaign"]), str(authorization["stage"]))]
    if authorization.get("plan_sha") != plan["launch_plan_contract_sha"]:
        raise RuntimeError("authorization plan SHA differs from the regenerated frozen plan")
    entries = {str(row["run_key"]): row for row in plan["runs"]}
    completed = authorization.get("completed_steps") or {}
    segment_ends = authorization.get("segment_end_steps") or {}
    source_ids = authorization.get("source_actions_run_ids") or {}
    claims = authorization.get("dispatch_claims") or {}
    selected: dict[str, dict[str, Any]] = {}
    for key in keys:
        if key not in entries:
            raise RuntimeError(f"authorized run key is absent from the frozen plan: {key}")
        start = int(completed.get(key, -1))
        end = int(segment_ends.get(key, -1))
        source_id = int(source_ids.get(key, 0))
        if not (0 < start < end <= int(entries[key]["max_steps"])) or source_id <= 0:
            raise RuntimeError(f"invalid continuation boundary or source owner for {key}")
        claim = claims.get(key) or {}
        if (
            claim.get("action") != authorization["action"]
            or claim.get("campaign") != authorization["campaign"]
            or claim.get("stage") != authorization["stage"]
            or claim.get("run_key") != key
            or int(claim.get("source_actions_run_id", 0)) != source_id
            or int(claim.get("segment_end_step", -1)) != end
        ):
            raise RuntimeError(f"semantic dispatch claim differs from authorization for {key}")
        selected[key] = entries[key]
    if len(selected) != len(keys) or not auth_sha:
        raise RuntimeError("authorization selection is incomplete")
    return selected


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    previous = None
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        event = json.loads(line)
        observed = str(event.pop("event_sha256", ""))
        if event.get("contract") != LEDGER_CONTRACT:
            raise RuntimeError(f"ledger contract mismatch at line {line_number}")
        if event.get("previous_event_sha256") != previous:
            raise RuntimeError(f"ledger hash chain mismatch at line {line_number}")
        computed = sha256_value(event)
        if observed != computed:
            raise RuntimeError(f"ledger event SHA mismatch at line {line_number}")
        event["event_sha256"] = observed
        events.append(event)
        previous = observed
    return events


def append_ledger(state_dir: Path, mirror_dir: Path, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    state_dir.mkdir(parents=True, exist_ok=True)
    mirror_dir.mkdir(parents=True, exist_ok=True)
    local_path = state_dir / "ledger.jsonl"
    mirror_path = mirror_dir / "ledger.jsonl"
    lock_path = state_dir / "ledger.lock"
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        local_events = read_ledger(local_path)
        mirror_events = read_ledger(mirror_path)
        if local_events != mirror_events:
            raise RuntimeError("primary and mirror ledgers disagree")
        previous = local_events[-1]["event_sha256"] if local_events else None
        event = {
            "contract": LEDGER_CONTRACT,
            "event_index": len(local_events) + 1,
            "event_type": event_type,
            "observed_at_utc": now_utc(),
            "previous_event_sha256": previous,
            "payload": payload,
        }
        event["event_sha256"] = sha256_value(event)
        line = canonical_json(event) + "\n"
        for path in (local_path, mirror_path):
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        return event


def github_nonterminal_runs() -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for workflow in (SUPERVISOR_WORKFLOW, *PAID_WORKFLOWS):
        rows = run_json(
            [
                "gh", "run", "list", "--workflow", workflow, "--limit", "100",
                "--json", "databaseId,status,conclusion,displayTitle,headSha,url",
            ]
        )
        active.extend(row for row in rows if row.get("status") != "completed")
    return active


def require_supervisor_disabled() -> None:
    repository = run_json(["gh", "repo", "view", "--json", "nameWithOwner"])
    name_with_owner = str(repository.get("nameWithOwner") or "")
    if "/" not in name_with_owner:
        raise RuntimeError("cannot resolve the GitHub repository for workflow ownership")
    state = run_json(
        [
            "gh", "api",
            f"repos/{name_with_owner}/actions/workflows/{SUPERVISOR_WORKFLOW}",
        ]
    )
    if state.get("state") != "disabled_manually":
        raise RuntimeError("GitHub frontier supervisor must be disabled during local ownership")


def artifact_manifest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def restore_one(
    *,
    key: str,
    entry: dict[str, Any],
    authorization: dict[str, Any],
    state_dir: Path,
    manager: Any,
) -> dict[str, Any]:
    plan_dir = ROOT / str(authorization["plan_dir"])
    run_dir = plan_dir / "runs" / key
    source_id = int(authorization["source_actions_run_ids"][key])
    expected_steps = int(authorization["completed_steps"][key])
    artifact_name = str(authorization["source_artifact_prefix"]) + key

    if not run_dir.exists():
        download_root = state_dir / "downloads"
        download_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f"{key}.", dir=download_root))
        manager.gh_run_download(
            [
                "gh", "run", "download", str(source_id), "--name", artifact_name,
                "--dir", str(temporary),
            ]
        )
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, run_dir)

    audit = audit_training_continuation_artifact(
        plan_entry=entry,
        run_dir=run_dir,
        source_actions_run_id=source_id,
    )
    if int(audit["completed_steps"]) != expected_steps:
        raise RuntimeError(f"restored checkpoint boundary differs from authorization for {key}")

    source_backup = state_dir / "source_artifacts" / key
    if source_backup.exists():
        if artifact_manifest(source_backup) != artifact_manifest(run_dir):
            raise RuntimeError(f"existing source backup differs from restored artifact for {key}")
    else:
        source_backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(run_dir, source_backup)
    manifest = artifact_manifest(source_backup)
    receipt = {
        "contract": "pearl.frontier-local-source-restore/1",
        "run_key": key,
        "source_actions_run_id": source_id,
        "source_artifact_name": artifact_name,
        "completed_steps": expected_steps,
        "training_continuation_audit_sha256": audit["receipt_sha256"],
        "source_artifact_manifest_sha256": sha256_value(manifest),
        "source_artifact_file_count": len(manifest),
        "scientific_values_omitted": True,
    }
    receipt["receipt_sha256"] = sha256_value(receipt)
    atomic_json(state_dir / "restore_receipts" / f"{key}.json", receipt)
    return receipt


def prepare(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir).resolve()
    mirror_dir = Path(args.mirror_dir).resolve()
    authorization = read_json(Path(args.authorization).resolve())
    executor = read_json(Path(args.executor_config).resolve())
    manager = load_script("frontier_campaign_manager", "manage_scaling_paradox_campaign.py")
    selected = validate_authorization(authorization, executor=executor, manager=manager)
    if read_ledger(state_dir / "ledger.jsonl"):
        raise RuntimeError("local controller ledger already exists; refusing a second prepare")

    source_run = run_json(
        [
            "gh", "run", "view", str(args.source_supervisor_run_id),
            "--json", "databaseId,status,conclusion,headSha,displayTitle,url",
        ]
    )
    if (
        source_run.get("status") != "completed"
        or source_run.get("conclusion") != "success"
        or int(source_run.get("databaseId", 0)) != args.source_supervisor_run_id
    ):
        raise RuntimeError("source supervisor status run is not terminal-success")
    if github_nonterminal_runs():
        raise RuntimeError("GitHub frontier supervisor or paid workers are still nonterminal")

    receipts: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=args.download_workers) as pool:
        futures = {
            pool.submit(
                restore_one,
                key=key,
                entry=selected[key],
                authorization=authorization,
                state_dir=state_dir,
                manager=manager,
            ): key
            for key in authorization["authorized_run_keys"]
        }
        for future in as_completed(futures):
            key = futures[future]
            receipts[key] = future.result()

    if set(receipts) != set(authorization["authorized_run_keys"]):
        raise RuntimeError("source restore did not cover the exact authorization")
    atomic_json(state_dir / "authorization.json", authorization)
    atomic_json(mirror_dir / "authorization.json", authorization)
    event = append_ledger(
        state_dir,
        mirror_dir,
        "local_takeover_prepared",
        {
            "authorization_sha256": authorization["authorization_sha256"],
            "source_supervisor_run_id": args.source_supervisor_run_id,
            "source_supervisor_head_sha": source_run["headSha"],
            "controller_source_commit": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                capture_output=True, text=True,
            ).stdout.strip(),
            "authorized_run_keys": authorization["authorized_run_keys"],
            "restore_receipt_sha256_by_run_key": {
                key: receipts[key]["receipt_sha256"]
                for key in authorization["authorized_run_keys"]
            },
            "estimated_cost_usd": authorization["estimated_cost_usd"],
            "max_active_after_dispatch": authorization["max_active_after_dispatch"],
            "scientific_contract_changed": False,
        },
    )
    print(json.dumps({"prepared": len(receipts), "event_sha256": event["event_sha256"]}, indent=2))


def write_local_authorization_receipt(
    *,
    run_dir: Path,
    key: str,
    authorization: dict[str, Any],
    plan_entry: dict[str, Any],
    controller_commit: str,
    intent_event_sha: str,
) -> dict[str, Any]:
    receipt = {
        "contract": LOCAL_RECEIPT_CONTRACT,
        "authorization_sha256": authorization["authorization_sha256"],
        "action": authorization["action"],
        "campaign": authorization["campaign"],
        "stage": authorization["stage"],
        "run_key": key,
        "run_contract_sha": plan_entry["run_contract_sha"],
        "dispatch_claim_sha256": authorization["dispatch_claims"][key]["dispatch_claim_sha256"],
        "source_actions_run_id": authorization["source_actions_run_ids"][key],
        "completed_steps": authorization["completed_steps"][key],
        "segment_end_step": authorization["segment_end_steps"][key],
        "controller_source_commit": controller_commit,
        "launch_intent_event_sha256": intent_event_sha,
        "scientific_contract_changed": False,
    }
    receipt["receipt_sha256"] = sha256_value(receipt)
    atomic_json(run_dir / "local_controller_authorization_receipt.json", receipt)
    return receipt


def audit_local_result(
    *,
    key: str,
    entry: dict[str, Any],
    authorization: dict[str, Any],
    state_dir: Path,
) -> dict[str, Any]:
    run_dir = ROOT / str(authorization["plan_dir"]) / "runs" / key
    expected_end = int(authorization["segment_end_steps"][key])
    if expected_end == int(entry["max_steps"]):
        audit = audit_training_artifact(plan_entry=entry, run_dir=run_dir)
        observed_end = int(audit["terminal_step"])
        kind = "terminal"
    else:
        audit = audit_training_continuation_artifact(plan_entry=entry, run_dir=run_dir)
        observed_end = int(audit["completed_steps"])
        kind = "continuation"
    if observed_end != expected_end:
        raise RuntimeError(f"local result boundary differs from authorization for {key}")
    receipt = {
        "contract": "pearl.frontier-local-segment-audit/1",
        "run_key": key,
        "result_kind": kind,
        "authorized_segment_end_step": expected_end,
        "artifact_audit_sha256": audit["receipt_sha256"],
        "local_authorization_receipt_sha256": sha256_file(
            run_dir / "local_controller_authorization_receipt.json"
        ),
        "scientific_values_omitted": True,
        "segment_valid": True,
    }
    receipt["receipt_sha256"] = sha256_value(receipt)
    atomic_json(state_dir / "local_segment_receipts" / f"{key}.json", receipt)
    return receipt


def run_controller(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir).resolve()
    mirror_dir = Path(args.mirror_dir).resolve()
    authorization = read_json(state_dir / "authorization.json")
    executor = read_json(Path(args.executor_config).resolve())
    manager = load_script("frontier_campaign_manager", "manage_scaling_paradox_campaign.py")
    launcher = load_script("frontier_launcher", "launch_scaling_paradox_v1.py")
    selected = validate_authorization(authorization, executor=executor, manager=manager)
    controller_commit = tracked_source_is_clean()
    deadline = time.monotonic() + 30
    while True:
        prepared = read_ledger(state_dir / "ledger.jsonl")
        if any(event["event_type"] == "local_controller_spawned" for event in prepared):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("controller launch is not bound to the prepared ledger")
        time.sleep(0.1)
    if github_nonterminal_runs():
        raise RuntimeError("GitHub frontier ownership reappeared before local launch")
    require_supervisor_disabled()

    plans = manager.build_plans(executor)
    manifest = manager.build_manifest(executor)
    provider_snapshot = manager.build_provider_snapshot(plans)
    atomic_json(state_dir / "provider_snapshot_at_launch.json", provider_snapshot)
    active_runs: list[dict[str, Any]] = []
    recomputed = manager.next_authorization(
        manifest=manifest,
        state_dir=Path(args.bootstrap_state_dir).resolve(),
        active_paid_cells=0,
        active_runs=active_runs,
        provider_snapshot=provider_snapshot,
    )
    if semantic_authorization_payload(recomputed) != semantic_authorization_payload(
        authorization
    ):
        raise RuntimeError("live provider state no longer reproduces the exact dispatch decision")
    atomic_json(state_dir / "live_recomputed_authorization.json", recomputed)
    append_ledger(
        state_dir,
        mirror_dir,
        "live_launch_preflight_passed",
        {
            "authorization_sha256": authorization["authorization_sha256"],
            "live_recomputed_authorization_sha256": recomputed["authorization_sha256"],
            "provider_snapshot_sha256": provider_snapshot["snapshot_sha256"],
            "controller_source_commit": controller_commit,
            "active_github_paid_cells": 0,
            "scientific_values_omitted": True,
        },
    )

    children: list[tuple[str, int]] = []
    launch_failed = False
    for key in authorization["authorized_run_keys"]:
        run_dir = ROOT / str(authorization["plan_dir"]) / "runs" / key
        intent = append_ledger(
            state_dir,
            mirror_dir,
            "segment_launch_intent",
            {
                "authorization_sha256": authorization["authorization_sha256"],
                "run_key": key,
                "source_actions_run_id": authorization["source_actions_run_ids"][key],
                "completed_steps": authorization["completed_steps"][key],
                "segment_end_step": authorization["segment_end_steps"][key],
            },
        )
        receipt = write_local_authorization_receipt(
            run_dir=run_dir,
            key=key,
            authorization=authorization,
            plan_entry=selected[key],
            controller_commit=controller_commit,
            intent_event_sha=intent["event_sha256"],
        )
        try:
            pid, returncode = launcher.launch_one(
                selected[key],
                plans[(str(authorization["campaign"]), str(authorization["stage"]))],
                ROOT / str(authorization["plan_dir"]),
                resume=True,
                wait=False,
                segment_end_step=int(authorization["segment_end_steps"][key]),
            )
            if returncode is not None:
                raise RuntimeError("detached trainer unexpectedly returned synchronously")
        except Exception as error:
            append_ledger(
                state_dir,
                mirror_dir,
                "segment_launch_failed",
                {"run_key": key, "failure": f"{type(error).__name__}: {error}"},
            )
            launch_failed = True
            break
        children.append((key, pid))
        append_ledger(
            state_dir,
            mirror_dir,
            "segment_trainer_started",
            {
                "run_key": key,
                "pid": pid,
                "local_authorization_receipt_sha256": receipt["receipt_sha256"],
            },
        )

    append_ledger(
        state_dir,
        mirror_dir,
        "local_wave_started" if not launch_failed else "local_wave_partial_prefix_started",
        {
            "authorization_sha256": authorization["authorization_sha256"],
            "started_count": len(children),
            "authorized_count": len(authorization["authorized_run_keys"]),
            "pids_by_run_key": {key: pid for key, pid in children},
        },
    )

    failures: list[str] = []
    for key, pid in children:
        _, status = os.waitpid(pid, 0)
        returncode = os.waitstatus_to_exitcode(status)
        event_type = "segment_process_exited"
        payload: dict[str, Any] = {"run_key": key, "pid": pid, "returncode": returncode}
        if returncode == 0:
            try:
                receipt = audit_local_result(
                    key=key,
                    entry=selected[key],
                    authorization=authorization,
                    state_dir=state_dir,
                )
                payload["local_segment_receipt_sha256"] = receipt["receipt_sha256"]
                payload["segment_valid"] = True
            except Exception as error:
                payload["segment_valid"] = False
                payload["audit_failure"] = f"{type(error).__name__}: {error}"
                failures.append(key)
        else:
            payload["segment_valid"] = False
            failures.append(key)
        append_ledger(state_dir, mirror_dir, event_type, payload)

    append_ledger(
        state_dir,
        mirror_dir,
        "local_wave_terminal",
        {
            "authorization_sha256": authorization["authorization_sha256"],
            "started_count": len(children),
            "valid_segment_count": len(children) - len(failures),
            "failed_run_keys": failures,
            "launch_prefix_complete": not launch_failed,
        },
    )
    if launch_failed or failures:
        raise SystemExit(1)


def spawn_controller(args: argparse.Namespace) -> None:
    state_dir = Path(args.state_dir).resolve()
    mirror_dir = Path(args.mirror_dir).resolve()
    events = read_ledger(state_dir / "ledger.jsonl")
    if not events or events[-1]["event_type"] != "local_takeover_prepared":
        raise RuntimeError("local takeover is not in the exact prepared state")
    if not os.environ.get("TINKER_API_KEY"):
        raise RuntimeError("TINKER_API_KEY is required for paid local execution")
    tracked_source_is_clean()
    if github_nonterminal_runs():
        raise RuntimeError("GitHub frontier ownership is not idle")
    require_supervisor_disabled()

    log_path = state_dir / "controller.log"
    command = [
        "/usr/bin/caffeinate", "-dimsu", sys.executable, str(Path(__file__).resolve()),
        "_run", "--state-dir", str(state_dir), "--mirror-dir", str(mirror_dir),
        "--bootstrap-state-dir", str(Path(args.bootstrap_state_dir).resolve()),
        "--executor-config", str(Path(args.executor_config).resolve()),
    ]
    append_ledger(
        state_dir,
        mirror_dir,
        "local_controller_spawn_requested",
        {"authorization_sha256": events[-1]["payload"]["authorization_sha256"]},
    )
    with log_path.open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=os.environ.copy(),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    append_ledger(
        state_dir,
        mirror_dir,
        "local_controller_spawned",
        {"controller_pid": process.pid, "caffeinate": True, "command_sha256": sha256_value(command)},
    )

    deadline = time.monotonic() + args.start_timeout_seconds
    while time.monotonic() < deadline:
        current = read_ledger(state_dir / "ledger.jsonl")
        terminal = current[-1]
        if terminal["event_type"] in {
            "local_wave_started", "local_wave_partial_prefix_started", "local_wave_terminal"
        }:
            print(
                json.dumps(
                    {
                        "controller_pid": process.pid,
                        "event_type": terminal["event_type"],
                        "payload": terminal["payload"],
                    },
                    indent=2,
                )
            )
            if terminal["event_type"] != "local_wave_started":
                raise SystemExit(1)
            return
        if process.poll() is not None:
            raise RuntimeError(f"local controller exited before wave start: {process.returncode}")
        time.sleep(1)
    raise RuntimeError("timed out waiting for the local controller launch handshake")


def status(args: argparse.Namespace) -> None:
    events = read_ledger(Path(args.state_dir).resolve() / "ledger.jsonl")
    print(
        json.dumps(
            {
                "event_count": len(events),
                "last_event": events[-1] if events else None,
                "started_run_keys": [
                    event["payload"]["run_key"]
                    for event in events
                    if event["event_type"] == "segment_trainer_started"
                ],
            },
            indent=2,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--authorization", required=True)
    prepare_parser.add_argument("--state-dir", required=True)
    prepare_parser.add_argument("--mirror-dir", required=True)
    prepare_parser.add_argument("--executor-config", default=str(DEFAULT_EXECUTOR))
    prepare_parser.add_argument("--source-supervisor-run-id", type=int, required=True)
    prepare_parser.add_argument("--download-workers", type=int, default=6)

    launch_parser = subparsers.add_parser("launch")
    launch_parser.add_argument("--state-dir", required=True)
    launch_parser.add_argument("--mirror-dir", required=True)
    launch_parser.add_argument("--bootstrap-state-dir", required=True)
    launch_parser.add_argument("--executor-config", default=str(DEFAULT_EXECUTOR))
    launch_parser.add_argument("--start-timeout-seconds", type=int, default=600)

    run_parser = subparsers.add_parser("_run")
    run_parser.add_argument("--state-dir", required=True)
    run_parser.add_argument("--mirror-dir", required=True)
    run_parser.add_argument("--bootstrap-state-dir", required=True)
    run_parser.add_argument("--executor-config", default=str(DEFAULT_EXECUTOR))

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--state-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "prepare":
        prepare(args)
    elif args.command == "launch":
        spawn_controller(args)
    elif args.command == "_run":
        run_controller(args)
    else:
        status(args)


if __name__ == "__main__":
    main()
