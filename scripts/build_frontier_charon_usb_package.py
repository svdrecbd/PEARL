#!/usr/bin/env python3
"""Build the minimal secret-free USB handoff after the replication sentinel hold."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.scaling_campaign import read_json, sha256_file, sha256_value, write_json  # noqa: E402


DEFAULT_EXECUTOR = ROOT / "configs" / "experiments" / "frontier_adaptation_v2_executor.json"
DATA_ARCHIVE = "pearl-scaling-paradox-v1-data-v2.tar.gz"
DATA_RELEASE_TAG = "scaling-paradox-v1-data-v2"
DATA_ARCHIVE_SHA256 = "ffad79ec8e104bf06979882e186290ea4d94b87531e48b111e954b6c09e8e962"


def load_script(name: str, filename: str) -> Any:
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        list(args),
        cwd=ROOT,
        check=True,
        capture_output=capture,
        text=True,
    )
    return result.stdout.strip() if capture else ""


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def build(args: argparse.Namespace) -> Path:
    manager = load_script("charon_package_manager", "manage_scaling_paradox_campaign.py")
    local = load_script("charon_package_local", "manage_frontier_local_wave.py")
    executor_path = Path(args.executor_config).resolve()
    executor = read_json(executor_path)
    plans = manager.build_plans(executor)
    plan = plans[("replication", "core")]
    ordered = [str(row["run_key"]) for row in plan["runs"]]
    sentinel = ordered[0]
    if len(ordered) != 48 or plan["launch_plan_contract_sha"] != (
        "85660f7b99193e34a546f9eb50dfe18ff10fe42d3127232686be9b5ee7fd2593"
    ):
        raise RuntimeError("USB package has the wrong frozen replication plan")
    source_commit = local.tracked_source_is_clean()
    branch = command("git", "branch", "--show-current", capture=True)
    if not branch:
        raise RuntimeError("USB package must be built from a named clean branch")
    if local.github_nonterminal_runs():
        raise RuntimeError("USB package cannot be built while GitHub frontier work is nonterminal")
    local.require_supervisor_disabled()

    hold_run_id = int(args.hold_supervisor_run_id)
    hold_run = manager.gh_json(
        ["gh", "run", "view", str(hold_run_id), "--json", "status,conclusion,workflowName,headSha"]
    )
    if (
        hold_run.get("status") != "completed"
        or hold_run.get("conclusion") != "success"
        or hold_run.get("workflowName") != executor["supervisor_workflow_name"]
        or hold_run.get("headSha") != source_commit
    ):
        raise RuntimeError("USB package hold run is not a successful matching supervisor")

    output = Path(args.output_dir).resolve()
    if output.exists():
        raise RuntimeError("USB package output already exists")
    output.mkdir(parents=True)
    try:
        with tempfile.TemporaryDirectory(prefix="pearl-charon-package-") as temporary:
            temporary_root = Path(temporary)
            state = temporary_root / "state"
            imported = manager.import_external_completion_handoff(
                executor=executor,
                plans=plans,
                state_dir=state,
            )
            if imported != {"training": 48, "evaluation": 48}:
                raise RuntimeError("USB package did not import the exact original 48/48 handoff")
            manager.sync_github_state(
                executor=executor,
                plans=plans,
                state_dir=state,
            )
            training_path = manager.receipt_path(state, "training", sentinel)
            evaluation_path = manager.receipt_path(state, "evaluation", sentinel)
            training = read_json(training_path)
            evaluation = read_json(evaluation_path)
            if (
                training.get("training_terminal_valid") is not True
                or evaluation.get("evaluation_terminal_valid") is not True
                or training.get("scientific_values_omitted") is not True
                or evaluation.get("scientific_values_omitted") is not True
                or evaluation.get("source_training_actions_run_id")
                != training.get("source_actions_run_id")
            ):
                raise RuntimeError("USB package sentinel evidence is not terminal-valid")
            post_sentinel_receipts = [
                key
                for key in ordered[1:]
                if manager.receipt_path(state, "training", key).is_file()
                or manager.receipt_path(state, "evaluation", key).is_file()
                or manager.continuation_path(state, key).is_file()
            ]
            if post_sentinel_receipts:
                raise RuntimeError("USB package observed post-sentinel replication evidence")

            hold_artifact_dir = temporary_root / "hold-artifact"
            command(
                "gh",
                "run",
                "download",
                str(hold_run_id),
                "--name",
                f"frontier-adaptation-v2-supervisor-state-{hold_run_id}",
                "--dir",
                str(hold_artifact_dir),
            )
            authorizations = list(hold_artifact_dir.rglob("authorization.json"))
            if len(authorizations) != 1:
                raise RuntimeError("USB package hold supervisor has no unique authorization")
            hold_authorization = read_json(authorizations[0])
            if (
                hold_authorization.get("action") != "wait"
                or hold_authorization.get("reason")
                != "replication_sentinel_complete_pending_charon_takeover"
                or hold_authorization.get("authorized_run_keys") != []
            ):
                raise RuntimeError("USB package supervisor is not at the Charon hold")

            source_spec = executor.get("external_completion_handoff") or {}
            source_path = Path(str(source_spec.get("path") or ""))
            if not source_path.is_absolute():
                source_path = ROOT / source_path
            if not source_path.is_file() or sha256_file(source_path) != source_spec.get("sha256"):
                raise RuntimeError("USB package original completion handoff is absent or changed")
            bootstrap = {
                "contract": "pearl.frontier-charon-bootstrap/1",
                "source_commit": source_commit,
                "original_completion_handoff_file_sha256": source_spec["sha256"],
                "replication_plan_sha": plan["launch_plan_contract_sha"],
                "replication_sentinel_run_key": sentinel,
                "sentinel_training_receipt_sha256": training["receipt_sha256"],
                "sentinel_evaluation_receipt_sha256": evaluation["receipt_sha256"],
                "hold_supervisor_actions_run_id": hold_run_id,
                "hold_authorization_sha256": sha256_value(hold_authorization),
                "post_sentinel_hold_reason": hold_authorization["reason"],
                "scientific_values_omitted": True,
                "analysis_authorized": False,
            }
            bootstrap["bootstrap_sha256"] = sha256_value(bootstrap)
            write_json(output / "bootstrap" / "charon_bootstrap.json", bootstrap)
            copy_file(training_path, output / "bootstrap" / "sentinel" / "training_receipt.json")
            copy_file(evaluation_path, output / "bootstrap" / "sentinel" / "evaluation_receipt.json")

        command("git", "bundle", "create", str(output / "pearl-frontier-charon.bundle"), branch)
        (output / "SOURCE_COMMIT").write_text(source_commit + "\n", encoding="utf-8")
        (output / "DATA_ARCHIVE_SHA256").write_text(DATA_ARCHIVE_SHA256 + "\n", encoding="utf-8")
        command(
            "curl",
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--retry",
            "5",
            "--retry-all-errors",
            "--output",
            str(output / DATA_ARCHIVE),
            f"https://github.com/svdrecbd/PEARL/releases/download/{DATA_RELEASE_TAG}/{DATA_ARCHIVE}",
        )
        if sha256_file(output / DATA_ARCHIVE) != DATA_ARCHIVE_SHA256:
            raise RuntimeError("USB package frozen dataset SHA mismatch")
        for filename in (
            "README.md",
            "provision-windows.ps1",
            "install-wsl.sh",
        ):
            copy_file(ROOT / "deploy" / "charon" / filename, output / filename)

        package_manifest = {
            "contract": "pearl.frontier-charon-usb-package/1",
            "source_commit": source_commit,
            "bootstrap_sha256": bootstrap["bootstrap_sha256"],
            "replication_plan_sha": plan["launch_plan_contract_sha"],
            "sentinel_run_key": sentinel,
            "secret_files_included": False,
            "analysis_authorized": False,
        }
        package_manifest["package_manifest_sha256"] = sha256_value(package_manifest)
        write_json(output / "PACKAGE_MANIFEST.json", package_manifest)
        checksums: list[str] = []
        for path in sorted(item for item in output.rglob("*") if item.is_file()):
            if path.name == "SHA256SUMS":
                continue
            checksums.append(f"{sha256_file(path)}  {path.relative_to(output).as_posix()}")
        (output / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor-config", default=str(DEFAULT_EXECUTOR))
    parser.add_argument("--hold-supervisor-run-id", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = build(args)
    print(json.dumps({"package": str(output), "sha256s": str(output / "SHA256SUMS")}, indent=2))


if __name__ == "__main__":
    main()
