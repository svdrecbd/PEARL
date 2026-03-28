from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path
from typing import Any

import numpy as np
import tinker
from tinker import types

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import build_sequence_prompt, resolve_base_model
from petase_family import compute_family_stats, load_reference_records


def main() -> None:
    args = parse_args()
    random_generator = random.Random(args.seed)
    output_dir = Path(args.output_dir) / sanitize_name(args.name)
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset_rows = load_jsonl(Path(args.dataset_path))
    if args.max_examples is not None:
        dataset_rows = dataset_rows[: args.max_examples]
    reference_records = load_reference_records(Path(args.records_path))
    family_stats = compute_family_stats(reference_records)

    service_client = tinker.ServiceClient()
    base_model, supported_models = resolve_base_model(service_client)
    training_client = (
        service_client.create_training_client_from_state(path=args.init_state_path)
        if args.init_state_path
        else service_client.create_lora_training_client(base_model=base_model, rank=args.rank)
    )
    tokenizer = training_client.get_tokenizer()
    adam_params = types.AdamParams(
        learning_rate=args.learning_rate,
        beta1=0.9,
        beta2=0.95,
        eps=1e-8,
    )

    batch_reports: list[dict[str, Any]] = []
    pair_reports: list[dict[str, Any]] = []
    for epoch in range(args.epochs):
        epoch_rows = list(dataset_rows)
        random_generator.shuffle(epoch_rows)
        for batch_index, batch_rows in enumerate(chunked(epoch_rows, args.batch_size)):
            datums: list[types.Datum] = []
            for row in batch_rows:
                prompt = resolve_training_prompt(row)
                sequence_prompt = build_sequence_prompt(prompt, family_stats)
                prompt_input = types.ModelInput.from_ints(
                    tokenizer.encode(sequence_prompt, add_special_tokens=False)
                )
                target_tokens = tokenizer.encode(str(row["sequence"]), add_special_tokens=False)
                datums.append(build_cross_entropy_datum(prompt_input, target_tokens))
                pair_reports.append(
                    {
                        "epoch": epoch,
                        "batch_index": batch_index,
                        "accession": row.get("accession"),
                        "label": row.get("label"),
                        "prompt": prompt,
                        "sequence_length": len(row["sequence"]),
                        "esm_score": row.get("esm_score"),
                    }
                )

            forward_backward_result = training_client.forward_backward(
                datums,
                loss_fn="cross_entropy",
            ).result()
            optim_step_result = training_client.optim_step(adam_params).result()
            batch_reports.append(
                {
                    "epoch": epoch,
                    "batch_index": batch_index,
                    "batch_size": len(batch_rows),
                    "forward_backward_metrics": forward_backward_result.metrics,
                    "optim_step_metrics": optim_step_result.metrics,
                }
            )
            print(
                json.dumps(
                    {
                        "epoch": epoch,
                        "batch_index": batch_index,
                        "batch_size": len(batch_rows),
                        "forward_backward_metrics": forward_backward_result.metrics,
                        "optim_step_metrics": optim_step_result.metrics,
                    }
                ),
                flush=True,
            )

    save_result = training_client.save_state(args.checkpoint_name).result()
    report = {
        "name": args.name,
        "base_model": base_model,
        "supported_models": supported_models,
        "init_state_path": args.init_state_path,
        "checkpoint_name": args.checkpoint_name,
        "checkpoint_path": save_result.path,
        "dataset_path": args.dataset_path,
        "records_path": args.records_path,
        "pair_count": len(dataset_rows),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "prompt_variant": os.environ.get("PROMPT_VARIANT", "baseline"),
        "batches": batch_reports,
        "pairs": pair_reports,
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    summary = {
        "name": args.name,
        "checkpoint_path": save_result.path,
        "init_state_path": args.init_state_path,
        "dataset_path": args.dataset_path,
        "pair_count": len(dataset_rows),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "report_path": str(report_path),
        "mean_sequence_length": round(
            sum(len(str(row["sequence"])) for row in dataset_rows) / max(1, len(dataset_rows)),
            2,
        ),
        "mean_esm_score": round(
            sum(float(row.get("esm_score", 0.0)) for row in dataset_rows) / max(1, len(dataset_rows)),
            2,
        ),
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a short cross-entropy warm-start on geometry-positive pairs")
    parser.add_argument("--name", required=True)
    parser.add_argument("--dataset-path", required=True)
    parser.add_argument("--records-path", required=True)
    parser.add_argument("--output-dir", default="/Users/svdr/tinker/reports/warmstart")
    parser.add_argument("--model", default="Qwen/Qwen3-8B")
    parser.add_argument("--init-state-path")
    parser.add_argument("--checkpoint-name")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=5e-5)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--max-examples", type=int)
    args = parser.parse_args()
    if not args.checkpoint_name:
        args.checkpoint_name = sanitize_name(args.name)
    if args.model:
        os.environ["TINKER_BASE_MODEL"] = args.model
    return args


def build_cross_entropy_datum(
    prompt_input: types.ModelInput,
    target_tokens: list[int],
) -> types.Datum:
    if not target_tokens:
        raise RuntimeError("Cross-entropy target sequence tokenized to zero length")

    observed_prompt_length = prompt_input.length - 1
    model_input = (
        prompt_input
        if len(target_tokens) == 1
        else prompt_input.append(types.EncodedTextChunk(tokens=target_tokens[:-1]))
    )
    padded_targets = np.asarray([0] * observed_prompt_length + target_tokens, dtype=np.int64)
    weights = np.asarray(
        [0.0] * observed_prompt_length + [1.0] * (model_input.length - observed_prompt_length),
        dtype=np.float32,
    )
    if model_input.length != len(padded_targets) or model_input.length != len(weights):
        raise RuntimeError("Cross-entropy tensors are not aligned")
    return types.Datum(
        model_input=model_input,
        loss_fn_inputs={
            "target_tokens": padded_targets,
            "weights": weights,
        },
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def resolve_training_prompt(row: dict[str, Any]) -> str:
    prompt = str(row.get("prompt") or row.get("source_prompt") or "").strip()
    if prompt:
        return prompt

    length = int(row.get("length") or row.get("sequence_length") or len(str(row.get("sequence") or "")) or 300)
    motif = str(row.get("derived_motif") or "").strip()
    if not motif:
        family_eval = row.get("family_evaluation") or {}
        serine_motifs = family_eval.get("serine_motifs") or []
        if serine_motifs:
            motif = str(serine_motifs[0]).strip()

    motif_clause = f" with canonical serine motif {motif}" if motif else ""
    return (
        f"Generate a PETase-family esterase sequence around {length} aa"
        f"{motif_clause} while preserving catalytic bridge geometry."
    )


def chunked(rows: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + batch_size] for index in range(0, len(rows), batch_size)]


def sanitize_name(value: str) -> str:
    chars = []
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("-")
    sanitized = "".join(chars).strip("-")
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized or "run"


if __name__ == "__main__":
    main()
