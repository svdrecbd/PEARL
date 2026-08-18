#!/usr/bin/env python3
"""Run one locally authorized frontier-v2 checkpoint evaluation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.scaling_campaign import read_json, sha256_file, sha256_value  # noqa: E402


def load_script(name: str, filename: str) -> Any:
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_authorization(path: Path, run_key: str) -> dict[str, Any]:
    authorization = read_json(path)
    unsigned = dict(authorization)
    observed = str(unsigned.pop("authorization_sha256", ""))
    if observed != sha256_value(unsigned):
        raise RuntimeError("evaluation authorization SHA is invalid")
    campaign = str(authorization.get("campaign") or "")
    expected_actions = {
        "original": "evaluate_missing_original_endpoints",
        "replication": "evaluate_charon_replication_endpoints",
    }
    if (
        authorization.get("contract") != "pearl.frontier-local-evaluation-authorization/1"
        or campaign not in expected_actions
        or authorization.get("action") != expected_actions.get(campaign)
        or authorization.get("stage") != "core"
        or run_key not in authorization.get("authorized_run_keys", [])
        or authorization.get("analysis_authorized") is not False
        or (
            campaign == "original"
            and authorization.get("replication_authorized") is not False
        )
        or (
            campaign == "replication"
            and authorization.get("replication_authorized") is not True
        )
    ):
        raise RuntimeError("evaluation is outside its bounded frontier authorization")
    expected_files = {
        "evaluator_sha256": ROOT / "scripts" / "evaluate_scaling_paradox_checkpoint.py",
        "evaluation_worker_sha256": Path(__file__).resolve(),
    }
    for field, source_path in expected_files.items():
        if authorization.get(field) != sha256_file(source_path):
            raise RuntimeError(f"authorized {field} differs from local source")
    return authorization


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--run-contract", required=True)
    parser.add_argument("--training-report", required=True)
    parser.add_argument("--checkpoint-lineage", required=True)
    parser.add_argument("--provider-json", required=True)
    parser.add_argument("--executor-config", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    authorization_path = Path(args.authorization).resolve()
    authorization = validate_authorization(authorization_path, args.run_key)
    contract = read_json(Path(args.run_contract).resolve())
    campaign_ids = {
        "original": "pearl-frontier-adaptation-v2-original",
        "replication": "pearl-frontier-adaptation-v2-replication",
    }
    if (
        contract.get("run_key") != args.run_key
        or contract.get("campaign_id") != campaign_ids[authorization["campaign"]]
        or contract.get("stage") != "core"
        or contract.get("run_contract_sha")
        != authorization["run_contract_shas"][args.run_key]
    ):
        raise RuntimeError("evaluation source differs from the frozen frontier plan")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    commands = [
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_scaling_paradox_provider.py"),
            "--run-contract",
            str(Path(args.run_contract).resolve()),
            "--checkpoint-lineage",
            str(Path(args.checkpoint_lineage).resolve()),
            "--executor-config",
            str(Path(args.executor_config).resolve()),
            "--provider-json",
            str(Path(args.provider_json).resolve()),
            "--output",
            str(output_dir / "provider_identity_receipt.json"),
        ],
        [
            sys.executable,
            str(ROOT / "scripts" / "evaluate_scaling_paradox_checkpoint.py"),
            "--run-contract",
            str(Path(args.run_contract).resolve()),
            "--training-report",
            str(Path(args.training_report).resolve()),
            "--output-dir",
            str(output_dir),
        ],
    ]
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)
    print(json.dumps({"status": "complete", "run_key": args.run_key}))


if __name__ == "__main__":
    main()
