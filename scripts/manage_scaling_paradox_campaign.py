#!/usr/bin/env python3
"""Build, audit, and advance the frozen scaling-paradox campaign without discretionary choices."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.scaling_campaign import (  # noqa: E402
    audit_evaluation_artifact,
    audit_training_continuation_artifact,
    audit_training_artifact,
    read_json,
    sha256_file,
    sha256_value,
    write_json,
)
from pearl.tinker_dpo import pair_rows_fingerprint  # noqa: E402


DEFAULT_EXECUTOR = ROOT / "configs" / "experiments" / "scaling_paradox_executor_v1.json"
TERMINAL_AFTER_RECONSTRUCTION_EXIT_CODE = 75


class TerminalAfterReconstructionError(RuntimeError):
    """A paid worker completed after the last authoritative artifact reconstruction."""


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
            if float(plan["estimated_stage_cost_usd"]) != float(
                stage["estimated_cost_usd"]
            ):
                raise RuntimeError(f"{campaign_name}:{stage_name} cost mismatch")
            plans[(campaign_name, stage_name)] = plan
    return plans


def import_external_completion_handoff(
    *,
    executor: dict[str, Any],
    plans: dict[tuple[str, str], dict[str, Any]],
    state_dir: Path,
) -> dict[str, int]:
    """Import one immutable, result-blind local completion handoff.

    The handoff is versioned with the supervisor source.  It contains only audited
    receipts and their hashes; endpoint values and reports are deliberately absent.
    Existing identical receipts are accepted, while any conflicting owner stops.
    """

    specification = executor.get("external_completion_handoff")
    if specification is None:
        return {"training": 0, "evaluation": 0}
    if specification.get("contract") != "pearl.frontier-external-completion-handoff-source/1":
        raise RuntimeError("external completion handoff source contract is unknown")
    handoff_path = repo_path(str(specification.get("path") or ""))
    if not handoff_path.is_file():
        raise RuntimeError("external completion handoff is absent")
    if sha256_file(handoff_path) != specification.get("sha256"):
        raise RuntimeError("external completion handoff file SHA mismatch")
    handoff = read_json(handoff_path)
    supplied_handoff_sha = str(handoff.get("handoff_sha256") or "")
    if supplied_handoff_sha != sha256_value(
        {key: value for key, value in handoff.items() if key != "handoff_sha256"}
    ):
        raise RuntimeError("external completion handoff canonical SHA mismatch")
    if handoff.get("contract") != "pearl.frontier-original-completion-handoff/1":
        raise RuntimeError("external completion handoff contract is unknown")

    plan = plans[("original", "core")]
    entries = {str(row["run_key"]): row for row in plan["runs"]}
    ordered_keys = [str(row["run_key"]) for row in plan["runs"]]
    if (
        handoff.get("campaign_id") != "pearl-frontier-adaptation-v2-original"
        or handoff.get("plan_sha") != plan["launch_plan_contract_sha"]
        or handoff.get("run_keys") != ordered_keys
        or handoff.get("scientific_values_omitted") is not True
        or handoff.get("replication_started") is not False
        or handoff.get("analysis_started") is not False
    ):
        raise RuntimeError("external completion handoff differs from the frozen original cohort")

    gate = handoff.get("completion_gate")
    if not isinstance(gate, dict):
        raise RuntimeError("external completion handoff lacks its completion gate")
    if gate.get("gate_sha256") != sha256_value(
        {key: value for key, value in gate.items() if key != "gate_sha256"}
    ):
        raise RuntimeError("external completion gate SHA mismatch")
    if (
        gate.get("contract") != "pearl.scaling-paradox-wave-gate/1"
        or gate.get("campaign_id") != handoff["campaign_id"]
        or gate.get("run_keys") != ordered_keys
        or gate.get("terminal_valid") is not True
        or gate.get("scientific_values_omitted") is not True
    ):
        raise RuntimeError("external completion gate differs from the frozen original cohort")

    imported: dict[str, int] = {"training": 0, "evaluation": 0}
    for kind, valid_field in (
        ("training", "training_terminal_valid"),
        ("evaluation", "evaluation_terminal_valid"),
    ):
        receipts = handoff.get(f"{kind}_receipts")
        if not isinstance(receipts, dict) or set(receipts) != set(ordered_keys):
            raise RuntimeError(f"external {kind} receipts do not exactly cover original core")
        gate_shas = gate[f"{kind}_receipt_shas"]
        if gate_shas != [receipts[key].get("receipt_sha256") for key in ordered_keys]:
            raise RuntimeError(f"external {kind} receipts differ from the completion gate")
        for run_key in ordered_keys:
            receipt = receipts[run_key]
            if not isinstance(receipt, dict):
                raise RuntimeError(f"external {kind} receipt has invalid shape")
            if receipt.get("receipt_sha256") != sha256_value(
                {key: value for key, value in receipt.items() if key != "receipt_sha256"}
            ):
                raise RuntimeError(f"external {kind} receipt SHA mismatch for {run_key}")
            expected = entries[run_key]
            if (
                receipt.get("run_key") != run_key
                or receipt.get("campaign_id") != handoff["campaign_id"]
                or receipt.get("run_contract_sha") != expected["run_contract_sha"]
                or receipt.get(valid_field) is not True
                or receipt.get("scientific_values_omitted") is not True
            ):
                raise RuntimeError(f"external {kind} receipt is invalid for {run_key}")
            destination = receipt_path(state_dir, kind, run_key)
            if destination.is_file():
                if read_json(destination) != receipt:
                    raise RuntimeError(f"external {kind} receipt conflicts with prior owner: {run_key}")
                continue
            write_json(destination, receipt)
            imported[kind] += 1
    return imported


def build_provider_snapshot(
    plans: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    launcher = load_launcher()
    expected = {
        (str(row["campaign_id"]), str(row["run_key"]), str(row["run_contract_sha"]))
        for plan in plans.values()
        for row in plan["runs"]
    }
    runs: list[dict[str, Any]] = []
    for row in launcher.provider_runs():
        metadata = row.get("user_metadata") or {}
        if metadata.get("pearl_task") != "physical_to_sequence_dpo":
            continue
        campaign_id = str(metadata.get("campaign_id") or "")
        if not campaign_id.startswith("pearl-frontier-adaptation-v2-"):
            continue
        identity = (
            campaign_id,
            str(metadata.get("run_key") or ""),
            str(metadata.get("contract_sha") or ""),
        )
        if identity not in expected:
            raise RuntimeError(
                "provider frontier DPO record is outside the frozen plans"
            )
        provider_id = row.get("id", row.get("run_id", row.get("training_run_id")))
        if provider_id in (None, ""):
            raise RuntimeError("provider frontier DPO record has no stable ID")
        corrupted = row.get("corrupted", row.get("is_corrupted"))
        if corrupted is not False:
            raise RuntimeError("provider frontier DPO record is corrupted or ambiguous")
        last_request_time = str(row.get("last_request_time") or "")
        parse_utc_timestamp(last_request_time, field="provider last-request time")
        runs.append(
            {
                "provider_training_run_id": str(provider_id),
                "campaign_id": campaign_id,
                "run_key": identity[1],
                "run_contract_sha": identity[2],
                "corrupted": False,
                "last_request_time": last_request_time,
            }
        )
    if len({row["provider_training_run_id"] for row in runs}) != len(runs):
        raise RuntimeError("provider frontier DPO snapshot has duplicate stable IDs")
    payload = {
        "contract": "pearl.frontier-provider-operational-snapshot/1",
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "scientific_values_omitted": True,
        "runs": sorted(
            runs,
            key=lambda row: (
                row["campaign_id"],
                row["run_key"],
                row["provider_training_run_id"],
            ),
        ),
    }
    payload["snapshot_sha256"] = sha256_value(payload)
    return payload


def validate_redundant_quarantine(
    executor: dict[str, Any], plans: dict[tuple[str, str], dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    claims = executor.get("redundant_training_continuation_quarantine", {})
    if not isinstance(claims, dict):
        raise RuntimeError("redundant continuation quarantine is malformed")
    provider_ids: set[str] = set()
    canonical_provider_ids: set[str] = set()
    canonical_ids: set[int] = set()
    result: dict[str, dict[str, Any]] = {}
    for actions_id_text, claim in claims.items():
        if not isinstance(claim, dict) or claim.get("contract") != (
            "pearl.frontier-redundant-continuation-quarantine/1"
        ):
            raise RuntimeError("redundant continuation quarantine contract is invalid")
        actions_id = int(actions_id_text)
        run_key = str(claim.get("run_key") or "")
        _, _, entry = identify_plan_entry(plans, run_key)
        canonical_id = int(claim.get("canonical_actions_run_id", 0))
        source_id = int(claim.get("expected_source_actions_run_id", 0))
        redundant_supervisor_id = int(claim.get("redundant_supervisor_run_id", 0))
        canonical_supervisor_id = int(claim.get("canonical_supervisor_run_id", 0))
        completed_steps = int(claim.get("expected_completed_steps", 0))
        source_completed_steps = int(
            claim.get("expected_source_completed_steps", 0)
        )
        provider_id = str(claim.get("redundant_provider_training_run_id") or "")
        canonical_provider_id = str(
            claim.get("canonical_provider_training_run_id") or ""
        )
        hashes = (
            str(claim.get("canonical_authorization_sha256") or ""),
            str(
                claim.get("canonical_worker_authorization_receipt_sha256") or ""
            ),
            str(claim.get("redundant_authorization_sha256") or ""),
            str(
                claim.get("redundant_worker_authorization_receipt_sha256") or ""
            ),
        )
        if (
            actions_id <= 0
            or canonical_id <= 0
            or source_id <= 0
            or redundant_supervisor_id <= 0
            or canonical_supervisor_id <= 0
            or actions_id == canonical_id
            or completed_steps <= 0
            or completed_steps >= int(entry["max_steps"])
            or source_completed_steps <= 0
            or source_completed_steps >= completed_steps
            or not provider_id
            or not canonical_provider_id
            or provider_id == canonical_provider_id
            or provider_id in provider_ids
            or canonical_provider_id in canonical_provider_ids
            or canonical_id in canonical_ids
            or not re.fullmatch(r"[0-9a-f]{40}", str(claim.get("head_sha") or ""))
            or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes)
            or float(claim.get("estimated_recovery_overhead_usd", -1.0)) < 0.0
        ):
            raise RuntimeError("redundant continuation quarantine identity is invalid")
        provider_ids.add(provider_id)
        canonical_provider_ids.add(canonical_provider_id)
        canonical_ids.add(canonical_id)
        result[actions_id_text] = claim
    return result


def validate_preauthorization_failure_quarantine(
    executor: dict[str, Any], plans: dict[tuple[str, str], dict[str, Any]]
) -> dict[int, dict[str, Any]]:
    group = executor.get("preauthorization_failure_quarantine")
    if group is None:
        return {}
    if not isinstance(group, dict) or group.get("contract") != (
        "pearl.frontier-preauthorization-failure-quarantine/1"
    ):
        raise RuntimeError("preauthorization failure quarantine contract is invalid")
    supervisor_id = int(group.get("source_supervisor_actions_run_id", 0))
    valid_child_id = int(group.get("valid_old_head_child_actions_run_id", 0))
    supervisor_head = str(group.get("source_supervisor_head_sha") or "")
    worker_head = str(group.get("worker_head_sha") or "")
    authorization_sha = str(group.get("source_authorization_sha256") or "")
    failed = group.get("failed_actions_runs")
    expected_steps = group.get("expected_step_conclusions")
    if (
        supervisor_id <= 0
        or valid_child_id <= 0
        or not re.fullmatch(r"[0-9a-f]{40}", supervisor_head)
        or not re.fullmatch(r"[0-9a-f]{40}", worker_head)
        or supervisor_head == worker_head
        or not re.fullmatch(r"[0-9a-f]{64}", authorization_sha)
        or not isinstance(failed, dict)
        or len(failed) != int(group.get("failed_child_count", -1))
        or not failed
        or not isinstance(expected_steps, dict)
        or expected_steps.get("Verify one-time supervisor authorization")
        != "failure"
        or expected_steps.get("Run one supervised Tinker cell") != "skipped"
        or not str(group.get("expected_failure_message") or "")
        or group.get("disposition")
        != "excluded_pre_authorization_shell_zero_spend_no_scientific_observation"
    ):
        raise RuntimeError("preauthorization failure quarantine identity is invalid")
    valid_run_key = str(group.get("valid_old_head_child_run_key") or "")
    identify_plan_entry(plans, valid_run_key)
    result: dict[int, dict[str, Any]] = {}
    run_keys: set[str] = set()
    for actions_id_text, run_key_value in failed.items():
        actions_id = int(actions_id_text)
        run_key = str(run_key_value or "")
        identify_plan_entry(plans, run_key)
        if (
            actions_id <= 0
            or actions_id == valid_child_id
            or actions_id in result
            or run_key == valid_run_key
            or run_key in run_keys
        ):
            raise RuntimeError(
                "preauthorization failure quarantine has a duplicate identity"
            )
        claim = dict(group)
        claim["actions_run_id"] = actions_id
        claim["run_key"] = run_key
        claim.pop("failed_actions_runs", None)
        result[actions_id] = claim
        run_keys.add(run_key)
    return result


def build_manifest(executor: dict[str, Any]) -> dict[str, Any]:
    plans = build_plans(executor)
    redundant_quarantine = validate_redundant_quarantine(executor, plans)
    preauthorization_quarantine = validate_preauthorization_failure_quarantine(
        executor, plans
    )
    launcher = load_launcher()
    phases: list[dict[str, Any]] = []
    for phase_index, phase_name in enumerate(executor["stage_order"], start=1):
        campaign_name, stage_name = phase_name.split(":", 1)
        campaign = executor["campaigns"][campaign_name]
        stage = campaign["stages"][stage_name]
        plan = plans[(campaign_name, stage_name)]
        scheduling = stage.get(
            "scheduling",
            {
                "contract": "pearl.scaling-paradox-scheduling/1",
                "mode": "strict_waves",
            },
        )
        if scheduling.get("contract") != "pearl.scaling-paradox-scheduling/1":
            raise RuntimeError(f"{phase_name} scheduling contract is unknown")
        if scheduling.get("mode") not in {"strict_waves", "rolling_ordered"}:
            raise RuntimeError(f"{phase_name} scheduling mode is unknown")
        if scheduling.get("mode") == "rolling_ordered":
            if not scheduling.get("preserve_execution_order"):
                raise RuntimeError(
                    f"{phase_name} rolling schedule does not preserve run order"
                )
            if scheduling.get("open_after_sentinel_evaluation") is not True:
                raise RuntimeError(
                    f"{phase_name} rolling schedule lacks the endpoint sentinel gate"
                )
            ramp = scheduling.get("capacity_ramp")
            if ramp is not None:
                if ramp.get("contract") != "pearl.frontier-capacity-ramp/1":
                    raise RuntimeError(
                        f"{phase_name} capacity-ramp contract is unknown"
                    )
                tiers = ramp.get("tiers")
                if not isinstance(tiers, list) or not tiers:
                    raise RuntimeError(f"{phase_name} capacity ramp has no tiers")
                limits = [int(row.get("max_active_cells", 0)) for row in tiers]
                if (
                    limits != sorted(set(limits))
                    or limits[0] <= 0
                    or limits[-1] != int(executor["global_max_active_paid_cells"])
                ):
                    raise RuntimeError(f"{phase_name} capacity-ramp tiers are invalid")
                for index, tier in enumerate(tiers):
                    if int(tier.get("minimum_started_cells", -1)) != (
                        0 if index == 0 else limits[index - 1]
                    ):
                        raise RuntimeError(
                            f"{phase_name} capacity-ramp started-cell gate is invalid"
                        )
                    if int(tier.get("observation_minutes", -1)) < 0:
                        raise RuntimeError(
                            f"{phase_name} capacity-ramp observation window is invalid"
                        )
        by_order = {int(row["execution_order"]): row for row in plan["runs"]}
        waves: list[dict[str, Any]] = []
        for wave_index, orders in enumerate(stage["waves"], start=1):
            rows = [by_order[int(order)] for order in orders]
            training_cost = round(
                sum(
                    float(row["cost_estimate"]["estimated_training_cost_usd"])
                    for row in rows
                ),
                4,
            )
            endpoint_cost_by_run_key: dict[str, float] = {}
            if stage.get("evaluation_required", True):
                for row in rows:
                    run_endpoint_cost = 0.0
                    prices = launcher.TINKER_MODEL_PRICES[str(row["model"])]
                    for path_key in ("holdout_path", "challenge_path"):
                        partition_rows = launcher.load_jsonl(repo_path(row[path_key]))
                        run_endpoint_cost += float(
                            launcher.estimate_preference_evaluation_cost(
                                pair_rows=partition_rows,
                                prices=prices,
                                pair_count=len(partition_rows),
                                policy_count=2,
                            )["estimated_cost_usd"]
                        )
                    endpoint_cost_by_run_key[str(row["run_key"])] = round(
                        run_endpoint_cost, 4
                    )
            else:
                endpoint_cost_by_run_key = {str(row["run_key"]): 0.0 for row in rows}
            endpoint_cost = round(sum(endpoint_cost_by_run_key.values()), 4)
            waves.append(
                {
                    "wave_index": wave_index,
                    "execution_orders": orders,
                    "run_keys": [row["run_key"] for row in rows],
                    "run_contract_shas": [row["run_contract_sha"] for row in rows],
                    "run_model_tags": {
                        row["run_key"]: row["model_tag"] for row in rows
                    },
                    "run_max_steps": {
                        row["run_key"]: int(row["max_steps"]) for row in rows
                    },
                    "estimated_training_cost_by_run_key": {
                        row["run_key"]: float(
                            row["cost_estimate"]["estimated_training_cost_usd"]
                        )
                        for row in rows
                    },
                    "estimated_checkpoint_evaluation_cost_by_run_key": endpoint_cost_by_run_key,
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
                "scheduling": scheduling,
                "waves": waves,
            }
        )
    observed_recovery_overhead = round(
        sum(
            float(row.get("estimated_recovery_overhead_usd", 0.0))
            for row in executor.get(
                "legacy_training_continuation_actions_runs", {}
            ).values()
        )
        + sum(
            float(row.get("estimated_recovery_overhead_usd", 0.0))
            for row in redundant_quarantine.values()
        ),
        4,
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
        "training_slicing": executor.get(
            "training_slicing",
            {
                "contract": "pearl.frontier-training-slicing/1",
                "scientific_contract_unchanged": True,
                "default": "terminal_in_one_worker",
                "model_overrides": {},
            },
        ),
        "max_continuation_recovery_overhead_usd": float(
            executor.get("max_continuation_recovery_overhead_usd", 0.0)
        ),
        "observed_continuation_recovery_overhead_usd": observed_recovery_overhead,
        "preauthorization_failure_quarantine_count": len(
            preauthorization_quarantine
        ),
        "planned_total_tinker_ceiling_usd": float(
            executor.get(
                "planned_total_tinker_ceiling_usd",
                executor["planned_pre_structural_tinker_ceiling_usd"],
            )
        ),
        "planned_total_with_recovery_ceiling_usd": float(
            executor.get(
                "planned_total_with_recovery_ceiling_usd",
                float(
                    executor.get(
                        "planned_total_tinker_ceiling_usd",
                        executor["planned_pre_structural_tinker_ceiling_usd"],
                    )
                )
                + float(executor.get("max_continuation_recovery_overhead_usd", 0.0)),
            )
        ),
        "supervisor_workflow_name": executor.get(
            "supervisor_workflow_name",
            "Scaling paradox campaign — validate and dispatch one exact wave",
        ),
        "phases": phases,
    }
    observed_training = round(
        sum(
            wave["estimated_training_cost_usd"]
            for phase in phases
            for wave in phase["waves"]
        ),
        2,
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
    if observed_evaluation > float(
        executor["planned_checkpoint_evaluation_ceiling_usd"]
    ):
        raise RuntimeError("evaluation plan exceeds the frozen evaluation ceiling")
    if round(observed_training + observed_evaluation, 2) > float(
        executor["planned_pre_structural_tinker_ceiling_usd"]
    ):
        raise RuntimeError("pre-structural plan exceeds the frozen Tinker ceiling")
    if float(executor["planned_pre_structural_tinker_ceiling_usd"]) > float(
        executor["max_authorized_tinker_usd"]
    ):
        raise RuntimeError(
            "frozen pre-structural ceiling exceeds the authorized Tinker envelope"
        )
    if float(payload["planned_total_with_recovery_ceiling_usd"]) > float(
        executor["max_authorized_tinker_usd"]
    ):
        raise RuntimeError(
            "continuation recovery ceiling exceeds the authorized Tinker envelope"
        )
    expected_recovery_total = round(
        float(payload["planned_total_tinker_ceiling_usd"])
        + float(payload["max_continuation_recovery_overhead_usd"]),
        2,
    )
    if expected_recovery_total != float(
        payload["planned_total_with_recovery_ceiling_usd"]
    ):
        raise RuntimeError(
            "continuation recovery total is inconsistent with the frozen ceilings"
        )
    if observed_recovery_overhead > float(
        payload["max_continuation_recovery_overhead_usd"]
    ):
        raise RuntimeError(
            "observed continuation recovery overhead exceeds its frozen allowance"
        )
    payload["manifest_sha256"] = sha256_value(payload)
    return payload


def plan_entry(
    plans: dict[tuple[str, str], dict[str, Any]],
    campaign: str,
    stage: str,
    run_key: str,
) -> dict[str, Any]:
    rows = [
        row for row in plans[(campaign, stage)]["runs"] if row["run_key"] == run_key
    ]
    if len(rows) != 1:
        raise RuntimeError("run key is absent or non-unique in the frozen plan")
    return rows[0]


def partition_contracts(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    launcher = load_launcher()
    result: dict[str, dict[str, Any]] = {}
    for name, path_key in (
        ("holdout", "holdout_path"),
        ("challenge", "challenge_path"),
    ):
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


def gh_json(command: list[str], *, max_attempts: int = 5) -> Any:
    """Run an approved read-only GitHub query with bounded retries."""
    read_only_prefixes = (
        ["gh", "api"],
        ["gh", "repo", "view"],
        ["gh", "run", "list"],
        ["gh", "run", "view"],
    )
    if not any(command[: len(prefix)] == prefix for prefix in read_only_prefixes):
        raise RuntimeError("gh_json refuses a command that is not an approved read")
    if command[:2] == ["gh", "api"]:
        method = "GET"
        for flag in ("--method", "-X"):
            if flag in command:
                method = command[command.index(flag) + 1].upper()
        has_fields = any(
            value in command for value in ("-f", "--raw-field", "-F", "--field")
        )
        if method != "GET" or (has_fields and "--method" not in command):
            raise RuntimeError("gh_json refuses a GitHub API mutation")
    if max_attempts <= 0:
        raise RuntimeError("gh_json requires at least one attempt")

    last_failure = "GitHub returned no result"
    for attempt in range(1, max_attempts + 1):
        result = subprocess.run(
            command, check=False, capture_output=True, text=True, cwd=ROOT
        )
        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                last_failure = f"GitHub returned invalid JSON: {exc}"
        else:
            detail = (result.stderr.strip() or result.stdout.strip())[:1000]
            last_failure = (
                f"GitHub read exited {result.returncode}"
                + (f": {detail}" if detail else "")
            )
        if attempt < max_attempts:
            time.sleep(2 ** (attempt - 1))
    raise RuntimeError(
        f"GitHub JSON read failed after {max_attempts} attempts: {last_failure}"
    )


def gh_run_download(command: list[str], *, max_attempts: int = 5) -> None:
    """Download an Actions run artifact with bounded retries."""
    if command[:3] != ["gh", "run", "download"]:
        raise RuntimeError("gh_run_download refuses a non-download command")
    if max_attempts <= 0:
        raise RuntimeError("gh_run_download requires at least one attempt")

    last_failure = "GitHub returned no result"
    for attempt in range(1, max_attempts + 1):
        result = subprocess.run(
            command, check=False, capture_output=True, text=True, cwd=ROOT
        )
        if result.returncode == 0:
            return
        detail = (result.stderr.strip() or result.stdout.strip())[:1000]
        last_failure = (
            f"GitHub artifact download exited {result.returncode}"
            + (f": {detail}" if detail else "")
        )
        if attempt < max_attempts:
            time.sleep(2 ** (attempt - 1))
    raise RuntimeError(
        f"GitHub artifact download failed after {max_attempts} attempts: {last_failure}"
    )


def dispatch_claim(
    *,
    action: str,
    campaign: str,
    stage: str,
    run_key: str,
    source_actions_run_id: int | None,
    segment_end_step: int | None,
) -> dict[str, Any]:
    payload = {
        "contract": "pearl.frontier-dispatch-claim/1",
        "action": action,
        "campaign": campaign,
        "stage": stage,
        "run_key": run_key,
        "source_actions_run_id": source_actions_run_id,
        "segment_end_step": segment_end_step,
    }
    payload["dispatch_claim_sha256"] = sha256_value(payload)
    return payload


def dispatch_claim_from_worker_auth(worker_auth: dict[str, Any]) -> dict[str, Any]:
    source_value = worker_auth.get("source_training_actions_run_id")
    segment_value = worker_auth.get("segment_end_step")
    return dispatch_claim(
        action=str(worker_auth["action"]),
        campaign=str(worker_auth["campaign"]),
        stage=str(worker_auth["stage"]),
        run_key=str(worker_auth["run_key"]),
        source_actions_run_id=(int(source_value) if source_value is not None else None),
        segment_end_step=(int(segment_value) if segment_value is not None else None),
    )


def attach_and_validate_dispatch_claims(
    state_dir: Path, authorization: dict[str, Any]
) -> None:
    action = str(authorization["action"])
    kind = "evaluation" if action == "dispatch_evaluation_wave" else "training"
    observed_claims: set[str] = set()
    actions_dir = state_dir / "actions_runs" / kind
    if actions_dir.is_dir():
        for path in actions_dir.glob("*.json"):
            marker = read_json(path)
            claim_sha = str(marker.get("dispatch_claim_sha256") or "")
            if claim_sha:
                observed_claims.add(claim_sha)
    claims: dict[str, dict[str, Any]] = {}
    for run_key in authorization["authorized_run_keys"]:
        source_value = (authorization.get("source_actions_run_ids") or {}).get(
            run_key
        )
        segment_value = (authorization.get("segment_end_steps") or {}).get(run_key)
        claim = dispatch_claim(
            action=action,
            campaign=str(authorization["campaign"]),
            stage=str(authorization["stage"]),
            run_key=str(run_key),
            source_actions_run_id=(
                int(source_value) if source_value is not None else None
            ),
            segment_end_step=(
                int(segment_value) if segment_value is not None else None
            ),
        )
        if claim["dispatch_claim_sha256"] in observed_claims:
            raise RuntimeError("semantic dispatch claim was already consumed")
        claims[str(run_key)] = claim
    authorization["dispatch_claims"] = claims


def quarantine_receipt_path(state_dir: Path, actions_run_id: int) -> Path:
    return state_dir / "quarantines" / "training" / f"{actions_run_id}.json"


def preauthorization_failure_receipt_path(
    state_dir: Path, actions_run_id: int
) -> Path:
    return (
        state_dir
        / "operational_failures"
        / "preauthorization"
        / f"{actions_run_id}.json"
    )


def audit_preauthorization_failure(
    *,
    state_dir: Path,
    actions_run_id: int,
    row: dict[str, Any],
    claim: dict[str, Any],
    kind: str,
) -> dict[str, Any]:
    run_key = str(claim["run_key"])
    supervisor_id = int(claim["source_supervisor_actions_run_id"])
    expected_title = f"Frontier train original {run_key} supervisor-{supervisor_id}"
    if (
        kind != "training"
        or int(row.get("databaseId", 0)) != actions_run_id
        or row.get("status") != "completed"
        or row.get("conclusion") != "failure"
        or row.get("headSha") != claim["worker_head_sha"]
        or row.get("displayTitle") != expected_title
    ):
        raise RuntimeError(
            f"preauthorization failure Actions identity differs: {actions_run_id}"
        )
    result = subprocess.run(
        [
            "gh",
            "run",
            "view",
            str(actions_run_id),
            "--json",
            "databaseId,status,conclusion,headSha,displayTitle,jobs",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"could not audit preauthorization failure {actions_run_id}"
        )
    detail = json.loads(result.stdout)
    if any(
        detail.get(key) != value
        for key, value in {
            "databaseId": actions_run_id,
            "status": "completed",
            "conclusion": "failure",
            "headSha": claim["worker_head_sha"],
            "displayTitle": expected_title,
        }.items()
    ):
        raise RuntimeError(
            f"preauthorization failure detail differs: {actions_run_id}"
        )
    jobs = detail.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != 1:
        raise RuntimeError(
            f"preauthorization failure has ambiguous jobs: {actions_run_id}"
        )
    job = jobs[0]
    if (
        job.get("name") != claim["expected_job_name"]
        or job.get("status") != "completed"
        or job.get("conclusion") != "failure"
    ):
        raise RuntimeError(
            f"preauthorization failure job identity differs: {actions_run_id}"
        )
    steps = job.get("steps")
    if not isinstance(steps, list):
        raise RuntimeError(
            f"preauthorization failure steps are unavailable: {actions_run_id}"
        )
    step_conclusions = {
        str(step.get("name") or ""): str(step.get("conclusion") or "")
        for step in steps
    }
    if any(
        step_conclusions.get(name) != conclusion
        for name, conclusion in claim["expected_step_conclusions"].items()
    ):
        raise RuntimeError(
            f"preauthorization failure crossed its zero-spend boundary: {actions_run_id}"
        )
    log_result = subprocess.run(
        ["gh", "run", "view", str(actions_run_id), "--log-failed"],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if (
        log_result.returncode != 0
        or claim["expected_failure_message"]
        not in (log_result.stdout + log_result.stderr)
    ):
        raise RuntimeError(
            f"preauthorization failure reason differs: {actions_run_id}"
        )
    receipt = {
        "contract": "pearl.frontier-preauthorization-failure-receipt/1",
        "actions_run_id": actions_run_id,
        "run_key": run_key,
        "source_supervisor_actions_run_id": supervisor_id,
        "source_supervisor_head_sha": claim["source_supervisor_head_sha"],
        "source_authorization_sha256": claim["source_authorization_sha256"],
        "worker_head_sha": claim["worker_head_sha"],
        "failed_step": "Verify one-time supervisor authorization",
        "failure_message": claim["expected_failure_message"],
        "provider_accessed": False,
        "training_started": False,
        "estimated_tinker_spend_usd": 0.0,
        "scientific_observation_created": False,
        "scientific_dispatch_claim_consumed": False,
        "disposition": claim["disposition"],
    }
    receipt["receipt_sha256"] = sha256_value(receipt)
    write_json(
        preauthorization_failure_receipt_path(state_dir, actions_run_id), receipt
    )
    write_json(
        state_dir / "actions_runs" / "training" / f"{actions_run_id}.json",
        {
            "actions_run_id": actions_run_id,
            "run_key": run_key,
            "preauthorization_failure_receipt_sha256": receipt["receipt_sha256"],
            "disposition": receipt["disposition"],
        },
    )
    return receipt


def lineage_provider_ids(receipt: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for checkpoint in receipt.get("checkpoint_lineage") or []:
        state_path = str(checkpoint.get("state_path") or "")
        if not state_path.startswith("tinker://") or "/weights/" not in state_path:
            raise RuntimeError("checkpoint lineage has an invalid provider state path")
        provider_id = state_path.removeprefix("tinker://").split("/weights/", 1)[0]
        if provider_id not in result:
            result.append(provider_id)
    if not result:
        raise RuntimeError("checkpoint lineage has no provider identity")
    return result


def provider_state_path_parts(checkpoint: dict[str, Any]) -> tuple[str, str]:
    state_path = str(checkpoint.get("state_path") or "")
    if not state_path.startswith("tinker://") or "/weights/" not in state_path:
        raise RuntimeError("checkpoint lineage has an invalid provider state path")
    provider_id, suffix = state_path.removeprefix("tinker://").split(
        "/weights/", 1
    )
    return provider_id, suffix


def quarantine_redundant_continuation(
    *,
    state_dir: Path,
    actions_run_id: int,
    claim: dict[str, Any],
    prior: dict[str, Any],
    receipt: dict[str, Any],
    worker_auth: dict[str, Any],
) -> None:
    if int(prior.get("source_actions_run_id", 0)) != int(
        claim["canonical_actions_run_id"]
    ):
        raise RuntimeError("redundant continuation canonical Actions owner differs")
    if int(receipt.get("completed_steps", -1)) != int(
        claim["expected_completed_steps"]
    ) or int(prior.get("completed_steps", -2)) != int(
        claim["expected_completed_steps"]
    ):
        raise RuntimeError("redundant continuation does not match the canonical boundary")
    prior_lineage = prior.get("checkpoint_lineage") or []
    redundant_lineage = receipt.get("checkpoint_lineage") or []
    source_marker_path = (
        state_dir
        / "actions_runs"
        / "training"
        / f"{int(claim['expected_source_actions_run_id'])}.json"
    )
    if not source_marker_path.is_file():
        raise RuntimeError("redundant continuation source lineage is unavailable")
    source_marker = read_json(source_marker_path)
    source_lineage = source_marker.get("checkpoint_lineage") or []
    source_last_step = int(source_lineage[-1].get("step", -1)) if source_lineage else -1
    if (
        source_marker.get("run_key") != receipt.get("run_key")
        or source_last_step != int(claim["expected_source_completed_steps"])
        or len(prior_lineage) != len(redundant_lineage)
        or len(source_lineage) >= len(prior_lineage)
        or prior_lineage[: len(source_lineage)] != source_lineage
        or redundant_lineage[: len(source_lineage)] != source_lineage
    ):
        raise RuntimeError("redundant continuation diverges before its final provider branch")
    canonical_provider_id = str(claim["canonical_provider_training_run_id"])
    quarantined_provider_id = str(claim["redundant_provider_training_run_id"])
    for canonical_checkpoint, redundant_checkpoint in zip(
        prior_lineage[len(source_lineage) :],
        redundant_lineage[len(source_lineage) :],
        strict=True,
    ):
        canonical_metadata = {
            key: value
            for key, value in canonical_checkpoint.items()
            if key != "state_path"
        }
        redundant_metadata = {
            key: value
            for key, value in redundant_checkpoint.items()
            if key != "state_path"
        }
        canonical_observed, canonical_suffix = provider_state_path_parts(
            canonical_checkpoint
        )
        redundant_observed, redundant_suffix = provider_state_path_parts(
            redundant_checkpoint
        )
        if (
            canonical_metadata != redundant_metadata
            or canonical_suffix != redundant_suffix
            or canonical_observed != canonical_provider_id
            or redundant_observed != quarantined_provider_id
            or bool(canonical_checkpoint.get("terminal"))
            or bool(redundant_checkpoint.get("terminal"))
        ):
            raise RuntimeError(
                "redundant continuation final provider branch is not equivalent"
            )
    prior_provider_ids = lineage_provider_ids(prior)
    redundant_provider_ids = lineage_provider_ids(receipt)
    if (
        quarantined_provider_id not in redundant_provider_ids
        or quarantined_provider_id in prior_provider_ids
        or canonical_provider_id not in prior_provider_ids
        or canonical_provider_id in redundant_provider_ids
        or set(redundant_provider_ids) - set(prior_provider_ids)
        != {quarantined_provider_id}
        or set(prior_provider_ids) - set(redundant_provider_ids)
        != {canonical_provider_id}
    ):
        raise RuntimeError("redundant continuation provider branch is not exact")
    quarantine = {
        "contract": "pearl.frontier-redundant-continuation-quarantine-receipt/1",
        "run_key": receipt["run_key"],
        "redundant_actions_run_id": actions_run_id,
        "canonical_actions_run_id": int(claim["canonical_actions_run_id"]),
        "source_actions_run_id": int(claim["expected_source_actions_run_id"]),
        "completed_steps": int(claim["expected_completed_steps"]),
        "redundant_provider_training_run_id": quarantined_provider_id,
        "canonical_receipt_sha256": prior["receipt_sha256"],
        "redundant_receipt_sha256": receipt["receipt_sha256"],
        "disposition": "excluded_operational_duplicate_not_a_replicate",
        "scientific_values_omitted": True,
    }
    quarantine["quarantine_sha256"] = sha256_value(quarantine)
    write_json(quarantine_receipt_path(state_dir, actions_run_id), quarantine)
    consumed_dispatch_claim = dispatch_claim_from_worker_auth(worker_auth)
    write_json(
        state_dir / "actions_runs" / "training" / f"{actions_run_id}.json",
        {
            "actions_run_id": actions_run_id,
            "run_key": receipt["run_key"],
            "receipt_sha256": receipt["receipt_sha256"],
            "checkpoint_lineage": receipt.get("checkpoint_lineage"),
            "disposition": quarantine["disposition"],
            "quarantine_sha256": quarantine["quarantine_sha256"],
            "dispatch_claim_sha256": consumed_dispatch_claim[
                "dispatch_claim_sha256"
            ],
        },
    )


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
            "gh",
            "run",
            "view",
            str(actions_run_id),
            "--json",
            "status,conclusion,workflowName,headSha",
        ]
    )
    if run.get("status") != "completed":
        raise RuntimeError("Actions run is not terminal")
    if kind == "evaluation" and run.get("conclusion") != "success":
        raise RuntimeError("checkpoint-evaluation Actions run is not terminal-success")
    repository = gh_json(["gh", "repo", "view", "--json", "nameWithOwner"])[
        "nameWithOwner"
    ]
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
            row
            for row in artifacts
            if row.get("name", "").startswith(training_prefixes)
            and not row.get("name", "").startswith(evaluation_prefixes)
        ]
    else:
        candidates = [
            row
            for row in artifacts
            if row.get("name", "").startswith(evaluation_prefixes)
        ]
    if len(candidates) != 1 or candidates[0].get("expired"):
        raise RuntimeError("Actions run has no unique unexpired campaign artifact")
    artifact = candidates[0]
    with tempfile.TemporaryDirectory(prefix="pearl-scaling-collector-") as temporary:
        destination = Path(temporary)
        gh_run_download(
            [
                "gh",
                "run",
                "download",
                str(actions_run_id),
                "--name",
                str(artifact["name"]),
                "--dir",
                str(destination),
            ]
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
                raise RuntimeError(
                    "evaluation artifact has a non-unique evaluation report"
                )
            observed = read_json(reports[0])
            run_key = str((observed.get("contract") or {}).get("source_run_key") or "")
            campaign, stage, entry = identify_plan_entry(plans, run_key)
            artifact_root = reports[0].parent
        legacy_continuation_claim = executor.get(
            "legacy_training_continuation_actions_runs", {}
        ).get(str(actions_run_id))
        redundant_continuation_claim = executor.get(
            "redundant_training_continuation_quarantine", {}
        ).get(str(actions_run_id))
        canonical_quarantine_claims = [
            claim
            for claim in executor.get(
                "redundant_training_continuation_quarantine", {}
            ).values()
            if int(claim.get("canonical_actions_run_id", 0)) == actions_run_id
        ]
        if len(canonical_quarantine_claims) > 1:
            raise RuntimeError("canonical continuation is claimed by multiple quarantines")
        canonical_quarantine_claim = (
            canonical_quarantine_claims[0] if canonical_quarantine_claims else None
        )
        if (
            legacy_continuation_claim is not None
            and redundant_continuation_claim is not None
        ):
            raise RuntimeError("continuation cannot be both legacy and redundant")
        special_continuation_claim = (
            redundant_continuation_claim or legacy_continuation_claim
        )
        if special_continuation_claim is not None:
            if kind != "training":
                raise RuntimeError(
                    "continuation exception was used outside training"
                )
            if run["headSha"] != special_continuation_claim["head_sha"]:
                raise RuntimeError(
                    "continuation exception has the wrong approved source commit"
                )
            if run_key != special_continuation_claim["run_key"]:
                raise RuntimeError("continuation exception has the wrong approved run key")
        if redundant_continuation_claim is None:
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
        worker_auth: dict[str, Any] | None = None
        legacy = executor.get("legacy_original_core_actions_runs", {})
        if str(actions_run_id) in legacy:
            legacy_claim = legacy[str(actions_run_id)]
            if kind != "training" or campaign != "original" or stage != "core":
                raise RuntimeError(
                    "legacy Actions allowlist was used outside original core training"
                )
            if run["headSha"] != legacy_claim["head_sha"]:
                raise RuntimeError(
                    "legacy Actions run has the wrong approved source commit"
                )
            if run_key != legacy_claim["run_key"]:
                raise RuntimeError("legacy Actions run has the wrong approved run key")
        else:
            auth_path = artifact_root / "worker_authorization_receipt.json"
            if not auth_path.is_file():
                raise RuntimeError(
                    "future worker artifact lacks its supervisor authorization receipt"
                )
            worker_auth = read_json(auth_path)
            supplied = worker_auth.get("receipt_sha256")
            if supplied != sha256_value(
                {
                    key: value
                    for key, value in worker_auth.items()
                    if key != "receipt_sha256"
                }
            ):
                raise RuntimeError("worker authorization receipt hash mismatch")
            if kind == "training":
                expected_action = str(worker_auth.get("action") or "")
                if expected_action not in {
                    "dispatch_training_wave",
                    "dispatch_training_resume",
                }:
                    raise RuntimeError("training worker has an unauthorized action")
            else:
                expected_action = "dispatch_evaluation_wave"
            expected_auth = {
                "action": expected_action,
                "campaign": campaign,
                "stage": stage,
                "run_key": run_key,
                "plan_sha": plans[(campaign, stage)]["launch_plan_contract_sha"],
                "source_commit_sha": run["headSha"],
            }
            if any(
                worker_auth.get(key) != value for key, value in expected_auth.items()
            ):
                raise RuntimeError(
                    "worker authorization receipt differs from the collected cell"
                )
            if canonical_quarantine_claim is not None:
                expected_canonical = {
                    "receipt_sha256": canonical_quarantine_claim[
                        "canonical_worker_authorization_receipt_sha256"
                    ],
                    "source_training_actions_run_id": int(
                        canonical_quarantine_claim["expected_source_actions_run_id"]
                    ),
                    "segment_end_step": int(
                        canonical_quarantine_claim["expected_completed_steps"]
                    ),
                    "supervisor_run_id": int(
                        canonical_quarantine_claim["canonical_supervisor_run_id"]
                    ),
                    "authorization_sha256": canonical_quarantine_claim[
                        "canonical_authorization_sha256"
                    ],
                }
                if any(
                    worker_auth.get(key) != value
                    for key, value in expected_canonical.items()
                ):
                    raise RuntimeError(
                        "canonical continuation authorization differs from quarantine"
                    )
            if kind == "evaluation":
                training_evidence = read_json(
                    receipt_path(state_dir, "training", run_key)
                )
                if worker_auth.get(
                    "source_training_actions_run_id"
                ) != training_evidence.get("source_actions_run_id"):
                    raise RuntimeError(
                        "evaluation worker used the wrong training Actions source"
                    )
            if kind == "training" and expected_action == "dispatch_training_resume":
                prior_continuation = load_valid_receipt(
                    continuation_path(state_dir, run_key),
                    run_key=run_key,
                    field="training_continuation_valid",
                )
                if prior_continuation is None:
                    raise RuntimeError(
                        "training resume lacks a collected predecessor continuation"
                    )
                if redundant_continuation_claim is not None:
                    expected_redundant = {
                        "receipt_sha256": redundant_continuation_claim[
                            "redundant_worker_authorization_receipt_sha256"
                        ],
                        "source_training_actions_run_id": int(
                            redundant_continuation_claim[
                                "expected_source_actions_run_id"
                            ]
                        ),
                        "segment_end_step": int(
                            redundant_continuation_claim["expected_completed_steps"]
                        ),
                        "supervisor_run_id": int(
                            redundant_continuation_claim["redundant_supervisor_run_id"]
                        ),
                        "authorization_sha256": redundant_continuation_claim[
                            "redundant_authorization_sha256"
                        ],
                    }
                    if any(
                        worker_auth.get(key) != value
                        for key, value in expected_redundant.items()
                    ):
                        raise RuntimeError(
                            "redundant continuation authorization differs from quarantine"
                        )
                elif (
                    worker_auth.get("source_training_actions_run_id")
                    != prior_continuation.get("source_actions_run_id")
                    and legacy_continuation_claim is None
                ):
                    raise RuntimeError(
                        "training resume used the wrong predecessor Actions run"
                    )
            supervisor_id = int(worker_auth.get("supervisor_run_id", -1))
            supervisor = gh_json(
                [
                    "gh",
                    "run",
                    "view",
                    str(supervisor_id),
                    "--json",
                    "status,conclusion,workflowName,headSha",
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
                raise RuntimeError(
                    "worker is not bound to a successful matching supervisor"
                )
        if kind == "training":
            if (artifact_root / "report.json").is_file():
                receipt = audit_training_artifact(
                    plan_entry=entry,
                    run_dir=artifact_root,
                    source_actions_run_id=actions_run_id,
                )
            else:
                receipt = audit_training_continuation_artifact(
                    plan_entry=entry,
                    run_dir=artifact_root,
                    source_actions_run_id=actions_run_id,
                    allow_legacy_missing_report=legacy_continuation_claim is not None,
                )
                if legacy_continuation_claim is not None and int(
                    receipt["completed_steps"]
                ) != int(legacy_continuation_claim["expected_completed_steps"]):
                    raise RuntimeError(
                        "legacy continuation has the wrong completed-step count"
                    )
                if redundant_continuation_claim is not None and int(
                    receipt["completed_steps"]
                ) != int(redundant_continuation_claim["expected_completed_steps"]):
                    raise RuntimeError(
                        "redundant continuation has the wrong completed-step count"
                    )
        else:
            receipt = audit_evaluation_artifact(
                plan_entry=entry,
                evaluation_dir=artifact_root,
                training_receipt=read_json(
                    receipt_path(state_dir, "training", run_key)
                ),
                partition_contracts=partition_contracts(entry),
                source_actions_run_id=actions_run_id,
            )
        if (
            kind == "training"
            and worker_auth is not None
            and worker_auth.get("segment_end_step") is not None
        ):
            observed_step = int(
                receipt.get("completed_steps", receipt.get("terminal_step", -1))
            )
            if observed_step != int(worker_auth["segment_end_step"]):
                raise RuntimeError(
                    "training artifact ended at the wrong authorized segment step"
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
        else campaign_contract.get(
            "evaluation_artifact_prefix", "scaling-paradox-evaluation-"
        )
    )
    if artifact["name"] != f"{expected_prefix}{run_key}":
        raise RuntimeError("Actions artifact name differs from the frozen campaign")
    receipt["source_artifact_id"] = int(artifact["id"])
    receipt["source_artifact_name"] = artifact["name"]
    receipt["source_commit_sha"] = run["headSha"]
    receipt["source_actions_conclusion"] = run.get("conclusion")
    receipt["receipt_sha256"] = sha256_value(
        {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    )
    is_continuation = bool(receipt.get("training_continuation_valid"))
    existing_owner = (
        continuation_path(state_dir, run_key)
        if is_continuation
        else receipt_path(state_dir, kind, run_key)
    )
    if existing_owner.is_file():
        prior = read_json(existing_owner)
        if is_continuation:
            if int(receipt["completed_steps"]) <= int(prior.get("completed_steps", -1)):
                if redundant_continuation_claim is not None:
                    quarantine_redundant_continuation(
                        state_dir=state_dir,
                        actions_run_id=actions_run_id,
                        claim=redundant_continuation_claim,
                        prior=prior,
                        receipt=receipt,
                        worker_auth=worker_auth,
                    )
                    return receipt
                if legacy_continuation_claim is None:
                    raise RuntimeError(
                        "training continuation did not advance monotonically"
                    )
                write_json(
                    state_dir / "actions_runs" / kind / f"{actions_run_id}.json",
                    {
                        "actions_run_id": actions_run_id,
                        "run_key": run_key,
                        "receipt_sha256": receipt["receipt_sha256"],
                        "checkpoint_lineage": receipt.get("checkpoint_lineage"),
                    },
                )
                return receipt
        elif int(prior.get("source_actions_run_id", -1)) != actions_run_id:
            raise RuntimeError("run key already has a different terminal Actions owner")
    write_json(existing_owner, receipt)
    marker = {
        "actions_run_id": actions_run_id,
        "run_key": run_key,
        "receipt_sha256": receipt["receipt_sha256"],
        "checkpoint_lineage": receipt.get("checkpoint_lineage"),
    }
    if worker_auth is not None:
        consumed_dispatch_claim = dispatch_claim_from_worker_auth(worker_auth)
        marker["dispatch_claim_sha256"] = consumed_dispatch_claim[
            "dispatch_claim_sha256"
        ]
    write_json(state_dir / "actions_runs" / kind / f"{actions_run_id}.json", marker)
    return receipt


def sync_github_state(
    *,
    executor: dict[str, Any],
    plans: dict[tuple[str, str], dict[str, Any]],
    state_dir: Path,
) -> dict[str, int]:
    workflows = {
        "training": tuple(
            dict.fromkeys(
                str(campaign["workflow"]) for campaign in executor["campaigns"].values()
            )
        ),
        "evaluation": tuple(
            dict.fromkeys(
                str(
                    campaign.get(
                        "evaluation_workflow",
                        "scaling-paradox-checkpoint-evaluation.yml",
                    )
                )
                for campaign in executor["campaigns"].values()
            )
        ),
    }
    counts = {"training": 0, "evaluation": 0}
    preauthorization_failures = validate_preauthorization_failure_quarantine(
        executor, plans
    )
    legacy = {
        int(value) for value in executor.get("legacy_original_core_actions_runs", {})
    }
    for kind, names in workflows.items():
        for workflow in names:
            command = [
                "gh",
                "run",
                "list",
                "--workflow",
                workflow,
                "--limit",
                "1000",
                "--json",
                "conclusion,databaseId,displayTitle,headSha,status",
            ]
            try:
                rows = gh_json(command)
            except RuntimeError as exc:
                if kind == "evaluation" and "not found" in str(exc).lower():
                    continue
                raise
            for row in sorted(
                rows, key=lambda item: int(item["databaseId"])
            ):
                run_id = int(row["databaseId"])
                if row.get("status") != "completed":
                    continue
                if (state_dir / "actions_runs" / kind / f"{run_id}.json").is_file():
                    continue
                preauthorization_claim = preauthorization_failures.get(run_id)
                if preauthorization_claim is not None:
                    audit_preauthorization_failure(
                        state_dir=state_dir,
                        actions_run_id=run_id,
                        row=row,
                        claim=preauthorization_claim,
                        kind=kind,
                    )
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
                    raise RuntimeError(
                        f"paid {kind} run {run_id} has no auditable campaign artifact"
                    )
                counts[kind] += 1
    return counts


def build_paid_actions_inventory(
    *,
    manifest: dict[str, Any],
    state_dir: Path,
    rows_by_kind: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    known: dict[tuple[str, str], dict[str, Any]] = {}
    for phase in manifest["phases"]:
        for wave in phase["waves"]:
            for run_key, contract_sha in zip(
                wave["run_keys"], wave["run_contract_shas"], strict=True
            ):
                identity = (str(phase["campaign"]), str(run_key))
                if identity in known:
                    raise RuntimeError("campaign manifest has a duplicate run identity")
                known[identity] = {
                    "phase": phase["phase"],
                    "run_contract_sha": contract_sha,
                }
    title_pattern = re.compile(
        r"^Frontier (train|eval) (original|replication) (\S+) supervisor-([1-9][0-9]*)$"
    )
    active_rows: list[dict[str, Any]] = []
    active_identities: set[tuple[str, str]] = set()
    for expected_kind, rows in rows_by_kind.items():
        if expected_kind not in {"training", "evaluation"}:
            raise RuntimeError("paid Actions inventory has an unknown kind")
        for row in rows:
            title = str(row.get("displayTitle") or "")
            match = title_pattern.fullmatch(title)
            if match is None:
                if row.get("status") != "completed" and "supervisor-" in title:
                    raise RuntimeError(f"unrecognized active paid-run title: {title}")
                continue
            title_kind, campaign, run_key, supervisor_id = match.groups()
            kind = "training" if title_kind == "train" else "evaluation"
            identity = (campaign, run_key)
            if kind != expected_kind or identity not in known:
                raise RuntimeError(f"paid Actions identity is outside the manifest: {title}")
            actions_run_id = int(row.get("databaseId", 0))
            if actions_run_id <= 0:
                raise RuntimeError("paid Actions inventory has an invalid run ID")
            status = str(row.get("status") or "")
            if status == "completed":
                marker = (
                    state_dir / "actions_runs" / kind / f"{actions_run_id}.json"
                )
                if not marker.is_file():
                    raise TerminalAfterReconstructionError(
                        "paid run became terminal after artifact reconstruction: "
                        f"{kind} Actions run {actions_run_id} ({title}); rerun the "
                        "supervisor without dispatch"
                    )
                continue
            if status not in {"requested", "queued", "in_progress", "waiting", "pending"}:
                raise RuntimeError("paid Actions inventory has an unknown status")
            active_identity = (kind, run_key)
            if active_identity in active_identities:
                raise RuntimeError("active paid run inventory has duplicate ownership")
            active_identities.add(active_identity)
            active_rows.append(
                {
                    "actions_run_id": actions_run_id,
                    "supervisor_actions_run_id": int(supervisor_id),
                    "kind": kind,
                    "campaign": campaign,
                    "phase": known[identity]["phase"],
                    "run_key": run_key,
                    "run_contract_sha": known[identity]["run_contract_sha"],
                    "status": status,
                    "created_at": row.get("createdAt"),
                    "started_at": row.get("startedAt"),
                    "updated_at": row.get("updatedAt"),
                }
            )
    return sorted(active_rows, key=lambda row: int(row["actions_run_id"]))


def query_paid_actions_inventory(
    *, executor: dict[str, Any], manifest: dict[str, Any], state_dir: Path
) -> list[dict[str, Any]]:
    workflows = {
        "training": tuple(
            dict.fromkeys(
                str(campaign["workflow"])
                for campaign in executor["campaigns"].values()
            )
        ),
        "evaluation": tuple(
            dict.fromkeys(
                str(
                    campaign.get(
                        "evaluation_workflow",
                        "scaling-paradox-checkpoint-evaluation.yml",
                    )
                )
                for campaign in executor["campaigns"].values()
            )
        ),
    }
    rows_by_kind: dict[str, list[dict[str, Any]]] = {
        "training": [],
        "evaluation": [],
    }
    for kind, names in workflows.items():
        for workflow in names:
            result = subprocess.run(
                [
                    "gh",
                    "run",
                    "list",
                    "--workflow",
                    workflow,
                    "--limit",
                    "1000",
                    "--json",
                    "createdAt,databaseId,displayTitle,startedAt,status,updatedAt",
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            if result.returncode != 0:
                if kind == "evaluation" and "not found" in result.stderr.lower():
                    continue
                raise RuntimeError(f"could not query paid Actions state for {workflow}")
            rows_by_kind[kind].extend(json.loads(result.stdout))
    return build_paid_actions_inventory(
        manifest=manifest,
        state_dir=state_dir,
        rows_by_kind=rows_by_kind,
    )


def write_paid_actions_inventory(
    *,
    executor: dict[str, Any],
    manifest: dict[str, Any],
    state_dir: Path,
    output: Path,
) -> list[dict[str, Any]]:
    try:
        active_rows = query_paid_actions_inventory(
            executor=executor,
            manifest=manifest,
            state_dir=state_dir,
        )
    except TerminalAfterReconstructionError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(TERMINAL_AFTER_RECONSTRUCTION_EXIT_CODE) from exc
    write_json(output, active_rows)
    return active_rows


def actions_marker_count(state_dir: Path) -> int:
    return sum(
        1
        for kind in ("training", "evaluation")
        for _ in (state_dir / "actions_runs" / kind).glob("*.json")
    )


def converge_paid_actions_inventory(
    *,
    executor: dict[str, Any],
    plans: dict[tuple[str, str], dict[str, Any]],
    manifest: dict[str, Any],
    state_dir: Path,
    output: Path,
    provider_output: Path,
) -> list[dict[str, Any]]:
    maximum_crossings = int(manifest["global_max_active_paid_cells"])
    if maximum_crossings <= 0:
        raise RuntimeError("campaign active-cell cap must be positive")
    marker_count = actions_marker_count(state_dir)
    crossings = 0
    while True:
        try:
            active_rows = query_paid_actions_inventory(
                executor=executor,
                manifest=manifest,
                state_dir=state_dir,
            )
        except TerminalAfterReconstructionError as exc:
            print(str(exc), file=sys.stderr)
            if crossings >= maximum_crossings:
                raise RuntimeError(
                    "terminal-boundary convergence exceeded the frozen active-cell cap"
                ) from exc
            crossings += 1
            print(
                "Paid worker crossed the reconstruction boundary; refreshing "
                f"authoritative state (crossing {crossings} of at most "
                f"{maximum_crossings})."
            )
            time.sleep(5)
            sync_github_state(executor=executor, plans=plans, state_dir=state_dir)
            refreshed_marker_count = actions_marker_count(state_dir)
            if refreshed_marker_count <= marker_count:
                raise RuntimeError(
                    "terminal-boundary reconstruction made no auditable progress"
                ) from exc
            marker_count = refreshed_marker_count
            write_json(provider_output, build_provider_snapshot(plans))
            continue
        write_json(output, active_rows)
        print(
            json.dumps(
                {
                    "active_paid_cells": len(active_rows),
                    "terminal_boundary_crossings_reconciled": crossings,
                }
            )
        )
        return active_rows


def receipt_path(state_dir: Path, kind: str, run_key: str) -> Path:
    return state_dir / "receipts" / kind / f"{run_key}.json"


def submission_path(state_dir: Path, kind: str, run_key: str) -> Path:
    return state_dir / "submissions" / kind / f"{run_key}.json"


def authorization_claim_path(state_dir: Path, kind: str, run_key: str) -> Path:
    return state_dir / "authorization_claims" / kind / f"{run_key}.json"


def continuation_path(state_dir: Path, run_key: str) -> Path:
    return state_dir / "continuations" / "training" / f"{run_key}.json"


def training_segment_end(
    *,
    manifest: dict[str, Any],
    wave: dict[str, Any],
    run_key: str,
    completed_steps: int,
) -> int:
    maximum = int(wave["run_max_steps"][run_key])
    if completed_steps < 0 or completed_steps >= maximum:
        raise RuntimeError("invalid completed-step count for a training segment")
    model_tag = str(wave["run_model_tags"][run_key])
    slicing = manifest.get("training_slicing") or {}
    override = (slicing.get("model_overrides") or {}).get(model_tag)
    if not override:
        return maximum
    width_key = (
        "initial_segment_steps"
        if completed_steps == 0
        else "continuation_segment_steps"
    )
    width = int(override.get(width_key, 0))
    if width <= 0:
        raise RuntimeError("training slicing policy has a nonpositive segment width")
    return min(maximum, completed_steps + width)


def estimated_segment_cost(
    *, wave: dict[str, Any], run_key: str, start_step: int, end_step: int
) -> float:
    maximum = int(wave["run_max_steps"][run_key])
    full_cost = float(wave["estimated_training_cost_by_run_key"][run_key])
    if not (0 <= start_step < end_step <= maximum):
        raise RuntimeError("invalid training segment cost interval")
    return round(full_cost * (end_step - start_step) / maximum, 4)


def load_valid_receipt(
    path: Path, *, run_key: str, field: str
) -> dict[str, Any] | None:
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
    unsigned = {
        key: value for key, value in rescue_gate.items() if key != "gate_sha256"
    }
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
    if (
        rescue_gate.get("replication_core_plan_sha")
        != core_phases["replication"]["plan_sha"]
    ):
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
                    raise RuntimeError(
                        "conditional gate precedes a core evaluation receipt"
                    )
                expected_hashes.append(str(receipt["evaluation_report_file_sha256"]))
    if sorted(rescue_gate["evaluation_report_sha256s"]) != sorted(expected_hashes):
        raise RuntimeError(
            "conditional gate evidence differs from collected core evaluations"
        )


def phase_is_skipped(phase: dict[str, Any], rescue_gate: dict[str, Any] | None) -> bool:
    if not phase.get("conditional_gate"):
        return False
    if rescue_gate is None:
        return False
    if rescue_gate.get("gate_id") != phase["conditional_gate"]:
        raise RuntimeError("conditional gate receipt has the wrong gate ID")
    return not bool(rescue_gate.get("pass"))


def phase_run_entries(phase: dict[str, Any]) -> list[tuple[int, dict[str, Any], str]]:
    entries: list[tuple[int, dict[str, Any], str]] = []
    for wave in phase["waves"]:
        orders = wave.get("execution_orders") or range(1, len(wave["run_keys"]) + 1)
        if len(orders) != len(wave["run_keys"]):
            raise RuntimeError("wave execution-order and run-key counts differ")
        entries.extend(
            (int(order), wave, str(run_key))
            for order, run_key in zip(orders, wave["run_keys"], strict=True)
        )
    entries.sort(key=lambda row: row[0])
    if len({order for order, _, _ in entries}) != len(entries):
        raise RuntimeError("phase execution orders are not unique")
    if len({run_key for _, _, run_key in entries}) != len(entries):
        raise RuntimeError("phase run keys are not unique")
    return entries


def parse_utc_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{field} is absent or invalid") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def validate_provider_snapshot(
    provider_snapshot: dict[str, Any] | None,
) -> tuple[datetime, dict[str, list[dict[str, Any]]], str] | None:
    if provider_snapshot is None:
        return None
    if (
        provider_snapshot.get("contract")
        != "pearl.frontier-provider-operational-snapshot/1"
    ):
        raise RuntimeError("provider operational snapshot has the wrong contract")
    supplied_sha = provider_snapshot.get("snapshot_sha256")
    unsigned = {
        key: value
        for key, value in provider_snapshot.items()
        if key != "snapshot_sha256"
    }
    if supplied_sha != sha256_value(unsigned):
        raise RuntimeError("provider operational snapshot hash mismatch")
    if provider_snapshot.get("scientific_values_omitted") is not True:
        raise RuntimeError("provider operational snapshot is not result-blind")
    observed_at = parse_utc_timestamp(
        str(provider_snapshot.get("observed_at_utc") or ""),
        field="provider snapshot time",
    )
    now = datetime.now(UTC)
    if observed_at > now + timedelta(minutes=2) or observed_at < now - timedelta(
        minutes=10
    ):
        raise RuntimeError("provider operational snapshot is stale or future-dated")
    indexed: dict[str, list[dict[str, Any]]] = {}
    provider_ids: set[str] = set()
    rows = provider_snapshot.get("runs")
    if not isinstance(rows, list):
        raise RuntimeError("provider operational snapshot runs are malformed")
    for row in rows:
        if not isinstance(row, dict) or row.get("corrupted") is not False:
            raise RuntimeError("provider operational snapshot contains an invalid run")
        provider_id = str(row.get("provider_training_run_id") or "")
        run_key = str(row.get("run_key") or "")
        if not provider_id or not run_key or provider_id in provider_ids:
            raise RuntimeError("provider operational snapshot ownership is ambiguous")
        parse_utc_timestamp(
            str(row.get("last_request_time") or ""),
            field="provider last-request time",
        )
        provider_ids.add(provider_id)
        indexed.setdefault(run_key, []).append(row)
    return observed_at, indexed, str(supplied_sha)


def validate_active_runs(
    *,
    manifest: dict[str, Any],
    active_paid_cells: int,
    active_runs: list[dict[str, Any]] | None,
) -> dict[tuple[str, str], dict[str, Any]] | None:
    if active_runs is None:
        return None
    if len(active_runs) != active_paid_cells:
        raise RuntimeError(
            "active run inventory disagrees with the active paid-cell count"
        )
    known: dict[tuple[str, str], tuple[str, str, str | None]] = {}
    for phase in manifest["phases"]:
        for _, wave, run_key in phase_run_entries(phase):
            contract_by_key = dict(
                zip(
                    wave["run_keys"],
                    wave.get("run_contract_shas") or [None] * len(wave["run_keys"]),
                    strict=True,
                )
            )
            for kind in ("training", "evaluation"):
                identity = (kind, run_key)
                if identity in known:
                    raise RuntimeError(
                        "campaign manifest contains duplicate active-run identities"
                    )
                known[identity] = (
                    str(phase["phase"]),
                    str(phase["campaign"]),
                    contract_by_key[run_key],
                )
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    run_ids: set[int] = set()
    for row in active_runs:
        kind = str(row.get("kind", ""))
        run_key = str(row.get("run_key", ""))
        identity = (kind, run_key)
        run_id = int(row.get("actions_run_id", 0))
        if identity not in known:
            raise RuntimeError(
                f"active paid run is outside the frozen manifest: {kind}:{run_key}"
            )
        if identity in indexed or run_id in run_ids or run_id <= 0:
            raise RuntimeError(
                "active paid run inventory has duplicate or invalid ownership"
            )
        phase_name, campaign, contract_sha = known[identity]
        if row.get("phase") not in (None, phase_name):
            raise RuntimeError("active paid run has the wrong phase")
        if row.get("campaign") != campaign:
            raise RuntimeError("active paid run has the wrong campaign")
        if row.get("run_contract_sha") not in (None, contract_sha):
            raise RuntimeError("active paid run has the wrong contract SHA")
        if row.get("status") not in {
            "requested",
            "queued",
            "in_progress",
            "waiting",
            "pending",
        }:
            raise RuntimeError("active paid run inventory includes a non-active status")
        indexed[identity] = row
        run_ids.add(run_id)
    return indexed


def checkpoint_provider_ids(receipt: dict[str, Any] | None) -> list[str]:
    if receipt is None:
        return []
    result: list[str] = []
    for checkpoint in receipt.get("checkpoint_lineage") or []:
        state_path = str(checkpoint.get("state_path") or "")
        if not state_path.startswith("tinker://") or "/weights/" not in state_path:
            raise RuntimeError(
                "capacity gate found an invalid checkpoint provider path"
            )
        provider_id = state_path.removeprefix("tinker://").split("/weights/", 1)[0]
        if provider_id not in result:
            result.append(provider_id)
    return result


def all_prior_provider_ids(
    state_dir: Path, run_key: str, continuation: dict[str, Any] | None
) -> list[str]:
    result: list[str] = list(checkpoint_provider_ids(continuation)) if continuation else []
    quarantine_dir = state_dir / "quarantines" / "training"
    if quarantine_dir.is_dir():
        for path in quarantine_dir.glob("*.json"):
            data = read_json(path)
            supplied_sha = data.get("quarantine_sha256")
            unsigned = {
                key: value
                for key, value in data.items()
                if key != "quarantine_sha256"
            }
            if (
                supplied_sha != sha256_value(unsigned)
                or data.get("contract")
                != "pearl.frontier-redundant-continuation-quarantine-receipt/1"
                or data.get("disposition")
                != "excluded_operational_duplicate_not_a_replicate"
            ):
                raise RuntimeError("capacity gate found a malformed quarantine receipt")
            if data.get("run_key") != run_key:
                continue
            provider_id = str(data.get("redundant_provider_training_run_id") or "")
            if not provider_id or provider_id in result:
                raise RuntimeError("capacity gate found ambiguous quarantined ownership")
            result.append(provider_id)
    return result


def rolling_capacity_limit(
    *,
    manifest: dict[str, Any],
    phase: dict[str, Any],
    state_dir: Path,
    entries: list[tuple[int, dict[str, Any], str]],
    sentinel_complete: bool,
    active_phase: dict[tuple[str, str], dict[str, Any]],
    provider_state: tuple[datetime, dict[str, list[dict[str, Any]]], str] | None,
) -> tuple[int, str, dict[str, Any] | None]:
    if not sentinel_complete:
        return 1, "sentinel", None
    ramp = (phase.get("scheduling") or {}).get("capacity_ramp")
    if ramp is None:
        return int(manifest["global_max_active_paid_cells"]), "full", None
    if provider_state is None:
        raise RuntimeError(
            "capacity ramp requires a fresh provider operational snapshot"
        )
    observed_at, provider_by_key, provider_snapshot_sha = provider_state
    sentinel_orders = {
        int(value)
        for value in phase["scheduling"].get("sentinel_execution_orders", [1])
    }
    ordered_keys = [
        run_key for order, _, run_key in entries if order not in sentinel_orders
    ]
    started_keys: set[str] = set()
    for run_key in ordered_keys:
        if (
            ("training", run_key) in active_phase
            or continuation_path(state_dir, run_key).is_file()
            or receipt_path(state_dir, "training", run_key).is_file()
            or submission_path(state_dir, "training", run_key).is_file()
        ):
            started_keys.add(run_key)
    expected_prefix = set(ordered_keys[: len(started_keys)])
    if started_keys != expected_prefix:
        raise RuntimeError(
            "capacity ramp observed training outside the frozen ordered prefix"
        )

    tiers = ramp["tiers"]
    current_limit = int(tiers[0]["max_active_cells"])
    current_name = str(tiers[0]["name"])
    current_gate: dict[str, Any] | None = None
    for tier in tiers[1:]:
        required = int(tier["minimum_started_cells"])
        if len(started_keys) < required:
            break
        if len(active_phase) > current_limit:
            gate = {
                "contract": "pearl.frontier-capacity-gate/1",
                "campaign": phase["campaign"],
                "phase": phase["phase"],
                "minimum_started_cells": required,
                "authorized_max_active_cells": int(tier["max_active_cells"]),
                "provider_snapshot_sha256": provider_snapshot_sha,
                "scientific_values_omitted": True,
                "operational_evidence": [
                    {
                        "evidence": "previously_consumed_active_capacity_tier",
                        "active_paid_cells": len(active_phase),
                        "prior_capacity_limit": current_limit,
                        "started_ordered_prefix_count": len(started_keys),
                    }
                ],
            }
            gate["gate_sha256"] = sha256_value(gate)
            current_gate = gate
            current_limit = int(tier["max_active_cells"])
            current_name = str(tier["name"])
            continue
        observation_minutes = int(tier["observation_minutes"])
        staleness_minutes = int(tier["max_provider_staleness_minutes"])
        gate_rows: list[dict[str, Any]] = []
        healthy = True
        for run_key in ordered_keys[:required]:
            terminal = load_valid_receipt(
                receipt_path(state_dir, "training", run_key),
                run_key=run_key,
                field="training_terminal_valid",
            )
            continuation = load_valid_receipt(
                continuation_path(state_dir, run_key),
                run_key=run_key,
                field="training_continuation_valid",
            )
            progress_receipt = terminal or continuation
            active = active_phase.get(("training", run_key))
            if active is None and progress_receipt is not None:
                supplied_receipt_sha = progress_receipt.get("receipt_sha256")
                unsigned_receipt = {
                    key: value
                    for key, value in progress_receipt.items()
                    if key != "receipt_sha256"
                }
                if supplied_receipt_sha != sha256_value(unsigned_receipt):
                    raise RuntimeError(
                        "capacity gate found a malformed progress receipt"
                    )
                gate_rows.append(
                    {
                        "run_key": run_key,
                        "evidence": "audited_training_progress",
                        "receipt_sha256": supplied_receipt_sha,
                    }
                )
                continue
            if active is None or active.get("status") != "in_progress":
                healthy = False
                break
            started_at = parse_utc_timestamp(
                str(active.get("started_at") or ""), field="active Actions start time"
            )
            if observed_at - started_at < timedelta(minutes=observation_minutes):
                healthy = False
                break
            provider_rows = provider_by_key.get(run_key, [])
            expected_contract = str(active.get("run_contract_sha") or "")
            if not expected_contract:
                raise RuntimeError(
                    "active capacity-ramp row lacks its run contract SHA"
                )
            if any(
                row.get("campaign_id") != phase["campaign_id"]
                or row.get("run_contract_sha") != expected_contract
                for row in provider_rows
            ):
                raise RuntimeError(
                    "capacity-ramp provider ownership differs from the active plan"
                )
            prior_ids = all_prior_provider_ids(state_dir, run_key, continuation)
            provider_ids = {
                str(row["provider_training_run_id"]) for row in provider_rows
            }
            if not set(prior_ids).issubset(provider_ids):
                raise RuntimeError("capacity-ramp provider lineage lost a prior owner")
            if len(provider_ids) > len(prior_ids) + 1:
                raise RuntimeError(
                    "capacity ramp detected duplicate provider DPO ownership"
                )
            if len(provider_ids) != len(prior_ids) + 1:
                healthy = False
                break
            latest_request = max(
                parse_utc_timestamp(
                    str(row["last_request_time"]), field="provider last-request time"
                )
                for row in provider_rows
                if str(row["provider_training_run_id"]) not in prior_ids
            )
            if observed_at - latest_request > timedelta(minutes=staleness_minutes):
                healthy = False
                break
            gate_rows.append(
                {
                    "run_key": run_key,
                    "evidence": "sustained_uncorrupted_provider_progress",
                    "actions_run_id": int(active["actions_run_id"]),
                    "provider_training_run_ids": sorted(provider_ids),
                    "observed_minutes": observation_minutes,
                }
            )
        if not healthy:
            break
        gate = {
            "contract": "pearl.frontier-capacity-gate/1",
            "campaign": phase["campaign"],
            "phase": phase["phase"],
            "minimum_started_cells": required,
            "authorized_max_active_cells": int(tier["max_active_cells"]),
            "provider_snapshot_sha256": provider_snapshot_sha,
            "scientific_values_omitted": True,
            "operational_evidence": gate_rows,
        }
        gate["gate_sha256"] = sha256_value(gate)
        current_gate = gate
        current_limit = int(tier["max_active_cells"])
        current_name = str(tier["name"])
    return current_limit, current_name, current_gate


def rolling_authorization(
    *,
    manifest: dict[str, Any],
    phase: dict[str, Any],
    state_dir: Path,
    active_paid_cells: int,
    active_index: dict[tuple[str, str], dict[str, Any]] | None,
    provider_state: tuple[datetime, dict[str, list[dict[str, Any]]], str] | None,
) -> dict[str, Any] | None:
    if active_index is None and active_paid_cells:
        raise RuntimeError("rolling scheduling requires the exact active-run inventory")
    active_index = active_index or {}
    entries = phase_run_entries(phase)
    entry_by_key = {run_key: (order, wave) for order, wave, run_key in entries}
    phase_keys = set(entry_by_key)
    active_phase = {
        identity: row
        for identity, row in active_index.items()
        if identity[1] in phase_keys
    }
    active_elsewhere = set(active_index) - set(active_phase)

    training = {
        run_key: load_valid_receipt(
            receipt_path(state_dir, "training", run_key),
            run_key=run_key,
            field="training_terminal_valid",
        )
        for _, _, run_key in entries
    }
    evaluation = {
        run_key: (
            load_valid_receipt(
                receipt_path(state_dir, "evaluation", run_key),
                run_key=run_key,
                field="evaluation_terminal_valid",
            )
            if phase.get("evaluation_required", True)
            else True
        )
        for _, _, run_key in entries
    }
    if all(training.values()) and all(evaluation.values()):
        if active_phase:
            raise RuntimeError(
                "terminal-valid rolling phase still has active paid ownership"
            )
        return None
    if active_elsewhere:
        raise RuntimeError(
            "an incomplete rolling phase overlaps active work from another phase"
        )

    scheduling = phase["scheduling"]
    sentinel_orders = {
        int(value) for value in scheduling.get("sentinel_execution_orders", [1])
    }
    sentinel_keys = {
        run_key for order, _, run_key in entries if order in sentinel_orders
    }
    if len(sentinel_keys) != len(sentinel_orders):
        raise RuntimeError(
            "rolling schedule references an unknown sentinel execution order"
        )
    sentinel_complete = all(training[key] and evaluation[key] for key in sentinel_keys)
    post_sentinel_hold = scheduling.get("post_sentinel_hold")
    if sentinel_complete and post_sentinel_hold is not None:
        if post_sentinel_hold != "charon_local_takeover":
            raise RuntimeError("rolling schedule has an unknown post-sentinel hold")
        if active_phase:
            raise RuntimeError("post-sentinel Charon hold conflicts with active phase ownership")
        return {
            "contract": "pearl.scaling-paradox-authorization/1",
            "action": "wait",
            "reason": "replication_sentinel_complete_pending_charon_takeover",
            "active_paid_cells": active_paid_cells,
            "authorized_run_keys": [],
            "post_sentinel_hold": post_sentinel_hold,
        }
    eligible_keys = phase_keys if sentinel_complete else sentinel_keys
    maximum, capacity_tier, capacity_gate = rolling_capacity_limit(
        manifest=manifest,
        phase=phase,
        state_dir=state_dir,
        entries=entries,
        sentinel_complete=sentinel_complete,
        active_phase=active_phase,
        provider_state=provider_state,
    )
    if active_paid_cells > maximum:
        raise RuntimeError(
            "active paid cells exceed the evidence-authorized capacity tier"
        )
    slots = maximum - active_paid_cells
    forbidden_active = [
        f"{kind}:{run_key}"
        for kind, run_key in active_phase
        if run_key not in eligible_keys
    ]
    if forbidden_active:
        raise RuntimeError(
            "pre-sentinel rolling work is active outside the frozen sentinel: "
            + ", ".join(sorted(forbidden_active))
        )

    for kind, run_key in active_phase:
        if kind == "training" and training[run_key]:
            raise RuntimeError(
                "terminal training receipt conflicts with an active training owner"
            )
        if kind == "evaluation" and (not training[run_key] or evaluation[run_key]):
            raise RuntimeError(
                "active evaluation owner conflicts with frozen receipt state"
            )

    if slots == 0:
        return {
            "contract": "pearl.scaling-paradox-authorization/1",
            "action": "wait",
            "reason": "global_paid_cell_cap_is_full",
            "active_paid_cells": active_paid_cells,
            "authorized_run_keys": [],
        }

    ordered_eligible = [
        run_key for _, _, run_key in entries if run_key in eligible_keys
    ]
    continuations = {
        run_key: load_valid_receipt(
            continuation_path(state_dir, run_key),
            run_key=run_key,
            field="training_continuation_valid",
        )
        for run_key in ordered_eligible
        if training[run_key] is None and ("training", run_key) not in active_phase
    }
    resumable = [run_key for run_key in ordered_eligible if continuations.get(run_key)]
    evaluation_ready = [
        run_key
        for run_key in ordered_eligible
        if training[run_key]
        and not evaluation[run_key]
        and ("evaluation", run_key) not in active_phase
    ]
    new_training = [
        run_key
        for run_key in ordered_eligible
        if not training[run_key]
        and not continuations.get(run_key)
        and ("training", run_key) not in active_phase
    ]
    full_tier_exposure_fill = (
        capacity_tier == "full_original_or_replication_cohort"
        and bool(new_training)
    )

    for run_key in new_training:
        if (
            submission_path(state_dir, "training", run_key).is_file()
            or authorization_claim_path(state_dir, "training", run_key).is_file()
        ):
            raise RuntimeError(
                "submitted training cell lacks an active owner or continuation receipt: "
                + run_key
            )
    for run_key in evaluation_ready:
        if (
            submission_path(state_dir, "evaluation", run_key).is_file()
            or authorization_claim_path(state_dir, "evaluation", run_key).is_file()
        ):
            raise RuntimeError(
                "submitted evaluation cell lacks an active owner or terminal receipt: "
                + run_key
            )

    def common(action: str, selected: list[str], workflow: str) -> dict[str, Any]:
        waves = {run_key: entry_by_key[run_key][1] for run_key in selected}
        authorization = {
            "contract": "pearl.scaling-paradox-authorization/1",
            "action": action,
            "phase": phase["phase"],
            "wave_index": min(int(wave["wave_index"]) for wave in waves.values()),
            "wave_indices_by_run_key": {
                run_key: int(waves[run_key]["wave_index"]) for run_key in selected
            },
            "campaign": phase["campaign"],
            "stage": phase["stage"],
            "workflow": workflow,
            "plan_sha": phase["plan_sha"],
            "authorized_run_keys": selected,
            "max_active_after_dispatch": active_paid_cells + len(selected),
            "scheduling_mode": "rolling_ordered",
            "scheduling_priority": (
                "full_tier_complete_cohort_exposure"
                if full_tier_exposure_fill
                else "resume_then_evaluate_then_new"
            ),
            "capacity_tier": capacity_tier,
            "capacity_limit": maximum,
            "capacity_gate": capacity_gate,
            "capacity_gate_sha256": (
                capacity_gate["gate_sha256"] if capacity_gate is not None else None
            ),
        }
        return authorization

    if resumable and not full_tier_exposure_fill:
        selected = resumable[:slots]
        source_ids = {
            run_key: int(continuations[run_key]["source_actions_run_id"])
            for run_key in selected
        }
        completed = {
            run_key: int(continuations[run_key]["completed_steps"])
            for run_key in selected
        }
        segment_ends = {
            run_key: training_segment_end(
                manifest=manifest,
                wave=entry_by_key[run_key][1],
                run_key=run_key,
                completed_steps=completed[run_key],
            )
            for run_key in selected
        }
        authorization = common("dispatch_training_resume", selected, phase["workflow"])
        authorization.update(
            {
                "config": phase["config"],
                "plan_dir": phase["plan_dir"],
                "source_actions_run_ids": source_ids,
                "source_artifact_prefix": phase["artifact_prefix"],
                "completed_steps": completed,
                "segment_end_steps": segment_ends,
                "estimated_cost_usd": round(
                    sum(
                        estimated_segment_cost(
                            wave=entry_by_key[run_key][1],
                            run_key=run_key,
                            start_step=completed[run_key],
                            end_step=segment_ends[run_key],
                        )
                        for run_key in selected
                    ),
                    4,
                ),
            }
        )
    elif evaluation_ready and not full_tier_exposure_fill:
        selected = evaluation_ready[:slots]
        source_ids = {
            run_key: training[run_key].get("source_actions_run_id")
            for run_key in selected
        }
        if any(
            not isinstance(value, int) or value <= 0 for value in source_ids.values()
        ):
            raise RuntimeError(
                "evaluation dispatch requires source Actions run IDs in training receipts"
            )
        authorization = common(
            "dispatch_evaluation_wave", selected, phase["evaluation_workflow"]
        )
        authorization.update(
            {
                "source_workflow": phase["workflow"],
                "source_actions_run_ids": source_ids,
                "source_artifact_prefix": phase["artifact_prefix"],
                "estimated_cost_usd": round(
                    sum(
                        float(
                            entry_by_key[run_key][1][
                                "estimated_checkpoint_evaluation_cost_by_run_key"
                            ][run_key]
                        )
                        for run_key in selected
                    ),
                    4,
                ),
            }
        )
    elif new_training:
        selected = new_training[:slots]
        authorization = common("dispatch_training_wave", selected, phase["workflow"])
        authorization.update(
            {
                "config": phase["config"],
                "plan_dir": phase["plan_dir"],
                "segment_end_steps": {
                    run_key: training_segment_end(
                        manifest=manifest,
                        wave=entry_by_key[run_key][1],
                        run_key=run_key,
                        completed_steps=0,
                    )
                    for run_key in selected
                },
                "estimated_cost_usd": round(
                    sum(
                        estimated_segment_cost(
                            wave=entry_by_key[run_key][1],
                            run_key=run_key,
                            start_step=0,
                            end_step=training_segment_end(
                                manifest=manifest,
                                wave=entry_by_key[run_key][1],
                                run_key=run_key,
                                completed_steps=0,
                            ),
                        )
                        for run_key in selected
                    ),
                    4,
                ),
            }
        )
    else:
        return {
            "contract": "pearl.scaling-paradox-authorization/1",
            "action": "wait",
            "reason": "eligible_rolling_cells_are_active",
            "active_paid_cells": active_paid_cells,
            "authorized_run_keys": [],
        }
    attach_and_validate_dispatch_claims(state_dir, authorization)
    authorization["authorization_sha256"] = sha256_value(authorization)
    return authorization


def next_authorization(
    *,
    manifest: dict[str, Any],
    state_dir: Path,
    active_paid_cells: int,
    active_runs: list[dict[str, Any]] | None = None,
    provider_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    maximum = int(manifest["global_max_active_paid_cells"])
    if active_paid_cells < 0 or active_paid_cells > maximum:
        raise RuntimeError(
            "active paid cell count is invalid or exceeds the global cap"
        )
    active_index = validate_active_runs(
        manifest=manifest,
        active_paid_cells=active_paid_cells,
        active_runs=active_runs,
    )
    provider_state = validate_provider_snapshot(provider_snapshot)
    gate_path = state_dir / "analysis" / "adapter_rescue_gate.json"
    rescue_gate = read_json(gate_path) if gate_path.is_file() else None
    if rescue_gate is not None:
        validate_rescue_gate(
            manifest=manifest, state_dir=state_dir, rescue_gate=rescue_gate
        )
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
        if (phase.get("scheduling") or {}).get("mode") == "rolling_ordered":
            authorization = rolling_authorization(
                manifest=manifest,
                phase=phase,
                state_dir=state_dir,
                active_paid_cells=active_paid_cells,
                active_index=active_index,
                provider_state=provider_state,
            )
            if authorization is not None:
                return authorization
            continue
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
                continuations = {
                    key: load_valid_receipt(
                        continuation_path(state_dir, key),
                        run_key=key,
                        field="training_continuation_valid",
                    )
                    for key in missing_training
                }
                resumable = [
                    key for key, value in continuations.items() if value is not None
                ]
                if resumable:
                    unresolved = [
                        key for key in missing_training if continuations[key] is None
                    ]
                    if unresolved:
                        raise RuntimeError(
                            "training wave mixes resumable and unowned missing cells: "
                            + ", ".join(unresolved)
                        )
                    if len(resumable) > maximum:
                        raise RuntimeError(
                            "training continuation wave exceeds the global cap"
                        )
                    source_ids = {
                        key: int(continuations[key]["source_actions_run_id"])
                        for key in resumable
                    }
                    completed = {
                        key: int(continuations[key]["completed_steps"])
                        for key in resumable
                    }
                    segment_ends = {
                        key: training_segment_end(
                            manifest=manifest,
                            wave=wave,
                            run_key=key,
                            completed_steps=completed[key],
                        )
                        for key in resumable
                    }
                    authorization = {
                        "contract": "pearl.scaling-paradox-authorization/1",
                        "action": "dispatch_training_resume",
                        "phase": phase["phase"],
                        "wave_index": wave["wave_index"],
                        "campaign": phase["campaign"],
                        "stage": phase["stage"],
                        "workflow": phase["workflow"],
                        "config": phase["config"],
                        "plan_dir": phase["plan_dir"],
                        "plan_sha": phase["plan_sha"],
                        "authorized_run_keys": resumable,
                        "source_actions_run_ids": source_ids,
                        "source_artifact_prefix": phase["artifact_prefix"],
                        "completed_steps": completed,
                        "segment_end_steps": segment_ends,
                        "estimated_cost_usd": round(
                            sum(
                                estimated_segment_cost(
                                    wave=wave,
                                    run_key=key,
                                    start_step=completed[key],
                                    end_step=segment_ends[key],
                                )
                                for key in resumable
                            ),
                            4,
                        ),
                        "max_active_after_dispatch": len(resumable),
                    }
                    authorization["authorization_sha256"] = sha256_value(authorization)
                    return authorization
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
                if (manifest.get("training_slicing") or {}).get("model_overrides"):
                    authorization["segment_end_steps"] = {
                        key: training_segment_end(
                            manifest=manifest,
                            wave=wave,
                            run_key=key,
                            completed_steps=0,
                        )
                        for key in missing_training
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
            missing_evaluation = [
                key for key, value in evaluation.items() if value is None
            ]
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
                    key: training[key].get("source_actions_run_id")
                    for key in missing_evaluation
                }
                if any(
                    not isinstance(value, int) or value <= 0
                    for value in source_run_ids.values()
                ):
                    raise RuntimeError(
                        "evaluation dispatch requires source Actions run IDs in training receipts"
                    )
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
                    "estimated_cost_usd": wave[
                        "estimated_checkpoint_evaluation_cost_usd"
                    ],
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

    provider_parser = subparsers.add_parser("provider-snapshot")
    provider_parser.add_argument("--output", required=True)

    inventory_parser = subparsers.add_parser("write-active-inventory")
    inventory_parser.add_argument("--state-dir", required=True)
    inventory_parser.add_argument("--output", required=True)

    convergence_parser = subparsers.add_parser("converge-active-inventory")
    convergence_parser.add_argument("--state-dir", required=True)
    convergence_parser.add_argument("--output", required=True)
    convergence_parser.add_argument("--provider-output", required=True)

    audit_training_parser = subparsers.add_parser("audit-training")
    audit_training_parser.add_argument(
        "--campaign", choices=("original", "replication"), required=True
    )
    audit_training_parser.add_argument("--stage", required=True)
    audit_training_parser.add_argument("--run-key", required=True)
    audit_training_parser.add_argument("--run-dir", required=True)
    audit_training_parser.add_argument("--actions-run-id", type=int)
    audit_training_parser.add_argument("--output", required=True)

    audit_evaluation_parser = subparsers.add_parser("audit-evaluation")
    audit_evaluation_parser.add_argument(
        "--campaign", choices=("original", "replication"), required=True
    )
    audit_evaluation_parser.add_argument("--stage", required=True)
    audit_evaluation_parser.add_argument("--run-key", required=True)
    audit_evaluation_parser.add_argument("--evaluation-dir", required=True)
    audit_evaluation_parser.add_argument("--training-receipt", required=True)
    audit_evaluation_parser.add_argument("--actions-run-id", type=int)
    audit_evaluation_parser.add_argument("--output", required=True)

    next_parser = subparsers.add_parser("next")
    next_parser.add_argument("--state-dir", required=True)
    next_parser.add_argument("--active-paid-cells", type=int, required=True)
    next_parser.add_argument("--active-runs-json")
    next_parser.add_argument("--provider-snapshot")
    next_parser.add_argument("--output", required=True)

    for kind in ("training", "evaluation"):
        collect_parser = subparsers.add_parser(f"collect-{kind}")
        collect_parser.add_argument("--actions-run-id", type=int, required=True)
        collect_parser.add_argument("--state-dir", required=True)
    sync_parser = subparsers.add_parser("sync-github")
    sync_parser.add_argument("--state-dir", required=True)
    import_parser = subparsers.add_parser("import-external-completion")
    import_parser.add_argument("--state-dir", required=True)

    args = parser.parse_args()
    executor = read_json(repo_path(args.executor_config))
    plans = build_plans(executor)
    manifest = build_manifest(executor)
    if args.command == "write-manifest":
        write_json(repo_path(args.output), manifest)
    elif args.command == "provider-snapshot":
        write_json(repo_path(args.output), build_provider_snapshot(plans))
    elif args.command == "write-active-inventory":
        active_rows = write_paid_actions_inventory(
            executor=executor,
            manifest=manifest,
            state_dir=repo_path(args.state_dir),
            output=repo_path(args.output),
        )
        print(json.dumps({"active_paid_cells": len(active_rows)}))
    elif args.command == "converge-active-inventory":
        converge_paid_actions_inventory(
            executor=executor,
            plans=plans,
            manifest=manifest,
            state_dir=repo_path(args.state_dir),
            output=repo_path(args.output),
            provider_output=repo_path(args.provider_output),
        )
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
            active_runs=(
                read_json(repo_path(args.active_runs_json))
                if args.active_runs_json
                else None
            ),
            provider_snapshot=(
                read_json(repo_path(args.provider_snapshot))
                if args.provider_snapshot
                else None
            ),
        )
        write_json(repo_path(args.output), authorization)
        if authorization["action"] in {
            "dispatch_training_wave",
            "dispatch_training_resume",
            "dispatch_evaluation_wave",
        }:
            kind = (
                "evaluation"
                if authorization["action"] == "dispatch_evaluation_wave"
                else "training"
            )
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
        print(
            json.dumps(
                {
                    "action": authorization["action"],
                    "count": len(authorization["authorized_run_keys"]),
                }
            )
        )
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
                {
                    "collected": kind,
                    "run_key": receipt["run_key"] if receipt else None,
                    "valid": bool(receipt),
                }
            )
        )
    elif args.command == "import-external-completion":
        counts = import_external_completion_handoff(
            executor=executor,
            plans=plans,
            state_dir=repo_path(args.state_dir),
        )
        print(json.dumps({"external_completion_import": "complete", **counts}))
    else:
        counts = sync_github_state(
            executor=executor,
            plans=plans,
            state_dir=repo_path(args.state_dir),
        )
        print(json.dumps({"sync": "complete", **counts}))


if __name__ == "__main__":
    main()
