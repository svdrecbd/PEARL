#!/usr/bin/env python3
"""Restart fail-closed Tinker-to-S3 exporters after transient process exits."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_NO_PROGRESS_EXITS = 6
MAX_BACKOFF_SECONDS = 15 * 60
RUNTIME_PYTHON = Path("/tmp/pearl-runtime-py312.WoMhEt/venv/bin/python")


@dataclass(frozen=True)
class Job:
    name: str
    inventory: Path
    prefix: str
    state: Path
    log: Path
    shard_count: int
    shard_index: int
    keychain_service: str
    keychain_account: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def jobs() -> list[Job]:
    root = Path("reports/tinker_account_clearance")
    result = [
        Job(
            name="account1",
            inventory=root / "svdrecbd_account1_inventory_20260824.json",
            prefix="account-clearance/svdrecbd-account1-20260825",
            state=root / "svdrecbd_account1_sampler_s3_export_state_20260825.json",
            log=root / "svdrecbd_account1_sampler_s3_export_20260825.log",
            shard_count=1,
            shard_index=0,
            keychain_service="science.californiasynthetic.concord.tinker.svdrecbd",
            keychain_account="svdrecbd@gmail.com",
        )
    ]
    for index in range(8):
        result.append(
            Job(
                name=f"account2-shard{index}",
                inventory=root
                / "existing_default_account2_complete_sampler_inventory_20260825.json",
                prefix=f"account-clearance/ucsf-account2-20260825/shard-{index}",
                state=root
                / f"existing_default_account2_sampler_s3_export_shard{index}_20260825.json",
                log=root
                / f"existing_default_account2_sampler_s3_export_shard{index}_20260825.log",
                shard_count=8,
                shard_index=index,
                keychain_service="science.californiasynthetic.concord.tinker",
            )
        )
    return result


def completed_count(path: Path) -> tuple[int, bool]:
    if not path.exists():
        return 0, False
    value = json.loads(path.read_text(encoding="utf-8"))
    completed = value.get("completed")
    if not isinstance(completed, dict):
        raise RuntimeError(f"invalid completed map: {path}")
    return len(completed), value.get("terminal_valid") is True


def exporter_processes() -> str:
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def process_alive(job: Job, process_table: str) -> bool:
    marker = f"--state {job.state}"
    return any(
        "export_tinker_sampler_archives_to_s3.py" in line and marker in line
        for line in process_table.splitlines()
    )


def network_ready() -> bool:
    try:
        with socket.create_connection(("s3.us-west-1.amazonaws.com", 443), timeout=10):
            return True
    except OSError:
        return False


def launch(job: Job, attempt: int) -> None:
    security = ["security", "find-generic-password"]
    if job.keychain_account:
        security.extend(["-a", job.keychain_account])
    security.extend(["-s", job.keychain_service, "-w"])
    secret_command = " ".join(shlex.quote(item) for item in security)
    command = [
        shlex.quote(str(RUNTIME_PYTHON)),
        "scripts/export_tinker_sampler_archives_to_s3.py",
        "--inventory",
        shlex.quote(str(job.inventory)),
        "--bucket",
        "pearl-full-checkpoint-archive-20260822",
        "--prefix",
        shlex.quote(job.prefix),
        "--state",
        shlex.quote(str(job.state)),
        "--shard-count",
        str(job.shard_count),
        "--shard-index",
        str(job.shard_index),
    ]
    shell = (
        "set -euo pipefail; "
        f"cd {shlex.quote(str(Path.cwd()))}; "
        f"export TINKER_API_KEY=\"$({secret_command})\"; "
        f"exec caffeinate -dimsu {' '.join(command)} >> {shlex.quote(str(job.log))} 2>&1"
    )
    session = f"pearl-s3-{job.name}-r{attempt}"
    subprocess.run(["screen", "-dmS", session, "/bin/zsh", "-lc", shell], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval_seconds < 15:
        raise SystemExit("--interval-seconds must be at least 15")

    supervisor: dict[str, Any]
    if args.state.exists():
        supervisor = json.loads(args.state.read_text(encoding="utf-8"))
    else:
        supervisor = {"contract": "pearl.tinker-s3-export-supervisor/1", "jobs": {}}

    while True:
        table = exporter_processes()
        ready = network_ready()
        all_terminal = True
        now = time.time()
        for job in jobs():
            count, terminal = completed_count(job.state)
            record = supervisor["jobs"].setdefault(
                job.name,
                {
                    "attempts": 0,
                    "last_completed_count": count,
                    "no_progress_exits": 0,
                    "disabled": False,
                },
            )
            record["observed_at"] = utc_now()
            record["completed_count"] = count
            record["terminal_valid"] = terminal
            if terminal:
                record["status"] = "terminal_valid"
                continue
            all_terminal = False
            alive = process_alive(job, table)
            if alive:
                if count > int(record.get("last_completed_count", 0)):
                    record["no_progress_exits"] = 0
                record["last_completed_count"] = count
                record["status"] = "running"
                continue
            if record.get("disabled"):
                record["status"] = "disabled_after_repeated_no_progress_exits"
                continue
            if count > int(record.get("last_completed_count", 0)):
                record["no_progress_exits"] = 0
            else:
                record["no_progress_exits"] = int(record.get("no_progress_exits", 0)) + 1
            record["last_completed_count"] = count
            if record["no_progress_exits"] > MAX_NO_PROGRESS_EXITS:
                record["disabled"] = True
                record["status"] = "disabled_after_repeated_no_progress_exits"
                continue
            backoff = min(
                30 * (2 ** max(record["no_progress_exits"] - 1, 0)),
                MAX_BACKOFF_SECONDS,
            )
            last_attempt = float(record.get("last_attempt_epoch", 0))
            if now - last_attempt < backoff:
                record["status"] = "backoff"
                record["backoff_seconds"] = backoff
                continue
            if not ready:
                record["status"] = "waiting_for_network"
                continue
            record["attempts"] = int(record.get("attempts", 0)) + 1
            launch(job, record["attempts"])
            record["last_attempt_epoch"] = now
            record["last_attempt_at"] = utc_now()
            record["status"] = "restarted"
            print(f"{record['last_attempt_at']} RESTART {job.name}", flush=True)

        supervisor["updated_at"] = utc_now()
        supervisor["network_ready"] = ready
        atomic_json(args.state, supervisor)
        if args.once or all_terminal:
            return 0
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
