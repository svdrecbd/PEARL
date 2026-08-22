#!/usr/bin/env python3
"""Assemble one local, hash-validated structural authority state without replaying GitHub history."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pearl.scaling_campaign import read_json, sha256_file, sha256_value, write_json  # noqa: E402


SOURCE_FILES = {
    "run_contract.json": "run_contract_file_sha256",
    "report.json": "training_report_file_sha256",
    "checkpoint_lineage.json": "checkpoint_lineage_file_sha256",
}


def load_script(name: str) -> Any:
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_receipt(
    receipt: dict[str, Any], *, campaign_id: str, run_key: str, contract_sha: str, kind: str
) -> None:
    expected = {
        "campaign_id": campaign_id,
        "run_key": run_key,
        "run_contract_sha": contract_sha,
        "scientific_values_omitted": True,
        f"{kind}_terminal_valid": True,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise RuntimeError(f"{kind} receipt differs from frozen cell {run_key}")
    supplied = receipt.get("receipt_sha256")
    if supplied != sha256_value(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    ):
        raise RuntimeError(f"{kind} receipt hash mismatch for {run_key}")


def receipt_from_states(
    state_dirs: list[Path], *, kind: str, run_key: str
) -> tuple[dict[str, Any], Path]:
    matches = [
        path
        for state in state_dirs
        for path in [state / "receipts" / kind / f"{run_key}.json"]
        if path.is_file()
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one {kind} receipt for {run_key}, found {len(matches)}"
        )
    return read_json(matches[0]), matches[0]


def locate_source(root: Path, run_key: str) -> dict[str, Path] | None:
    direct = root / run_key
    candidates = [direct] if direct.is_dir() else []
    if not candidates and root.is_dir():
        candidates = [path for path in root.rglob(run_key) if path.is_dir()]
    valid: list[dict[str, Path]] = []
    for candidate in candidates:
        files = {name: candidate / name for name in SOURCE_FILES}
        if all(path.is_file() for path in files.values()):
            valid.append(files)
    if len(valid) > 1:
        raise RuntimeError(f"source artifact is non-unique for {run_key}")
    return valid[0] if valid else None


def locator_receipt(locator_states: list[Path], run_key: str) -> dict[str, Any] | None:
    matches = [
        path
        for state in locator_states
        for path in [state / "receipts" / "training" / f"{run_key}.json"]
        if path.is_file()
    ]
    usable = []
    for path in matches:
        receipt = read_json(path)
        if receipt.get("source_actions_run_id") and receipt.get("source_artifact_name"):
            usable.append(receipt)
    identities = {
        (int(row["source_actions_run_id"]), str(row["source_artifact_name"]))
        for row in usable
    }
    if len(identities) > 1:
        raise RuntimeError(f"conflicting source locators for {run_key}")
    return usable[0] if usable else None


def download_source(locator: dict[str, Any], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "gh",
            "run",
            "download",
            str(locator["source_actions_run_id"]),
            "--name",
            str(locator["source_artifact_name"]),
            "--dir",
            str(destination),
        ],
        check=True,
        cwd=ROOT,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replication-state-dir", action="append", required=True)
    parser.add_argument("--original-source-root", action="append", required=True)
    parser.add_argument("--replication-source-root", action="append", required=True)
    parser.add_argument("--locator-state-dir", action="append", default=[])
    parser.add_argument("--allow-one-time-github-source-download", action="store_true")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    output = Path(args.output_dir).resolve()
    state = output / "state"
    sources = output / "source_artifacts"
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("local structural output directory must be absent or empty")
    state.mkdir(parents=True, exist_ok=True)
    sources.mkdir(parents=True, exist_ok=True)

    manager = load_script("manage_scaling_paradox_campaign.py")
    executor = read_json(ROOT / "configs/experiments/frontier_adaptation_v2_executor.json")
    plans = manager.build_plans(executor)
    imported = manager.import_external_completion_handoff(
        executor=executor, plans=plans, state_dir=state
    )
    if imported != {"training": 48, "evaluation": 48}:
        raise RuntimeError("original completion handoff did not import exactly 48+48 receipts")

    replication_states = [Path(value).resolve() for value in args.replication_state_dir]
    replication_plan = plans[("replication", "core")]
    for entry in replication_plan["runs"]:
        run_key = str(entry["run_key"])
        for kind in ("training", "evaluation"):
            receipt, source_path = receipt_from_states(
                replication_states, kind=kind, run_key=run_key
            )
            validate_receipt(
                receipt,
                campaign_id=str(replication_plan["campaign_id"]),
                run_key=run_key,
                contract_sha=str(entry["run_contract_sha"]),
                kind=kind,
            )
            destination = state / "receipts" / kind / source_path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)

    roots = {
        "original": [Path(value).resolve() for value in args.original_source_root],
        "replication": [Path(value).resolve() for value in args.replication_source_root],
    }
    locator_states = [Path(value).resolve() for value in args.locator_state_dir]
    source_records: list[dict[str, Any]] = []
    github_downloads = 0
    for cohort in ("original", "replication"):
        plan = plans[(cohort, "core")]
        for entry in plan["runs"]:
            run_key = str(entry["run_key"])
            receipt = read_json(state / "receipts" / "training" / f"{run_key}.json")
            found = None
            for root in [*roots[cohort], sources / cohort]:
                candidate = locate_source(root, run_key)
                if candidate is not None:
                    if found is not None:
                        first = {name: sha256_file(path) for name, path in found.items()}
                        second = {name: sha256_file(path) for name, path in candidate.items()}
                        if first != second:
                            raise RuntimeError(f"conflicting source artifacts for {run_key}")
                    found = candidate
            if found is None:
                locator = locator_receipt(locator_states, run_key)
                if locator is None or not args.allow_one_time_github_source_download:
                    raise RuntimeError(f"source artifact is absent for {run_key}")
                download_root = sources / cohort / run_key
                download_source(locator, download_root)
                github_downloads += 1
                found = locate_source(download_root, run_key)
                if found is None:
                    nested = {
                        name: matches[0]
                        for name in SOURCE_FILES
                        if len(matches := list(download_root.rglob(name))) == 1
                    }
                    found = nested if len(nested) == len(SOURCE_FILES) else None
            if found is None:
                raise RuntimeError(f"downloaded source artifact is incomplete for {run_key}")
            destination = sources / cohort / run_key
            destination.mkdir(parents=True, exist_ok=True)
            hashes = {}
            for name, receipt_key in SOURCE_FILES.items():
                observed = sha256_file(found[name])
                if observed != receipt[receipt_key]:
                    raise RuntimeError(f"{name} hash mismatch for {run_key}")
                target = destination / name
                if found[name].resolve() != target.resolve():
                    shutil.copy2(found[name], target)
                hashes[name] = observed
            source_records.append(
                {"cohort": cohort, "run_key": run_key, "files": hashes}
            )

    manifest_path = output / "structural_manifest.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_frontier_adaptation_structural_manifest.py"),
            "--state-dir",
            str(state),
            "--output",
            str(manifest_path),
        ],
        check=True,
        cwd=ROOT,
    )
    manifest = read_json(manifest_path)
    packet = {
        "contract": "pearl.frontier-local-structural-authority/1",
        "action": "ready_no_launch",
        "structural_manifest_sha": manifest["structural_manifest_sha"],
        "structural_manifest_file_sha256": sha256_file(manifest_path),
        "source_commit_sha": manifest["source_commit_sha"],
        "original_terminal_cells": 48,
        "replication_terminal_cells": 48,
        "source_artifact_cells": len(source_records),
        "github_source_downloads": github_downloads,
        "github_history_replayed": False,
        "paid_execution_started": False,
        "scientific_contract_changes": [],
        "source_records_sha256": sha256_value(source_records),
    }
    packet["packet_sha256"] = sha256_value(packet)
    write_json(output / "authority_packet.json", packet)
    print(json.dumps(packet, indent=2))


if __name__ == "__main__":
    main()
