#!/usr/bin/env python3
"""Evaluate one terminal scaling-paradox checkpoint on both frozen endpoint partitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import importlib.util
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.io_utils import atomic_write_json  # noqa: E402
from pearl.model_rendering import RAW_RENDERER, RendererContract, renderer_diagnostics  # noqa: E402
from pearl.preference_distillation import load_jsonl  # noqa: E402
from pearl.tinker_dpo import build_dpo_datums, pair_rows_fingerprint  # noqa: E402

from run_tinker_dpo_smoke import (  # noqa: E402
    forward_preference_evaluation,
    paired_margin_diagnostics,
    resolve_base_model,
    validate_pair_rows,
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_source(contract: dict[str, Any], report: dict[str, Any]) -> None:
    if report.get("contract_sha") != contract.get("run_contract_sha"):
        raise RuntimeError("source training report and run contract differ")
    if report.get("run_key") != contract.get("run_key"):
        raise RuntimeError("source training report has the wrong run key")
    if report.get("campaign_id") != contract.get("campaign_id"):
        raise RuntimeError("source training report has the wrong campaign")
    if int(report.get("training_seed", -1)) != int(contract["training_seed"]):
        raise RuntimeError("source training report has the wrong seed")
    if len(report.get("batches", [])) != int(contract["max_steps"]):
        raise RuntimeError("source training report is not terminal")
    if not report.get("checkpoint_path"):
        raise RuntimeError("source training report has no terminal checkpoint")


def assert_no_prior_checkpoint_evaluation(contract: dict[str, Any]) -> None:
    launcher_path = ROOT / "scripts" / "launch_scaling_paradox_v1.py"
    spec = importlib.util.spec_from_file_location("checkpoint_eval_launcher", launcher_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load provider preflight")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    matches = []
    for row in launcher.provider_runs():
        metadata = row.get("user_metadata") or {}
        if (
            metadata.get("pearl_task") == "scaling_paradox_checkpoint_evaluation"
            and metadata.get("campaign_id") == contract["campaign_id"]
            and metadata.get("run_key") == contract["run_key"]
            and metadata.get("contract_sha") == contract["run_contract_sha"]
        ):
            matches.append(row)
    if matches:
        raise RuntimeError(
            "provider already contains a checkpoint evaluation for this immutable source; escalation required"
        )


def load_partition(contract: dict[str, Any], *, path_key: str, sha_key: str) -> list[dict[str, Any]]:
    path = repo_path(contract[path_key])
    if sha256_file(path) != contract[sha_key]:
        raise RuntimeError(f"partition hash mismatch for {path_key}")
    rows = load_jsonl(path)
    validate_pair_rows(rows)
    return rows


def evaluate_partition(
    *,
    policy_client: Any,
    reference_client: Any,
    rows: list[dict[str, Any]],
    tokenizer: Any,
    renderer_contract: RendererContract,
    batch_pairs: int,
) -> dict[str, Any]:
    datums, _ = build_dpo_datums(rows, tokenizer, renderer_contract=renderer_contract)
    reference = forward_preference_evaluation(
        reference_client,
        datums,
        rows,
        batch_pairs=batch_pairs,
    )
    policy = forward_preference_evaluation(
        policy_client,
        datums,
        rows,
        batch_pairs=batch_pairs,
    )
    return {
        "pair_count": len(rows),
        "pair_fingerprint": pair_rows_fingerprint(rows),
        "diagnostics": paired_margin_diagnostics(
            policy=policy,
            reference_raw=reference["raw_margins"],
            reference_per_residue=reference["per_residue_margins"],
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-contract", required=True)
    parser.add_argument("--training-report", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--eval-batch-pairs", type=int, default=64)
    parser.add_argument("--shape-only", action="store_true")
    args = parser.parse_args()

    contract_path = repo_path(args.run_contract)
    report_path = repo_path(args.training_report)
    contract = read_json(contract_path)
    report = read_json(report_path)
    validate_source(contract, report)
    holdout_rows = load_partition(
        contract,
        path_key="holdout_path",
        sha_key="holdout_sha256",
    )
    challenge_rows = load_partition(
        contract,
        path_key="challenge_path",
        sha_key="challenge_sha256",
    )
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    evaluation_identity = {
        "contract": "pearl.scaling-paradox-checkpoint-evaluation/1",
        "source_campaign_id": contract["campaign_id"],
        "source_run_key": contract["run_key"],
        "source_run_contract_sha": contract["run_contract_sha"],
        "source_run_contract_file_sha256": sha256_file(contract_path),
        "source_training_report_file_sha256": sha256_file(report_path),
        "checkpoint_path": report["checkpoint_path"],
        "checkpoint_step": int(contract["max_steps"]),
        "model": contract["model"],
        "renderer": contract["renderer"],
        "renderer_contract_fingerprint": contract["renderer_contract_fingerprint"],
        "training_seed": int(contract["training_seed"]),
        "rank": int(contract["rank"]),
        "holdout_sha256": contract["holdout_sha256"],
        "challenge_sha256": contract["challenge_sha256"],
        "holdout_pair_count": len(holdout_rows),
        "challenge_pair_count": len(challenge_rows),
        "primary_normalization": "chosen_and_rejected_logprob_sums_divided_by_respective_residue_counts",
        "evaluator_sha256": sha256_file(Path(__file__).resolve()),
    }
    evaluation_identity["evaluation_contract_sha"] = sha256_value(evaluation_identity)

    if args.shape_only:
        payload = {
            "contract": evaluation_identity,
            "status": "shape_validated",
            "complete": False,
        }
        atomic_write_json(output_dir / "evaluation_report.json", payload)
        print(json.dumps({"status": "shape_validated", "run_key": contract["run_key"]}))
        return
    if not os.environ.get("TINKER_API_KEY"):
        raise SystemExit("TINKER_API_KEY is required for checkpoint evaluation")

    import tinker

    assert_no_prior_checkpoint_evaluation(contract)
    service_client = tinker.ServiceClient()
    base_model = resolve_base_model(service_client, str(contract["model"]))
    metadata = {
        "campaign_id": str(contract["campaign_id"]),
        "run_key": str(contract["run_key"]),
        "training_seed": str(contract["training_seed"]),
        "contract_sha": str(contract["run_contract_sha"]),
    }
    policy_client = service_client.create_training_client_from_state(
        path=str(report["checkpoint_path"]),
        user_metadata={**metadata, "pearl_task": "scaling_paradox_checkpoint_evaluation"},
    )
    reference_client = service_client.create_lora_training_client(
        base_model=base_model,
        rank=int(contract["rank"]),
        seed=int(contract["training_seed"]),
        user_metadata={**metadata, "pearl_task": "scaling_paradox_reference_evaluation"},
    )
    renderer_contract = RendererContract(name=str(contract["renderer"]), model_name=base_model)
    if renderer_contract.fingerprint() != contract["renderer_contract_fingerprint"]:
        raise RuntimeError("renderer fingerprint differs from the training contract")
    tokenizer = policy_client.get_tokenizer() if contract["renderer"] == RAW_RENDERER else None
    renderer_report = renderer_diagnostics(
        str(holdout_rows[0]["prompt"]),
        str(holdout_rows[0]["chosen"]),
        tokenizer,
        renderer_contract,
    )
    if not renderer_report["generation_is_supervised_prefix"]:
        raise RuntimeError("renderer contract failed during checkpoint evaluation")

    payload = {
        "contract": evaluation_identity,
        "status": "complete",
        "complete": True,
        "holdout": evaluate_partition(
            policy_client=policy_client,
            reference_client=reference_client,
            rows=holdout_rows,
            tokenizer=tokenizer,
            renderer_contract=renderer_contract,
            batch_pairs=args.eval_batch_pairs,
        ),
        "challenge": evaluate_partition(
            policy_client=policy_client,
            reference_client=reference_client,
            rows=challenge_rows,
            tokenizer=tokenizer,
            renderer_contract=renderer_contract,
            batch_pairs=args.eval_batch_pairs,
        ),
    }
    evaluation_report_path = output_dir / "evaluation_report.json"
    atomic_write_json(evaluation_report_path, payload)
    receipt = {
        "contract": "pearl.scaling-paradox-operational-evaluation-receipt/1",
        "source_run_key": contract["run_key"],
        "source_run_contract_sha": contract["run_contract_sha"],
        "evaluation_contract_sha": evaluation_identity["evaluation_contract_sha"],
        "evaluation_report_sha256": sha256_file(evaluation_report_path),
        "holdout_complete": True,
        "holdout_pair_count": len(holdout_rows),
        "challenge_complete": True,
        "challenge_pair_count": len(challenge_rows),
        "scientific_values_omitted": True,
    }
    atomic_write_json(output_dir / "operational_evaluation_receipt.json", receipt)
    print(json.dumps({"status": "complete", "run_key": contract["run_key"]}))


if __name__ == "__main__":
    main()
