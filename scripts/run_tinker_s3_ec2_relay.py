#!/usr/bin/env python3
"""Run all resumable Tinker-to-S3 export shards on one disposable EC2 relay."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


BUCKET = "pearl-full-checkpoint-archive-20260822"
CONTROL_PREFIX = "control/ec2-relay-20260825"
ROOT = Path("/opt/pearl-relay")
REPORTS = ROOT / "reports/tinker_account_clearance"
EXPORTER = ROOT / "scripts/export_tinker_sampler_archives_to_s3.py"
JOB_CONFIG = ROOT / "job-config.json"
ACCOUNT1_PARAMETER = "/pearl/tinker-s3-relay/20260825/account1-api-key"
ACCOUNT2_PARAMETER = "/pearl/tinker-s3-relay/20260825/account2-api-key"


@dataclass(frozen=True)
class Job:
    name: str
    inventory: Path
    prefix: str
    state: Path
    log: Path
    shard_count: int
    shard_index: int
    parameter_name: str
    checkpoint_type: str = "sampler"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_sha256(value: dict[str, Any], omitted: str) -> str:
    payload = {key: item for key, item in value.items() if key != omitted}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def jobs() -> list[Job]:
    if JOB_CONFIG.exists():
        value = json.loads(JOB_CONFIG.read_text(encoding="utf-8"))
        if value.get("contract") != "pearl.tinker-s3-relay-jobs/1":
            raise RuntimeError("invalid relay job config contract")
        if value.get("config_sha256") != canonical_sha256(value, "config_sha256"):
            raise RuntimeError("relay job config SHA-256 mismatch")
        rows = value.get("jobs")
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("relay job config contains no jobs")
        return [
            Job(
                name=row["name"],
                inventory=ROOT / row["inventory"],
                prefix=row["prefix"],
                state=ROOT / row["state"],
                log=ROOT / row["log"],
                shard_count=int(row["shard_count"]),
                shard_index=int(row["shard_index"]),
                parameter_name=row["parameter_name"],
                checkpoint_type=row.get("checkpoint_type", "sampler"),
            )
            for row in rows
        ]

    result = [
        Job(
            name="account1",
            inventory=REPORTS / "svdrecbd_account1_inventory_20260824.json",
            prefix="account-clearance/svdrecbd-account1-20260825",
            state=REPORTS / "svdrecbd_account1_sampler_s3_export_state_20260825.json",
            log=REPORTS / "svdrecbd_account1_sampler_s3_export_20260825.ec2.log",
            shard_count=1,
            shard_index=0,
            parameter_name=ACCOUNT1_PARAMETER,
        )
    ]
    for index in range(8):
        result.append(
            Job(
                name=f"account2-shard{index}",
                inventory=REPORTS
                / "existing_default_account2_complete_sampler_inventory_20260825.json",
                prefix=f"account-clearance/ucsf-account2-20260825/shard-{index}",
                state=REPORTS
                / f"existing_default_account2_sampler_s3_export_shard{index}_20260825.json",
                log=REPORTS
                / f"existing_default_account2_sampler_s3_export_shard{index}_20260825.ec2.log",
                shard_count=8,
                shard_index=index,
                parameter_name=ACCOUNT2_PARAMETER,
            )
        )
    return result


def state_summary(path: Path) -> tuple[int, bool]:
    if not path.exists():
        return 0, False
    value = json.loads(path.read_text(encoding="utf-8"))
    completed = value.get("completed")
    if not isinstance(completed, dict):
        raise RuntimeError(f"invalid completed map: {path}")
    return len(completed), value.get("terminal_valid") is True


def put_bytes(s3: Any, key: str, body: bytes, content_type: str) -> None:
    checksum = base64.b64encode(hashlib.sha256(body).digest()).decode()
    response = s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=body,
        ChecksumSHA256=checksum,
        ServerSideEncryption="AES256",
        ContentType=content_type,
    )
    if response.get("ChecksumSHA256") != checksum:
        raise RuntimeError(f"S3 checksum mismatch while writing {key}")


def sync_artifacts(s3: Any, status: dict[str, Any], configured_jobs: list[Job]) -> None:
    body = json.dumps(status, indent=2, sort_keys=True).encode() + b"\n"
    put_bytes(s3, f"{CONTROL_PREFIX}/status.json", body, "application/json")
    for job in configured_jobs:
        for path, suffix in ((job.state, "state.json"), (job.log, "log.txt")):
            if path.exists():
                s3.upload_file(
                    str(path),
                    BUCKET,
                    f"{CONTROL_PREFIX}/jobs/{job.name}/{suffix}",
                    ExtraArgs={"ServerSideEncryption": "AES256"},
                )


def launch(job: Job, api_key: str, attempt: int) -> tuple[subprocess.Popen[bytes], BinaryIO]:
    job.log.parent.mkdir(parents=True, exist_ok=True)
    handle = job.log.open("ab", buffering=0)
    marker = f"\n{utc_now()} START attempt={attempt}\n".encode()
    handle.write(marker)
    command = [
        str(ROOT / "venv/bin/python"),
        str(EXPORTER),
        "--inventory",
        str(job.inventory),
        "--bucket",
        BUCKET,
        "--prefix",
        job.prefix,
        "--state",
        str(job.state),
        "--checkpoint-type",
        job.checkpoint_type,
        "--shard-count",
        str(job.shard_count),
        "--shard-index",
        str(job.shard_index),
        "--range-concurrency",
        "4",
        "--disable-pyqwest",
    ]
    environment = os.environ.copy()
    environment["TINKER_API_KEY"] = api_key
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    return process, handle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deadline-hours", type=float, default=12.0)
    parser.add_argument("--sync-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.deadline_hours <= 0 or args.sync_seconds < 60:
        raise SystemExit("invalid deadline or sync interval")

    config = Config(
        retries={"total_max_attempts": 8, "mode": "adaptive"},
        connect_timeout=10,
        read_timeout=180,
        max_pool_connections=20,
    )
    s3 = boto3.client("s3", region_name="us-west-1", config=config)
    ssm = boto3.client("ssm", region_name="us-west-1", config=config)
    configured_jobs = jobs()
    parameter_names = sorted({job.parameter_name for job in configured_jobs})
    parameters = ssm.get_parameters(Names=parameter_names, WithDecryption=True)
    if parameters.get("InvalidParameters"):
        raise RuntimeError(f"missing encrypted parameters: {parameters['InvalidParameters']}")
    secrets = {row["Name"]: row["Value"] for row in parameters["Parameters"]}
    if set(secrets) != set(parameter_names):
        raise RuntimeError("did not retrieve every configured Tinker credential")

    started = time.monotonic()
    deadline = started + args.deadline_hours * 3600
    last_sync = 0.0
    processes: dict[str, subprocess.Popen[bytes]] = {}
    handles: dict[str, BinaryIO] = {}
    records: dict[str, dict[str, Any]] = {}

    try:
        while True:
            now = time.monotonic()
            all_terminal = True
            status_jobs: dict[str, Any] = {}
            for job in configured_jobs:
                completed, terminal = state_summary(job.state)
                record = records.setdefault(
                    job.name,
                    {
                        "attempts": 0,
                        "last_completed_count": completed,
                        "next_launch_monotonic": 0.0,
                    },
                )
                process = processes.get(job.name)
                if terminal:
                    if process is not None and process.poll() is None:
                        process.terminate()
                    status_jobs[job.name] = {
                        "status": "terminal_valid",
                        "completed_count": completed,
                        "attempts": record["attempts"],
                    }
                    continue

                all_terminal = False
                if process is not None and process.poll() is None:
                    status_jobs[job.name] = {
                        "status": "running",
                        "completed_count": completed,
                        "attempts": record["attempts"],
                        "pid": process.pid,
                    }
                    record["last_completed_count"] = completed
                    continue

                if process is not None:
                    handles.pop(job.name).close()
                    processes.pop(job.name)
                    if completed > int(record["last_completed_count"]):
                        record["consecutive_no_progress_exits"] = 0
                    else:
                        record["consecutive_no_progress_exits"] = int(
                            record.get("consecutive_no_progress_exits", 0)
                        ) + 1
                    delay = min(
                        30 * (2 ** max(record["consecutive_no_progress_exits"] - 1, 0)),
                        900,
                    )
                    record["next_launch_monotonic"] = now + delay
                record["last_completed_count"] = completed

                if now >= float(record["next_launch_monotonic"]):
                    record["attempts"] = int(record["attempts"]) + 1
                    process, handle = launch(
                        job, secrets[job.parameter_name], int(record["attempts"])
                    )
                    processes[job.name] = process
                    handles[job.name] = handle
                    status = "started"
                else:
                    status = "backoff"
                status_jobs[job.name] = {
                    "status": status,
                    "completed_count": completed,
                    "attempts": record["attempts"],
                    "consecutive_no_progress_exits": record.get(
                        "consecutive_no_progress_exits", 0
                    ),
                }

            status = {
                "contract": "pearl.tinker-s3-ec2-relay-status/1",
                "updated_at": utc_now(),
                "deadline_hours": args.deadline_hours,
                "elapsed_seconds": int(now - started),
                "all_terminal_valid": all_terminal,
                "jobs": status_jobs,
            }
            if all_terminal or now - last_sync >= args.sync_seconds:
                sync_artifacts(s3, status, configured_jobs)
                last_sync = now
            if all_terminal:
                subprocess.run(["/usr/sbin/shutdown", "-h", "now"], check=False)
                return 0
            if now >= deadline:
                status["deadline_reached"] = True
                sync_artifacts(s3, status, configured_jobs)
                subprocess.run(["/usr/sbin/shutdown", "-h", "now"], check=False)
                return 2
            time.sleep(30)
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        for handle in handles.values():
            handle.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ClientError, OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
