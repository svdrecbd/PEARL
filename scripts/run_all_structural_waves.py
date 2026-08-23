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


def report_path_for(job, output_root):
    """Resolve the generation report path via the run_key contract, matching
    the controller's own layout (directories are run_key-named, not job_key)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_frontier_adaptation_gmn_manifest",
        ROOT / "scripts/build_frontier_adaptation_gmn_manifest.py",
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    contract = builder.expected_generation_contract(job)
    return Path(output_root) / str(contract["run_key"]) / "generation_report.json"


def wave_complete(manifest, wave_job_keys, output_root):
    jobs_by_key = {j["job_key"]: j for j in manifest["jobs"]}
    for key in wave_job_keys:
        job = jobs_by_key.get(key)
        if job is None:
            return False
        report_path = report_path_for(job, output_root)
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


def clear_stale_claims(state_dir, keys, output_root, manifest):
    """Remove claim files for cells that are not complete, so the
    controller can resume them. Claims for completed cells are kept."""
    claims_dir = Path(state_dir) / "claims"
    if not claims_dir.is_dir():
        return
    jobs_by_key = {j["job_key"]: j for j in manifest["jobs"]}
    for key in keys:
        claim = claims_dir / f"{key}.json"
        if not claim.is_file():
            continue
        job = jobs_by_key.get(key)
        if job is None:
            continue
        report_path = report_path_for(job, output_root)
        done = False
        if report_path.is_file():
            report = json.loads(report_path.read_text())
            expected = report.get("expected_candidate_count", 0)
            completed = report.get("completed_candidate_count", 0)
            done = (
                report.get("status") == "complete"
                and completed == expected
                and expected > 0
            )
        if not done:
            claim.unlink()
            print(f"  Cleared stale claim for {key}", flush=True)


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

        # Bounded retry loop: relaunch the wave (resumable) up to max_wave_attempts
        # times, clearing stale claims between attempts so a crashed worker cannot
        # wedge the overnight run.
        max_wave_attempts = 8
        for attempt in range(1, max_wave_attempts + 1):
            if wave_complete(manifest, keys, args.output_root):
                break
            clear_stale_claims(
                args.state_dir, keys, args.output_root, manifest
            )
            print(f"  Attempt {attempt}/{max_wave_attempts}: launching...", flush=True)
            result = subprocess.run(cmd, cwd=str(ROOT), env=env)
            if result.returncode != 0:
                print(
                    f"  Wave {wave_idx + 1} exited with code {result.returncode}",
                    flush=True,
                )
            if wave_complete(manifest, keys, args.output_root):
                break
            backoff = min(60 * attempt, 300)
            print(
                f"  Incomplete after attempt {attempt}; backing off {backoff}s...",
                flush=True,
            )
            time.sleep(backoff)

        # Wait for completion (workers may still be flushing); bounded polling.
        waited = 0
        max_wait = 3600  # 1h grace for stragglers after final launch
        while not wave_complete(manifest, keys, args.output_root) and waited < max_wait:
            done_in_wave = sum(
                1 for k in keys
                if wave_complete(manifest, [k], args.output_root)
            )
            print(f"  Wave {wave_idx + 1}: {done_in_wave}/{len(keys)} cells complete. Polling in {args.poll_seconds}s...", flush=True)
            time.sleep(args.poll_seconds)
            waited += args.poll_seconds

        if not wave_complete(manifest, keys, args.output_root):
            print(
                f"  FATAL: Wave {wave_idx + 1} did not complete after "
                f"{max_wave_attempts} attempts. Stopping the runner so no further "
                f"spend occurs. Re-run this script to resume.",
                flush=True,
            )
            sys.exit(2)

        completed_total += len(keys)
        print(f"  Wave {wave_idx + 1} COMPLETE! ({completed_total}/{total_cells} total)", flush=True)

    print(f"\n{'='*60}", flush=True)
    print(f"ALL {len(waves)} WAVES COMPLETE! {completed_total}/{total_cells} cells.", flush=True)


if __name__ == "__main__":
    main()
