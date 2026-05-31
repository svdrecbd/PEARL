#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.io_utils import atomic_write_json
from pearl.opd_lite import build_sparse_cross_entropy_datum, validate_sparse_target_rows
from pearl.preference_distillation import load_jsonl


def main() -> None:
    args = parse_args()
    output_dir = repo_path(args.output_dir) / sanitize_name(args.name)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"

    target_rows = load_jsonl(repo_path(args.targets_path))
    if args.max_rows is not None:
        target_rows = target_rows[: args.max_rows]
    if not target_rows:
        raise RuntimeError("No sparse OPD target rows were provided")
    shape_summary = validate_target_rows(target_rows)

    if args.shape_only:
        payload = {
            "name": args.name,
            "status": "shape_validated",
            "targets_path": str(repo_path(args.targets_path)),
            "target_count": len(target_rows),
            "shape_summary": shape_summary,
            "tinker_client_created": False,
        }
        atomic_write_json(report_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    import tinker
    from tinker import types

    service_client = tinker.ServiceClient()
    base_model = resolve_base_model(service_client, args.model)
    training_client = (
        service_client.create_training_client_from_state(path=args.init_state_path)
        if args.init_state_path
        else service_client.create_lora_training_client(
            base_model=base_model,
            rank=args.rank,
            user_metadata={"pearl_task": "sparse_opd_topk_distillation"},
        )
    )
    tokenizer = training_client.get_tokenizer()
    datums = [build_sparse_cross_entropy_datum(row, tokenizer) for row in target_rows]

    if args.prepare_only:
        payload = {
            "name": args.name,
            "status": "prepared",
            "base_model": base_model,
            "targets_path": str(repo_path(args.targets_path)),
            "target_count": len(target_rows),
            "datum_count": len(datums),
            "rank": args.rank,
            "learning_rate": args.learning_rate,
            "init_state_path": args.init_state_path,
            "shape_summary": shape_summary,
        }
        atomic_write_json(report_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    adam_params = types.AdamParams(
        learning_rate=args.learning_rate,
        beta1=0.9,
        beta2=0.95,
        eps=1e-8,
    )
    batch_reports: list[dict[str, Any]] = []
    for epoch in range(args.epochs):
        for batch_index, batch_start in enumerate(range(0, len(datums), args.batch_size)):
            batch_datums = datums[batch_start : batch_start + args.batch_size]
            forward_backward_result = training_client.forward_backward(batch_datums, "cross_entropy").result()
            optim_step_result = training_client.optim_step(adam_params).result()
            batch_report = {
                "epoch": epoch,
                "batch_index": batch_index,
                "batch_size": len(batch_datums),
                "forward_backward_metrics": forward_backward_result.metrics,
                "optim_step_metrics": optim_step_result.metrics,
            }
            batch_reports.append(batch_report)
            print(json.dumps(batch_report), flush=True)

    save_result = training_client.save_state(args.checkpoint_name or sanitize_name(args.name)).result()
    report = {
        "name": args.name,
        "status": "trained",
        "base_model": base_model,
        "targets_path": str(repo_path(args.targets_path)),
        "target_count": len(target_rows),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "rank": args.rank,
        "init_state_path": args.init_state_path,
        "checkpoint_path": save_result.path,
        "shape_summary": shape_summary,
        "batches": batch_reports,
    }
    atomic_write_json(report_path, report)
    print(json.dumps(report, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a small Tinker sparse-OPD top-K distillation smoke from prebuilt target rows."
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("--targets-path", required=True)
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "tinker_sparse_opd_smoke"))
    parser.add_argument("--model", default="moonshotai/Kimi-K2.6")
    parser.add_argument("--init-state-path")
    parser.add_argument("--checkpoint-name")
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--learning-rate", type=float, default=5e-7)
    parser.add_argument("--shape-only", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    return parser.parse_args()


def validate_target_rows(target_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return validate_sparse_target_rows(target_rows)


def resolve_base_model(service_client: Any, requested_model: str) -> str:
    capabilities = service_client.get_server_capabilities()
    supported_models = [model.model_name for model in capabilities.supported_models]
    if requested_model not in supported_models:
        raise RuntimeError(f"Requested model {requested_model!r} is not supported. Supported: {supported_models}")
    return requested_model


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
    return sanitized or "tinker-sparse-opd-smoke"


if __name__ == "__main__":
    main()
