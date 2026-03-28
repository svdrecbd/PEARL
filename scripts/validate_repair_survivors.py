from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from petase_family import compute_family_stats, evaluate_candidate, load_reference_records


def main() -> None:
    args = parse_args()
    survivors_path = Path(args.survivors_path)
    records_path = Path(args.records_path)

    records = load_reference_records(records_path)
    family_stats = compute_family_stats(records)
    survivors = load_jsonl(survivors_path)
    validated = [
        validate_row(
            row=row,
            family_stats=family_stats,
            reference_records=records,
            min_esm=args.min_esm,
            max_mutations=args.max_mutations,
            max_gap_error=args.max_gap_error,
        )
        for row in survivors
    ]

    validated.sort(key=sort_key, reverse=True)

    strict_shortlist = [
        row
        for row in validated
        if bool(row["strict_bridge"]) or bool(row["strict_family"])
    ]
    review_rows = [row for row in validated if row["validation_bucket"] == "review"]
    reject_rows = [row for row in validated if row["validation_bucket"] == "reject"]

    output_path = Path(args.output_path)
    strict_path = Path(args.strict_output_path)
    review_path = Path(args.review_output_path)
    reject_path = Path(args.reject_output_path)
    summary_path = Path(args.summary_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_path, validated)
    write_jsonl(strict_path, strict_shortlist)
    write_jsonl(review_path, review_rows)
    write_jsonl(reject_path, reject_rows)

    summary = build_summary(
        survivors_path=survivors_path,
        records_path=records_path,
        validated=validated,
        strict_shortlist=strict_shortlist,
        review_rows=review_rows,
        reject_rows=reject_rows,
        min_esm=args.min_esm,
        max_mutations=args.max_mutations,
        max_gap_error=args.max_gap_error,
        output_path=output_path,
        strict_path=strict_path,
        review_path=review_path,
        reject_path=reject_path,
    )
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Re-evaluate capped repair survivors under the full family screen and split them into "
            "strict/review/reject buckets."
        )
    )
    parser.add_argument("--survivors-path", required=True)
    parser.add_argument("--records-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--strict-output-path", required=True)
    parser.add_argument("--review-output-path", required=True)
    parser.add_argument("--reject-output-path", required=True)
    parser.add_argument("--summary-path", required=True)
    parser.add_argument("--min-esm", type=float, default=95.0)
    parser.add_argument("--max-mutations", type=int, default=2)
    parser.add_argument(
        "--max-gap-error",
        type=int,
        default=14,
        help=(
            "Maximum catalytic triad gap error for strict bridge acceptance. "
            "Default 14 matches the median gap of the current mined family-faithful bridge set."
        ),
    )
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def validate_row(
    *,
    row: dict[str, Any],
    family_stats: dict[str, Any],
    reference_records: list[dict[str, Any]],
    min_esm: float,
    max_mutations: int,
    max_gap_error: int,
) -> dict[str, Any]:
    sequence = str(row.get("sequence") or "").strip().upper()
    family_evaluation = evaluate_candidate(
        sequence=sequence,
        family_stats=family_stats,
        reference_records=reference_records,
    )
    catalytic_geometry = family_evaluation["catalytic_geometry"]
    gap_error = catalytic_geometry.get("best_gap_error")
    motif_count = len(family_evaluation["serine_motifs"])
    esm_score = float(row.get("esm_score") or 0.0)
    mutation_count = int(row.get("source_mutation_count") or 0)

    geometry_passes = bool(catalytic_geometry.get("passes"))
    family_motif = bool(family_evaluation["has_family_serine_motif"])
    single_motif = motif_count == 1
    length_in_band = bool(family_evaluation["length_in_family_band"])
    passes_core_screen = bool(family_evaluation["passes_core_screen"])
    novelty_identity = float((family_evaluation.get("novelty") or {}).get("closest_edit_identity") or 0.0)

    strict_bridge = bool(
        geometry_passes
        and family_motif
        and single_motif
        and esm_score >= min_esm
        and mutation_count <= max_mutations
        and isinstance(gap_error, int)
        and gap_error <= max_gap_error
    )
    strict_family = bool(
        geometry_passes
        and family_motif
        and single_motif
        and esm_score >= min_esm
        and mutation_count <= max_mutations
        and length_in_band
        and passes_core_screen
    )
    strict_consensus = bool(strict_bridge and strict_family)

    reject_reasons: list[str] = []
    if not family_motif:
        reject_reasons.append("missing_family_serine_motif")
    if not single_motif:
        reject_reasons.append("multi_serine_motif")
    if esm_score < min_esm:
        reject_reasons.append("esm_below_strict_floor")
    if mutation_count > max_mutations:
        reject_reasons.append("mutation_count_too_high")
    if not isinstance(gap_error, int) or gap_error > max_gap_error:
        reject_reasons.append("gap_error_above_strict_bridge_limit")
    if not length_in_band:
        reject_reasons.append("outside_family_length_band")
    if not passes_core_screen:
        reject_reasons.append("fails_family_core_screen")

    if strict_consensus:
        bucket = "strict_consensus"
    elif strict_bridge or strict_family:
        bucket = "strict_shortlist"
    elif geometry_passes and family_motif and single_motif and esm_score >= min_esm:
        bucket = "review"
    else:
        bucket = "reject"

    enriched = dict(row)
    enriched["family_evaluation"] = family_evaluation
    enriched["validated_geometry_passes"] = geometry_passes
    enriched["validated_family_motif"] = family_motif
    enriched["validated_single_motif"] = single_motif
    enriched["validated_length_in_family_band"] = length_in_band
    enriched["validated_passes_core_screen"] = passes_core_screen
    enriched["validated_novelty_identity"] = novelty_identity
    enriched["strict_bridge"] = strict_bridge
    enriched["strict_family"] = strict_family
    enriched["strict_consensus"] = strict_consensus
    enriched["validation_bucket"] = bucket
    enriched["validation_reject_reasons"] = reject_reasons
    return enriched


def sort_key(row: dict[str, Any]) -> tuple[float, ...]:
    family_eval = row.get("family_evaluation") or {}
    catalytic_geometry = family_eval.get("catalytic_geometry") or {}
    gap_error = catalytic_geometry.get("best_gap_error")
    return (
        float(bool(row.get("strict_consensus"))),
        float(bool(row.get("strict_family"))),
        float(bool(row.get("strict_bridge"))),
        float(row.get("esm_score") or 0.0),
        -float(int(gap_error) if isinstance(gap_error, int) else 999),
        -float(int(row.get("source_mutation_count") or 0)),
    )


def build_summary(
    *,
    survivors_path: Path,
    records_path: Path,
    validated: list[dict[str, Any]],
    strict_shortlist: list[dict[str, Any]],
    review_rows: list[dict[str, Any]],
    reject_rows: list[dict[str, Any]],
    min_esm: float,
    max_mutations: int,
    max_gap_error: int,
    output_path: Path,
    strict_path: Path,
    review_path: Path,
    reject_path: Path,
) -> dict[str, Any]:
    reject_hist = Counter()
    for row in reject_rows:
        reject_hist.update(row.get("validation_reject_reasons") or [])

    strict_bridge_rows = [row for row in validated if bool(row["strict_bridge"])]
    strict_family_rows = [row for row in validated if bool(row["strict_family"])]
    strict_consensus_rows = [row for row in validated if bool(row["strict_consensus"])]

    return {
        "survivors_path": str(survivors_path),
        "records_path": str(records_path),
        "output_path": str(output_path),
        "strict_output_path": str(strict_path),
        "review_output_path": str(review_path),
        "reject_output_path": str(reject_path),
        "input_count": len(validated),
        "strict_shortlist_count": len(strict_shortlist),
        "strict_bridge_count": len(strict_bridge_rows),
        "strict_family_count": len(strict_family_rows),
        "strict_consensus_count": len(strict_consensus_rows),
        "review_count": len(review_rows),
        "reject_count": len(reject_rows),
        "unique_parent_runs_in_strict_shortlist": len(
            {str(row.get("source_parent_run") or "") for row in strict_shortlist}
        ),
        "thresholds": {
            "min_esm": min_esm,
            "max_mutations": max_mutations,
            "max_gap_error": max_gap_error,
        },
        "reject_reason_hist": dict(sorted(reject_hist.items())),
        "top_strict_rows": [summarize_row(row) for row in strict_shortlist[:10]],
        "top_review_rows": [summarize_row(row) for row in review_rows[:10]],
    }


def summarize_row(row: dict[str, Any]) -> dict[str, Any]:
    family_eval = row.get("family_evaluation") or {}
    catalytic_geometry = family_eval.get("catalytic_geometry") or {}
    return {
        "source_parent_run": row.get("source_parent_run"),
        "esm_score": row.get("esm_score"),
        "source_mutation_count": row.get("source_mutation_count"),
        "strict_bridge": row.get("strict_bridge"),
        "strict_family": row.get("strict_family"),
        "strict_consensus": row.get("strict_consensus"),
        "validated_length_in_family_band": row.get("validated_length_in_family_band"),
        "validated_passes_core_screen": row.get("validated_passes_core_screen"),
        "validated_novelty_identity": row.get("validated_novelty_identity"),
        "best_gap_error": catalytic_geometry.get("best_gap_error"),
        "sequence": row.get("sequence"),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row))
            handle.write("\n")


if __name__ == "__main__":
    main()
