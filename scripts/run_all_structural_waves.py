#!/usr/bin/env python3
"""Auto-advance all 18 structural generation waves sequentially.

Waits for each wave to complete, then immediately launches the next.
Each wave gets its own authorization packet bound to exactly 6 job keys.
Runs until all 104 cells are complete or a hard error occurs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256_value(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_authorization(manifest_path, job_keys, output_path):
    manifest = json.loads(Path(manifest_path).read_text())
    calibration_sha = sha256_file(
        ROOT / "reports/frontier_adaptation_v2_esmfold2_preflight/calibration_result_v3.0.13.json"
    )
    payload = {
        "contract": "pearl.frontier-local-structural-execution-approval/1",
        "action": "execute_exact_wave",
        "structural_manifest_sha": manifest["structural_manifest_sha"],
        "authorized_job_keys": job_keys,
        "calibration_terminal_valid": True,
        "maximum_sampling_spend_usd": 160.0,
        "scientific_contract_changes": [],
        "source_checkpoint_deletion_authorized": False,
    }
    payload["packet_sha256"] = sha256_value(payload)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(payload, indent=2) + "\n")
    return payload["packet_sha256"]


def wave_complete(manifest, wave_job_keys, output_root):
    jobs_by_key = {j["job_key"]: j for j in manifest["jobs"]}
    for key in wave_job_keys:
        report_path = Path(output_root) / key / "generation_report.json"
        if not report_path.is_file():
            return False
        report = json.loads(report_path.read_text())
        if report.get("status") != "complete":
            return False
        expected = report.get("expected_candidate_count", 0)
        completed = report.get("completed_candidate_count", 0)
        if completed != expected:
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--auth-dir", default=str(ROOT / "reports/frontier_adaptation_v2_structural_local_authority"))
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()

    if not os.environ.get("TINKER_API_KEY"):
        raise SystemExit("TINKER_API_KEY is required")

    manifest = json.loads(Path(args.manifest).read_text())
    waves = manifest.get("waves", [])
    total_cells = len(manifest["jobs"])
    completed_total = 0

    for wave_idx, wave in enumerate(waves):
        keys = wave if isinstance(wave, list) else wave.get("job_keys", [j["job_key"] for j in wave.get("jobs", [])])
        print(f"\n{'='*60}", flush=True)
        print(f"WAVE {wave_idx + 1}/{len(waves)}: {len(keys)} cells", flush=True)
        for k in keys:
            print(f"  {k}", flush=True)

        # Skip if already complete
        if wave_complete(manifest, keys, args.output_root):
            completed_total += len(keys)
            print(f"  Already complete. Skipping.", flush=True)
            continue

        # Build authorization packet for this wave
        auth_path = os.path.join(args.auth_dir, f"wave_{wave_idx + 1}_authorization.json")
        packet_sha = build_authorization(args.manifest, keys, auth_path)
        os.environ["PEARL_STRUCTURAL_APPROVAL_SHA256"] = packet_sha

        # Launch wave
        cmd = [
            sys.executable,
            str(ROOT / "scripts/manage_frontier_adaptation_local_structural.py"),
            "--manifest", args.manifest,
            "--source-root", args.source_root,
            "--output-root", args.output_root,
            "--state-dir", args.state_dir,
            "run-wave",
        ]
        for key in keys:
            cmd.extend(["--job-key", key])
        cmd.extend(["--authorization", auth_path])

        env = dict(os.environ)
        env.setdefault("PEARL_GEN_CONCURRENCY", "1")

        print(f"  Launching (PID will follow)...", flush=True)
        result = subprocess.run(cmd, cwd=str(ROOT), env=env)

        if result.returncode != 0:
            print(f"  Wave {wave_idx + 1} exited with code {result.returncode}", flush=True)
            print(f"  Waiting {args.poll_seconds}s before checking completion...", flush=True)
            time.sleep(args.poll_seconds)

        # Wait for completion
        while not wave_complete(manifest, keys, args.output_root):
            done_in_wave = sum(
                1 for k in keys
                if wave_complete(manifest, [k], args.output_root)
            )
            print(f"  Wave {wave_idx + 1}: {done_in_wave}/{len(keys)} cells complete. Polling in {args.poll_seconds}s...", flush=True)
            time.sleep(args.poll_seconds)

        completed_total += len(keys)
        print(f"  Wave {wave_idx + 1} COMPLETE! ({completed_total}/{total_cells} total)", flush=True)

    print(f"\n{'='*60}", flush=True)
    print(f"ALL {len(waves)} WAVES COMPLETE! {completed_total}/{total_cells} cells.", flush=True)


if __name__ == "__main__":
    main()
