#!/usr/bin/env python3
"""Validate structural generations and emit exact contamination-safe GMN build jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pearl.model_rendering import RendererContract  # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_value(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def expected_generation_contract(job: dict[str, Any]) -> dict[str, Any]:
    config_path = ROOT / job["structural_config"]
    config = read_json(config_path)
    training = read_json(ROOT / config["training_config"])
    model_row = next(row for row in training["models"] if row["model"] == job["model"])
    renderer = str(training["common"]["renderer"])
    source = job.get("source_training")
    source_identity = None
    if source:
        source_identity = {
            "source_run_key": source["run_key"],
            "source_run_contract_sha": source["run_contract_sha"],
            "source_run_contract_file_sha256": source["run_contract_file_sha256"],
            "source_training_report_file_sha256": source["training_report_file_sha256"],
            "source_checkpoint_lineage_file_sha256": source[
                "checkpoint_lineage_file_sha256"
            ],
        }
    identity = {
        "campaign_id": config["campaign_id"],
        "structural_contract": config["contract"],
        "structural_config_sha256": sha256_file(config_path),
        "prompt_panel_sha256": sha256_file(ROOT / config["prompt_panel"]),
        "model": job["model"],
        "model_tag": model_row["tag"],
        "renderer": renderer,
        "renderer_contract_fingerprint": RendererContract(
            name=renderer, model_name=job["model"]
        ).fingerprint(),
        "arm": job["arm"],
        "training_seed": int(job["training_seed"]),
        "checkpoint_step": int(job["checkpoint_step"]),
        "checkpoint_path": job["checkpoint_path"],
        "sampling": config["sampling"],
        "source_training": source_identity,
    }
    identity["generation_contract_sha"] = sha256_value(identity)
    identity["run_key"] = (
        f"struct-{model_row['tag']}-{job['arm']}-seed{job['training_seed']}-"
        f"step{job['checkpoint_step']}-{identity['generation_contract_sha'][:10]}"
    )
    return identity


def expected_fold_contract(job: dict[str, Any], generation: dict[str, Any]) -> dict[str, Any]:
    config_path = ROOT / job["structural_config"]
    config = read_json(config_path)
    gate = config["structure_gate"]
    identity = {
        "campaign_id": config["campaign_id"],
        "structural_contract": config["contract"],
        "structural_config_sha256": sha256_file(config_path),
        "generation_contract_sha": generation["generation_contract_sha"],
        "generation_run_key": generation["run_key"],
        "expected_candidate_count": 96,
        "backend": gate["backend"],
        "model_name": gate["model_name"],
        "model_revision": gate["model_revision"],
        "transformers_version": gate["transformers_version"],
        "torch_version": gate["torch_version"],
        "plddt_gate": gate["plddt_gate"],
        "triad_hbond_max_angstrom": gate["triad_hbond_max_angstrom"],
        "required_triad_method": gate["required_triad_method"],
        "calibration_sha256": sha256_file(ROOT / gate["calibration"]),
        "evaluator_sha256": sha256_file(ROOT / "scripts/run_scaling_paradox_structure.py"),
        "structure_gate_library_sha256": sha256_file(ROOT / "src/pearl/structure_gate.py"),
    }
    identity["fold_contract_sha"] = sha256_value(identity)
    return identity


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--structural-manifest", required=True)
    parser.add_argument("--generation-root", required=True)
    parser.add_argument("--context-output-dir", required=True)
    parser.add_argument("--git-ref", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.git_ref):
        raise RuntimeError("GMN manifest requires an exact 40-character source commit SHA")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    if head != args.git_ref:
        raise RuntimeError("GMN source commit must equal the checked-out approved commit")
    for command in (["git", "diff", "--quiet"], ["git", "diff", "--cached", "--quiet"]):
        if subprocess.run(command, cwd=ROOT, check=False).returncode != 0:
            raise RuntimeError("GMN context must be built from a clean tracked checkout")
    manifest_path = Path(args.structural_manifest)
    manifest = read_json(manifest_path)
    supplied_manifest_sha = manifest.get("structural_manifest_sha")
    if supplied_manifest_sha != sha256_value(
        {key: value for key, value in manifest.items() if key != "structural_manifest_sha"}
    ):
        raise RuntimeError("structural manifest self-hash mismatch")
    if manifest.get("source_commit_sha") != args.git_ref:
        raise RuntimeError("GMN source commit differs from the structural supervisor commit")
    reports = list(Path(args.generation_root).rglob("generation_report.json"))
    jobs_by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
    for job in manifest["jobs"]:
        source = job.get("source_training") or {}
        key = (
            job["model"], job["arm"], int(job["training_seed"]),
            int(job["checkpoint_step"]), source.get("run_contract_sha"),
        )
        jobs_by_identity[key] = job
    observed: dict[str, Path] = {}
    for path in reports:
        report = read_json(path)
        contract = report.get("contract") or {}
        source = contract.get("source_training") or {}
        key = (
            contract.get("model"), contract.get("arm"), int(contract.get("training_seed", -1)),
            int(contract.get("checkpoint_step", -1)), source.get("source_run_contract_sha"),
        )
        if key not in jobs_by_identity:
            continue
        job_key = jobs_by_identity[key]["job_key"]
        if job_key in observed:
            raise RuntimeError(f"duplicate generation report for {job_key}")
        if (
            report.get("status") != "complete"
            or not report.get("complete")
            or int(report.get("expected_candidate_count", -1)) != 96
            or int(report.get("completed_candidate_count", -1)) != 96
            or len(report.get("candidates", [])) != 96
        ):
            raise RuntimeError(f"incomplete generation report for {job_key}")
        if contract != expected_generation_contract(jobs_by_identity[key]):
            raise RuntimeError(f"generation contract differs from exact manifest job {job_key}")
        observed[job_key] = path
    if set(observed) != {job["job_key"] for job in manifest["jobs"]}:
        raise RuntimeError("GMN manifest requires all 111 exact generation reports")
    output_dir = Path(args.context_output_dir)
    rows = []
    executor = read_json(ROOT / "configs/experiments/scaling_paradox_executor_v1.json")
    anchor_commit = subprocess.run(
        ["git", "rev-parse", f"{executor['givemeanode_anchor_ref']}^{{commit}}"],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    ).stdout.strip()
    if anchor_commit != args.git_ref:
        raise RuntimeError("frozen GMN anchor tag does not resolve to the source commit")
    dockerfile = ROOT / "deploy/scaling_paradox_v1/Dockerfile.esmfold"
    entrypoint = ROOT / executor["givemeanode_entrypoint"]
    source_paths = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", args.git_ref, "--", "src"],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    ).stdout.splitlines()
    runtime_paths = [
        "requirements.txt",
        "scripts/run_scaling_paradox_structure.py",
        "configs/structure_gate_calibration.esmfold.json",
        "configs/experiments/scaling_paradox_structural_v1.json",
        "configs/experiments/scaling_paradox_structural_v1_replication.json",
        executor["givemeanode_entrypoint"],
        *source_paths,
    ]
    runtime_member_sha256s = {
        f"./{path}": sha256_file(ROOT / path) for path in runtime_paths
    }
    runtime_member_sha256s["./Dockerfile.esmfold"] = sha256_file(dockerfile)
    for job in manifest["jobs"]:
        job_key = job["job_key"]
        report_path = observed[job_key]
        generation_contract = read_json(report_path)["contract"]
        archive = output_dir / f"{job_key}.tar.zst"
        rows.append(
            {
                "job_key": job_key,
                "generation_report": str(report_path),
                "generation_report_sha256": sha256_file(report_path),
                "context_archive": str(archive),
                "build_command": [
                    "deploy/scaling_paradox_v1/build_esmf_context.sh",
                    str(report_path), str(archive), args.git_ref,
                ],
                "expected_gmn_result_contract": "pearl.scaling-paradox-structural-job/1",
                "candidate_slots": 96,
                "generation_contract_sha": generation_contract["generation_contract_sha"],
                "generation_run_key": generation_contract["run_key"],
                "expected_fold_contract": expected_fold_contract(job, generation_contract),
                "structural_job_sha": job["structural_job_sha"],
                "execution": {
                    "source_commit_sha": args.git_ref,
                    "hardware": executor["givemeanode_hardware"],
                    "dockerfile": "deploy/scaling_paradox_v1/Dockerfile.esmfold",
                    "dockerfile_sha256": sha256_file(dockerfile),
                    "entrypoint": executor["givemeanode_entrypoint"],
                    "entrypoint_sha256": sha256_file(entrypoint),
                    "environment": {
                        "GENERATION_REPORT": "/workspace/input/generation_report.json",
                        "GMN_OUTPUT_DIR": "/workspace/output",
                        "GMN_RESULT_PATH": "/workspace/output/gmn_result.json",
                    },
                    "required_outputs": [
                        "/workspace/output/gmn_result.json",
                        "/workspace/output/scaling-paradox-structural/*/structure_report.json",
                        "/workspace/output/scaling-paradox-structural/*/pdb/*.pdb",
                    ],
                    "context_member_sha256s": {
                        **runtime_member_sha256s,
                        "./input/generation_report.json": sha256_file(report_path),
                    },
                },
            }
        )
    payload = {
        "contract": "pearl.scaling-paradox-gmn-manifest/1",
        "source_structural_manifest_sha": manifest["structural_manifest_sha"],
        "source_structural_manifest_file_sha256": sha256_file(manifest_path),
        "git_ref": args.git_ref,
        "source_commit_sha": args.git_ref,
        "anchor_ref": executor["givemeanode_anchor_ref"],
        "max_active_jobs": executor["givemeanode_max_active_jobs"],
        "max_authorized_usd": executor["max_authorized_givemeanode_usd"],
        "job_count": len(rows),
        "jobs": rows,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["gmn_manifest_sha"] = hashlib.sha256(encoded).hexdigest()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "complete", "job_count": len(rows)}))


if __name__ == "__main__":
    main()
