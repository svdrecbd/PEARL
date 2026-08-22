#!/usr/bin/env python3
"""Validate, inspect, or execute one explicitly approved local structural-generation wave."""

from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pearl.scaling_campaign import read_json, sha256_file, sha256_value, write_json  # noqa: E402


def load_script(name: str) -> Any:
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_manifest(path: Path) -> dict[str, Any]:
    manifest = read_json(path)
    supplied = manifest.get("structural_manifest_sha")
    if supplied != sha256_value(
        {key: value for key, value in manifest.items() if key != "structural_manifest_sha"}
    ):
        raise RuntimeError("structural manifest hash mismatch")
    jobs = manifest.get("jobs") or []
    if (
        manifest.get("contract") != "pearl.frontier-adaptation-structural-manifest/3"
        or len(jobs) != 104
        or len({row.get("job_key") for row in jobs}) != 104
        or manifest.get("candidate_slots_per_job") != 384
    ):
        raise RuntimeError("local controller requires the exact 104-cell frontier manifest")
    return manifest


def validate_source(job: dict[str, Any], source_root: Path) -> dict[str, Path]:
    source = job.get("source_training")
    if source is None:
        return {}
    root = source_root / str(job["campaign"]) / str(source["run_key"])
    bindings = {
        "run_contract.json": "run_contract_file_sha256",
        "report.json": "training_report_file_sha256",
        "checkpoint_lineage.json": "checkpoint_lineage_file_sha256",
    }
    paths = {name: root / name for name in bindings}
    for name, receipt_key in bindings.items():
        if not paths[name].is_file() or sha256_file(paths[name]) != source[receipt_key]:
            raise RuntimeError(f"local structural source {name} mismatch for {job['job_key']}")
    return paths


def command_for(job: dict[str, Any], source_root: Path, output_root: Path) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "scripts/run_scaling_paradox_generation.py"),
        "--config",
        str(ROOT / job["structural_config"]),
        "--model",
        str(job["model"]),
        "--arm",
        str(job["arm"]),
        "--training-seed",
        str(job["training_seed"]),
        "--checkpoint-step",
        str(job["checkpoint_step"]),
        "--output-dir",
        str(output_root),
    ]
    if job.get("checkpoint_path"):
        paths = validate_source(job, source_root)
        command.extend(
            [
                "--checkpoint-path",
                str(job["checkpoint_path"]),
                "--source-run-contract",
                str(paths["run_contract.json"]),
                "--source-training-report",
                str(paths["report.json"]),
                "--source-checkpoint-lineage",
                str(paths["checkpoint_lineage.json"]),
            ]
        )
    return command


def generation_report(job: dict[str, Any], output_root: Path) -> Path:
    builder = load_script("build_frontier_adaptation_gmn_manifest.py")
    contract = builder.expected_generation_contract(job)
    return output_root / str(contract["run_key"]) / "generation_report.json"


def complete(job: dict[str, Any], output_root: Path) -> bool:
    path = generation_report(job, output_root)
    if not path.is_file():
        return False
    builder = load_script("build_frontier_adaptation_gmn_manifest.py")
    expected = builder.expected_generation_contract(job)
    report = read_json(path)
    return bool(
        report.get("contract") == expected
        and report.get("status") == "complete"
        and report.get("complete") is True
        and report.get("expected_candidate_count") == 384
        and report.get("completed_candidate_count") == 384
        and len(report.get("candidates") or []) == 384
    )


def validate_authorization(
    path: Path, manifest: dict[str, Any], requested: list[str]
) -> dict[str, Any]:
    authorization = read_json(path)
    supplied = authorization.get("packet_sha256")
    if supplied != sha256_value(
        {key: value for key, value in authorization.items() if key != "packet_sha256"}
    ):
        raise RuntimeError("local structural authorization hash mismatch")
    checks = {
        "contract": "pearl.frontier-local-structural-execution-approval/1",
        "action": "execute_exact_wave",
        "structural_manifest_sha": manifest["structural_manifest_sha"],
        "authorized_job_keys": requested,
        "calibration_terminal_valid": True,
        "source_checkpoint_deletion_authorized": False,
        "scientific_contract_changes": [],
    }
    if any(authorization.get(key) != value for key, value in checks.items()):
        raise RuntimeError("local structural authorization differs from requested wave")
    if float(authorization.get("maximum_sampling_spend_usd", -1)) > 40.0:
        raise RuntimeError("local structural authorization exceeds frozen Tinker ceiling")
    if os.environ.get("PEARL_STRUCTURAL_APPROVAL_SHA256") != supplied:
        raise RuntimeError("exact local structural approval SHA is not armed in the environment")
    return authorization


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--state-dir", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    shape = subparsers.add_parser("shape")
    shape.add_argument("--job-key", required=True)
    run = subparsers.add_parser("run-wave")
    run.add_argument("--job-key", action="append", required=True)
    run.add_argument("--authorization", required=True)
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    manifest = validate_manifest(manifest_path)
    source_root = Path(args.source_root).resolve()
    output_root = Path(args.output_root).resolve()
    state_dir = Path(args.state_dir).resolve()
    jobs = {str(row["job_key"]): row for row in manifest["jobs"]}
    for job in jobs.values():
        validate_source(job, source_root)

    if args.command == "status":
        completed = [key for key, job in jobs.items() if complete(job, output_root)]
        print(
            json.dumps(
                {
                    "manifest_sha": manifest["structural_manifest_sha"],
                    "complete": len(completed),
                    "remaining": len(jobs) - len(completed),
                    "paid_execution_started": bool(completed or output_root.exists()),
                }
            )
        )
        return

    requested = [str(args.job_key)] if args.command == "shape" else list(args.job_key)
    if len(requested) != len(set(requested)) or any(key not in jobs for key in requested):
        raise RuntimeError("requested local structural job set is duplicate or unknown")
    if args.command == "shape":
        subprocess.run(
            [*command_for(jobs[requested[0]], source_root, output_root), "--shape-only"],
            check=True,
            cwd=ROOT,
        )
        return
    if len(requested) > 6:
        raise RuntimeError("local structural wave exceeds the frozen six-job cap")
    authorization = validate_authorization(Path(args.authorization), manifest, requested)
    if not os.environ.get("TINKER_API_KEY"):
        raise RuntimeError("TINKER_API_KEY is required for paid structural generation")
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "exclusive_owner.lock"
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another local structural owner is active") from error
        claims = state_dir / "claims"
        claims.mkdir(parents=True, exist_ok=True)
        for key in requested:
            claim = claims / f"{key}.json"
            if claim.exists() and not complete(jobs[key], output_root):
                raise RuntimeError(f"unresolved prior structural claim for {key}")
            write_json(
                claim,
                {
                    "contract": "pearl.frontier-local-structural-claim/1",
                    "job_key": key,
                    "structural_manifest_sha": manifest["structural_manifest_sha"],
                    "authorization_sha256": authorization["packet_sha256"],
                },
            )
        failures = []
        with ThreadPoolExecutor(max_workers=len(requested)) as pool:
            futures = {
                pool.submit(
                    subprocess.run,
                    command_for(jobs[key], source_root, output_root),
                    check=False,
                    cwd=ROOT,
                ): key
                for key in requested
                if not complete(jobs[key], output_root)
            }
            for future in as_completed(futures):
                result = future.result()
                if result.returncode != 0:
                    failures.append({"job_key": futures[future], "exit_code": result.returncode})
        if failures:
            raise RuntimeError(f"local structural wave failed: {failures}")
        if any(not complete(jobs[key], output_root) for key in requested):
            raise RuntimeError("local structural wave exited without complete audited reports")
        print(json.dumps({"status": "complete", "job_keys": requested}))


if __name__ == "__main__":
    main()
