#!/usr/bin/env python3
"""Build, audit, and advance the frozen scaling-paradox campaign without discretionary choices."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.scaling_campaign import (  # noqa: E402
    audit_evaluation_artifact,
    audit_training_artifact,
    read_json,
    sha256_file,
    sha256_value,
    write_json,
)
from pearl.tinker_dpo import pair_rows_fingerprint  # noqa: E402


DEFAULT_EXECUTOR = ROOT / "configs" / "experiments" / "scaling_paradox_executor_v1.json"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_launcher() -> Any:
    path = ROOT / "scripts" / "launch_scaling_paradox_v1.py"
    spec = importlib.util.spec_from_file_location("scaling_paradox_launcher", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the scaling-paradox launcher")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_plans(executor: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    launcher = load_launcher()
    plans: dict[tuple[str, str], dict[str, Any]] = {}
    for campaign_name, campaign in executor["campaigns"].items():
        config = read_json(repo_path(campaign["config"]))
        manifest = read_json(repo_path(config["dataset_manifest"]))
        for stage_name, stage in campaign["stages"].items():
            plan = launcher.build_plan(config, manifest, stage_name)
            if plan["launch_plan_contract_sha"] != stage["plan_sha"]:
                raise RuntimeError(f"{campaign_name}:{stage_name} plan SHA mismatch")
            if int(plan["run_count"]) != int(stage["run_count"]):
                raise RuntimeError(f"{campaign_name}:{stage_name} run count mismatch")
            if float(plan["estimated_stage_cost_usd"]) != float(stage["estimated_cost_usd"]):
                raise RuntimeError(f"{campaign_name}:{stage_name} cost mismatch")
            plans[(campaign_name, stage_name)] = plan
    return plans


def build_manifest(executor: dict[str, Any]) -> dict[str, Any]:
    plans = build_plans(executor)
    launcher = load_launcher()
    phases: list[dict[str, Any]] = []
    for phase_index, phase_name in enumerate(executor["stage_order"], start=1):
        campaign_name, stage_name = phase_name.split(":", 1)
        campaign = executor["campaigns"][campaign_name]
        stage = campaign["stages"][stage_name]
        plan = plans[(campaign_name, stage_name)]
        by_order = {int(row["execution_order"]): row for row in plan["runs"]}
        waves: list[dict[str, Any]] = []
        for wave_index, orders in enumerate(stage["waves"], start=1):
            rows = [by_order[int(order)] for order in orders]
            training_cost = round(
                sum(float(row["cost_estimate"]["estimated_training_cost_usd"]) for row in rows), 4
            )
            endpoint_cost = 0.0
            if stage.get("evaluation_required", True):
                for row in rows:
                    prices = launcher.TINKER_MODEL_PRICES[str(row["model"])]
                    for path_key in ("holdout_path", "challenge_path"):
                        partition_rows = launcher.load_jsonl(repo_path(row[path_key]))
                        endpoint_cost += float(
                            launcher.estimate_preference_evaluation_cost(
                                pair_rows=partition_rows,
                                prices=prices,
                                pair_count=len(partition_rows),
                                policy_count=2,
                            )["estimated_cost_usd"]
                        )
            endpoint_cost = round(endpoint_cost, 4)
            waves.append(
                {
                    "wave_index": wave_index,
                    "execution_orders": orders,
                    "run_keys": [row["run_key"] for row in rows],
                    "run_contract_shas": [row["run_contract_sha"] for row in rows],
                    "estimated_training_cost_usd": training_cost,
                    "estimated_checkpoint_evaluation_cost_usd": endpoint_cost,
                    "estimated_cost_usd": round(training_cost + endpoint_cost, 4),
                }
            )
        phases.append(
            {
                "phase_index": phase_index,
                "phase": phase_name,
                "campaign": campaign_name,
                "campaign_id": campaign["campaign_id"],
                "stage": stage_name,
                "workflow": campaign["workflow"],
                "workflow_name": campaign.get("workflow_name"),
                "artifact_prefix": campaign["artifact_prefix"],
                "evaluation_workflow": campaign.get(
                    "evaluation_workflow", "scaling-paradox-checkpoint-evaluation.yml"
                ),
                "evaluation_workflow_name": campaign.get(
                    "evaluation_workflow_name",
                    "Scaling paradox — one immutable checkpoint evaluation",
                ),
                "evaluation_artifact_prefix": campaign.get(
                    "evaluation_artifact_prefix", "scaling-paradox-evaluation-"
                ),
                "config": campaign["config"],
                "plan_dir": campaign["plan_dir"],
                "plan_sha": stage["plan_sha"],
                "conditional_gate": stage.get("conditional_gate"),
                "evaluation_required": stage.get("evaluation_required", True),
                "waves": waves,
            }
        )
    payload = {
        "contract": "pearl.scaling-paradox-campaign-manifest/1",
        "executor_contract": executor["contract"],
        "global_max_active_paid_cells": executor["global_max_active_paid_cells"],
        "max_authorized_tinker_usd": executor["max_authorized_tinker_usd"],
        "planned_training_ceiling_usd": executor["planned_training_ceiling_usd"],
        "planned_checkpoint_evaluation_ceiling_usd": executor[
            "planned_checkpoint_evaluation_ceiling_usd"
        ],
        "planned_pre_structural_tinker_ceiling_usd": executor[
            "planned_pre_structural_tinker_ceiling_usd"
        ],
        "supervisor_workflow_name": executor.get(
            "supervisor_workflow_name",
            "Scaling paradox campaign — validate and dispatch one exact wave",
        ),
        "phases": phases,
    }
    observed_training = round(
        sum(wave["estimated_training_cost_usd"] for phase in phases for wave in phase["waves"]), 2
    )
    observed_evaluation = round(
        sum(
            wave["estimated_checkpoint_evaluation_cost_usd"]
            for phase in phases
            for wave in phase["waves"]
        ),
        2,
    )
    if observed_training > float(executor["planned_training_ceiling_usd"]):
        raise RuntimeError("training plan exceeds the frozen training ceiling")
    if observed_evaluation > float(executor["planned_checkpoint_evaluation_ceiling_usd"]):
        raise RuntimeError("evaluation plan exceeds the frozen evaluation ceiling")
    if round(observed_training + observed_evaluation, 2) > float(
        executor["planned_pre_structural_tinker_ceiling_usd"]
    ):
        raise RuntimeError("pre-structural plan exceeds the frozen Tinker ceiling")
    if float(executor["planned_pre_structural_tinker_ceiling_usd"]) > float(
        executor["max_authorized_tinker_usd"]
    ):
        raise RuntimeError("frozen pre-structural ceiling exceeds the authorized Tinker envelope")
    payload["manifest_sha256"] = sha256_value(payload)
    return payload


def plan_entry(
    plans: dict[tuple[str, str], dict[str, Any]], campaign: str, stage: str, run_key: str
) -> dict[str, Any]:
    rows = [row for row in plans[(campaign, stage)]["runs"] if row["run_key"] == run_key]
    if len(rows) != 1:
        raise RuntimeError("run key is absent or non-unique in the frozen plan")
    return rows[0]


def partition_contracts(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    launcher = load_launcher()
    result: dict[str, dict[str, Any]] = {}
    for name, path_key in (("holdout", "holdout_path"), ("challenge", "challenge_path")):
        rows = launcher.load_jsonl(repo_path(entry[path_key]))
        result[name] = {
            "pair_count": len(rows),
            "pair_fingerprint": pair_rows_fingerprint(rows),
        }
    return result


def identify_plan_entry(
    plans: dict[tuple[str, str], dict[str, Any]], run_key: str
) -> tuple[str, str, dict[str, Any]]:
    matches = [
        (campaign, stage, row)
        for (campaign, stage), plan in plans.items()
        for row in plan["runs"]
        if row["run_key"] == run_key
    ]
    if len(matches) != 1:
        raise RuntimeError("run key is absent or non-unique across the frozen campaign")
    return matches[0]


def gh_json(command: list[str]) -> Any:
    result = subprocess.run(command, check=True, capture_output=True, text=True, cwd=ROOT)
    return json.loads(result.stdout)


def collect_actions_artifact(
    *,
    executor: dict[str, Any],
    plans: dict[tuple[str, str], dict[str, Any]],
    actions_run_id: int,
    state_dir: Path,
    kind: str,
) -> dict[str, Any] | None:
    run = gh_json(
        [
            "gh", "run", "view", str(actions_run_id),
            "--json", "status,conclusion,workflowName,headSha",
        ]
    )
    if run.get("status") != "completed":
        raise RuntimeError("Actions run is not terminal")
    if kind == "evaluation" and run.get("conclusion") != "success":
        raise RuntimeError("checkpoint-evaluation Actions run is not terminal-success")
    repository = gh_json(["gh", "repo", "view", "--json", "nameWithOwner"])["nameWithOwner"]
    artifacts = gh_json(
        ["gh", "api", f"repos/{repository}/actions/runs/{actions_run_id}/artifacts"]
    ).get("artifacts", [])
    training_prefixes = tuple(
        str(campaign["artifact_prefix"]) for campaign in executor["campaigns"].values()
    )
    evaluation_prefixes = tuple(
        str(campaign.get("evaluation_artifact_prefix", "scaling-paradox-evaluation-"))
        for campaign in executor["campaigns"].values()
    )
    if kind == "training":
        candidates = [
            row for row in artifacts
            if row.get("name", "").startswith(training_prefixes)
            and not row.get("name", "").startswith(evaluation_prefixes)
        ]
    else:
        candidates = [
            row for row in artifacts if row.get("name", "").startswith(evaluation_prefixes)
        ]
    if len(candidates) != 1 or candidates[0].get("expired"):
        raise RuntimeError("Actions run has no unique unexpired campaign artifact")
    artifact = candidates[0]
    with tempfile.TemporaryDirectory(prefix="pearl-scaling-collector-") as temporary:
        destination = Path(temporary)
        subprocess.run(
            [
                "gh", "run", "download", str(actions_run_id),
                "--name", str(artifact["name"]), "--dir", str(destination),
            ],
            check=True,
            cwd=ROOT,
        )
        if kind == "training":
            contracts = list(destination.rglob("run_contract.json"))
            if not contracts:
                return None
            if len(contracts) != 1:
                raise RuntimeError("training artifact has a non-unique run contract")
            observed = read_json(contracts[0])
            run_key = str(observed.get("run_key") or "")
            campaign, stage, entry = identify_plan_entry(plans, run_key)
            artifact_root = contracts[0].parent
        else:
            reports = list(destination.rglob("evaluation_report.json"))
            if not reports:
                return None
            if len(reports) != 1:
                raise RuntimeError("evaluation artifact has a non-unique evaluation report")
            observed = read_json(reports[0])
            run_key = str((observed.get("contract") or {}).get("source_run_key") or "")
            campaign, stage, entry = identify_plan_entry(plans, run_key)
            artifact_root = reports[0].parent
        write_json(
            submission_path(state_dir, kind, run_key),
            {
                "contract": "pearl.scaling-paradox-submission/1",
                "kind": kind,
                "campaign": campaign,
                "stage": stage,
                "run_key": run_key,
                "source_actions_run_id": actions_run_id,
                "source_artifact_id": int(artifact["id"]),
                "source_commit_sha": run["headSha"],
            },
        )
        legacy = executor.get("legacy_original_core_actions_runs", {})
        if str(actions_run_id) in legacy:
            legacy_claim = legacy[str(actions_run_id)]
            if kind != "training" or campaign != "original" or stage != "core":
                raise RuntimeError("legacy Actions allowlist was used outside original core training")
            if run["headSha"] != legacy_claim["head_sha"]:
                raise RuntimeError("legacy Actions run has the wrong approved source commit")
            if run_key != legacy_claim["run_key"]:
                raise RuntimeError("legacy Actions run has the wrong approved run key")
        else:
            auth_path = artifact_root / "worker_authorization_receipt.json"
            if not auth_path.is_file():
                raise RuntimeError("future worker artifact lacks its supervisor authorization receipt")
            worker_auth = read_json(auth_path)
            supplied = worker_auth.get("receipt_sha256")
            if supplied != sha256_value(
                {key: value for key, value in worker_auth.items() if key != "receipt_sha256"}
            ):
                raise RuntimeError("worker authorization receipt hash mismatch")
            expected_action = "dispatch_training_wave" if kind == "training" else "dispatch_evaluation_wave"
            expected_auth = {
                "action": expected_action,
                "campaign": campaign,
                "stage": stage,
                "run_key": run_key,
                "plan_sha": plans[(campaign, stage)]["launch_plan_contract_sha"],
                "source_commit_sha": run["headSha"],
            }
            if any(worker_auth.get(key) != value for key, value in expected_auth.items()):
                raise RuntimeError("worker authorization receipt differs from the collected cell")
            if kind == "evaluation":
                training_evidence = read_json(receipt_path(state_dir, "training", run_key))
                if worker_auth.get("source_training_actions_run_id") != training_evidence.get(
                    "source_actions_run_id"
                ):
                    raise RuntimeError("evaluation worker used the wrong training Actions source")
            supervisor_id = int(worker_auth.get("supervisor_run_id", -1))
            supervisor = gh_json(
                [
                    "gh", "run", "view", str(supervisor_id),
                    "--json", "status,conclusion,workflowName,headSha",
                ]
            )
            if (
                supervisor.get("workflowName")
                != executor.get(
                    "supervisor_workflow_name",
                    "Scaling paradox campaign — validate and dispatch one exact wave",
                )
                or supervisor.get("headSha") != run["headSha"]
                or supervisor.get("status") != "completed"
                or supervisor.get("conclusion") != "success"
            ):
                raise RuntimeError("worker is not bound to a successful matching supervisor")
        if kind == "training":
            receipt = audit_training_artifact(
                plan_entry=entry,
                run_dir=artifact_root,
                source_actions_run_id=actions_run_id,
            )
        else:
            receipt = audit_evaluation_artifact(
                plan_entry=entry,
                evaluation_dir=artifact_root,
                training_receipt=read_json(receipt_path(state_dir, "training", run_key)),
                partition_contracts=partition_contracts(entry),
                source_actions_run_id=actions_run_id,
            )
    campaign_contract = executor["campaigns"][campaign]
    fallback_training_names = {
        "original": "Scaling paradox v1 — one immutable run",
        "replication": "Scaling paradox v1 replication — one immutable run",
    }
    expected_workflow = (
        campaign_contract.get("workflow_name", fallback_training_names[campaign])
        if kind == "training"
        else campaign_contract.get(
            "evaluation_workflow_name",
            "Scaling paradox — one immutable checkpoint evaluation",
        )
    )
    if run.get("workflowName") != expected_workflow:
        raise RuntimeError("Actions workflow identity differs from the frozen campaign")
    expected_prefix = (
        campaign_contract["artifact_prefix"]
        if kind == "training"
        else campaign_contract.get("evaluation_artifact_prefix", "scaling-paradox-evaluation-")
    )
    if artifact["name"] != f"{expected_prefix}{run_key}":
        raise RuntimeError("Actions artifact name differs from the frozen campaign")
    receipt["source_artifact_id"] = int(artifact["id"])
    receipt["source_artifact_name"] = artifact["name"]
    receipt["source_commit_sha"] = run["headSha"]
    receipt["source_actions_conclusion"] = run.get("conclusion")
    receipt["receipt_sha256"] = sha256_value({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    existing_owner = receipt_path(state_dir, kind, run_key)
    if existing_owner.is_file():
        prior = read_json(existing_owner)
        if int(prior.get("source_actions_run_id", -1)) != actions_run_id:
            raise RuntimeError("run key already has a different Actions owner")
    write_json(existing_owner, receipt)
    write_json(
        state_dir / "actions_runs" / kind / f"{actions_run_id}.json",
        {"actions_run_id": actions_run_id, "run_key": run_key, "receipt_sha256": receipt["receipt_sha256"]},
    )
    return receipt


def sync_github_state(
    *, executor: dict[str, Any], plans: dict[tuple[str, str], dict[str, Any]], state_dir: Path
) -> dict[str, int]:
    workflows = {
        "training": tuple(dict.fromkeys(
            str(campaign["workflow"]) for campaign in executor["campaigns"].values()
        )),
        "evaluation": tuple(dict.fromkeys(
            str(campaign.get("evaluation_workflow", "scaling-paradox-checkpoint-evaluation.yml"))
            for campaign in executor["campaigns"].values()
        )),
    }
    counts = {"training": 0, "evaluation": 0}
    legacy = {int(value) for value in executor.get("legacy_original_core_actions_runs", {})}
    for kind, names in workflows.items():
        for workflow in names:
            result = subprocess.run(
                [
                    "gh", "run", "list", "--workflow", workflow, "--limit", "500",
                    "--json", "databaseId,status,displayTitle",
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            if result.returncode != 0:
                if kind == "evaluation" and "not found" in result.stderr.lower():
                    continue
                raise RuntimeError(f"could not enumerate {workflow}: {result.stderr.strip()}")
            for row in json.loads(result.stdout):
                run_id = int(row["databaseId"])
                if row.get("status") != "completed":
                    continue
                if (state_dir / "actions_runs" / kind / f"{run_id}.json").is_file():
                    continue
                title = str(row.get("displayTitle") or "")
                is_paid_worker = run_id in legacy or (
                    "supervisor-" in title and "supervisor-validate" not in title
                )
                if kind == "training" and not is_paid_worker:
                    continue
                receipt = collect_actions_artifact(
                    executor=executor,
                    plans=plans,
                    actions_run_id=run_id,
                    state_dir=state_dir,
                    kind=kind,
                )
                if receipt is None:
                    raise RuntimeError(f"paid {kind} run {run_id} has no auditable campaign artifact")
                counts[kind] += 1
    return counts


def receipt_path(state_dir: Path, kind: str, run_key: str) -> Path:
    return state_dir / "receipts" / kind / f"{run_key}.json"


def submission_path(state_dir: Path, kind: str, run_key: str) -> Path:
    return state_dir / "submissions" / kind / f"{run_key}.json"


def authorization_claim_path(state_dir: Path, kind: str, run_key: str) -> Path:
    return state_dir / "authorization_claims" / kind / f"{run_key}.json"


def load_valid_receipt(path: Path, *, run_key: str, field: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    receipt = read_json(path)
    if receipt.get("run_key") != run_key or not receipt.get(field):
        raise RuntimeError(f"invalid receipt: {path}")
    return receipt


def validate_rescue_gate(
    *, manifest: dict[str, Any], state_dir: Path, rescue_gate: dict[str, Any]
) -> None:
    if rescue_gate.get("contract") != "pearl.scaling-paradox-adapter-rescue-gate/1":
        raise RuntimeError("conditional gate receipt has the wrong contract")
    supplied_sha = rescue_gate.get("gate_sha256")
    unsigned = {key: value for key, value in rescue_gate.items() if key != "gate_sha256"}
    if supplied_sha != sha256_value(unsigned):
        raise RuntimeError("conditional gate receipt hash mismatch")
    if int(rescue_gate.get("complete_matrix_cell_count", -1)) != 36:
        raise RuntimeError("conditional gate is not bound to the complete core matrix")
    if len(rescue_gate.get("evaluation_report_sha256s", [])) != 36:
        raise RuntimeError("conditional gate lacks 36 evaluation report hashes")
    if rescue_gate.get("analyzer_sha256") != sha256_file(
        ROOT / "scripts/analyze_scaling_paradox_optimization.py"
    ):
        raise RuntimeError("conditional gate used the wrong frozen analyzer")
    if rescue_gate.get("executor_config_sha256") != sha256_file(DEFAULT_EXECUTOR):
        raise RuntimeError("conditional gate used the wrong executor contract")
    core_phases = {
        phase["campaign"]: phase
        for phase in manifest["phases"]
        if phase["stage"] == "core"
    }
    if rescue_gate.get("original_core_plan_sha") != core_phases["original"]["plan_sha"]:
        raise RuntimeError("conditional gate has the wrong original core plan SHA")
    if rescue_gate.get("replication_core_plan_sha") != core_phases["replication"]["plan_sha"]:
        raise RuntimeError("conditional gate has the wrong replication core plan SHA")
    expected_hashes: list[str] = []
    for phase in core_phases.values():
        for wave in phase["waves"]:
            for run_key in wave["run_keys"]:
                receipt = load_valid_receipt(
                    receipt_path(state_dir, "evaluation", run_key),
                    run_key=run_key,
                    field="evaluation_terminal_valid",
                )
                if receipt is None:
                    raise RuntimeError("conditional gate precedes a core evaluation receipt")
                expected_hashes.append(str(receipt["evaluation_report_file_sha256"]))
    if sorted(rescue_gate["evaluation_report_sha256s"]) != sorted(expected_hashes):
        raise RuntimeError("conditional gate evidence differs from collected core evaluations")


def phase_is_skipped(phase: dict[str, Any], rescue_gate: dict[str, Any] | None) -> bool:
    if not phase.get("conditional_gate"):
        return False
    if rescue_gate is None:
        return False
    if rescue_gate.get("gate_id") != phase["conditional_gate"]:
        raise RuntimeError("conditional gate receipt has the wrong gate ID")
    return not bool(rescue_gate.get("pass"))


def next_authorization(
    *, manifest: dict[str, Any], state_dir: Path, active_paid_cells: int
) -> dict[str, Any]:
    maximum = int(manifest["global_max_active_paid_cells"])
    if active_paid_cells < 0 or active_paid_cells > maximum:
        raise RuntimeError("active paid cell count is invalid or exceeds the global cap")
    gate_path = state_dir / "analysis" / "adapter_rescue_gate.json"
    rescue_gate = read_json(gate_path) if gate_path.is_file() else None
    if rescue_gate is not None:
        validate_rescue_gate(manifest=manifest, state_dir=state_dir, rescue_gate=rescue_gate)
    for phase in manifest["phases"]:
        if phase_is_skipped(phase, rescue_gate):
            continue
        if phase.get("conditional_gate") and rescue_gate is None:
            return {
                "contract": "pearl.scaling-paradox-authorization/1",
                "action": "analyze_core",
                "reason": "frozen_adapter_rescue_gate_is_missing",
                "authorized_run_keys": [],
            }
        for wave in phase["waves"]:
            keys = list(wave["run_keys"])
            training = {
                key: load_valid_receipt(
                    receipt_path(state_dir, "training", key),
                    run_key=key,
                    field="training_terminal_valid",
                )
                for key in keys
            }
            missing_training = [key for key, value in training.items() if value is None]
            if missing_training:
                if active_paid_cells:
                    return {
                        "contract": "pearl.scaling-paradox-authorization/1",
                        "action": "wait",
                        "reason": "paid_cells_are_active",
                        "active_paid_cells": active_paid_cells,
                        "authorized_run_keys": [],
                    }
                already_submitted = [
                    key
                    for key in missing_training
                    if submission_path(state_dir, "training", key).is_file()
                    or authorization_claim_path(state_dir, "training", key).is_file()
                ]
                if already_submitted:
                    raise RuntimeError(
                        "submitted training cells lack terminal receipts; resume or escalation is required: "
                        + ", ".join(already_submitted)
                    )
                if len(missing_training) != len(keys):
                    raise RuntimeError("partially observed wave cannot be redispatched")
                authorization = {
                    "contract": "pearl.scaling-paradox-authorization/1",
                    "action": "dispatch_training_wave",
                    "phase": phase["phase"],
                    "wave_index": wave["wave_index"],
                    "campaign": phase["campaign"],
                    "stage": phase["stage"],
                    "workflow": phase["workflow"],
                    "config": phase["config"],
                    "plan_dir": phase["plan_dir"],
                    "plan_sha": phase["plan_sha"],
                    "authorized_run_keys": missing_training,
                    "estimated_cost_usd": wave["estimated_training_cost_usd"],
                    "max_active_after_dispatch": len(missing_training),
                }
                authorization["authorization_sha256"] = sha256_value(authorization)
                return authorization
            evaluation = {
                key: load_valid_receipt(
                    receipt_path(state_dir, "evaluation", key),
                    run_key=key,
                    field="evaluation_terminal_valid",
                )
                for key in keys
            }
            if not phase.get("evaluation_required", True):
                continue
            missing_evaluation = [key for key, value in evaluation.items() if value is None]
            if missing_evaluation:
                if active_paid_cells:
                    return {
                        "contract": "pearl.scaling-paradox-authorization/1",
                        "action": "wait",
                        "reason": "paid_cells_are_active",
                        "active_paid_cells": active_paid_cells,
                        "authorized_run_keys": [],
                    }
                if active_paid_cells + len(missing_evaluation) > maximum:
                    return {
                        "contract": "pearl.scaling-paradox-authorization/1",
                        "action": "wait",
                        "reason": "evaluation_wave_would_exceed_global_cap",
                        "active_paid_cells": active_paid_cells,
                        "authorized_run_keys": [],
                    }
                already_submitted = [
                    key
                    for key in missing_evaluation
                    if submission_path(state_dir, "evaluation", key).is_file()
                    or authorization_claim_path(state_dir, "evaluation", key).is_file()
                ]
                if already_submitted:
                    raise RuntimeError(
                        "submitted evaluation cells lack terminal receipts; escalation is required: "
                        + ", ".join(already_submitted)
                    )
                source_run_ids = {
                    key: training[key].get("source_actions_run_id") for key in missing_evaluation
                }
                if any(not isinstance(value, int) or value <= 0 for value in source_run_ids.values()):
                    raise RuntimeError("evaluation dispatch requires source Actions run IDs in training receipts")
                authorization = {
                    "contract": "pearl.scaling-paradox-authorization/1",
                    "action": "dispatch_evaluation_wave",
                    "phase": phase["phase"],
                    "wave_index": wave["wave_index"],
                    "campaign": phase["campaign"],
                    "stage": phase["stage"],
                    "workflow": phase["evaluation_workflow"],
                    "source_workflow": phase["workflow"],
                    "plan_sha": phase["plan_sha"],
                    "authorized_run_keys": missing_evaluation,
                    "source_actions_run_ids": source_run_ids,
                    "source_artifact_prefix": phase["artifact_prefix"],
                    "estimated_cost_usd": wave["estimated_checkpoint_evaluation_cost_usd"],
                    "max_active_after_dispatch": len(missing_evaluation),
                }
                authorization["authorization_sha256"] = sha256_value(authorization)
                return authorization
    return {
        "contract": "pearl.scaling-paradox-authorization/1",
        "action": "training_and_checkpoint_evaluation_complete",
        "authorized_run_keys": [],
    }


def manifest_artifact_prefix(manifest: dict[str, Any], campaign: str) -> str:
    prefixes = {
        phase["artifact_prefix"]
        for phase in manifest["phases"]
        if phase["campaign"] == campaign
    }
    if len(prefixes) != 1:
        raise RuntimeError("unknown or ambiguous campaign artifact prefix")
    return prefixes.pop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor-config", default=str(DEFAULT_EXECUTOR))
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest_parser = subparsers.add_parser("write-manifest")
    manifest_parser.add_argument("--output", required=True)

    audit_training_parser = subparsers.add_parser("audit-training")
    audit_training_parser.add_argument("--campaign", choices=("original", "replication"), required=True)
    audit_training_parser.add_argument("--stage", required=True)
    audit_training_parser.add_argument("--run-key", required=True)
    audit_training_parser.add_argument("--run-dir", required=True)
    audit_training_parser.add_argument("--actions-run-id", type=int)
    audit_training_parser.add_argument("--output", required=True)

    audit_evaluation_parser = subparsers.add_parser("audit-evaluation")
    audit_evaluation_parser.add_argument("--campaign", choices=("original", "replication"), required=True)
    audit_evaluation_parser.add_argument("--stage", required=True)
    audit_evaluation_parser.add_argument("--run-key", required=True)
    audit_evaluation_parser.add_argument("--evaluation-dir", required=True)
    audit_evaluation_parser.add_argument("--training-receipt", required=True)
    audit_evaluation_parser.add_argument("--actions-run-id", type=int)
    audit_evaluation_parser.add_argument("--output", required=True)

    next_parser = subparsers.add_parser("next")
    next_parser.add_argument("--state-dir", required=True)
    next_parser.add_argument("--active-paid-cells", type=int, required=True)
    next_parser.add_argument("--output", required=True)

    for kind in ("training", "evaluation"):
        collect_parser = subparsers.add_parser(f"collect-{kind}")
        collect_parser.add_argument("--actions-run-id", type=int, required=True)
        collect_parser.add_argument("--state-dir", required=True)
    sync_parser = subparsers.add_parser("sync-github")
    sync_parser.add_argument("--state-dir", required=True)

    args = parser.parse_args()
    executor = read_json(repo_path(args.executor_config))
    plans = build_plans(executor)
    manifest = build_manifest(executor)
    if args.command == "write-manifest":
        write_json(repo_path(args.output), manifest)
    elif args.command == "audit-training":
        entry = plan_entry(plans, args.campaign, args.stage, args.run_key)
        receipt = audit_training_artifact(
            plan_entry=entry,
            run_dir=repo_path(args.run_dir),
            source_actions_run_id=args.actions_run_id,
        )
        write_json(repo_path(args.output), receipt)
    elif args.command == "audit-evaluation":
        entry = plan_entry(plans, args.campaign, args.stage, args.run_key)
        receipt = audit_evaluation_artifact(
            plan_entry=entry,
            evaluation_dir=repo_path(args.evaluation_dir),
            training_receipt=read_json(repo_path(args.training_receipt)),
            partition_contracts=partition_contracts(entry),
            source_actions_run_id=args.actions_run_id,
        )
        write_json(repo_path(args.output), receipt)
    elif args.command == "next":
        authorization = next_authorization(
            manifest=manifest,
            state_dir=repo_path(args.state_dir),
            active_paid_cells=args.active_paid_cells,
        )
        write_json(repo_path(args.output), authorization)
        if authorization["action"] in {"dispatch_training_wave", "dispatch_evaluation_wave"}:
            kind = "training" if authorization["action"] == "dispatch_training_wave" else "evaluation"
            for run_key in authorization["authorized_run_keys"]:
                write_json(
                    authorization_claim_path(repo_path(args.state_dir), kind, run_key),
                    {
                        "contract": "pearl.scaling-paradox-authorization-claim/1",
                        "kind": kind,
                        "run_key": run_key,
                        "authorization_sha256": authorization["authorization_sha256"],
                        "submitted": False,
                    },
                )
        print(json.dumps({"action": authorization["action"], "count": len(authorization["authorized_run_keys"])}))
    elif args.command.startswith("collect-"):
        kind = args.command.removeprefix("collect-")
        receipt = collect_actions_artifact(
            executor=executor,
            plans=plans,
            actions_run_id=args.actions_run_id,
            state_dir=repo_path(args.state_dir),
            kind=kind,
        )
        print(
            json.dumps(
                {"collected": kind, "run_key": receipt["run_key"] if receipt else None, "valid": bool(receipt)}
            )
        )
    else:
        counts = sync_github_state(
            executor=executor,
            plans=plans,
            state_dir=repo_path(args.state_dir),
        )
        print(json.dumps({"sync": "complete", **counts}))


if __name__ == "__main__":
    main()
