#!/usr/bin/env python3
"""Materialize and attest exact replication sampler views for frontier-v2.

The frozen structural manifest binds training-weight paths. Tinker sampling uses a
sampler-weight view of the same adapter. This controller validates the immutable
manifest and hashed source triplets, loads each exact terminal training checkpoint,
saves a sampler view, verifies its live provider metadata, and writes a resumable,
self-hashed attestation. It never changes the structural manifest or generation
contract.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    ROOT
    / "reports"
    / "frontier_adaptation_v2_structural_local_authority"
    / "structural_manifest.json"
)
DEFAULT_SOURCE_ROOT = (
    ROOT
    / "reports"
    / "frontier_adaptation_v2_structural_local_authority"
    / "source_artifacts"
)
DEFAULT_OUTPUT = (
    ROOT
    / "reports"
    / "frontier_adaptation_v2_structural_sampler_weight_attestation_v2.json"
)
EXPECTED_MANIFEST_SHA256 = (
    "2cf37f0b1cd1e10848a55232916be59d34e7703fcd22f13681e221207aa6c788"
)
EXPECTED_COUNT = 48
CAMPAIGN = "replication"
ATTESTATION_CONTRACT = "pearl.structural-sampler-weight-attestation/2"
ENTRY_CONTRACT = "pearl.structural-sampler-weight-attestation-entry/2"
TINKER_PATH = re.compile(r"tinker://[^/]+/sampler_weights/[^/]+")


class MaterializationError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_value(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MaterializationError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def load_local_controller() -> Any:
    path = ROOT / "scripts" / "manage_frontier_adaptation_local_structural.py"
    spec = importlib.util.spec_from_file_location("frontier_local_structural", path)
    if spec is None or spec.loader is None:
        raise MaterializationError("could not load local structural controller")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_paths(job: dict[str, Any], source_root: Path) -> dict[str, Path]:
    source = job["source_training"]
    root = source_root / CAMPAIGN / source["run_key"]
    return {
        "run_contract": root / "run_contract.json",
        "training_report": root / "report.json",
        "checkpoint_lineage": root / "checkpoint_lineage.json",
    }


def validate_job_source(
    job: dict[str, Any], source_root: Path, controller: Any
) -> dict[str, Any]:
    controller.validate_source(job, source_root)
    paths = source_paths(job, source_root)
    source = job["source_training"]
    contract = read_json(paths["run_contract"])
    report = read_json(paths["training_report"])
    lineage = read_json(paths["checkpoint_lineage"])
    checks = {
        "run contract SHA": contract.get("run_contract_sha")
        == source["run_contract_sha"],
        "run key": contract.get("run_key") == source["run_key"],
        "campaign": contract.get("campaign_id")
        == "pearl-frontier-adaptation-v2-replication",
        "model": contract.get("model") == job["model"],
        "arm": contract.get("arm") == job["arm"],
        "training seed": int(contract.get("training_seed", -1))
        == int(job["training_seed"]),
        "rank": int(contract.get("rank", -1)) == 32,
        "terminal report path": report.get("checkpoint_path")
        == job["checkpoint_path"],
        "terminal report contract": report.get("contract_sha")
        == source["run_contract_sha"],
    }
    terminal = [
        row
        for row in lineage.get("checkpoints", [])
        if row.get("terminal") is True
        and int(row.get("step", -1)) == int(job["checkpoint_step"])
        and row.get("state_path") == job["checkpoint_path"]
    ]
    checks["unique terminal lineage"] = len(terminal) == 1
    failures = [name for name, valid in checks.items() if not valid]
    if failures:
        raise MaterializationError(
            f"source validation failed for {job['job_key']}: {', '.join(failures)}"
        )
    return {"rank": int(contract["rank"]), "source": source}


def validate_manifest(
    manifest_path: Path, source_root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    controller = load_local_controller()
    manifest = controller.validate_manifest(manifest_path)
    if manifest["structural_manifest_sha"] != EXPECTED_MANIFEST_SHA256:
        raise MaterializationError("unexpected structural manifest SHA")
    jobs = sorted(
        [
            row
            for row in manifest["jobs"]
            if row.get("campaign") == CAMPAIGN and row.get("checkpoint_path")
        ],
        key=lambda row: row["job_key"],
    )
    if len(jobs) != EXPECTED_COUNT:
        raise MaterializationError(
            f"expected {EXPECTED_COUNT} replication jobs, found {len(jobs)}"
        )
    if len({row["checkpoint_path"] for row in jobs}) != EXPECTED_COUNT:
        raise MaterializationError("replication source checkpoint paths are not unique")
    validated = {
        row["job_key"]: validate_job_source(row, source_root, controller)
        for row in jobs
    }
    return manifest, jobs, validated


def new_attestation(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": ATTESTATION_CONTRACT,
        "structural_manifest_sha": manifest["structural_manifest_sha"],
        "campaign": CAMPAIGN,
        "expected_mapping_count": EXPECTED_COUNT,
        "scientific_contract_changes": [],
        "source_checkpoint_deletion_authorized": False,
        "mappings": {},
    }


def validate_entry(entry: dict[str, Any], job: dict[str, Any]) -> None:
    supplied = entry.get("entry_sha256")
    unsigned = {key: value for key, value in entry.items() if key != "entry_sha256"}
    if supplied != sha256_value(unsigned):
        raise MaterializationError(f"entry self-hash mismatch for {job['job_key']}")
    source = job["source_training"]
    checks = {
        "contract": entry.get("contract") == ENTRY_CONTRACT,
        "manifest": entry.get("structural_manifest_sha")
        == EXPECTED_MANIFEST_SHA256,
        "job": entry.get("job_key") == job["job_key"],
        "job SHA": entry.get("structural_job_sha") == job["structural_job_sha"],
        "source path": entry.get("source_checkpoint_path")
        == job["checkpoint_path"],
        "source contract": entry.get("source_run_contract_sha")
        == source["run_contract_sha"],
        "model": entry.get("model") == job["model"],
        "rank": entry.get("lora_rank") == 32,
        "sampler path": bool(
            TINKER_PATH.fullmatch(str(entry.get("sampler_path", "")))
        ),
    }
    failures = [name for name, valid in checks.items() if not valid]
    if failures:
        raise MaterializationError(
            f"attestation entry mismatch for {job['job_key']}: {', '.join(failures)}"
        )


def load_attestation(
    path: Path, manifest: dict[str, Any], jobs_by_key: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    if not path.is_file():
        return new_attestation(manifest)
    value = read_json(path)
    supplied = value.get("attestation_sha256")
    if supplied is not None:
        unsigned = {
            key: item for key, item in value.items() if key != "attestation_sha256"
        }
        if supplied != sha256_value(unsigned):
            raise MaterializationError("sampler attestation self-hash mismatch")
    checks = {
        "contract": value.get("contract") == ATTESTATION_CONTRACT,
        "manifest": value.get("structural_manifest_sha")
        == manifest["structural_manifest_sha"],
        "campaign": value.get("campaign") == CAMPAIGN,
        "count": value.get("expected_mapping_count") == EXPECTED_COUNT,
        "scientific changes": value.get("scientific_contract_changes") == [],
        "deletion": value.get("source_checkpoint_deletion_authorized") is False,
    }
    failures = [name for name, valid in checks.items() if not valid]
    if failures:
        raise MaterializationError(
            f"sampler attestation header mismatch: {', '.join(failures)}"
        )
    mappings = value.get("mappings")
    if not isinstance(mappings, dict):
        raise MaterializationError("sampler attestation mappings are invalid")
    for job_key, entry in mappings.items():
        if job_key not in jobs_by_key:
            raise MaterializationError(f"unknown attested job: {job_key}")
        validate_entry(entry, jobs_by_key[job_key])
    return value


def checkpoint_metadata(rest: Any, tinker: Any, path: str) -> dict[str, Any]:
    parsed = tinker.types.ParsedCheckpointTinkerPath.from_tinker_path(path)
    checkpoints = rest.list_checkpoints(parsed.training_run_id).result(timeout=60)
    matches = [row for row in checkpoints.checkpoints if row.tinker_path == path]
    if len(matches) != 1 or matches[0].checkpoint_type != "sampler":
        raise MaterializationError(f"sampler checkpoint is absent or non-unique: {path}")
    row = matches[0]
    return {
        "checkpoint_id": row.checkpoint_id,
        "checkpoint_type": row.checkpoint_type,
        "created_at": row.time.isoformat(),
        "size_bytes": row.size_bytes,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "public": row.public,
    }


def verify_weights_info(rest: Any, path: str, job: dict[str, Any], rank: int) -> None:
    info = rest.get_weights_info_by_tinker_path(path).result(timeout=60)
    if (
        info.base_model != job["model"]
        or info.is_lora is not True
        or info.lora_rank != rank
    ):
        raise MaterializationError(
            f"provider weights metadata mismatch for {job['job_key']}"
        )


def finalize_attestation(value: dict[str, Any], path: Path) -> None:
    completed_count = len(value["mappings"])
    value["completed_mapping_count"] = completed_count
    value["terminal_valid"] = completed_count == EXPECTED_COUNT
    if value["terminal_valid"]:
        value.setdefault("completed_at", utc_now())
    else:
        value.pop("completed_at", None)
    value.pop("attestation_sha256", None)
    value["attestation_sha256"] = sha256_value(value)
    write_json(path, value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    try:
        manifest, jobs, validated = validate_manifest(
            args.manifest.resolve(), args.source_root.resolve()
        )
        jobs_by_key = {row["job_key"]: row for row in jobs}
        attestation = load_attestation(args.output, manifest, jobs_by_key)
        if not os.environ.get("TINKER_API_KEY"):
            raise MaterializationError("TINKER_API_KEY is required")

        import tinker

        service = tinker.ServiceClient(
            api_key=os.environ["TINKER_API_KEY"],
            user_metadata={
                "pearl_task": "frontier_v2_replication_sampler_attestation_v2",
                "structural_manifest_sha": manifest["structural_manifest_sha"],
            },
        )
        rest = service.create_rest_client()

        for job in jobs:
            source = validated[job["job_key"]]
            verify_weights_info(
                rest, job["checkpoint_path"], job, int(source["rank"])
            )
            existing = attestation["mappings"].get(job["job_key"])
            if existing is not None:
                validate_entry(existing, job)
                verify_weights_info(
                    rest, existing["sampler_path"], job, int(source["rank"])
                )
                continue
            if args.verify_only:
                continue

            name = f"frontier-v2-repl-{job['structural_job_sha'][:24]}"
            training = service.create_lora_training_client(
                base_model=job["model"],
                rank=int(source["rank"]),
                user_metadata={
                    "purpose": "frontier_v2_replication_sampler_view_v2",
                    "job_key": job["job_key"],
                    "structural_job_sha": job["structural_job_sha"],
                    "source_run_contract_sha": source["source"]["run_contract_sha"],
                },
            )
            training.load_state(path=job["checkpoint_path"]).result(timeout=180)
            response = training.save_weights_for_sampler(name=name).result(timeout=180)
            sampler_path = getattr(response, "path", None)
            if not isinstance(sampler_path, str) or not TINKER_PATH.fullmatch(
                sampler_path
            ):
                raise MaterializationError(
                    f"provider returned an invalid sampler path for {job['job_key']}"
                )
            verify_weights_info(rest, sampler_path, job, int(source["rank"]))
            entry = {
                "contract": ENTRY_CONTRACT,
                "materialized_at": utc_now(),
                "structural_manifest_sha": manifest["structural_manifest_sha"],
                "job_key": job["job_key"],
                "structural_job_sha": job["structural_job_sha"],
                "source_checkpoint_path": job["checkpoint_path"],
                "source_run_contract_sha": source["source"]["run_contract_sha"],
                "source_run_contract_file_sha256": source["source"][
                    "run_contract_file_sha256"
                ],
                "source_training_report_file_sha256": source["source"][
                    "training_report_file_sha256"
                ],
                "source_checkpoint_lineage_file_sha256": source["source"][
                    "checkpoint_lineage_file_sha256"
                ],
                "model": job["model"],
                "lora_rank": int(source["rank"]),
                "sampler_path": sampler_path,
                "provider_checkpoint": checkpoint_metadata(
                    rest, tinker, sampler_path
                ),
            }
            entry["entry_sha256"] = sha256_value(entry)
            attestation["mappings"][job["job_key"]] = entry
            finalize_attestation(attestation, args.output)
            print(
                f"[{len(attestation['mappings'])}/{EXPECTED_COUNT}] "
                f"{job['job_key']}",
                flush=True,
            )
            time.sleep(0.1)

        finalize_attestation(attestation, args.output)
        summary = {
            "attestation": str(args.output),
            "attestation_sha256": attestation["attestation_sha256"],
            "completed_mapping_count": len(attestation["mappings"]),
            "terminal_valid": attestation["terminal_valid"],
            "verify_only": args.verify_only,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        if not attestation["terminal_valid"] and not args.verify_only:
            raise MaterializationError("sampler attestation is incomplete")
        return 0
    except (MaterializationError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
