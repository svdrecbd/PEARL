from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_checkpoint_lineage(
    payload: dict[str, Any], *, contract_sha: str, terminal_step: int, checkpoint_path: str
) -> None:
    if payload.get("contract_sha") != contract_sha:
        raise RuntimeError("checkpoint lineage has the wrong contract SHA")
    rows = payload.get("checkpoints")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("checkpoint lineage is empty")
    steps = [int(row.get("step", -1)) for row in rows]
    if steps != sorted(steps) or len(set(steps)) != len(steps):
        raise RuntimeError("checkpoint lineage is not strictly ordered")
    terminal = rows[-1]
    if int(terminal.get("step", -1)) != terminal_step or not terminal.get("terminal"):
        raise RuntimeError("checkpoint lineage has no valid terminal record")
    if terminal.get("state_path") != checkpoint_path:
        raise RuntimeError("terminal checkpoint differs between report and lineage")


def audit_training_continuation_artifact(
    *,
    plan_entry: dict[str, Any],
    run_dir: Path,
    source_actions_run_id: int | None = None,
    allow_legacy_missing_report: bool = False,
) -> dict[str, Any]:
    """Validate a nonterminal, exactly resumable training artifact without endpoint reads."""

    contract_path = run_dir / "run_contract.json"
    metadata_path = run_dir / "checkpoint_meta.json"
    lineage_path = run_dir / "checkpoint_lineage.json"
    batches_path = run_dir / "batch_reports_checkpoint.json"
    reference_path = run_dir / "reference_margins.json"
    continuation_path = run_dir / "continuation_report.json"
    required = (contract_path, metadata_path, lineage_path, batches_path, reference_path)
    for path in required:
        if not path.is_file():
            raise RuntimeError(f"training continuation is missing {path.name}")
    if not continuation_path.is_file() and not allow_legacy_missing_report:
        raise RuntimeError("training continuation is missing continuation_report.json")

    contract = read_json(contract_path)
    metadata = read_json(metadata_path)
    lineage = read_json(lineage_path)
    batches = json.loads(batches_path.read_text(encoding="utf-8"))
    if contract != plan_entry:
        raise RuntimeError("continuation run contract differs from the frozen plan entry")
    if not isinstance(batches, list):
        raise RuntimeError("continuation batch history is not a list")
    contract_sha = str(plan_entry["run_contract_sha"])
    completed_steps = int(metadata.get("completed_steps", -1))
    terminal_step = int(plan_entry["max_steps"])
    if completed_steps <= 0 or completed_steps >= terminal_step:
        raise RuntimeError("continuation completed-step count is not strictly nonterminal")
    if len(batches) != completed_steps:
        raise RuntimeError("continuation batch history length differs from checkpoint metadata")

    batch_pairs = int(plan_entry["batch_pairs"])
    max_pairs = int(
        plan_entry.get("max_pairs")
        or (plan_entry.get("cost_estimate") or {}).get("pair_count")
        or 0
    )
    if batch_pairs <= 0 or max_pairs <= 0:
        raise RuntimeError("continuation plan lacks a valid batch geometry")
    batches_per_epoch = (max_pairs + batch_pairs - 1) // batch_pairs
    for index, row in enumerate(batches):
        expected_epoch, expected_batch = divmod(index, batches_per_epoch)
        if (
            not isinstance(row, dict)
            or int(row.get("epoch", -1)) != expected_epoch
            or int(row.get("batch_index", -1)) != expected_batch
        ):
            raise RuntimeError("continuation batch history is not the exact ordered trajectory")
    expected_epoch, expected_batch = divmod(completed_steps, batches_per_epoch)
    if (
        int(metadata.get("epoch", -1)) != expected_epoch
        or int(metadata.get("batch_index", -1)) != expected_batch
    ):
        raise RuntimeError("continuation cursor does not follow the recorded trajectory")

    if lineage.get("contract_sha") != contract_sha:
        raise RuntimeError("continuation checkpoint lineage has the wrong contract SHA")
    rows = lineage.get("checkpoints")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("continuation checkpoint lineage is empty")
    steps = [int(row.get("step", -1)) for row in rows]
    if steps != sorted(steps) or len(set(steps)) != len(steps):
        raise RuntimeError("continuation checkpoint lineage is not strictly ordered")
    last = rows[-1]
    checkpoint_path = str(metadata.get("state_path") or "")
    if (
        int(last.get("step", -1)) != completed_steps
        or bool(last.get("terminal"))
        or str(last.get("state_path") or "") != checkpoint_path
        or str(last.get("checkpoint_name") or "") != str(metadata.get("checkpoint_name") or "")
        or not checkpoint_path
    ):
        raise RuntimeError("continuation metadata and checkpoint lineage disagree")

    if continuation_path.is_file():
        continuation = read_json(continuation_path)
        expected = {
            "contract": "pearl.tinker-training-continuation/1",
            "campaign_id": plan_entry["campaign_id"],
            "run_key": plan_entry["run_key"],
            "run_contract_sha": contract_sha,
            "completed_steps": completed_steps,
            "target_steps": terminal_step,
            "checkpoint_path": checkpoint_path,
            "checkpoint_name": metadata["checkpoint_name"],
            "terminal": False,
        }
        if any(continuation.get(key) != value for key, value in expected.items()):
            raise RuntimeError("continuation report differs from checkpoint evidence")

    receipt = {
        "contract": "pearl.scaling-paradox-training-continuation-audit/1",
        "campaign_id": plan_entry["campaign_id"],
        "run_key": plan_entry["run_key"],
        "run_contract_sha": contract_sha,
        "source_actions_run_id": source_actions_run_id,
        "run_contract_file_sha256": sha256_file(contract_path),
        "checkpoint_metadata_file_sha256": sha256_file(metadata_path),
        "checkpoint_lineage_file_sha256": sha256_file(lineage_path),
        "batch_history_file_sha256": sha256_file(batches_path),
        "reference_margins_file_sha256": sha256_file(reference_path),
        "continuation_report_file_sha256": (
            sha256_file(continuation_path) if continuation_path.is_file() else None
        ),
        "completed_steps": completed_steps,
        "target_steps": terminal_step,
        "checkpoint_path": checkpoint_path,
        "checkpoint_lineage": [
            {
                "step": int(row["step"]),
                "state_path": str(row["state_path"]),
                "terminal": bool(row.get("terminal")),
            }
            for row in rows
        ],
        "training_continuation_valid": True,
        "scientific_values_omitted": True,
    }
    receipt["receipt_sha256"] = sha256_value(receipt)
    return receipt


def audit_training_artifact(
    *, plan_entry: dict[str, Any], run_dir: Path, source_actions_run_id: int | None = None
) -> dict[str, Any]:
    contract_path = run_dir / "run_contract.json"
    report_path = run_dir / "report.json"
    lineage_path = run_dir / "checkpoint_lineage.json"
    for path in (contract_path, report_path, lineage_path):
        if not path.is_file():
            raise RuntimeError(f"training artifact is missing {path.name}")
    contract = read_json(contract_path)
    report = read_json(report_path)
    lineage = read_json(lineage_path)
    if contract != plan_entry:
        raise RuntimeError("run contract differs from the frozen plan entry")
    contract_sha = str(plan_entry["run_contract_sha"])
    if report.get("contract_sha") != contract_sha:
        raise RuntimeError("terminal report has the wrong contract SHA")
    if report.get("run_key") != plan_entry["run_key"]:
        raise RuntimeError("terminal report has the wrong run key")
    if report.get("campaign_id") != plan_entry["campaign_id"]:
        raise RuntimeError("terminal report has the wrong campaign")
    if int(report.get("training_seed", -1)) != int(plan_entry["training_seed"]):
        raise RuntimeError("terminal report has the wrong training seed")
    if report.get("base_model") != plan_entry["model"]:
        raise RuntimeError("terminal report has the wrong model")
    if len(report.get("batches", [])) != int(plan_entry["max_steps"]):
        raise RuntimeError("terminal report has an incomplete optimizer trajectory")
    checkpoint_path = str(report.get("checkpoint_path") or "")
    if not checkpoint_path:
        raise RuntimeError("terminal report has no checkpoint path")
    validate_checkpoint_lineage(
        lineage,
        contract_sha=contract_sha,
        terminal_step=int(plan_entry["max_steps"]),
        checkpoint_path=checkpoint_path,
    )
    receipt = {
        "contract": "pearl.scaling-paradox-training-audit/1",
        "campaign_id": plan_entry["campaign_id"],
        "run_key": plan_entry["run_key"],
        "run_contract_sha": contract_sha,
        "source_actions_run_id": source_actions_run_id,
        "run_contract_file_sha256": sha256_file(contract_path),
        "training_report_file_sha256": sha256_file(report_path),
        "checkpoint_lineage_file_sha256": sha256_file(lineage_path),
        "terminal_step": int(plan_entry["max_steps"]),
        "checkpoint_path": checkpoint_path,
        "checkpoint_lineage": [
            {
                "step": int(row["step"]),
                "state_path": str(row["state_path"]),
                "terminal": bool(row.get("terminal")),
            }
            for row in lineage["checkpoints"]
        ],
        "training_terminal_valid": True,
        "scientific_values_omitted": True,
    }
    receipt["receipt_sha256"] = sha256_value(receipt)
    return receipt


def audit_evaluation_artifact(
    *,
    plan_entry: dict[str, Any],
    evaluation_dir: Path,
    training_receipt: dict[str, Any],
    partition_contracts: dict[str, dict[str, Any]],
    source_actions_run_id: int | None = None,
) -> dict[str, Any]:
    report_path = evaluation_dir / "evaluation_report.json"
    operational_path = evaluation_dir / "operational_evaluation_receipt.json"
    provider_path = evaluation_dir / "provider_identity_receipt.json"
    for path in (report_path, operational_path, provider_path):
        if not path.is_file():
            raise RuntimeError(f"evaluation artifact is missing {path.name}")
    report = read_json(report_path)
    operational = read_json(operational_path)
    provider = read_json(provider_path)
    contract = report.get("contract") or {}
    if (
        training_receipt.get("run_key") != plan_entry["run_key"]
        or training_receipt.get("run_contract_sha") != plan_entry["run_contract_sha"]
        or not training_receipt.get("training_terminal_valid")
    ):
        raise RuntimeError("checkpoint evaluation is not bound to a valid training receipt")
    if report.get("status") != "complete" or not report.get("complete"):
        raise RuntimeError("checkpoint evaluation is incomplete")
    if contract.get("source_run_key") != plan_entry["run_key"]:
        raise RuntimeError("checkpoint evaluation has the wrong run key")
    if contract.get("source_run_contract_sha") != plan_entry["run_contract_sha"]:
        raise RuntimeError("checkpoint evaluation has the wrong run contract")
    if contract.get("holdout_sha256") != plan_entry["holdout_sha256"]:
        raise RuntimeError("checkpoint evaluation has the wrong holdout partition")
    if contract.get("challenge_sha256") != plan_entry["challenge_sha256"]:
        raise RuntimeError("checkpoint evaluation has the wrong challenge partition")
    if contract.get("source_run_contract_file_sha256") != training_receipt.get(
        "run_contract_file_sha256"
    ):
        raise RuntimeError("checkpoint evaluation source contract differs from training evidence")
    if contract.get("source_training_report_file_sha256") != training_receipt.get(
        "training_report_file_sha256"
    ):
        raise RuntimeError("checkpoint evaluation source report differs from training evidence")
    if contract.get("checkpoint_path") != training_receipt.get("checkpoint_path"):
        raise RuntimeError("checkpoint evaluation used the wrong terminal checkpoint")
    if int(contract.get("checkpoint_step", -1)) != int(training_receipt.get("terminal_step", -2)):
        raise RuntimeError("checkpoint evaluation used the wrong checkpoint step")
    normalization = (
        "chosen_and_rejected_logprob_sums_divided_by_respective_residue_counts"
    )
    if contract.get("primary_normalization") != normalization:
        raise RuntimeError("checkpoint evaluation has the wrong normalization contract")
    evaluator_path = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_scaling_paradox_checkpoint.py"
    if contract.get("evaluator_sha256") != sha256_file(evaluator_path):
        raise RuntimeError("checkpoint evaluation used the wrong evaluator")
    for name in ("holdout", "challenge"):
        expected = partition_contracts[name]
        observed = report.get(name) or {}
        if int(contract.get(f"{name}_pair_count", -1)) != int(expected["pair_count"]):
            raise RuntimeError(f"checkpoint evaluation has the wrong {name} pair count")
        if int(observed.get("pair_count", -1)) != int(expected["pair_count"]):
            raise RuntimeError(f"checkpoint evaluation report has the wrong {name} pair count")
        if observed.get("pair_fingerprint") != expected["pair_fingerprint"]:
            raise RuntimeError(f"checkpoint evaluation has the wrong {name} fingerprint")
        if int(operational.get(f"{name}_pair_count", -1)) != int(expected["pair_count"]):
            raise RuntimeError(f"operational receipt has the wrong {name} pair count")
    if not operational.get("holdout_complete") or not operational.get("challenge_complete"):
        raise RuntimeError("operational evaluation receipt is incomplete")
    if operational.get("evaluation_report_sha256") != sha256_file(report_path):
        raise RuntimeError("operational evaluation receipt does not bind the report")
    if (
        provider.get("run_key") != plan_entry["run_key"]
        or provider.get("run_contract_sha") != plan_entry["run_contract_sha"]
        or not provider.get("provider_identity_valid")
        or not provider.get("provider_continuation_chain_valid")
        or provider.get("provider_corrupted") is not False
        or int(provider.get("provider_dpo_trainer_count", -1)) < 1
    ):
        raise RuntimeError("provider identity receipt is invalid")
    receipt = {
        "contract": "pearl.scaling-paradox-evaluation-audit/1",
        "campaign_id": plan_entry["campaign_id"],
        "run_key": plan_entry["run_key"],
        "run_contract_sha": plan_entry["run_contract_sha"],
        "source_actions_run_id": source_actions_run_id,
        "source_training_actions_run_id": training_receipt.get("source_actions_run_id"),
        "evaluation_contract_sha": contract.get("evaluation_contract_sha"),
        "evaluation_report_file_sha256": sha256_file(report_path),
        "operational_receipt_file_sha256": sha256_file(operational_path),
        "provider_receipt_file_sha256": sha256_file(provider_path),
        "provider_identity_valid": True,
        "holdout_complete": True,
        "challenge_complete": True,
        "evaluation_terminal_valid": True,
        "scientific_values_omitted": True,
    }
    receipt["receipt_sha256"] = sha256_value(receipt)
    return receipt


def build_wave_gate(
    *,
    campaign_id: str,
    wave_name: str,
    expected_run_keys: list[str],
    training_receipts: list[dict[str, Any]],
    evaluation_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = set(expected_run_keys)
    training = {str(row.get("run_key")): row for row in training_receipts}
    evaluation = {str(row.get("run_key")): row for row in evaluation_receipts}
    if set(training) != expected or set(evaluation) != expected:
        raise RuntimeError("wave receipts do not exactly match the expected run keys")
    if any(not row.get("training_terminal_valid") for row in training.values()):
        raise RuntimeError("wave contains an invalid training receipt")
    if any(not row.get("evaluation_terminal_valid") for row in evaluation.values()):
        raise RuntimeError("wave contains an invalid evaluation receipt")
    gate = {
        "contract": "pearl.scaling-paradox-wave-gate/1",
        "campaign_id": campaign_id,
        "wave": wave_name,
        "run_keys": expected_run_keys,
        "training_receipt_shas": [training[key]["receipt_sha256"] for key in expected_run_keys],
        "evaluation_receipt_shas": [evaluation[key]["receipt_sha256"] for key in expected_run_keys],
        "terminal_valid": True,
        "scientific_values_omitted": True,
    }
    gate["gate_sha256"] = sha256_value(gate)
    return gate


def audit_provider_identity(
    *,
    plan_entry: dict[str, Any],
    provider_rows: list[dict[str, Any]],
    checkpoint_lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for row in provider_rows:
        metadata = row.get("user_metadata") or {}
        if (
            metadata.get("pearl_task") == "physical_to_sequence_dpo"
            and metadata.get("campaign_id") == plan_entry["campaign_id"]
            and metadata.get("run_key") == plan_entry["run_key"]
            and metadata.get("contract_sha") == plan_entry["run_contract_sha"]
        ):
            matches.append(row)
    provider_ids: list[str] = []
    for match in matches:
        corrupted = match.get("corrupted", match.get("is_corrupted"))
        if corrupted is not False:
            raise RuntimeError("provider corrupted state is absent, unknown, or true")
        provider_id = match.get("id", match.get("run_id", match.get("training_run_id")))
        if provider_id in (None, ""):
            raise RuntimeError("provider DPO trainer has no stable ID")
        provider_ids.append(str(provider_id))
    if not provider_ids or len(provider_ids) != len(set(provider_ids)):
        raise RuntimeError("provider DPO trainer identities are absent or duplicated")

    if checkpoint_lineage is None:
        if len(provider_ids) != 1:
            raise RuntimeError(
                f"expected exactly one provider DPO trainer, observed {len(provider_ids)}"
            )
        lineage_provider_ids = list(provider_ids)
    else:
        if checkpoint_lineage.get("contract_sha") != plan_entry["run_contract_sha"]:
            raise RuntimeError("provider audit checkpoint lineage has the wrong contract")
        checkpoints = checkpoint_lineage.get("checkpoints")
        if not isinstance(checkpoints, list) or not checkpoints:
            raise RuntimeError("provider audit checkpoint lineage is empty")
        lineage_provider_ids: list[str] = []
        for checkpoint in checkpoints:
            state_path = str(checkpoint.get("state_path") or "")
            if not state_path.startswith("tinker://") or "/weights/" not in state_path:
                raise RuntimeError("checkpoint lineage has an invalid Tinker state path")
            provider_id = state_path.removeprefix("tinker://").split("/weights/", 1)[0]
            if provider_id not in lineage_provider_ids:
                lineage_provider_ids.append(provider_id)
        if set(lineage_provider_ids) != set(provider_ids):
            raise RuntimeError("provider DPO trainers differ from the checkpoint continuation chain")
    receipt = {
        "contract": "pearl.scaling-paradox-provider-audit/1",
        "campaign_id": plan_entry["campaign_id"],
        "run_key": plan_entry["run_key"],
        "run_contract_sha": plan_entry["run_contract_sha"],
        "provider_dpo_trainer_id": lineage_provider_ids[-1],
        "provider_dpo_trainer_ids": lineage_provider_ids,
        "provider_dpo_trainer_count": len(lineage_provider_ids),
        "provider_corrupted": False,
        "provider_continuation_chain_valid": True,
        "provider_identity_valid": True,
        "scientific_values_omitted": True,
    }
    receipt["receipt_sha256"] = sha256_value(receipt)
    return receipt
