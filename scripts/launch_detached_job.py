from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.detached_jobs import launch_detached, parse_env_overrides


def main() -> None:
    args = parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("launch_detached_job.py requires a command after '--'")

    metadata = launch_detached(
        job_name=args.job_name,
        cwd=args.cwd,
        metadata_path=Path(args.metadata_path),
        log_path=Path(args.log_path) if args.log_path else None,
        env_overrides=parse_env_overrides(args.env),
        command=command,
    )
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


if __name__ == "__main__":
    main()
