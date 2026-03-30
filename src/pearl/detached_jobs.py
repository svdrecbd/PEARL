from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any


DEFAULT_GRACE_SECONDS = 5.0
DEFAULT_KILL_WAIT_SECONDS = 2.0
POLL_INTERVAL_SECONDS = 0.2
REQUIRED_EMPTY_POLLS = 3


def parse_env_overrides(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Invalid --env value '{value}'. Expected KEY=VALUE.")
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit(f"Invalid --env value '{value}'. Empty key.")
        overrides[key] = raw
    return overrides


def redact_env_overrides(overrides: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in overrides.items():
        upper = key.upper()
        if any(token in upper for token in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            redacted[key] = "***REDACTED***" if value else ""
        else:
            redacted[key] = value
    return redacted


def load_existing_metadata(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


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


def process_is_alive(pid: int) -> bool:
    if not process_exists(pid):
        return False
    return not process_is_zombie(pid)


def launch_detached(
    *,
    job_name: str,
    cwd: str,
    metadata_path: Path,
    log_path: Path | None,
    env_overrides: dict[str, str],
    command: list[str],
) -> dict[str, Any]:
    metadata_path = metadata_path.expanduser().resolve()
    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_existing_metadata(metadata_path)
    if existing is not None:
        existing_pid = int(existing.get("pid") or 0)
        if existing_pid and process_is_alive(existing_pid):
            raise SystemExit(
                f"Refusing to launch duplicate job '{existing.get('job_name', job_name)}'; "
                f"PID {existing_pid} is still running."
            )

    resolved_log_path = log_path.expanduser().resolve() if log_path is not None else None
    if resolved_log_path is not None:
        resolved_log_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(env_overrides)

    stdout_handle = open(resolved_log_path, "ab", buffering=0) if resolved_log_path is not None else subprocess.DEVNULL
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        if resolved_log_path is not None:
            stdout_handle.close()

    metadata = {
        "job_name": job_name,
        "pid": process.pid,
        "process_group_id": os.getpgid(process.pid),
        "session_id": os.getsid(process.pid),
        "cwd": cwd,
        "command": command,
        "log_path": str(resolved_log_path) if resolved_log_path is not None else None,
        "launched_at": int(time.time()),
        "launcher_pid": os.getpid(),
        "env_overrides": redact_env_overrides(env_overrides),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


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
        entries.append(
            {
                "pid": pid,
                "ppid": ppid,
                "pgid": pgid,
                "is_zombie": "Z" in parts[3],
            }
        )
    return entries


def list_group_members(pgid: int) -> list[int]:
    if pgid <= 0:
        return []
    entries = list_process_entries()
    return [int(entry["pid"]) for entry in entries if entry["pgid"] == pgid and not entry["is_zombie"]]


def list_descendants(root_pid: int) -> list[int]:
    if root_pid <= 0:
        return []
    entries = list_process_entries()
    by_parent: dict[int, list[int]] = {}
    for entry in entries:
        if entry["is_zombie"]:
            continue
        by_parent.setdefault(int(entry["ppid"]), []).append(int(entry["pid"]))
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


def stop_detached(
    metadata_path: Path,
    *,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
    kill_wait_seconds: float = DEFAULT_KILL_WAIT_SECONDS,
) -> dict[str, Any]:
    resolved_path = metadata_path.expanduser().resolve()
    metadata = load_metadata(resolved_path)

    pid = int(metadata.get("pid") or 0)
    pgid = resolve_process_group_id(metadata, pid)
    survivors_before = list_survivors(pid=pid, pgid=pgid)

    if not survivors_before:
        return {
            "job_name": metadata.get("job_name"),
            "metadata_path": str(resolved_path),
            "stopped": False,
            "already_stopped": True,
            "pid": pid,
            "process_group_id": pgid,
            "survivors": [],
        }

    term_sent = False
    kill_sent = False
    if pgid is not None:
        send_signal_to_group(pgid, signal.SIGTERM)
        term_sent = True
    term_sent = send_signal_to_pids(survivors_before, signal.SIGTERM) or term_sent

    wait_for_exit(pid=pid, pgid=pgid, timeout_seconds=grace_seconds)
    survivors_after_term = list_survivors(pid=pid, pgid=pgid)

    if survivors_after_term:
        if pgid is not None:
            send_signal_to_group(pgid, signal.SIGKILL)
            kill_sent = True
        kill_sent = send_signal_to_pids(survivors_after_term, signal.SIGKILL) or kill_sent
        wait_for_exit(pid=pid, pgid=pgid, timeout_seconds=kill_wait_seconds)

    survivors_final = list_survivors(pid=pid, pgid=pgid)
    return {
        "job_name": metadata.get("job_name"),
        "metadata_path": str(resolved_path),
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
