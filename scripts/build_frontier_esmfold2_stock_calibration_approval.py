#!/usr/bin/env python3
"""Build a self-hashed, no-launch stock-image calibration approval packet."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pearl.scaling_campaign import read_json, sha256_file, sha256_value, write_json  # noqa: E402


STOCK_IMAGE = (
    "docker.io/nvidia/cuda:13.0.2-cudnn-runtime-ubuntu24.04@"
    "sha256:14d94b039cb94bbd5da559f303b46bc4b0d5d6c24ab1a9d7b186e566ed3400dc"
)
BOOTSTRAP = Path("deploy/frontier_adaptation_v2/bootstrap_esmfold2_stock_image.sh")


def provider_command(source_commit: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source commit must be an exact lowercase Git SHA")
    bash_program = " ".join(
        [
            "set -euo pipefail;",
            "if command -v sudo >/dev/null 2>&1; then",
            "sudo apt-get update && sudo apt-get install --yes --no-install-recommends ca-certificates git;",
            "else apt-get update && apt-get install --yes --no-install-recommends ca-certificates git; fi;",
            "source_root=$(mktemp -d /tmp/pearl-source.XXXXXX);",
            'git init "$source_root";',
            'git -C "$source_root" remote add origin https://github.com/svdrecbd/PEARL.git;',
            f'git -C "$source_root" fetch --depth 1 origin {source_commit};',
            'git -C "$source_root" checkout --detach FETCH_HEAD;',
            'cd "$source_root";',
            f"exec ./{BOOTSTRAP.as_posix()}",
        ]
    )
    # GiveMeANode invokes --command through /bin/sh. Keep that outer shell
    # POSIX-only and enter Bash before enabling pipefail.
    return f"exec /usr/bin/env bash -lc {shlex.quote(bash_program)}"


def packet(source_commit: str, *, replacement_job_id: str) -> dict[str, Any]:
    config_path = ROOT / "configs/experiments/frontier_adaptation_structural_v2_original.json"
    config = read_json(config_path)
    bootstrap_path = ROOT / BOOTSTRAP
    runtime_lock_path = ROOT / config["structure_gate"]["runtime_lock"]
    calibration_path = ROOT / config["structure_gate"]["calibration"]
    command = provider_command(source_commit)
    subprocess.run(["/bin/sh", "-n"], input=command, text=True, check=True, cwd=ROOT)
    payload: dict[str, Any] = {
        "contract": "pearl.frontier-esmfold2-stock-calibration-approval/2",
        "action": "approval_required_no_launch",
        "replacement_for_provider_job_id": replacement_job_id,
        "replacement_reason": (
            "The prior stock-image command was interpreted by /bin/sh, which rejected "
            "pipefail before bootstrap. This packet enters Bash explicitly and changes no "
            "scientific setting."
        ),
        "source_commit_sha": source_commit,
        "stock_image": STOCK_IMAGE,
        "bootstrap_path": BOOTSTRAP.as_posix(),
        "bootstrap_sha256": sha256_file(bootstrap_path),
        "runtime_lock_sha256": sha256_file(runtime_lock_path),
        "structural_config_sha256": sha256_file(config_path),
        "pending_calibration_sha256": sha256_file(calibration_path),
        "provider_shell": "/bin/sh",
        "provider_command": command,
        "provider_command_sha256": sha256_value(command),
        "provider_command_posix_syntax_valid": True,
        "provider": {
            "workspace": "default",
            "credential_owner": "pearl-structural-ops-20260822",
            "chip": "h100",
            "chip_count": 1,
            "clock_lock": True,
            "hf_cache": True,
            "max_duration_minutes": 300,
            "max_restarts": 1,
            "effective_rate_per_min_usd": 0.04995,
            "provider_max_cost_usd": 14.985,
        },
        "environment": {"PEARL_SOURCE_COMMIT": source_commit},
        "scientific_contract_changes": [],
        "source_checkpoint_deletion_authorized": False,
        "endpoint_generation_started": False,
        "scientific_endpoint_inspection_performed": False,
    }
    payload["packet_sha256"] = sha256_value(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--replacement-job-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    observed_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    ).stdout.strip()
    if args.source_commit != observed_head:
        raise RuntimeError("approval source commit must equal the checked-out commit")
    payload = packet(args.source_commit, replacement_job_id=args.replacement_job_id)
    write_json(Path(args.output), payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
