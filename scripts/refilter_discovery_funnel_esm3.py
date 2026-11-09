#!/usr/bin/env python3
"""Apply the versioned post-hoc repeat screen to the complete ESM3 catalog.

This script does not run a model. It preserves every original ESM3 score and
rebuilds the ranked, random-survivor, and audit panels only from sequences that
pass the declared repeat/composition screen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any


MAX_TESTED_PERIOD = 100
MAX_GLOBAL_PERIODICITY = 0.80
MAX_EXACT_TANDEM_COVERAGE = 0.40
KMER_SIZE = 5
MIN_DISTINCT_KMER_FRACTION = 0.75
MAX_SINGLE_RESIDUE_FRACTION = 0.20
SELECTED_PANEL_SIZE = 96
RANDOM_SURVIVORS = 24
AUDIT_POOL_SIZE = 48
SELECTION_SEED = 20260822


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_source(source: dict[str, Any]) -> None:
    if source.get("contract") != "pearl.frontier-discovery-funnel-esm3/1":
        raise RuntimeError("repeat filtering requires the complete original ESM3 catalog")
    if source.get("status") != "complete":
        raise RuntimeError("source ESM3 catalog is incomplete")
    expected = sha256_value({key: value for key, value in source.items() if key != "funnel_sha256"})
    if source.get("funnel_sha256") != expected:
        raise RuntimeError("source ESM3 catalog self-hash mismatch")
    ranker = source.get("ranker", {})
    if not ranker.get("all_survivors_rescored_from_scratch"):
        raise RuntimeError("source did not rescore all survivors with ESM3")
    if ranker.get("esm2_scores_consumed") is not False:
        raise RuntimeError("source ESM3 catalog consumed ESM2 scores")
    if len(source.get("scored_sequences", [])) != int(source.get("after_filter", -1)):
        raise RuntimeError("source ESM3 catalog row count mismatch")


def repeat_metrics(sequence: str) -> dict[str, Any]:
    length = len(sequence)
    best_periodicity = 0.0
    best_periodicity_period = None
    best_tandem_coverage = 0.0
    best_tandem_period = None
    for period in range(1, min(MAX_TESTED_PERIOD, length // 2) + 1):
        equality = [left == right for left, right in zip(sequence[period:], sequence[:-period])]
        periodicity = sum(equality) / len(equality)
        if periodicity > best_periodicity:
            best_periodicity = periodicity
            best_periodicity_period = period

        run = 0
        longest_run = 0
        for equal in equality:
            run = run + 1 if equal else 0
            longest_run = max(longest_run, run)
        if longest_run >= period:
            coverage = (longest_run + period) / length
            if coverage > best_tandem_coverage:
                best_tandem_coverage = coverage
                best_tandem_period = period

    kmers = [
        sequence[index : index + KMER_SIZE]
        for index in range(max(0, length - KMER_SIZE + 1))
    ]
    distinct_kmer_fraction = len(set(kmers)) / len(kmers) if kmers else 1.0
    counts = Counter(sequence)
    max_single_residue_fraction = max(counts.values()) / length if length else 1.0
    return {
        "max_global_periodicity": round(best_periodicity, 6),
        "max_global_periodicity_period": best_periodicity_period,
        "max_exact_tandem_coverage": round(best_tandem_coverage, 6),
        "max_exact_tandem_period": best_tandem_period,
        "distinct_5mer_fraction": round(distinct_kmer_fraction, 6),
        "max_single_residue_fraction": round(max_single_residue_fraction, 6),
    }


def rejection_reasons(metrics: dict[str, Any]) -> list[str]:
    reasons = []
    if metrics["max_global_periodicity"] >= MAX_GLOBAL_PERIODICITY:
        reasons.append("global_periodicity")
    if metrics["max_exact_tandem_coverage"] >= MAX_EXACT_TANDEM_COVERAGE:
        reasons.append("exact_tandem_repeat")
    if metrics["distinct_5mer_fraction"] < MIN_DISTINCT_KMER_FRACTION:
        reasons.append("low_distinct_5mer_fraction")
    if metrics["max_single_residue_fraction"] > MAX_SINGLE_RESIDUE_FRACTION:
        reasons.append("single_residue_composition_bias")
    return reasons


def select_panels(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], ...]:
    if len(rows) < SELECTED_PANEL_SIZE + RANDOM_SURVIVORS + AUDIT_POOL_SIZE:
        raise RuntimeError("not enough repeat-filtered survivors for disjoint panels")
    ranked = sorted(rows, key=lambda row: (-float(row["esm3_score"]), row["sequence_sha256"]))
    selected = ranked[:SELECTED_PANEL_SIZE]
    remaining = ranked[SELECTED_PANEL_SIZE:]
    rng = random.Random(SELECTION_SEED)
    random_survivors = rng.sample(remaining, RANDOM_SURVIVORS)
    random_hashes = {row["sequence_sha256"] for row in random_survivors}
    audit_eligible = [row for row in remaining if row["sequence_sha256"] not in random_hashes]
    audit_pool = rng.sample(audit_eligible, AUDIT_POOL_SIZE)
    return selected, random_survivors, audit_pool


def build_payload(source: dict[str, Any], *, source_file_sha256: str) -> dict[str, Any]:
    screened = []
    passed = []
    rejected = Counter()
    for source_row in source["scored_sequences"]:
        metrics = repeat_metrics(str(source_row["sequence"]))
        reasons = rejection_reasons(metrics)
        row = {
            **source_row,
            "repeat_screen": {
                **metrics,
                "passes": not reasons,
                "rejection_reasons": reasons,
            },
        }
        screened.append(row)
        if reasons:
            for reason in reasons:
                rejected[reason] += 1
        else:
            passed.append(row)

    selected, random_survivors, audit_pool = select_panels(passed)
    payload = {
        "contract": "pearl.frontier-discovery-funnel-esm3-repeat-filtered/1",
        "analysis_scope": "replication_only_salvage_exploratory_posthoc_repeat_filtered",
        "source_esm3_file_sha256": source_file_sha256,
        "source_esm3_funnel_sha256": source["funnel_sha256"],
        "manifest_sha256": source["manifest_sha256"],
        "selected_campaigns": source["selected_campaigns"],
        "ranker": {
            **source["ranker"],
            "scores_reused_without_recomputation": True,
            "posthoc_repeat_filter_applied": True,
        },
        "repeat_filter": {
            "status": "posthoc_exploratory",
            "max_tested_period": MAX_TESTED_PERIOD,
            "max_global_periodicity_exclusive": MAX_GLOBAL_PERIODICITY,
            "max_exact_tandem_coverage_exclusive": MAX_EXACT_TANDEM_COVERAGE,
            "kmer_size": KMER_SIZE,
            "min_distinct_kmer_fraction_inclusive": MIN_DISTINCT_KMER_FRACTION,
            "max_single_residue_fraction_inclusive": MAX_SINGLE_RESIDUE_FRACTION,
            "selection_seed": SELECTION_SEED,
        },
        "total_esm3_scored_sequences": len(screened),
        "repeat_filter_rejections_by_overlapping_reason": dict(rejected),
        "repeat_filter_rejected_unique": len(screened) - len(passed),
        "after_repeat_filter": len(passed),
        "selected_panel_size": len(selected),
        "random_survivors_size": len(random_survivors),
        "audit_pool_size": len(audit_pool),
        "screened_sequences": screened,
        "repeat_filtered_sequences": passed,
        "selected_sequences": selected,
        "random_survivor_sequences": random_survivors,
        "audit_pool_sequences": audit_pool,
        "status": "complete",
    }
    payload["funnel_sha256"] = sha256_value(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Complete ESM3 funnel JSON")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    input_path = Path(args.input)
    source = json.loads(input_path.read_text(encoding="utf-8"))
    validate_source(source)
    payload = build_payload(source, source_file_sha256=sha256_file(input_path))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    omitted = {
        "screened_sequences", "repeat_filtered_sequences", "selected_sequences",
        "random_survivor_sequences", "audit_pool_sequences",
    }
    print(json.dumps({key: value for key, value in payload.items() if key not in omitted}, indent=2))


if __name__ == "__main__":
    main()
