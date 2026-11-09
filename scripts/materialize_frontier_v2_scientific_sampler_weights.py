#!/usr/bin/env python3
"""Materialize portable sampler adapters for replication scientific milestones.

This tool is intentionally narrow.  It accepts the frozen Frontier v2 structural
manifest and its 48 replication source triplets, selects only steps 500, 1000,
1500, and 2000, proves those exact native checkpoints exist in a supplied live
inventory, and creates one sampler-weight view per source checkpoint.

The terminal step-2250 sampler views are already covered by the separate frozen
structural attestation.  Step-1 and continuation-boundary checkpoints are never
selected here.  The output is resumable and self-hashed.  A provider-side view
created before a local interruption is adopted only when its exact deterministic
job identity is unique; ambiguous or duplicate ownership fails closed.

The default mode is a no-spend plan.  External mutation requires both --execute
and the exact --confirm-plan-sha printed by the plan mode.
"""

from __future__ import annotations

import argparse
import hashlib
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
DEFAULT_INVENTORY = Path("/tmp/pearl_tinker_checkpoints_live_20260824.json")
DEFAULT_OUTPUT = (
    ROOT
    / "reports"
    / "frontier_v2_checkpoint_preservation"
    / "replication_scientific_sampler_attestation.json"
)

EXPECTED_MANIFEST_SHA256 = (
    "2cf37f0b1cd1e10848a55232916be59d34e7703fcd22f13681e221207aa6c788"
)
EXPECTED_CELLS = 48
SCIENTIFIC_STEPS = (500, 1000, 1500, 2000)
CAMPAIGN = "replication"
SOURCE_CAMPAIGN_ID = "pearl-frontier-adaptation-v2-replication"
PURPOSE = "frontier_v2_replication_scientific_sampler_view_v1"
PLAN_CONTRACT = "pearl.frontier-v2-scientific-sampler-plan/1"
ATTESTATION_CONTRACT = "pearl.frontier-v2-scientific-sampler-attestation/1"
ENTRY_CONTRACT = "pearl.frontier-v2-scientific-sampler-attestation-entry/1"
TINKER_PATH = re.compile(r"tinker://[^/]+/(?:weights|sampler_weights)/[^/]+")


class PreservationError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreservationError(f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def source_paths(job: dict[str, Any], source_root: Path) -> dict[str, Path]:
    root = source_root / CAMPAIGN / job["source_training"]["run_key"]
    return {
        "run_contract": root / "run_contract.json",
        "training_report": root / "report.json",
        "checkpoint_lineage": root / "checkpoint_lineage.json",
    }


def load_inventory(path: Path) -> dict[str, dict[str, Any]]:
    value = read_json(path)
    rows = value.get("checkpoints")
    if not isinstance(rows, list):
        raise PreservationError("live inventory has no checkpoint list")
    paths = [row.get("tinker_path") for row in rows]
    if any(not isinstance(item, str) for item in paths):
        raise PreservationError("live inventory contains a checkpoint without a path")
    if len(paths) != len(set(paths)):
        raise PreservationError("live inventory contains duplicate checkpoint paths")
    return {row["tinker_path"]: row for row in rows}


def validate_manifest_header(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("structural_manifest_sha") != EXPECTED_MANIFEST_SHA256:
        raise PreservationError("unexpected structural manifest SHA")
    jobs = sorted(
        [
            row
            for row in manifest.get("jobs", [])
            if row.get("campaign") == CAMPAIGN and row.get("checkpoint_path")
        ],
        key=lambda row: row["source_training"]["run_key"],
    )
    if len(jobs) != EXPECTED_CELLS:
        raise PreservationError(
            f"expected {EXPECTED_CELLS} replication source cells, found {len(jobs)}"
        )
    run_keys = [row["source_training"]["run_key"] for row in jobs]
    contracts = [row["source_training"]["run_contract_sha"] for row in jobs]
    if len(run_keys) != len(set(run_keys)) or len(contracts) != len(set(contracts)):
        raise PreservationError("replication source identities are not unique")
    return jobs


def validate_source_cell(
    job: dict[str, Any],
    source_root: Path,
    inventory: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source = job["source_training"]
    paths = source_paths(job, source_root)
    expected_file_hashes = {
        "run_contract": source["run_contract_file_sha256"],
        "training_report": source["training_report_file_sha256"],
        "checkpoint_lineage": source["checkpoint_lineage_file_sha256"],
    }
    for name, path in paths.items():
        if not path.is_file():
            raise PreservationError(f"missing {name} for {source['run_key']}: {path}")
        if file_sha256(path) != expected_file_hashes[name]:
            raise PreservationError(
                f"{name} file hash mismatch for {source['run_key']}"
            )

    contract = read_json(paths["run_contract"])
    report = read_json(paths["training_report"])
    lineage = read_json(paths["checkpoint_lineage"])
    checks = {
        "campaign": contract.get("campaign_id") == SOURCE_CAMPAIGN_ID,
        "run key": contract.get("run_key") == source["run_key"],
        "run contract": contract.get("run_contract_sha")
        == source["run_contract_sha"],
        "model": contract.get("model") == job["model"],
        "arm": contract.get("arm") == job["arm"],
        "seed": int(contract.get("training_seed", -1))
        == int(job["training_seed"]),
        "rank": int(contract.get("rank", -1)) == 32,
        "max steps": int(contract.get("max_steps", -1)) == 2250,
        "report contract": report.get("contract_sha") == source["run_contract_sha"],
        "terminal path": report.get("checkpoint_path") == job["checkpoint_path"],
        "lineage contract": lineage.get("contract_sha")
        == source["run_contract_sha"],
    }
    failures = [name for name, valid in checks.items() if not valid]
    if failures:
        raise PreservationError(
            f"source contract mismatch for {source['run_key']}: {', '.join(failures)}"
        )

    checkpoints = lineage.get("checkpoints")
    if not isinstance(checkpoints, list):
        raise PreservationError(f"invalid checkpoint lineage for {source['run_key']}")
    selected: list[dict[str, Any]] = []
    for step in SCIENTIFIC_STEPS:
        matches = [row for row in checkpoints if int(row.get("step", -1)) == step]
        if len(matches) != 1:
            raise PreservationError(
                f"step {step} is absent or non-unique for {source['run_key']}"
            )
        lineage_row = matches[0]
        tinker_path = lineage_row.get("state_path")
        if not isinstance(tinker_path, str) or not TINKER_PATH.fullmatch(tinker_path):
            raise PreservationError(
                f"invalid step-{step} checkpoint path for {source['run_key']}"
            )
        provider = inventory.get(tinker_path)
        if provider is None or provider.get("checkpoint_type") != "training":
            raise PreservationError(
                f"live native step-{step} checkpoint is missing for {source['run_key']}"
            )
        job_identity = {
            "source_run_contract_sha": source["run_contract_sha"],
            "source_checkpoint_path": tinker_path,
            "checkpoint_step": step,
            "model": job["model"],
            "model_tag": job["model_tag"],
            "arm": job["arm"],
            "training_seed": int(job["training_seed"]),
            "lora_rank": int(contract["rank"]),
        }
        preservation_job_sha = canonical_sha256(job_identity)
        selected.append(
            {
                **job_identity,
                "preservation_job_sha": preservation_job_sha,
                "run_key": source["run_key"],
                "source_checkpoint_provider_size_bytes": int(
                    provider.get("size_bytes", 0)
                ),
                "source_run_contract_file_sha256": expected_file_hashes[
                    "run_contract"
                ],
                "source_training_report_file_sha256": expected_file_hashes[
                    "training_report"
                ],
                "source_checkpoint_lineage_file_sha256": expected_file_hashes[
                    "checkpoint_lineage"
                ],
            }
        )
    return contract, selected


def build_plan(
    manifest_path: Path, source_root: Path, inventory_path: Path
) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    source_jobs = validate_manifest_header(manifest)
    inventory = load_inventory(inventory_path)
    materialization_jobs: list[dict[str, Any]] = []
    terminal_native: list[dict[str, Any]] = []
    for source_job in source_jobs:
        contract, selected = validate_source_cell(source_job, source_root, inventory)
        materialization_jobs.extend(selected)
        terminal_path = source_job["checkpoint_path"]
        terminal_provider = inventory.get(terminal_path)
        if terminal_provider is None or terminal_provider.get("checkpoint_type") != "training":
            raise PreservationError(
                f"live native terminal checkpoint is missing for {contract['run_key']}"
            )
        terminal_native.append(
            {
                "run_key": contract["run_key"],
                "source_run_contract_sha": contract["run_contract_sha"],
                "checkpoint_step": 2250,
                "checkpoint_path": terminal_path,
                "provider_size_bytes": int(terminal_provider.get("size_bytes", 0)),
                "model": contract["model"],
                "arm": contract["arm"],
                "training_seed": int(contract["training_seed"]),
            }
        )

    materialization_jobs.sort(
        key=lambda row: (
            row["checkpoint_step"],
            row["model_tag"],
            row["arm"],
            row["training_seed"],
        )
    )
    terminal_native.sort(key=lambda row: row["run_key"])
    if len(materialization_jobs) != EXPECTED_CELLS * len(SCIENTIFIC_STEPS):
        raise PreservationError("unexpected scientific materialization job count")
    if len({row["preservation_job_sha"] for row in materialization_jobs}) != len(
        materialization_jobs
    ):
        raise PreservationError("scientific materialization job identities are not unique")
    if len({row["source_checkpoint_path"] for row in materialization_jobs}) != len(
        materialization_jobs
    ):
        raise PreservationError("scientific source checkpoint paths are not unique")

    unsigned = {
        "contract": PLAN_CONTRACT,
        "structural_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "structural_manifest_file_sha256": file_sha256(manifest_path),
        "live_inventory_file_sha256": file_sha256(inventory_path),
        "campaign": CAMPAIGN,
        "scientific_steps": list(SCIENTIFIC_STEPS),
        "expected_cell_count": EXPECTED_CELLS,
        "materialization_job_count": len(materialization_jobs),
        "source_native_bytes": sum(
            row["source_checkpoint_provider_size_bytes"]
            for row in materialization_jobs
        ),
        "temporary_native_terminal_retention": {
            "reason": "exact Tinker optimizer-state continuation insurance",
            "checkpoint_step": 2250,
            "checkpoint_count": len(terminal_native),
            "provider_size_bytes": sum(
                row["provider_size_bytes"] for row in terminal_native
            ),
            "checkpoints": terminal_native,
        },
        "excluded_steps": {
            "terminal_2250": "portable views already attested separately",
            "step_1_and_segment_boundaries": "recovery-only, not scientific milestones",
        },
        "source_checkpoint_deletion_authorized": False,
        "materialization_jobs": materialization_jobs,
    }
    return {**unsigned, "plan_sha256": canonical_sha256(unsigned)}


def validate_plan_hash(plan: dict[str, Any]) -> None:
    supplied = plan.get("plan_sha256")
    unsigned = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if supplied != canonical_sha256(unsigned):
        raise PreservationError("preservation plan self-hash mismatch")


def new_attestation(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": ATTESTATION_CONTRACT,
        "plan_sha256": plan["plan_sha256"],
        "expected_mapping_count": plan["materialization_job_count"],
        "scientific_contract_changes": [],
        "source_checkpoint_deletion_authorized": False,
        "mappings": {},
    }


def validate_entry(entry: dict[str, Any], job: dict[str, Any], plan_sha: str) -> None:
    supplied = entry.get("entry_sha256")
    unsigned = {key: value for key, value in entry.items() if key != "entry_sha256"}
    if supplied != canonical_sha256(unsigned):
        raise PreservationError(
            f"attestation entry hash mismatch for {job['preservation_job_sha']}"
        )
    checks = {
        "contract": entry.get("contract") == ENTRY_CONTRACT,
        "plan": entry.get("plan_sha256") == plan_sha,
        "job": entry.get("preservation_job_sha")
        == job["preservation_job_sha"],
        "source": entry.get("source_checkpoint_path")
        == job["source_checkpoint_path"],
        "source contract": entry.get("source_run_contract_sha")
        == job["source_run_contract_sha"],
        "step": entry.get("checkpoint_step") == job["checkpoint_step"],
        "model": entry.get("model") == job["model"],
        "rank": entry.get("lora_rank") == job["lora_rank"],
        "sampler": isinstance(entry.get("sampler_path"), str)
        and "/sampler_weights/" in entry["sampler_path"],
    }
    failures = [name for name, valid in checks.items() if not valid]
    if failures:
        raise PreservationError(
            f"attestation mismatch for {job['preservation_job_sha']}: "
            + ", ".join(failures)
        )


def load_attestation(
    path: Path, plan: dict[str, Any], jobs_by_sha: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    if not path.is_file():
        return new_attestation(plan)
    value = read_json(path)
    supplied = value.get("attestation_sha256")
    if supplied is not None:
        unsigned = {
            key: item for key, item in value.items() if key != "attestation_sha256"
        }
        if supplied != canonical_sha256(unsigned):
            raise PreservationError("sampler attestation self-hash mismatch")
    checks = {
        "contract": value.get("contract") == ATTESTATION_CONTRACT,
        "plan": value.get("plan_sha256") == plan["plan_sha256"],
        "count": value.get("expected_mapping_count")
        == plan["materialization_job_count"],
        "scientific changes": value.get("scientific_contract_changes") == [],
        "deletion": value.get("source_checkpoint_deletion_authorized") is False,
    }
    failures = [name for name, valid in checks.items() if not valid]
    if failures:
        raise PreservationError(
            "sampler attestation header mismatch: " + ", ".join(failures)
        )
    mappings = value.get("mappings")
    if not isinstance(mappings, dict):
        raise PreservationError("sampler attestation mappings are invalid")
    for job_sha, entry in mappings.items():
        if job_sha not in jobs_by_sha:
            raise PreservationError(f"unknown attested job: {job_sha}")
        validate_entry(entry, jobs_by_sha[job_sha], plan["plan_sha256"])
    return value


def finalize_attestation(value: dict[str, Any], path: Path) -> None:
    value["completed_mapping_count"] = len(value["mappings"])
    value["terminal_valid"] = (
        value["completed_mapping_count"] == value["expected_mapping_count"]
    )
    if value["terminal_valid"]:
        value.setdefault("completed_at", utc_now())
    else:
        value.pop("completed_at", None)
    value.pop("attestation_sha256", None)
    value["attestation_sha256"] = canonical_sha256(value)
    atomic_json(path, value)


def sampler_checkpoint_metadata(rest: Any, tinker: Any, path: str) -> dict[str, Any]:
    parsed = tinker.types.ParsedCheckpointTinkerPath.from_tinker_path(path)
    response = rest.list_checkpoints(parsed.training_run_id).result(timeout=60)
    matches = [row for row in response.checkpoints if row.tinker_path == path]
    if len(matches) != 1 or matches[0].checkpoint_type != "sampler":
        raise PreservationError(f"sampler checkpoint is absent or non-unique: {path}")
    row = matches[0]
    return {
        "checkpoint_id": row.checkpoint_id,
        "checkpoint_type": row.checkpoint_type,
        "created_at": row.time.isoformat(),
        "size_bytes": int(row.size_bytes),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "public": bool(row.public),
    }


def verify_weights_info(rest: Any, path: str, job: dict[str, Any]) -> None:
    info = rest.get_weights_info_by_tinker_path(path).result(timeout=60)
    if (
        info.base_model != job["model"]
        or info.is_lora is not True
        or int(info.lora_rank) != int(job["lora_rank"])
    ):
        raise PreservationError(
            f"provider weights metadata mismatch for {job['preservation_job_sha']}"
        )


def provider_existing_views(rest: Any) -> dict[str, Any]:
    response = rest.list_training_runs(limit=0).result(timeout=120)
    owners: dict[str, list[Any]] = {}
    for row in response.training_runs:
        metadata = row.user_metadata or {}
        if metadata.get("purpose") != PURPOSE:
            continue
        job_sha = metadata.get("preservation_job_sha")
        if isinstance(job_sha, str):
            owners.setdefault(job_sha, []).append(row)
    duplicates = {key: value for key, value in owners.items() if len(value) != 1}
    if duplicates:
        raise PreservationError(
            "duplicate provider ownership for scientific sampler jobs: "
            + ", ".join(sorted(duplicates))
        )
    return {key: value[0] for key, value in owners.items()}


def entry_for_sampler(
    rest: Any,
    tinker: Any,
    plan: dict[str, Any],
    job: dict[str, Any],
    sampler_path: str,
    materialization_mode: str,
) -> dict[str, Any]:
    verify_weights_info(rest, sampler_path, job)
    entry = {
        "contract": ENTRY_CONTRACT,
        "materialized_at": utc_now(),
        "materialization_mode": materialization_mode,
        "plan_sha256": plan["plan_sha256"],
        "preservation_job_sha": job["preservation_job_sha"],
        "run_key": job["run_key"],
        "source_checkpoint_path": job["source_checkpoint_path"],
        "source_run_contract_sha": job["source_run_contract_sha"],
        "checkpoint_step": job["checkpoint_step"],
        "model": job["model"],
        "model_tag": job["model_tag"],
        "arm": job["arm"],
        "training_seed": job["training_seed"],
        "lora_rank": job["lora_rank"],
        "sampler_path": sampler_path,
        "provider_checkpoint": sampler_checkpoint_metadata(rest, tinker, sampler_path),
    }
    entry["entry_sha256"] = canonical_sha256(entry)
    return entry


def execute(
    plan: dict[str, Any], output: Path, confirm_plan_sha: str
) -> dict[str, Any]:
    if confirm_plan_sha != plan["plan_sha256"]:
        raise PreservationError("--confirm-plan-sha does not match the exact plan")
    api_key = os.environ.get("TINKER_API_KEY")
    if not api_key:
        raise PreservationError("TINKER_API_KEY is required for execution")

    import tinker

    jobs = plan["materialization_jobs"]
    jobs_by_sha = {row["preservation_job_sha"]: row for row in jobs}
    attestation = load_attestation(output, plan, jobs_by_sha)
    service = tinker.ServiceClient(
        api_key=api_key,
        user_metadata={
            "pearl_task": PURPOSE,
            "preservation_plan_sha": plan["plan_sha256"],
        },
    )
    rest = service.create_rest_client()
    existing_views = provider_existing_views(rest)
    unknown = sorted(set(existing_views) - set(jobs_by_sha))
    if unknown:
        raise PreservationError(
            "provider contains scientific sampler jobs outside this plan: "
            + ", ".join(unknown)
        )

    for index, job in enumerate(jobs, start=1):
        job_sha = job["preservation_job_sha"]
        verify_weights_info(rest, job["source_checkpoint_path"], job)
        local_entry = attestation["mappings"].get(job_sha)
        if local_entry is not None:
            validate_entry(local_entry, job, plan["plan_sha256"])
            verify_weights_info(rest, local_entry["sampler_path"], job)
            print(f"[{index}/{len(jobs)}] RECORDED {job['run_key']} step {job['checkpoint_step']}", flush=True)
            continue

        existing = existing_views.get(job_sha)
        if existing is not None:
            sampler = existing.last_sampler_checkpoint
            if sampler is None or sampler.checkpoint_type != "sampler":
                raise PreservationError(
                    f"provider owner has no sampler checkpoint for {job_sha}"
                )
            metadata = existing.user_metadata or {}
            checks = {
                "plan": metadata.get("preservation_plan_sha") == plan["plan_sha256"],
                "source": metadata.get("source_checkpoint_path")
                == job["source_checkpoint_path"],
                "source contract": metadata.get("source_run_contract_sha")
                == job["source_run_contract_sha"],
                "step": int(metadata.get("checkpoint_step", -1))
                == int(job["checkpoint_step"]),
            }
            failures = [name for name, valid in checks.items() if not valid]
            if failures:
                raise PreservationError(
                    f"provider adoption mismatch for {job_sha}: {', '.join(failures)}"
                )
            entry = entry_for_sampler(
                rest, tinker, plan, job, sampler.tinker_path, "adopted_after_interruption"
            )
        else:
            name = f"frontier-v2-repl-science-{job_sha[:20]}"
            training = service.create_lora_training_client(
                base_model=job["model"],
                rank=int(job["lora_rank"]),
                user_metadata={
                    "purpose": PURPOSE,
                    "preservation_plan_sha": plan["plan_sha256"],
                    "preservation_job_sha": job_sha,
                    "source_run_contract_sha": job["source_run_contract_sha"],
                    "source_checkpoint_path": job["source_checkpoint_path"],
                    "checkpoint_step": str(job["checkpoint_step"]),
                    "run_key": job["run_key"],
                },
            )
            training.load_state(path=job["source_checkpoint_path"]).result(timeout=300)
            response = training.save_weights_for_sampler(name=name).result(timeout=300)
            sampler_path = getattr(response, "path", None)
            if not isinstance(sampler_path, str) or "/sampler_weights/" not in sampler_path:
                raise PreservationError(f"provider returned an invalid sampler path for {job_sha}")
            entry = entry_for_sampler(
                rest, tinker, plan, job, sampler_path, "created"
            )
            existing_views[job_sha] = True

        attestation["mappings"][job_sha] = entry
        finalize_attestation(attestation, output)
        print(
            f"[{index}/{len(jobs)}] VERIFIED {job['run_key']} step {job['checkpoint_step']}",
            flush=True,
        )
        time.sleep(0.1)

    finalize_attestation(attestation, output)
    return attestation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-plan-sha")
    args = parser.parse_args()

    try:
        plan = build_plan(
            args.manifest.resolve(), args.source_root.resolve(), args.inventory.resolve()
        )
        validate_plan_hash(plan)
        if args.plan_output:
            atomic_json(args.plan_output.resolve(), plan)
        summary = {
            "contract": plan["contract"],
            "plan_sha256": plan["plan_sha256"],
            "materialization_job_count": plan["materialization_job_count"],
            "source_native_bytes": plan["source_native_bytes"],
            "terminal_native_retention_count": plan[
                "temporary_native_terminal_retention"
            ]["checkpoint_count"],
            "terminal_native_retention_bytes": plan[
                "temporary_native_terminal_retention"
            ]["provider_size_bytes"],
            "external_mutation": bool(args.execute),
        }
        if args.execute:
            if not args.confirm_plan_sha:
                raise PreservationError("--execute requires --confirm-plan-sha")
            attestation = execute(plan, args.output.resolve(), args.confirm_plan_sha)
            summary.update(
                {
                    "attestation": str(args.output.resolve()),
                    "completed_mapping_count": attestation[
                        "completed_mapping_count"
                    ],
                    "terminal_valid": attestation["terminal_valid"],
                    "attestation_sha256": attestation["attestation_sha256"],
                }
            )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    except (PreservationError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
