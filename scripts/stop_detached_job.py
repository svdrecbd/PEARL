from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any


DEFAULT_GRACE_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.2
REQUIRED_EMPTY_POLLS = 3


def main() -> None:
    args = parse_args()
    metadata_path = Path(args.metadata_path).expanduser().resolve()
    metadata = load_metadata(metadata_path)

    pid = int(metadata.get("pid") or 0)
    pgid = resolve_process_group_id(metadata, pid)
    survivors_before = list_survivors(pid=pid, pgid=pgid)

    if not survivors_before:
        print(
            json.dumps(
                {
                    "job_name": metadata.get("job_name"),
                    "metadata_path": str(metadata_path),
                    "stopped": False,
                    "already_stopped": True,
                    "pid": pid,
                    "process_group_id": pgid,
                    "survivors": [],
                },
                indent=2,
            )
        )
        return

    term_sent = False
    kill_sent = False
    if pgid is not None:
        send_signal_to_group(pgid, signal.SIGTERM)
        term_sent = True
    term_sent = send_signal_to_pids(survivors_before, signal.SIGTERM) or term_sent

    wait_for_exit(pid=pid, pgid=pgid, timeout_seconds=args.grace_seconds)
    survivors_after_term = list_survivors(pid=pid, pgid=pgid)

    if survivors_after_term:
        if pgid is not None:
            send_signal_to_group(pgid, signal.SIGKILL)
            kill_sent = True
        kill_sent = send_signal_to_pids(survivors_after_term, signal.SIGKILL) or kill_sent
        wait_for_exit(pid=pid, pgid=pgid, timeout_seconds=args.kill_wait_seconds)

    survivors_final = list_survivors(pid=pid, pgid=pgid)
    payload = {
        "job_name": metadata.get("job_name"),
        "metadata_path": str(metadata_path),
        "pid": pid,
        "process_group_id": pgid,
        "term_sent": term_sent,
        "kill_sent": kill_sent,
        "stopped": not survivors_final,
        "already_stopped": False,
        "survivors_before": survivors_before,
        "survivors_after_term": survivors_after_term,
        "survivors_final": survivors_final,
    }
    if not payload["stopped"]:
        raise SystemExit(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop a detached PEARL job and its full process group")
    parser.add_argument("--metadata-path", required=True)
    parser.add_argument("--grace-seconds", type=float, default=DEFAULT_GRACE_SECONDS)
    parser.add_argument("--kill-wait-seconds", type=float, default=2.0)
    return parser.parse_args()


def load_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Metadata file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Could not parse metadata JSON at {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Metadata file must contain a JSON object: {path}")
    return payload


def resolve_process_group_id(metadata: dict[str, Any], pid: int) -> int | None:
    recorded_pgid = int(metadata.get("process_group_id") or 0)
    if recorded_pgid > 0:
        return recorded_pgid
    if pid <= 0 or not process_exists(pid):
        return None
    try:
        return os.getpgid(pid)
    except ProcessLookupError:
        return None


def send_signal_to_group(pgid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return


def send_signal_to_pids(pids: list[int], sig: signal.Signals) -> bool:
    sent = False
    for pid in sorted(set(pids)):
        if pid <= 0:
            continue
        try:
            os.kill(pid, sig)
            sent = True
        except ProcessLookupError:
            continue
    return sent


def wait_for_exit(*, pid: int, pgid: int | None, timeout_seconds: float) -> None:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    consecutive_empty_polls = 0
    while time.monotonic() < deadline:
        if not list_survivors(pid=pid, pgid=pgid):
            consecutive_empty_polls += 1
            if consecutive_empty_polls >= REQUIRED_EMPTY_POLLS:
                return
        else:
            consecutive_empty_polls = 0
        time.sleep(POLL_INTERVAL_SECONDS)


def list_group_members(pgid: int) -> list[int]:
    if pgid <= 0:
        return []
    entries = list_process_entries()
    members: list[int] = []
    for entry in entries:
        if entry["pgid"] != pgid or entry["is_zombie"]:
            continue
        members.append(entry["pid"])
    return members


def list_descendants(root_pid: int) -> list[int]:
    if root_pid <= 0:
        return []
    entries = list_process_entries()
    by_parent: dict[int, list[int]] = {}
    for entry in entries:
        if entry["is_zombie"]:
            continue
        by_parent.setdefault(entry["ppid"], []).append(entry["pid"])
    descendants: list[int] = []
    pending = list(by_parent.get(root_pid, []))
    while pending:
        current = pending.pop()
        descendants.append(current)
        pending.extend(by_parent.get(current, []))
    return descendants


def list_survivors(*, pid: int, pgid: int | None) -> list[int]:
    survivors: set[int] = set()
    if pid > 0 and process_is_alive(pid):
        survivors.add(pid)
    if pgid is not None:
        survivors.update(list_group_members(pgid))
    if pid > 0:
        survivors.update(list_descendants(pid))
    return sorted(survivors)


def list_process_entries() -> list[dict[str, int | bool]]:
    try:
        completed = subprocess.run(
            ["ps", "-ax", "-o", "pid=,ppid=,pgid=,stat="],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []

    entries: list[dict[str, int | bool]] = []
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
            pgid = int(parts[2])
        except ValueError:
            continue
        state = parts[3]
        entries.append(
            {
                "pid": pid,
                "ppid": ppid,
                "pgid": pgid,
                "is_zombie": "Z" in state,
            }
        )
    return entries


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_is_alive(pid: int) -> bool:
    if not process_exists(pid):
        return False
    return not process_is_zombie(pid)


def process_is_zombie(pid: int) -> bool:
    try:
        completed = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    state = completed.stdout.strip()
    if not state:
        return False
    return "Z" in state


if __name__ == "__main__":
    main()
