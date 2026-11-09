#!/usr/bin/env python3
"""Replication-salvage discovery funnel ranked from scratch with ESM3.

This is a post-protocol exploratory replacement for the frozen ESM2 funnel.
It applies the same deterministic filters and global exact deduplication, then
scores every survivor with a deterministic partition-masked ESM3 sequence
likelihood. No ESM2 score or shortlist is consumed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

ESM3_MODEL = "biohub/esm3-sm-open-v1"
ESM3_MODEL_REVISION = "47f0545b2b6daf26a93439a3cd610f4f7f3d5478"
ESM3_CODE_REVISION = "d0207ea3c8cbf072679ece3bb332787d25e06852"
MASK_PARTITIONS = 8
SELECTED_PANEL_SIZE = 96
RANDOM_SURVIVORS = 24
AUDIT_POOL_SIZE = 48
SELECTION_SEED = 20260822


def load_legacy_funnel() -> Any:
    path = ROOT / "scripts" / "discovery_funnel.py"
    spec = importlib.util.spec_from_file_location("legacy_discovery_funnel", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load deterministic discovery filters")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_value(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def partition_residue_offsets(length: int, partitions: int = MASK_PARTITIONS) -> list[list[int]]:
    """Partition zero-based residue offsets so every residue is scored exactly once."""
    if length < 1:
        return []
    if partitions < 1:
        raise ValueError("partitions must be positive")
    return [list(range(partition, length, partitions)) for partition in range(partitions)]


def load_esm3(*, device: str) -> tuple[Any, Any]:
    import torch
    from accelerate import init_empty_weights
    from esm.models.esm3 import ESM3
    from esm.tokenization import get_esm3_model_tokenizers
    from esm.utils.constants.models import ESM3_OPEN_SMALL
    from huggingface_hub import hf_hub_download

    def unused_decoder(_: Any) -> Any:
        raise RuntimeError("structure/function decoders are not used by the sequence ranker")

    tokenizers = get_esm3_model_tokenizers(ESM3_OPEN_SMALL)
    with init_empty_weights():
        model = ESM3(
            d_model=1536,
            n_heads=24,
            v_heads=256,
            n_layers=48,
            structure_encoder_fn=unused_decoder,
            structure_decoder_fn=unused_decoder,
            function_decoder_fn=unused_decoder,
            tokenizers=tokenizers,
        ).eval()
    weights = hf_hub_download(
        repo_id=ESM3_MODEL,
        filename="data/weights/esm3_sm_open_v1.pth",
        revision=ESM3_MODEL_REVISION,
    )
    state_dict = torch.load(weights, map_location=device, weights_only=True)
    model.load_state_dict(state_dict, assign=True)
    model = model.to(device).to(torch.bfloat16).eval()
    return tokenizers.sequence, model


def esm3_partition_scores(
    sequences: list[str],
    *,
    device: str = "cuda",
    partitions: int = MASK_PARTITIONS,
    max_variant_batch: int = 32,
) -> list[float]:
    """Score every residue once across deterministic, interleaved mask partitions.

    Each variant masks one interleaved partition of a sequence. The mean log
    probability of the true amino acid across all partitions is the score.
    Sequences are grouped by exact length so padding cannot alter the ranking.
    """
    import torch

    if not sequences:
        return []
    if max_variant_batch < partitions:
        raise ValueError("max_variant_batch must be at least the partition count")

    tokenizer, model = load_esm3(device=device)
    mask_token_id = int(tokenizer.mask_token_id)
    groups: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for index, sequence in enumerate(sequences):
        groups[len(sequence)].append((index, sequence))

    scores = [float("nan")] * len(sequences)
    sequences_per_forward = max(1, max_variant_batch // partitions)
    completed = 0
    with torch.inference_mode():
        for length in sorted(groups):
            rows = groups[length]
            offsets = partition_residue_offsets(length, partitions)
            for start in range(0, len(rows), sequences_per_forward):
                chunk = rows[start : start + sequences_per_forward]
                encoded = tokenizer(
                    [sequence for _, sequence in chunk],
                    add_special_tokens=True,
                    padding=False,
                    return_tensors="pt",
                )["input_ids"]
                true_ids = encoded.to(device)
                variants: list[Any] = []
                source_rows: list[int] = []
                target_positions: list[list[int]] = []
                for local_index in range(len(chunk)):
                    for residue_offsets in offsets:
                        variant = true_ids[local_index].clone()
                        token_positions = [offset + 1 for offset in residue_offsets]
                        if token_positions:
                            variant[token_positions] = mask_token_id
                        variants.append(variant)
                        source_rows.append(local_index)
                        target_positions.append(token_positions)
                batch = torch.stack(variants)
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    output = model(sequence_tokens=batch)
                log_probs = output.sequence_logits.float().log_softmax(dim=-1)
                score_sums = [0.0] * len(chunk)
                score_counts = [0] * len(chunk)
                for variant_index, (local_index, positions) in enumerate(
                    zip(source_rows, target_positions)
                ):
                    if not positions:
                        continue
                    pos = torch.tensor(positions, device=device, dtype=torch.long)
                    truth = true_ids[local_index].index_select(0, pos)
                    values = log_probs[variant_index, pos, truth]
                    score_sums[local_index] += float(values.sum().item())
                    score_counts[local_index] += len(positions)
                for local_index, (global_index, _) in enumerate(chunk):
                    if score_counts[local_index] != length:
                        raise RuntimeError("ESM3 partition scorer did not cover every residue")
                    scores[global_index] = round(
                        score_sums[local_index] / score_counts[local_index], 6
                    )
                completed += len(chunk)
                if completed % 32 == 0 or completed == len(sequences):
                    print(
                        json.dumps(
                            {
                                "model": ESM3_MODEL,
                                "scored": completed,
                                "expected": len(sequences),
                            }
                        ),
                        flush=True,
                    )
                del output, log_probs, batch
    return scores


def select_panels(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], ...]:
    ranked = sorted(rows, key=lambda row: row["esm3_score"], reverse=True)
    selected = ranked[:SELECTED_PANEL_SIZE]
    selected_hashes = {row["sequence_sha256"] for row in selected}
    remaining = [row for row in ranked if row["sequence_sha256"] not in selected_hashes]
    rng = random.Random(SELECTION_SEED)
    random_survivors = rng.sample(remaining, RANDOM_SURVIVORS)
    survivor_hashes = {row["sequence_sha256"] for row in random_survivors}
    audit_eligible = [
        row for row in remaining if row["sequence_sha256"] not in survivor_hashes
    ]
    audit_pool = rng.sample(audit_eligible, AUDIT_POOL_SIZE)
    return selected, random_survivors, audit_pool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--campaign", action="append", dest="campaigns")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--max-variant-batch", type=int, default=32)
    args = parser.parse_args()

    legacy = load_legacy_funnel()
    campaigns = set(args.campaigns) if args.campaigns else None
    candidates = legacy.load_discovery_candidates(
        Path(args.output_root), Path(args.manifest), campaigns=campaigns
    )
    passed: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    for row in candidates:
        ok, reason = legacy.cheap_filter(str(row.get("sequence", "")))
        if ok:
            passed.append(row)
        else:
            rejected[legacy.rejection_category(str(reason))] += 1
    print(
        json.dumps(
            {
                "total_discovery_candidates": len(candidates),
                "after_filter": len(passed),
                "filter_rejections": dict(rejected),
            }
        ),
        flush=True,
    )

    model_scores = esm3_partition_scores(
        [row["sequence"] for row in passed],
        device=args.device,
        max_variant_batch=args.max_variant_batch,
    )
    scored = [{**row, "esm3_score": score} for row, score in zip(passed, model_scores)]
    selected, random_survivors, audit_pool = select_panels(scored)
    payload = {
        "contract": "pearl.frontier-discovery-funnel-esm3/1",
        "analysis_scope": "replication_only_salvage_exploratory",
        "manifest_sha256": hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest(),
        "selected_campaigns": sorted(campaigns) if campaigns else None,
        "ranker": {
            "model": ESM3_MODEL,
            "model_revision": ESM3_MODEL_REVISION,
            "code_revision": ESM3_CODE_REVISION,
            "method": "deterministic_interleaved_partition_masked_mean_log_likelihood",
            "mask_partitions": MASK_PARTITIONS,
            "dtype": "bfloat16",
            "all_survivors_rescored_from_scratch": True,
            "esm2_scores_consumed": False,
        },
        "total_discovery_candidates": len(candidates),
        "filter_rejections": dict(rejected),
        "after_filter": len(passed),
        "selected_panel_size": len(selected),
        "random_survivors_size": len(random_survivors),
        "audit_pool_size": len(audit_pool),
        "scored_sequences": scored,
        "selected_sequences": selected,
        "random_survivor_sequences": random_survivors,
        "audit_pool_sequences": audit_pool,
        "status": "complete",
    }
    payload["funnel_sha256"] = sha256_value(payload)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in payload.items()
                if key
                not in {
                    "selected_sequences",
                    "scored_sequences",
                    "random_survivor_sequences",
                    "audit_pool_sequences",
                }
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
