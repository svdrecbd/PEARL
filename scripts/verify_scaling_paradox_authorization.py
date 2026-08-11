#!/usr/bin/env python3
"""Fail closed unless a worker invocation matches one supervisor authorization exactly."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.scaling_campaign import sha256_value  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", required=True)
    parser.add_argument("--supervisor-run-id", type=int, required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--plan-sha", required=True)
    parser.add_argument("--source-run-id", type=int)
    parser.add_argument(
        "--supervisor-workflow-name",
        default="Scaling paradox campaign — validate and dispatch one exact wave",
    )
    parser.add_argument("--receipt-output")
    args = parser.parse_args()

    if args.supervisor_run_id <= 0:
        raise SystemExit("paid execution requires a positive supervisor run ID")
    payload = json.loads(Path(args.authorization).read_text(encoding="utf-8"))
    supplied_sha = payload.pop("authorization_sha256", None)
    if supplied_sha != sha256_value(payload):
        raise SystemExit("supervisor authorization SHA mismatch")
    payload["authorization_sha256"] = supplied_sha
    expected = {
        "contract": "pearl.scaling-paradox-authorization/1",
        "action": args.action,
        "campaign": args.campaign,
        "stage": args.stage,
        "plan_sha": args.plan_sha,
    }
    mismatches = {
        key: (payload.get(key), value)
        for key, value in expected.items()
        if payload.get(key) != value
    }
    if mismatches:
        raise SystemExit(f"worker invocation differs from supervisor authorization: {mismatches}")
    if args.run_key not in payload.get("authorized_run_keys", []):
        raise SystemExit("run key is absent from supervisor authorization")
    if args.source_run_id is not None:
        source_ids = payload.get("source_actions_run_ids") or {}
        if source_ids.get(args.run_key) != args.source_run_id:
            raise SystemExit("source Actions run ID differs from supervisor authorization")

    token = os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GH_TOKEN is required to bind the supervisor source commit")
    result = subprocess.run(
        [
            "gh", "run", "view", str(args.supervisor_run_id),
            "--json", "headSha,workflowName,conclusion,status",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    supervisor = json.loads(result.stdout)
    if supervisor.get("workflowName") != args.supervisor_workflow_name:
        raise SystemExit("authorization did not come from the campaign supervisor")
    if supervisor.get("headSha") != os.environ.get("GITHUB_SHA"):
        raise SystemExit("worker and supervisor source commits differ")
    if supervisor.get("status") not in {"in_progress", "completed"}:
        raise SystemExit("supervisor run is not active or complete")
    if supervisor.get("status") == "completed" and supervisor.get("conclusion") != "success":
        raise SystemExit("supervisor did not complete successfully")
    receipt = {
        "contract": "pearl.scaling-paradox-worker-authorization/1",
        "authorization_sha256": supplied_sha,
        "supervisor_run_id": args.supervisor_run_id,
        "source_commit_sha": os.environ.get("GITHUB_SHA"),
        "action": args.action,
        "campaign": args.campaign,
        "stage": args.stage,
        "run_key": args.run_key,
        "plan_sha": args.plan_sha,
    }
    if args.source_run_id is not None:
        receipt["source_training_actions_run_id"] = args.source_run_id
    receipt["receipt_sha256"] = sha256_value(receipt)
    if args.receipt_output:
        path = Path(args.receipt_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"authorization": "valid", "run_key": args.run_key}))


if __name__ == "__main__":
    main()
