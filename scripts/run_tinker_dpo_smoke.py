#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.io_utils import atomic_write_json
from pearl.model_rendering import RAW_RENDERER, SUPPORTED_RENDERERS, RendererContract, renderer_diagnostics
from pearl.preference_distillation import load_jsonl
from pearl.tinker_dpo import (
    build_dpo_datums,
    build_tinker_dpo_loss_fn,
    pair_rows_fingerprint,
    preference_margin_diagnostics,
    reference_margins_from_forward_result,
    split_pair_rows_grouped,
)


def main() -> None:
    args = parse_args()
    if args.eval_only and not args.init_state_path:
        raise RuntimeError("--eval-only requires --init-state-path")
    output_dir = repo_path(args.output_dir) / sanitize_name(args.name)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"

    source_pair_rows = load_jsonl(repo_path(args.pairs_path))
    if not source_pair_rows:
        raise RuntimeError("No DPO pairs were provided")
    source_shape_summary = validate_pair_rows(source_pair_rows)
    pair_rows, holdout_rows = split_pair_rows_grouped(
        source_pair_rows,
        holdout_fraction=args.holdout_fraction,
        seed=args.split_seed,
        group_field=args.holdout_group_field,
    )
    random.Random(args.training_seed).shuffle(pair_rows)
    if args.max_pairs is not None:
        pair_rows = pair_rows[: args.max_pairs]
    if args.max_holdout_pairs is not None:
        holdout_rows = holdout_rows[: args.max_holdout_pairs]
    if not pair_rows:
        raise RuntimeError("No DPO training pairs remain after splitting")
    shape_summary = validate_pair_rows(pair_rows)
    holdout_shape_summary = validate_pair_rows(holdout_rows) if holdout_rows else None
    split_summary = build_split_summary(
        args=args,
        source_pair_rows=source_pair_rows,
        train_rows=pair_rows,
        holdout_rows=holdout_rows,
    )
    challenge_rows = load_jsonl(repo_path(args.challenge_pairs_path)) if args.challenge_pairs_path else []
    if args.max_challenge_pairs is not None:
        challenge_rows = challenge_rows[: args.max_challenge_pairs]
    challenge_shape_summary = validate_pair_rows(challenge_rows) if challenge_rows else None
    challenge_summary = build_challenge_summary(
        args=args,
        train_rows=pair_rows,
        challenge_rows=challenge_rows,
    )
    if args.require_challenge_chosen_disjoint and challenge_summary["chosen_sequence_overlap_count"]:
        raise RuntimeError("Challenge chosen sequences overlap the training partition")

    if args.shape_only:
        payload = build_shape_report(
            args=args,
            pair_rows=pair_rows,
            holdout_rows=holdout_rows,
            source_shape_summary=source_shape_summary,
            shape_summary=shape_summary,
            holdout_shape_summary=holdout_shape_summary,
            challenge_rows=challenge_rows,
            challenge_shape_summary=challenge_shape_summary,
            challenge_summary=challenge_summary,
            split_summary=split_summary,
        )
        atomic_write_json(report_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    import tinker
    from tinker import types

    service_client = tinker.ServiceClient()
    base_model = resolve_base_model(service_client, args.model)
    checkpoint_meta_path = output_dir / "checkpoint_meta.json"
    start_epoch = 0
    start_batch_index = 0
    current_state_path = args.init_state_path

    if checkpoint_meta_path.exists():
        try:
            with open(checkpoint_meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            start_epoch = meta.get("epoch", 0)
            start_batch_index = meta.get("batch_index", 0)
            current_state_path = meta.get("state_path", current_state_path)
            print(f"--- AUTO-RESUME DETECTED ---", flush=True)
            print(f"Resuming training from state: {current_state_path}", flush=True)
            print(f"Starting at Epoch {start_epoch}, Batch Index {start_batch_index}", flush=True)
        except Exception as exc:
            print(f"Warning: Failed to load checkpoint metadata. Error: {exc}", flush=True)

    training_client = (
        service_client.create_training_client_from_state(
            path=current_state_path,
            user_metadata=training_user_metadata(args, task="physical_to_sequence_dpo"),
        )
        if current_state_path
        else service_client.create_lora_training_client(
            base_model=base_model,
            rank=args.rank,
            seed=args.training_seed,
            user_metadata=training_user_metadata(args, task="physical_to_sequence_dpo"),
        )
    )
    renderer_contract = RendererContract(
        name=args.renderer,
        model_name=base_model,
        reasoning_effort=args.reasoning_effort,
    )
    # Native renderers own their tokenizer. This also avoids requiring Tinker's
    # private Inkling tokenizer package in the local client environment.
    tokenizer = training_client.get_tokenizer() if args.renderer == RAW_RENDERER else None
    renderer_report = renderer_diagnostics(
        str(pair_rows[0]["prompt"]),
        str(pair_rows[0]["chosen"]),
        tokenizer,
        renderer_contract,
    )
    if not renderer_report["generation_is_supervised_prefix"]:
        raise RuntimeError("Renderer contract failed: generation prompt is not an SFT prefix")
    atomic_write_json(output_dir / "renderer_contract.json", renderer_report)
    datums, metadata = build_dpo_datums(pair_rows, tokenizer, renderer_contract=renderer_contract)
    holdout_datums, holdout_metadata = (
        build_dpo_datums(holdout_rows, tokenizer, renderer_contract=renderer_contract)
        if holdout_rows
        else ([], [])
    )
    challenge_datums, challenge_metadata = (
        build_dpo_datums(challenge_rows, tokenizer, renderer_contract=renderer_contract)
        if challenge_rows
        else ([], [])
    )

    if args.prepare_only:
        payload = build_prepare_report(
            args=args,
            base_model=base_model,
            pair_rows=pair_rows,
            metadata=metadata,
            holdout_metadata=holdout_metadata,
            challenge_metadata=challenge_metadata,
            shape_summary=shape_summary,
            holdout_shape_summary=holdout_shape_summary,
            challenge_shape_summary=challenge_shape_summary,
            challenge_summary=challenge_summary,
            split_summary=split_summary,
            checkpoint_path=current_state_path,
        )
        atomic_write_json(report_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    init_wandb_run(
        args=args,
        base_model=base_model,
        train_pair_count=len(pair_rows),
        holdout_pair_count=len(holdout_rows),
        challenge_pair_count=len(challenge_rows),
    )

    reference_margins_path = output_dir / "reference_margins.json"
    reference_margins: list[float] = []
    holdout_reference_margins: list[float] = []
    challenge_reference_margins: list[float] = []
    renderer_fingerprint = renderer_contract.fingerprint()
    train_fingerprint = f"{pair_rows_fingerprint(pair_rows)}:{renderer_fingerprint}"
    holdout_fingerprint = f"{pair_rows_fingerprint(holdout_rows)}:{renderer_fingerprint}"
    challenge_fingerprint = f"{pair_rows_fingerprint(challenge_rows)}:{renderer_fingerprint}"

    if reference_margins_path.exists():
        try:
            with open(reference_margins_path, "r", encoding="utf-8") as f:
                cached_margins = json.load(f)
            if (
                isinstance(cached_margins, dict)
                and cached_margins.get("train_fingerprint") == train_fingerprint
                and cached_margins.get("holdout_fingerprint") == holdout_fingerprint
                and cached_margins.get("challenge_fingerprint") == challenge_fingerprint
            ):
                reference_margins = list(cached_margins.get("train") or [])
                holdout_reference_margins = list(cached_margins.get("holdout") or [])
                challenge_reference_margins = list(cached_margins.get("challenge") or [])
                print("--- LOADED MATCHED REFERENCE MARGINS ---", flush=True)
            else:
                print("Ignoring stale reference-margin cache with a different data split.", flush=True)
        except Exception as exc:
            print(f"Warning: Failed to load reference margins: {exc}", flush=True)

    missing_reference_margins = (
        not reference_margins
        or (holdout_datums and not holdout_reference_margins)
        or (challenge_datums and not challenge_reference_margins)
    )
    if args.eval_only and missing_reference_margins and not args.reference_state_path:
        raise RuntimeError(
            "--eval-only requires a matching reference-margin cache or an explicit --reference-state-path"
        )
    if missing_reference_margins:
        print("--- COMPUTING REFERENCE MARGINS (Upfront Forward Pass) ---", flush=True)
        reference_state_path = args.reference_state_path or args.init_state_path
        reference_client = (
            service_client.create_training_client_from_state(
                path=reference_state_path,
                user_metadata=training_user_metadata(args, task="reference_policy"),
            )
            if reference_state_path
            else service_client.create_lora_training_client(
                base_model=base_model,
                rank=args.rank,
                seed=args.training_seed,
                user_metadata=training_user_metadata(args, task="reference_policy"),
            )
        )
        reference_margins = forward_preference_margins(
            reference_client,
            datums,
            batch_pairs=args.eval_batch_pairs,
        )
        if holdout_datums:
            holdout_reference_margins = forward_preference_margins(
                reference_client,
                holdout_datums,
                batch_pairs=args.eval_batch_pairs,
            )
        if challenge_datums:
            challenge_reference_margins = forward_preference_margins(
                reference_client,
                challenge_datums,
                batch_pairs=args.eval_batch_pairs,
            )
        try:
            with open(reference_margins_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "train_fingerprint": train_fingerprint,
                        "holdout_fingerprint": holdout_fingerprint,
                        "challenge_fingerprint": challenge_fingerprint,
                        "train": reference_margins,
                        "holdout": holdout_reference_margins,
                        "challenge": challenge_reference_margins,
                    },
                    f,
                    indent=2,
                )
            print(f"Saved reference margins to: {reference_margins_path}", flush=True)
        except Exception as exc:
            print(f"Warning: Failed to save reference margins: {exc}", flush=True)

    adam_params = types.AdamParams(
        learning_rate=args.learning_rate,
        beta1=0.9,
        beta2=0.95,
        eps=1e-8,
    )
    batch_reports: list[dict[str, Any]] = []
    batches_per_epoch = (len(pair_rows) + args.batch_pairs - 1) // args.batch_pairs

    # If resuming, load existing batch reports from earlier checkpoint
    if start_batch_index > 0:
        reports_file = output_dir / "batch_reports_checkpoint.json"
        if reports_file.exists():
            try:
                with open(reports_file, "r", encoding="utf-8") as f:
                    batch_reports = json.load(f)
                print(f"Loaded {len(batch_reports)} historical batch reports.", flush=True)
            except Exception as exc:
                print(f"Warning: Failed to load historical batch reports: {exc}", flush=True)

    training_epochs = 0 if args.eval_only else args.epochs
    if args.max_steps and not args.eval_only:
        needed_epochs = (args.max_steps + batches_per_epoch - 1) // batches_per_epoch
        training_epochs = max(training_epochs, needed_epochs)

    for epoch in range(start_epoch, training_epochs):
        current_start_batch = start_batch_index if epoch == start_epoch else 0
        for batch_index, batch_start in enumerate(range(0, len(pair_rows), args.batch_pairs)):
            if batch_index < current_start_batch:
                continue

            batch_pair_count = min(args.batch_pairs, len(pair_rows) - batch_start)
            datum_start = batch_start * 2
            datum_end = datum_start + (batch_pair_count * 2)
            batch_datums = datums[datum_start:datum_end]
            batch_reference_margins = reference_margins[batch_start : batch_start + batch_pair_count]
            dpo_loss_fn = build_tinker_dpo_loss_fn(reference_margins=batch_reference_margins, beta=args.beta)
            forward_backward_result = forward_backward_custom_logprobs(training_client, batch_datums, dpo_loss_fn)
            optim_step_result = training_client.optim_step(adam_params).result()

            batch_report = {
                "epoch": epoch,
                "batch_index": batch_index,
                "batch_pair_count": batch_pair_count,
                "forward_backward_metrics": forward_backward_result.metrics,
                "optim_step_metrics": optim_step_result.metrics,
            }
            batch_reports.append(batch_report)
            print(json.dumps(batch_report), flush=True)

            # Auto-save state every 50 batches (but not on the very last batch of training)
            is_last_batch = (epoch == training_epochs - 1) and (batch_start + args.batch_pairs >= len(pair_rows))

            # W&B Logging
            try:
                import wandb

                # Initialize wandb on the very first batch
                # Combine forward/backward & optimization metrics
                log_data = {
                    "epoch": epoch,
                    "batch_index": batch_index,
                    "global_step": epoch * batches_per_epoch + batch_index,
                }
                if "forward_backward_metrics" in batch_report:
                    for k, v in batch_report["forward_backward_metrics"].items():
                        log_data[f"train/{k}"] = v
                if "optim_step_metrics" in batch_report:
                    for k, v in batch_report["optim_step_metrics"].items():
                        log_data[f"train/optim_{k}"] = v
                wandb.log(log_data)
            except Exception:
                # Silently catch import or network errors to not interrupt training
                pass

            total_steps = len(batch_reports)
            if args.max_steps and total_steps >= args.max_steps:
                print(f"Reached max_steps ({args.max_steps}), stopping training.", flush=True)
                break

            if args.save_every_steps and (total_steps % args.save_every_steps == 0 or total_steps == 1):
                print(f"--- AUTO-CHECKPOINTING (Step {total_steps}) ---", flush=True)
                checkpoint_name = f"{sanitize_name(args.name)}-chkpt-step{total_steps}"
                try:
                    chkpt_result = training_client.save_state(checkpoint_name).result()
                    next_epoch = epoch
                    next_batch_index = batch_index + 1
                    if next_batch_index >= batches_per_epoch:
                        next_epoch += 1
                        next_batch_index = 0
                    atomic_write_json(
                        checkpoint_meta_path,
                        {
                            "epoch": next_epoch,
                            "batch_index": next_batch_index,
                            "state_path": chkpt_result.path,
                            "checkpoint_name": checkpoint_name,
                            "completed_steps": total_steps,
                        },
                    )
                    atomic_write_json(output_dir / "batch_reports_checkpoint.json", batch_reports)
                    print(f"Checkpoint saved at step {total_steps}: {chkpt_result.path}", flush=True)
                except Exception as exc:
                    print(f"Warning: Failed to save intermediate checkpoint: {exc}", flush=True)
        if args.max_steps and len(batch_reports) >= args.max_steps:
            break

    # Clean up checkpoint metadata if training finished successfully
    if checkpoint_meta_path.exists():
        try:
            checkpoint_meta_path.unlink()
            reports_file = output_dir / "batch_reports_checkpoint.json"
            if reports_file.exists():
                reports_file.unlink()
        except Exception:
            pass

    checkpoint_path = args.init_state_path
    if not args.eval_only:
        save_result = training_client.save_state(args.checkpoint_name or sanitize_name(args.name)).result()
        checkpoint_path = save_result.path
    holdout_diagnostics = None
    if holdout_datums:
        holdout_policy_margins = forward_preference_margins(
            training_client,
            holdout_datums,
            batch_pairs=args.eval_batch_pairs,
        )
        holdout_diagnostics = preference_margin_diagnostics(
            policy_margins=holdout_policy_margins,
            reference_margins=holdout_reference_margins,
        )
    challenge_diagnostics = None
    if challenge_datums:
        challenge_policy_margins = forward_preference_margins(
            training_client,
            challenge_datums,
            batch_pairs=args.eval_batch_pairs,
        )
        challenge_diagnostics = preference_margin_diagnostics(
            policy_margins=challenge_policy_margins,
            reference_margins=challenge_reference_margins,
        )
    log_evaluation_to_wandb(
        holdout_diagnostics=holdout_diagnostics,
        challenge_diagnostics=challenge_diagnostics,
    )
    report = {
        "name": args.name,
        "base_model": base_model,
        "pairs_path": str(repo_path(args.pairs_path)),
        "pair_count": len(pair_rows),
        "holdout_pair_count": len(holdout_rows),
        "challenge_pair_count": len(challenge_rows),
        "epochs": args.epochs,
        "evaluation_only": args.eval_only,
        "batch_pairs": args.batch_pairs,
        "beta": args.beta,
        "learning_rate": args.learning_rate,
        "rank": args.rank,
        "training_seed": args.training_seed,
        "campaign_id": args.campaign_id,
        "run_key": args.run_key or args.name,
        "contract_sha": args.contract_sha,
        "renderer": renderer_report,
        "init_state_path": args.init_state_path,
        "reference_state_path": args.reference_state_path,
        "split": split_summary,
        "holdout_preference_diagnostics": holdout_diagnostics,
        "challenge": challenge_summary,
        "challenge_preference_diagnostics": challenge_diagnostics,
        "checkpoint_path": checkpoint_path,
        "batches": batch_reports,
    }
    atomic_write_json(report_path, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    finish_wandb_run()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a small Tinker custom-loss DPO smoke from PEARL Phase 8 or physical preference pairs."
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("--wandb-name")
    parser.add_argument("--wandb-project", default="pearl-dpo")
    parser.add_argument("--pairs-path", required=True)
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "tinker_dpo_smoke"))
    parser.add_argument("--model", default="moonshotai/Kimi-K2.6")
    parser.add_argument("--renderer", choices=SUPPORTED_RENDERERS, default=RAW_RENDERER)
    parser.add_argument("--reasoning-effort", type=float, default=0.0)
    parser.add_argument("--init-state-path")
    parser.add_argument("--reference-state-path")
    parser.add_argument("--checkpoint-name")
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--max-steps", type=int, help="Optional max optimizer steps limit (overrides epochs when reached)")
    parser.add_argument("--save-every-steps", type=int, default=500, help="Save intermediate state checkpoint every N steps")
    parser.add_argument("--batch-pairs", type=int, default=4)
    parser.add_argument("--max-pairs", type=int)
    parser.add_argument("--max-holdout-pairs", type=int)
    parser.add_argument("--challenge-pairs-path")
    parser.add_argument("--max-challenge-pairs", type=int)
    parser.add_argument("--require-challenge-chosen-disjoint", action="store_true")
    parser.add_argument("--holdout-fraction", type=float, default=0.0)
    parser.add_argument("--holdout-group-field", default="chosen_record_id")
    parser.add_argument("--split-seed", type=int, default=20260806)
    parser.add_argument(
        "--training-seed",
        type=int,
        default=20260806,
        help="Tinker LoRA initialization seed and deterministic training-row order seed",
    )
    parser.add_argument("--campaign-id", default="pearl-phase8")
    parser.add_argument("--run-key")
    parser.add_argument("--contract-sha")
    parser.add_argument("--eval-batch-pairs", type=int, default=64)
    parser.add_argument("--beta", type=float, default=0.05)
    parser.add_argument("--learning-rate", type=float, default=5e-7)
    parser.add_argument("--shape-only", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--eval-only", action="store_true")
    return parser.parse_args()


def training_user_metadata(args: argparse.Namespace, *, task: str) -> dict[str, str]:
    metadata = {
        "pearl_task": task,
        "campaign_id": str(args.campaign_id),
        "run_key": str(args.run_key or args.name),
        "training_seed": str(args.training_seed),
    }
    if args.contract_sha:
        metadata["contract_sha"] = str(args.contract_sha)
    return metadata


def resolve_base_model(service_client: Any, requested_model: str) -> str:
    capabilities = service_client.get_server_capabilities()
    supported_models = [model.model_name for model in capabilities.supported_models]
    if requested_model not in supported_models:
        raise RuntimeError(f"Requested model {requested_model!r} is not supported. Supported: {supported_models}")
    return requested_model


def build_prepare_report(
    *,
    args: argparse.Namespace,
    base_model: str,
    pair_rows: list[dict[str, Any]],
    metadata: list[Any],
    holdout_metadata: list[Any],
    challenge_metadata: list[Any],
    shape_summary: dict[str, Any],
    holdout_shape_summary: dict[str, Any] | None,
    challenge_shape_summary: dict[str, Any] | None,
    challenge_summary: dict[str, Any],
    split_summary: dict[str, Any],
    checkpoint_path: str | None,
) -> dict[str, Any]:
    return {
        "name": args.name,
        "status": "prepared",
        "base_model": base_model,
        "pairs_path": str(repo_path(args.pairs_path)),
        "pair_count": len(pair_rows),
        "datum_count": len(metadata),
        "holdout_datum_count": len(holdout_metadata),
        "challenge_datum_count": len(challenge_metadata),
        "beta": args.beta,
        "learning_rate": args.learning_rate,
        "rank": args.rank,
        "training_seed": args.training_seed,
        "campaign_id": args.campaign_id,
        "run_key": args.run_key or args.name,
        "contract_sha": args.contract_sha,
        "init_state_path": args.init_state_path,
        "reference_state_path": args.reference_state_path,
        "checkpoint_path": checkpoint_path,
        "shape_summary": shape_summary,
        "holdout_shape_summary": holdout_shape_summary,
        "challenge_shape_summary": challenge_shape_summary,
        "challenge": challenge_summary,
        "split": split_summary,
        "first_pair": {
            "chosen_id": pair_rows[0].get("chosen_id"),
            "rejected_id": pair_rows[0].get("rejected_id"),
            "preference_rule": pair_rows[0].get("preference_rule"),
        },
    }


def build_shape_report(
    *,
    args: argparse.Namespace,
    pair_rows: list[dict[str, Any]],
    holdout_rows: list[dict[str, Any]],
    challenge_rows: list[dict[str, Any]],
    source_shape_summary: dict[str, Any],
    shape_summary: dict[str, Any],
    holdout_shape_summary: dict[str, Any] | None,
    challenge_shape_summary: dict[str, Any] | None,
    challenge_summary: dict[str, Any],
    split_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "name": args.name,
        "status": "shape_validated",
        "pairs_path": str(repo_path(args.pairs_path)),
        "pair_count": len(pair_rows),
        "holdout_pair_count": len(holdout_rows),
        "challenge_pair_count": len(challenge_rows),
        "datum_count": len(pair_rows) * 2,
        "holdout_datum_count": len(holdout_rows) * 2,
        "challenge_datum_count": len(challenge_rows) * 2,
        "source_shape_summary": source_shape_summary,
        "shape_summary": shape_summary,
        "holdout_shape_summary": holdout_shape_summary,
        "challenge_shape_summary": challenge_shape_summary,
        "challenge": challenge_summary,
        "split": split_summary,
        "tinker_client_created": False,
        "first_pair": {
            "chosen_id": pair_rows[0].get("chosen_id"),
            "rejected_id": pair_rows[0].get("rejected_id"),
            "preference_rule": pair_rows[0].get("preference_rule"),
        },
    }


def build_split_summary(
    *,
    args: argparse.Namespace,
    source_pair_rows: list[dict[str, Any]],
    train_rows: list[dict[str, Any]],
    holdout_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    def overlap_count(field: str) -> int:
        train_values = {str(row.get(field) or "") for row in train_rows}
        holdout_values = {str(row.get(field) or "") for row in holdout_rows}
        return len((train_values & holdout_values) - {""})

    return {
        "source_pair_count": len(source_pair_rows),
        "train_pair_count": len(train_rows),
        "holdout_pair_count": len(holdout_rows),
        "holdout_fraction_requested": args.holdout_fraction,
        "holdout_fraction_observed": len(holdout_rows) / len(source_pair_rows),
        "group_field": args.holdout_group_field,
        "seed": args.split_seed,
        "train_fingerprint": pair_rows_fingerprint(train_rows),
        "holdout_fingerprint": pair_rows_fingerprint(holdout_rows),
        "chosen_group_overlap_count": overlap_count(args.holdout_group_field),
        "chosen_sequence_overlap_count": overlap_count("chosen"),
        "prompt_overlap_count": overlap_count("prompt"),
    }


def build_challenge_summary(
    *,
    args: argparse.Namespace,
    train_rows: list[dict[str, Any]],
    challenge_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    train_chosen = {str(row.get("chosen") or "") for row in train_rows}
    challenge_chosen = {str(row.get("chosen") or "") for row in challenge_rows}
    train_rejected = {str(row.get("rejected") or "") for row in train_rows}
    challenge_rejected = {str(row.get("rejected") or "") for row in challenge_rows}
    return {
        "path": str(repo_path(args.challenge_pairs_path)) if args.challenge_pairs_path else None,
        "pair_count": len(challenge_rows),
        "fingerprint": pair_rows_fingerprint(challenge_rows),
        "chosen_sequence_overlap_count": len((train_chosen & challenge_chosen) - {""}),
        "rejected_sequence_overlap_count": len((train_rejected & challenge_rejected) - {""}),
    }


def validate_pair_rows(pair_rows: list[dict[str, Any]]) -> dict[str, Any]:
    required_fields = ("prompt", "chosen", "rejected")
    issues: list[str] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    duplicate_pair_count = 0
    identical_choice_count = 0
    prompts: list[str] = []
    chosen_sequences: list[str] = []
    rejected_sequences: list[str] = []
    preference_rules: Counter[str] = Counter()

    for row_index, row in enumerate(pair_rows):
        row_values: dict[str, str] = {}
        if not isinstance(row, dict):
            issues.append(f"row {row_index}: expected object, observed {type(row).__name__}")
            continue
        for field_name in required_fields:
            value = row.get(field_name)
            if not isinstance(value, str) or not value.strip():
                issues.append(f"row {row_index}: missing non-empty {field_name!r}")
                continue
            row_values[field_name] = value
        if len(row_values) != len(required_fields):
            continue

        prompts.append(row_values["prompt"])
        chosen_sequences.append(row_values["chosen"])
        rejected_sequences.append(row_values["rejected"])
        if row_values["chosen"] == row_values["rejected"]:
            identical_choice_count += 1
            issues.append(f"row {row_index}: chosen and rejected are identical")
        pair_key = (row_values["prompt"], row_values["chosen"], row_values["rejected"])
        if pair_key in seen_pairs:
            duplicate_pair_count += 1
        seen_pairs.add(pair_key)
        preference_rule = row.get("preference_rule")
        if isinstance(preference_rule, str) and preference_rule:
            preference_rules[preference_rule] += 1

    if issues:
        preview = "; ".join(issues[:10])
        suffix = "" if len(issues) <= 10 else f"; plus {len(issues) - 10} more"
        raise RuntimeError(f"DPO pair shape validation failed: {preview}{suffix}")

    return {
        "unique_prompt_count": len(set(prompts)),
        "duplicate_pair_count": duplicate_pair_count,
        "identical_chosen_rejected_count": identical_choice_count,
        "prompt_chars": length_stats(prompts),
        "chosen_chars": length_stats(chosen_sequences),
        "rejected_chars": length_stats(rejected_sequences),
        "preference_rules": dict(sorted(preference_rules.items())),
    }


def length_stats(values: list[str]) -> dict[str, float]:
    lengths = [len(value) for value in values]
    return {
        "min": float(min(lengths)),
        "max": float(max(lengths)),
        "mean": float(sum(lengths) / len(lengths)),
    }


def forward_backward_custom_logprobs(training_client: Any, batch_datums: list[Any], dpo_loss_fn: Any) -> Any:
    try:
        return training_client.forward_backward_custom(
            batch_datums,
            dpo_loss_fn,
            loss_type_input="logprobs",
        ).result()
    except TypeError as exc:
        message = str(exc)
        if "loss_type_input" not in message:
            raise
        return training_client.forward_backward_custom(batch_datums, dpo_loss_fn).result()


def init_wandb_run(
    *,
    args: argparse.Namespace,
    base_model: str,
    train_pair_count: int,
    holdout_pair_count: int,
    challenge_pair_count: int,
) -> None:
    try:
        import wandb

        if wandb.run is None:
            wandb.init(
                project=args.wandb_project,
                name=args.wandb_name or args.name,
                config={
                    "model": base_model,
                    "learning_rate": args.learning_rate,
                    "beta": args.beta,
                    "epochs": args.epochs,
                    "batch_pairs": args.batch_pairs,
                    "rank": args.rank,
                    "training_seed": args.training_seed,
                    "campaign_id": args.campaign_id,
                    "run_key": args.run_key or args.name,
                    "contract_sha": args.contract_sha,
                    "renderer": args.renderer,
                    "reasoning_effort": args.reasoning_effort,
                    "init_state_path": args.init_state_path,
                    "pairs_path": args.pairs_path,
                    "split_seed": args.split_seed,
                    "holdout_fraction": args.holdout_fraction,
                    "holdout_group_field": args.holdout_group_field,
                    "train_pair_count": train_pair_count,
                    "holdout_pair_count": holdout_pair_count,
                    "challenge_pair_count": challenge_pair_count,
                    "evaluation_only": args.eval_only,
                },
            )
            wandb.log(
                {
                    "run/reference_phase_started": 1,
                    "run/train_pair_count": train_pair_count,
                    "run/holdout_pair_count": holdout_pair_count,
                    "run/challenge_pair_count": challenge_pair_count,
                }
            )
    except Exception as exc:
        print(f"Warning: W&B initialization failed: {exc}", flush=True)


def log_evaluation_to_wandb(
    *,
    holdout_diagnostics: dict[str, Any] | None,
    challenge_diagnostics: dict[str, Any] | None,
) -> None:
    try:
        import wandb

        if wandb.run is None:
            return
        metrics: dict[str, Any] = {"run/evaluation_completed": 1}
        for split_name, diagnostics in (
            ("holdout", holdout_diagnostics),
            ("challenge", challenge_diagnostics),
        ):
            if diagnostics:
                metrics.update({f"eval/{split_name}/{key}": value for key, value in diagnostics.items()})
        wandb.log(metrics)
    except Exception as exc:
        print(f"Warning: W&B evaluation logging failed: {exc}", flush=True)


def finish_wandb_run() -> None:
    try:
        import wandb

        if wandb.run is not None:
            wandb.finish()
    except Exception as exc:
        print(f"Warning: W&B finalization failed: {exc}", flush=True)


def forward_preference_margins(
    training_client: Any,
    datums: list[Any],
    *,
    batch_pairs: int,
) -> list[float]:
    if batch_pairs <= 0:
        raise ValueError("eval_batch_pairs must be positive")
    margins: list[float] = []
    batch_datums = batch_pairs * 2
    for start in range(0, len(datums), batch_datums):
        batch = datums[start : start + batch_datums]
        result = training_client.forward(batch, "cross_entropy").result()
        margins.extend(reference_margins_from_forward_result(result, batch))
    return margins


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path


def sanitize_name(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "-" for char in value]
    sanitized = "".join(chars).strip("-")
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized or "tinker-dpo-smoke"


if __name__ == "__main__":
    main()
