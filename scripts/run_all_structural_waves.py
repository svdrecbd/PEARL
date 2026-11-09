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


def build_authorization(
    manifest_path,
    job_keys,
    output_path,
    *,
    sampler_attestation_sha256=None,
    replication_wave_plan_sha256=None,
):
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
    if sampler_attestation_sha256 is not None:
        payload["sampler_attestation_sha256"] = sampler_attestation_sha256
    if replication_wave_plan_sha256 is not None:
        payload["replication_wave_plan_sha256"] = replication_wave_plan_sha256
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
    """Preserve then retire claims for cells without complete reports."""
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
            value = json.loads(claim.read_text())
            prior_sha = str(value.get("authorization_sha256", "unknown"))[:12]
            retired = Path(state_dir) / "superseded_claims"
            retired.mkdir(parents=True, exist_ok=True)
            destination = retired / f"{key}.{prior_sha}.json"
            if destination.exists() and destination.read_bytes() != claim.read_bytes():
                raise RuntimeError(f"superseded claim collision for {key}")
            if not destination.exists():
                claim.replace(destination)
            else:
                claim.unlink()
            print(f"  Preserved and retired stale claim for {key}", flush=True)


def validate_wave_plan(path, manifest):
    plan = json.loads(Path(path).read_text())
    supplied = plan.get("wave_plan_sha256")
    if supplied != sha256_value(
        {key: value for key, value in plan.items() if key != "wave_plan_sha256"}
    ):
        raise RuntimeError("replication wave plan self-hash mismatch")
    if (
        plan.get("contract") != "pearl.frontier-v2-replication-duration-wave-plan/1"
        or plan.get("structural_manifest_sha") != manifest["structural_manifest_sha"]
        or plan.get("campaign") != "replication"
        or plan.get("job_count") != 48
        or plan.get("wave_count") != 8
        or plan.get("maximum_concurrent_cells") != 6
        or plan.get("scientific_contract_changes") != []
        or plan.get("source_checkpoint_deletion_authorized") is not False
        or plan.get("generation_authorized_by_this_packet") is not False
    ):
        raise RuntimeError("replication wave plan header mismatch")
    jobs = {row["job_key"]: row for row in manifest["jobs"]}
    waves = plan.get("waves") or []
    ordered = []
    for expected_index, wave in enumerate(waves, start=1):
        keys = wave.get("job_keys") or []
        if (
            wave.get("wave_index") != expected_index
            or len(keys) != 6
            or len(set(keys)) != 6
            or any(key not in jobs for key in keys)
            or any(jobs[key].get("campaign") != "replication" for key in keys)
            or len({jobs[key]["model"] for key in keys}) != 1
            or wave.get("model") != jobs[keys[0]]["model"]
        ):
            raise RuntimeError(f"invalid grouped replication wave {expected_index}")
        ordered.extend(keys)
    if ordered != plan.get("ordered_job_keys") or len(set(ordered)) != 48:
        raise RuntimeError("replication wave plan job coverage mismatch")
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--auth-dir", default=str(ROOT / "reports/frontier_adaptation_v2_structural_local_authority"))
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument(
        "--wave-plan",
        help="Exact self-hashed grouped replication wave plan.",
    )
    parser.add_argument(
        "--waves",
        default=None,
        help="Comma-separated wave numbers (1-based) or inclusive ranges, e.g. '10-18'. Default: all.",
    )
    parser.add_argument(
        "--exclude-campaign-substring",
        default=None,
        help="Drop individual jobs whose campaign contains this substring before wave batching.",
    )
    args = parser.parse_args()

    if not os.environ.get("TINKER_API_KEY"):
        raise SystemExit("TINKER_API_KEY is required")

    manifest = json.loads(Path(args.manifest).read_text())
    wave_plan = None
    if args.wave_plan:
        if args.waves or args.exclude_campaign_substring:
            raise SystemExit("--wave-plan cannot be combined with wave filters")
        wave_plan = validate_wave_plan(args.wave_plan, manifest)
        selected = set(wave_plan["ordered_job_keys"])
        manifest["jobs"] = [
            row for row in manifest["jobs"] if row["job_key"] in selected
        ]
        manifest["waves"] = [row["job_keys"] for row in wave_plan["waves"]]
        print(
            f"Validated grouped replication plan {wave_plan['wave_plan_sha256']}: "
            f"8 model-homogeneous waves / 48 cells.",
            flush=True,
        )

    # Wave selection uses ORIGINAL manifest indexing (before any exclusion re-indexing)
    if args.waves:
        wanted = set()
        for part in args.waves.split(","):
            if "-" in part:
                lo, hi = part.split("-")
                wanted.update(range(int(lo), int(hi) + 1))
            else:
                wanted.add(int(part))
        all_waves = manifest["waves"]
        manifest["waves"] = [w for i, w in enumerate(all_waves, start=1) if i in wanted]
        print(f"Wave filter {args.waves}: running {len(manifest['waves'])} of {len(all_waves)} manifest waves.", flush=True)

    # Optional job filtering (execution-order flexibility only; per-cell contracts unchanged)
    excluded = set()
    if args.exclude_campaign_substring:
        for j in manifest["jobs"]:
            if args.exclude_campaign_substring in str(j.get("campaign", "")):
                excluded.add(j["job_key"])
        if excluded:
            print(f"Excluding {len(excluded)} jobs by campaign filter.", flush=True)
        manifest["jobs"] = [j for j in manifest["jobs"] if j["job_key"] not in excluded]
        manifest["waves"] = [
            [k for k in (w if isinstance(w, list) else w.get("job_keys")) if k not in excluded]
            for w in manifest["waves"]
        ]
        manifest["waves"] = [w for w in manifest["waves"] if w]

    waves = manifest["waves"]
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
        auth_name = (
            f"replication_grouped_wave_{wave_idx + 1}_authorization.json"
            if wave_plan
            else f"wave_{wave_idx + 1}_authorization.json"
        )
        auth_path = os.path.join(args.auth_dir, auth_name)
        packet_sha = build_authorization(
            args.manifest,
            keys,
            auth_path,
            sampler_attestation_sha256=(
                wave_plan["sampler_attestation_sha256"] if wave_plan else None
            ),
            replication_wave_plan_sha256=(
                wave_plan["wave_plan_sha256"] if wave_plan else None
            ),
        )
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
