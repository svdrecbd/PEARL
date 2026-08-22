#!/usr/bin/env python3
"""Discovery extension funnel: cheap filters → ESM2 scoring → selected panel.

Processes only discovery-extension slots (sample_index >= 1).
Produces a selection manifest for GMN folding and an audit manifest for
unselected-pool quality estimation. Separate from the confirmatory endpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

# Frozen thresholds from the hybrid amendment
MIN_LENGTH = 40
MAX_LENGTH = 500
MIN_ENTROPY = 2.5
MAX_HOMOPOLYMER = 8
ESM2_SMALL_MODEL = "facebook/esm2_t6_8M_UR50D"
ESM2_LARGE_MODEL = "facebook/esm2_t33_650M_UR50D"
RESCORE_FRACTION = 0.20
SELECTED_PANEL_SIZE = 96
RANDOM_SURVIVORS = 24
AUDIT_POOL_SIZE = 48


def sha256_value(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def shannon_entropy(sequence: str) -> float:
    if not sequence:
        return 0.0
    counts = Counter(sequence)
    total = len(sequence)
    return -sum(
        (count / total) * math.log2(count / total)
        for count in counts.values()
    )


def max_homopolymer_run(sequence: str) -> int:
    if not sequence:
        return 0
    max_run = 1
    current = 1
    for i in range(1, len(sequence)):
        if sequence[i] == sequence[i - 1]:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 1
    return max_run


VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")


def cheap_filter(sequence: str) -> tuple[bool, str | None]:
    """Return (passes, rejection_reason)."""
    if len(sequence) < MIN_LENGTH:
        return False, f"too_short_{len(sequence)}"
    if len(sequence) > MAX_LENGTH:
        return False, f"too_long_{len(sequence)}"
    invalid = set(sequence) - VALID_AA
    if invalid:
        return False, f"invalid_aa_{''.join(sorted(invalid))}"
    entropy = shannon_entropy(sequence)
    if entropy < MIN_ENTROPY:
        return False, f"low_entropy_{entropy:.2f}"
    longest_run = max_homopolymer_run(sequence)
    if longest_run > MAX_HOMOPOLYMER:
        return False, f"homopolymer_{longest_run}"
    return True, None


def load_discovery_candidates(output_root: Path, manifest_path: Path) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text())
    candidates = []
    seen_hashes = set()
    for job in manifest["jobs"]:
        report_path = output_root / job["job_key"] / "generation_report.json"
        if not report_path.is_file():
            continue
        report = json.loads(report_path.read_text())
        for row in report.get("candidates", []):
            cohort = row.get("cohort", "confirmatory")
            if cohort != "discovery":
                continue
            seq_hash = row.get("sequence_sha256")
            if not seq_hash or not row.get("valid_sequence"):
                continue
            if seq_hash in seen_hashes:
                continue
            seen_hashes.add(seq_hash)
            candidates.append(row)
    return candidates


def esm2_score(model_name: str, sequences: list[str]) -> list[float]:
    """Score sequences with mean log-likelihood using ESM2."""
    try:
        import torch
        from transformers import EsmForMaskedLM, AutoTokenizer

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = EsmForMaskedLM.from_pretrained(model_name).to(device).eval()
        scores = []
        with torch.no_grad():
            for seq in sequences:
                inputs = tokenizer(seq, return_tensors="pt", truncation=True, max_length=1024).to(device)
                outputs = model(**inputs, labels=inputs["input_ids"])
                loss = outputs.loss.item()
                scores.append(-loss)  # negative loss = higher is better
        del model
        torch.cuda.empty_cache()
        return scores
    except ImportError:
        raise RuntimeError("torch/transformers required for ESM2 scoring")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--skip-esm2", action="store_true", help="Skip ESM2 scoring (shape-only test)")
    args = parser.parse_args()

    output_root = Path(args.output_root)
    manifest_path = Path(args.manifest)

    candidates = load_discovery_candidates(output_root, manifest_path)
    print(f"Discovery candidates loaded: {len(candidates)}")

    # Stage 1: cheap deterministic filters
    passed_filter = []
    rejected = Counter()
    for row in candidates:
        ok, reason = cheap_filter(str(row.get("sequence", "")))
        if ok:
            passed_filter.append(row)
        else:
            rejected[reason] += 1
    print(f"After cheap filter: {len(passed_filter)} (rejected: {dict(rejected)})")

    # Stage 2: exact dedup already done in load_discovery_candidates

    # Stage 3-4: ESM2 scoring
    sequences = [row["sequence"] for row in passed_filter]
    small_scores: list[float] = [0.0] * len(sequences)
    large_scores: list[float] = [0.0] * len(sequences)

    if not args.skip_esm2 and sequences:
        small_scores = esm2_score(ESM2_SMALL_MODEL, sequences)
        resample_n = max(1, int(len(sequences) * RESCORE_FRACTION))
        top_indices = sorted(range(len(small_scores)), key=lambda i: small_scores[i], reverse=True)[:resample_n]
        large_batch = [sequences[i] for i in top_indices]
        large_results = esm2_score(ESM2_LARGE_MODEL, large_batch)
        for idx, score in zip(top_indices, large_results):
            large_scores[idx] = score

    combined = [
        {
            **row,
            "esm2_small_score": small_scores[i],
            "esm2_large_score": large_scores[i],
        }
        for i, row in enumerate(passed_filter)
    ]
    combined.sort(key=lambda r: r["esm2_small_score"] + r.get("esm2_large_score", 0), reverse=True)

    # Stage 5: selected panel + random survivors
    rng = random.Random(20260822)
    selected_panel = combined[:SELECTED_PANEL_SIZE]
    remaining = combined[SELECTED_PANEL_SIZE:]
    random_survivors = rng.sample(remaining, min(RANDOM_SURVIVORS, len(remaining)))

    # Stage 6: audit pool (random unselected candidates that didn't pass filter top)
    audit_pool = rng.sample(combined, min(AUDIT_POOL_SIZE, len(combined)))

    payload = {
        "contract": "pearl.frontier-discovery-funnel-selection/1",
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "total_discovery_candidates": len(candidates),
        "filter_rejections": dict(rejected),
        "after_filter": len(passed_filter),
        "selected_panel_size": len(selected_panel),
        "random_survivors_size": len(random_survivors),
        "audit_pool_size": len(audit_pool),
        "selected_sequences": [
            {"sequence_sha256": r["sequence_sha256"], "sequence_length": r["sequence_length"]}
            for r in selected_panel
        ],
        "random_survivor_sequences": [
            {"sequence_sha256": r["sequence_sha256"]} for r in random_survivors
        ],
        "audit_pool_sequences": [
            {"sequence_sha256": r["sequence_sha256"]} for r in audit_pool
        ],
    }
    payload["funnel_sha256"] = sha256_value(payload)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    summary = {k: v for k, v in payload.items() if k not in ("selected_sequences", "random_survivor_sequences", "audit_pool_sequences")}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
