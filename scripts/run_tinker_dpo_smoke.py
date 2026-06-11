#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.io_utils import atomic_write_json
from pearl.preference_distillation import load_jsonl
from pearl.tinker_dpo import build_dpo_datums, build_tinker_dpo_loss_fn, reference_margins_from_forward_result


def main() -> None:
    args = parse_args()
    output_dir = repo_path(args.output_dir) / sanitize_name(args.name)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"

    pair_rows = load_jsonl(repo_path(args.pairs_path))
    if args.max_pairs is not None:
        pair_rows = pair_rows[: args.max_pairs]
    if not pair_rows:
        raise RuntimeError("No DPO pairs were provided")
    shape_summary = validate_pair_rows(pair_rows)

    if args.shape_only:
        payload = build_shape_report(args=args, pair_rows=pair_rows, shape_summary=shape_summary)
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
        service_client.create_training_client_from_state(path=current_state_path)
        if current_state_path
        else service_client.create_lora_training_client(
            base_model=base_model,
            rank=args.rank,
            user_metadata={"pearl_task": "physical_to_sequence_dpo"},
        )
    )
    tokenizer = training_client.get_tokenizer()
    datums, metadata = build_dpo_datums(pair_rows, tokenizer)

    if args.prepare_only:
        payload = build_prepare_report(
            args=args,
            base_model=base_model,
            pair_rows=pair_rows,
            metadata=metadata,
            shape_summary=shape_summary,
            checkpoint_path=current_state_path,
        )
        atomic_write_json(report_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    reference_margins_path = output_dir / "reference_margins.json"
    reference_margins: list[float] = []

    if reference_margins_path.exists():
        try:
            with open(reference_margins_path, "r", encoding="utf-8") as f:
                reference_margins = json.load(f)
            print("--- LOADED REFERENCE MARGINS (Skipping expensive forward pass!) ---", flush=True)
        except Exception as exc:
            print(f"Warning: Failed to load reference margins: {exc}", flush=True)

    if not reference_margins:
        print("--- COMPUTING REFERENCE MARGINS (Upfront Forward Pass) ---", flush=True)
        # If no explicit reference checkpoint is supplied, freeze the initial policy
        # by computing all reference margins before any optimizer step.
        reference_client = (
            service_client.create_training_client_from_state(path=args.reference_state_path)
            if args.reference_state_path
            else service_client.create_lora_training_client(
                base_model=base_model,
                rank=args.rank,
                user_metadata={"pearl_task": "reference_policy"},
            )
        )
        reference_forward = reference_client.forward(datums, "cross_entropy").result()
        reference_margins = reference_margins_from_forward_result(reference_forward, datums)
        try:
            with open(reference_margins_path, "w", encoding="utf-8") as f:
                json.dump(reference_margins, f, indent=2)
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

    for epoch in range(start_epoch, args.epochs):
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
            is_last_batch = (epoch == args.epochs - 1) and (batch_start + args.batch_pairs >= len(pair_rows))

            # W&B Logging
            try:
                import wandb

                # Initialize wandb on the very first batch
                if epoch == start_epoch and batch_index == current_start_batch:
                    wandb.init(
                        project="pearl-dpo",
                        name=args.name,
                        config={
                            "model": base_model,
                            "learning_rate": args.learning_rate,
                            "beta": args.beta,
                            "epochs": args.epochs,
                            "batch_pairs": args.batch_pairs,
                            "rank": args.rank,
                            "init_state_path": args.init_state_path,
                            "pairs_path": args.pairs_path,
                        }
                    )

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

            if (batch_index + 1) % 50 == 0 and not is_last_batch:
                print(f"--- AUTO-CHECKPOINTING (Batch {batch_index}) ---", flush=True)
                checkpoint_name = f"{sanitize_name(args.name)}-chkpt-e{epoch}-b{batch_index}"
                try:
                    chkpt_result = training_client.save_state(checkpoint_name).result()
                    meta_payload = {
                        "epoch": epoch,
                        "batch_index": batch_index + 1,
                        "state_path": chkpt_result.path,
                        "checkpoint_name": checkpoint_name,
                    }
                    with open(checkpoint_meta_path, "w", encoding="utf-8") as f:
                        json.dump(meta_payload, f, indent=2)
                    
                    with open(output_dir / "batch_reports_checkpoint.json", "w", encoding="utf-8") as f:
                        json.dump(batch_reports, f, indent=2)
                        
                    print(f"Checkpoint saved: {chkpt_result.path}", flush=True)
                except Exception as exc:
                    print(f"Warning: Failed to save intermediate checkpoint: {exc}", flush=True)

    # Clean up checkpoint metadata if training finished successfully
    if checkpoint_meta_path.exists():
        try:
            checkpoint_meta_path.unlink()
            reports_file = output_dir / "batch_reports_checkpoint.json"
            if reports_file.exists():
                reports_file.unlink()
            if reference_margins_path.exists():
                reference_margins_path.unlink()
        except Exception:
            pass

    try:
        import wandb
        if wandb.run is not None:
            wandb.finish()
    except Exception:
        pass

    save_result = training_client.save_state(args.checkpoint_name or sanitize_name(args.name)).result()
    report = {
        "name": args.name,
        "base_model": base_model,
        "pairs_path": str(repo_path(args.pairs_path)),
        "pair_count": len(pair_rows),
        "epochs": args.epochs,
        "batch_pairs": args.batch_pairs,
        "beta": args.beta,
        "learning_rate": args.learning_rate,
        "rank": args.rank,
        "init_state_path": args.init_state_path,
        "reference_state_path": args.reference_state_path,
        "checkpoint_path": save_result.path,
        "batches": batch_reports,
    }
    atomic_write_json(report_path, report)
    print(json.dumps(report, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a small Tinker custom-loss DPO smoke from PEARL Phase 8 or physical preference pairs."
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("--pairs-path", required=True)
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "tinker_dpo_smoke"))
    parser.add_argument("--model", default="moonshotai/Kimi-K2.5")
    parser.add_argument("--init-state-path")
    parser.add_argument("--reference-state-path")
    parser.add_argument("--checkpoint-name")
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-pairs", type=int, default=4)
    parser.add_argument("--max-pairs", type=int)
    parser.add_argument("--beta", type=float, default=0.05)
    parser.add_argument("--learning-rate", type=float, default=5e-7)
    parser.add_argument("--shape-only", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    return parser.parse_args()


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
    shape_summary: dict[str, Any],
    checkpoint_path: str | None,
) -> dict[str, Any]:
    return {
        "name": args.name,
        "status": "prepared",
        "base_model": base_model,
        "pairs_path": str(repo_path(args.pairs_path)),
        "pair_count": len(pair_rows),
        "datum_count": len(metadata),
        "beta": args.beta,
        "learning_rate": args.learning_rate,
        "rank": args.rank,
        "init_state_path": args.init_state_path,
        "reference_state_path": args.reference_state_path,
        "checkpoint_path": checkpoint_path,
        "shape_summary": shape_summary,
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
    shape_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "name": args.name,
        "status": "shape_validated",
        "pairs_path": str(repo_path(args.pairs_path)),
        "pair_count": len(pair_rows),
        "datum_count": len(pair_rows) * 2,
        "shape_summary": shape_summary,
        "tinker_client_created": False,
        "first_pair": {
            "chosen_id": pair_rows[0].get("chosen_id"),
            "rejected_id": pair_rows[0].get("rejected_id"),
            "preference_rule": pair_rows[0].get("preference_rule"),
        },
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
