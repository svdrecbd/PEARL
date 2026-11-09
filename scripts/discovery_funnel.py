#!/usr/bin/env python3
"""Discovery extension funnel: cheap filters → ESM2 scoring → selected panel.

Processes only discovery-extension slots (sample_index >= 1).
Produces a selection manifest for GMN folding and an audit manifest for
unselected-pool quality estimation. Separate from the confirmatory endpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
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
ESM2_SMALL_REVISION = "c731040fcd8d73dceaa04b0a8e6329b345b0f5df"
ESM2_LARGE_REVISION = "08e4846e537177426273712802403f7ba8261b6c"
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


def rejection_category(reason: str) -> str:
    parts = reason.split("_", 2)
    if len(parts) > 1 and parts[0] in {"too", "low", "invalid"}:
        return "_".join(parts[:2])
    return parts[0]


def load_generation_builder() -> Any:
    path = ROOT / "scripts" / "build_frontier_adaptation_gmn_manifest.py"
    spec = importlib.util.spec_from_file_location("frontier_generation_builder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load frontier generation contract builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_discovery_candidates(
    output_root: Path,
    manifest_path: Path,
    *,
    campaigns: set[str] | None = None,
) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text())
    builder = load_generation_builder()
    candidates = []
    seen_hashes = set()
    for job in manifest["jobs"]:
        if campaigns is not None and str(job.get("campaign")) not in campaigns:
            continue
        expected_contract = (
            builder.expected_generation_contract(job) if job.get("structural_config") else None
        )
        run_key = expected_contract["run_key"] if expected_contract else str(job["job_key"])
        report_path = output_root / run_key / "generation_report.json"
        if not report_path.is_file():
            raise RuntimeError(f"generation report missing: {report_path}")
        report = json.loads(report_path.read_text())
        if report.get("status") != "complete" or (
            expected_contract is not None and report.get("contract") != expected_contract
        ):
            raise RuntimeError(f"generation report incomplete or mismatched: {report_path}")
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
            candidates.append({**row, "source_job_key": job["job_key"]})
    return candidates


def esm2_score(model_name: str, model_revision: str, sequences: list[str]) -> list[float]:
    """Score sequences with mean log-likelihood using ESM2."""
    try:
        import torch
        from pearl import esm_proxy

        esm_proxy.ESM2_MODEL_NAME = model_name
        esm_proxy.ESM2_REVISION = model_revision
        esm_proxy._get_esm2.cache_clear()
        esm_proxy._pll_sequence.cache_clear()
        scores = []
        chunk_size = 64
        for start in range(0, len(sequences), chunk_size):
            chunk = sequences[start : start + chunk_size]
            scores.extend(esm_proxy.get_esm2_plls(chunk))
            print(
                json.dumps({"model": model_name, "scored": len(scores), "expected": len(sequences)}),
                flush=True,
            )
        esm_proxy._get_esm2.cache_clear()
        esm_proxy._pll_sequence.cache_clear()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        return scores
    except ImportError:
        raise RuntimeError("torch/transformers required for ESM2 scoring")


def select_panels(
    combined: list[dict[str, Any]], *, seed: int = 20260822
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rescored = [row for row in combined if row["esm2_large_score"] != 0.0]
    rescored.sort(
        key=lambda row: row["esm2_small_score"] + row["esm2_large_score"], reverse=True
    )
    rng = random.Random(seed)
    selected_panel = rescored[:SELECTED_PANEL_SIZE]
    selected_hashes = {row["sequence_sha256"] for row in selected_panel}
    remaining = [row for row in combined if row["sequence_sha256"] not in selected_hashes]
    random_survivors = rng.sample(remaining, min(RANDOM_SURVIVORS, len(remaining)))
    survivor_hashes = {row["sequence_sha256"] for row in random_survivors}
    audit_eligible = [
        row for row in remaining if row["sequence_sha256"] not in survivor_hashes
    ]
    audit_pool = rng.sample(audit_eligible, min(AUDIT_POOL_SIZE, len(audit_eligible)))
    return selected_panel, random_survivors, audit_pool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--skip-esm2", action="store_true", help="Skip ESM2 scoring (shape-only test)")
    parser.add_argument(
        "--campaign",
        action="append",
        dest="campaigns",
        help="Campaign to include; repeat for multiple campaigns. Default: all.",
    )
    args = parser.parse_args()

    output_root = Path(args.output_root)
    manifest_path = Path(args.manifest)

    campaigns = set(args.campaigns) if args.campaigns else None
    candidates = load_discovery_candidates(output_root, manifest_path, campaigns=campaigns)
    print(f"Discovery candidates loaded: {len(candidates)}")

    # Stage 1: cheap deterministic filters
    passed_filter = []
    rejected = Counter()
    rejected_detail = Counter()
    for row in candidates:
        ok, reason = cheap_filter(str(row.get("sequence", "")))
        if ok:
            passed_filter.append(row)
        else:
            rejected_detail[str(reason)] += 1
            rejected[rejection_category(str(reason))] += 1
    print(f"After cheap filter: {len(passed_filter)} (rejected: {dict(rejected)})")

    # Stage 2: exact dedup already done in load_discovery_candidates

    # Stage 3-4: ESM2 scoring
    sequences = [row["sequence"] for row in passed_filter]
    small_scores: list[float] = [0.0] * len(sequences)
    large_scores: list[float] = [0.0] * len(sequences)

    if not args.skip_esm2 and sequences:
        small_scores = esm2_score(ESM2_SMALL_MODEL, ESM2_SMALL_REVISION, sequences)
        resample_n = max(1, int(len(sequences) * RESCORE_FRACTION))
        top_indices = sorted(range(len(small_scores)), key=lambda i: small_scores[i], reverse=True)[:resample_n]
        large_batch = [sequences[i] for i in top_indices]
        large_results = esm2_score(ESM2_LARGE_MODEL, ESM2_LARGE_REVISION, large_batch)
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
    # Stage 5: selected panel + random survivors
    # Stage 6: disjoint audit pool from candidates outside the selected top panel.
    if args.skip_esm2:
        selected_panel, random_survivors, audit_pool = [], [], []
    else:
        selected_panel, random_survivors, audit_pool = select_panels(combined)

    payload = {
        "contract": "pearl.frontier-discovery-funnel-selection/1",
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "selected_campaigns": sorted(campaigns) if campaigns else None,
        "esm2_model_revisions": {
            ESM2_SMALL_MODEL: ESM2_SMALL_REVISION,
            ESM2_LARGE_MODEL: ESM2_LARGE_REVISION,
        },
        "total_discovery_candidates": len(candidates),
        "filter_rejections": dict(rejected),
        "filter_rejection_detail": dict(rejected_detail),
        "after_filter": len(passed_filter),
        "selected_panel_size": len(selected_panel),
        "random_survivors_size": len(random_survivors),
        "audit_pool_size": len(audit_pool),
        "status": "shape_validated" if args.skip_esm2 else "complete",
        "selected_sequences": selected_panel,
        "random_survivor_sequences": random_survivors,
        "audit_pool_sequences": audit_pool,
    }
    payload["funnel_sha256"] = sha256_value(payload)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    summary = {k: v for k, v in payload.items() if k not in ("selected_sequences", "random_survivor_sequences", "audit_pool_sequences")}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
