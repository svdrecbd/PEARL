from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    args = parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("launch_detached_job.py requires a command after '--'")

    metadata_path = Path(args.metadata_path).expanduser().resolve()
    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_existing_metadata(metadata_path)
    if existing is not None:
        existing_pid = int(existing.get("pid") or 0)
        if existing_pid and process_is_alive(existing_pid):
            raise SystemExit(
                f"Refusing to launch duplicate job '{existing.get('job_name', args.job_name)}'; "
                f"PID {existing_pid} is still running."
            )

    log_path = Path(args.log_path).expanduser().resolve() if args.log_path else None
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(parse_env_overrides(args.env))

    stdout_handle = open(log_path, "ab", buffering=0) if log_path is not None else subprocess.DEVNULL
    try:
        process = subprocess.Popen(
            command,
            cwd=args.cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        if log_path is not None:
            stdout_handle.close()

    metadata = {
        "job_name": args.job_name,
        "pid": process.pid,
        "cwd": args.cwd,
        "command": command,
        "log_path": str(log_path) if log_path is not None else None,
        "launched_at": int(time.time()),
        "launcher_pid": os.getpid(),
        "env_overrides": redact_env_overrides(parse_env_overrides(args.env)),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch a PEARL job in a fully detached session")
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--metadata-path", required=True)
    parser.add_argument("--log-path")
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        help="Environment override in KEY=VALUE form. Can be passed multiple times.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args()


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


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


if __name__ == "__main__":
    main()
