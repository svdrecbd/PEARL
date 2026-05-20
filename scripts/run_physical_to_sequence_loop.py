#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.io_utils import atomic_write_json
from pearl.preference_distillation import (
    GateThresholds,
    PairingConfig,
    build_manifest,
    build_preference_pairs,
    load_candidate_metric_rows,
    normalize_candidate_rows,
    select_distillation_winners,
    write_jsonl,
)


def main() -> None:
    args = parse_args()
    candidate_path = repo_path(args.candidate_path)
    output_dir = repo_path(args.output_dir) / sanitize_name(args.name)
    output_dir.mkdir(parents=True, exist_ok=True)

    pairs_path = output_dir / "physical_dpo_pairs.jsonl"
    winners_path = output_dir / "opd_distillation_winners.jsonl"
    manifest_path = output_dir / "manifest.json"

    thresholds = GateThresholds(
        min_length=args.min_length,
        max_length=args.max_length,
        min_local_entropy=args.min_local_entropy,
        max_tandem_repeat_similarity=args.max_tandem_repeat_similarity,
        max_motif_count=args.max_motif_count,
        min_fold_confidence=args.min_fold_confidence,
        novelty_identity_min=args.novelty_identity_min,
        novelty_identity_max=args.novelty_identity_max,
    )
    pairing_config = PairingConfig(
        length_bucket_size=args.length_bucket_size,
        novelty_bucket_size=args.novelty_bucket_size,
        min_score_margin=args.min_score_margin,
        max_pairs_per_bucket=args.max_pairs_per_bucket,
        max_total_pairs=args.max_total_pairs,
    )

    raw_rows = load_candidate_metric_rows(candidate_path, input_format=args.input_format)
    candidates = normalize_candidate_rows(
        raw_rows,
        thresholds=thresholds,
        default_evaluator_version=args.evaluator_version,
    )
    pairs = build_preference_pairs(
        candidates,
        config=pairing_config,
        preference_family=args.preference_family,
    )
    winners = select_distillation_winners(
        candidates,
        require_independent_audit=args.require_independent_audit,
        max_winners=args.max_winners,
        min_weight=args.min_winner_weight,
    )

    write_jsonl(pairs_path, [pair.to_json() for pair in pairs])
    write_jsonl(winners_path, [winner.to_json() for winner in winners])
    manifest = build_manifest(
        candidates=candidates,
        pairs=pairs,
        winners=winners,
        config=pairing_config,
        thresholds=thresholds,
        candidate_path=candidate_path,
        pairs_path=pairs_path,
        winners_path=winners_path,
    )
    manifest.update(
        {
            "name": args.name,
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "preference_family": args.preference_family,
            "require_independent_audit": args.require_independent_audit,
            "min_winner_weight": args.min_winner_weight,
            "max_winners": args.max_winners,
        }
    )
    atomic_write_json(manifest_path, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build physical-to-sequence preference pairs and OPD distillation winners "
            "from evaluated PEARL candidate rows."
        )
    )
    parser.add_argument("--name", default="physical-to-sequence-dpo-opd")
    parser.add_argument(
        "--candidate-path",
        required=True,
        help="Candidate JSONL, PEARL candidate_audit.json, or PEARL report.json",
    )
    parser.add_argument(
        "--input-format",
        choices=("auto", "jsonl", "candidate_audit", "report"),
        default="auto",
    )
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "preference_distillation"))
    parser.add_argument("--evaluator-version", default="phase8_local_v1")
    parser.add_argument("--preference-family", default="on_policy_physical")

    parser.add_argument("--min-length", type=int, default=120)
    parser.add_argument("--max-length", type=int, default=360)
    parser.add_argument("--min-local-entropy", type=float, default=2.7)
    parser.add_argument("--max-tandem-repeat-similarity", type=float, default=0.85)
    parser.add_argument("--max-motif-count", type=int, default=1)
    parser.add_argument("--min-fold-confidence", type=float, default=85.0)
    parser.add_argument("--novelty-identity-min", type=float, default=0.0)
    parser.add_argument("--novelty-identity-max", type=float, default=0.9)

    parser.add_argument("--length-bucket-size", type=int, default=10)
    parser.add_argument("--novelty-bucket-size", type=float, default=0.05)
    parser.add_argument("--min-score-margin", type=float, default=0.05)
    parser.add_argument("--max-pairs-per-bucket", type=int, default=128)
    parser.add_argument("--max-total-pairs", type=int)

    parser.add_argument("--require-independent-audit", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--max-winners", type=int)
    parser.add_argument("--min-winner-weight", type=float, default=0.0)
    return parser.parse_args()


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
    return sanitized or "physical-to-sequence-dpo-opd"


if __name__ == "__main__":
    main()
