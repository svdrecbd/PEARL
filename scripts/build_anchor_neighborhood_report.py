#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.historical_hits import (
    classify_anchor_opportunity,
    load_jsonl,
    neighborhood_report_for_anchor,
    parse_identity_thresholds,
    select_anchor_rows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build anchor-neighborhood reports from a historical hit universe")
    parser.add_argument("--candidate-hit-path", required=True)
    parser.add_argument("--anchor-source-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--identity-thresholds", default="0.98,0.95,0.90,0.85")
    parser.add_argument("--strict-anchor-count", type=int, default=24)
    parser.add_argument("--bridge-anchor-count", type=int, default=24)
    parser.add_argument("--max-examples-per-threshold", type=int, default=12)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidate_hit_path = Path(args.candidate_hit_path).expanduser().resolve()
    anchor_source_path = Path(args.anchor_source_path).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    candidate_rows = load_jsonl(candidate_hit_path)
    anchor_source_rows = load_jsonl(anchor_source_path)
    selected = select_anchor_rows(
        anchor_source_rows,
        strict_anchor_count=args.strict_anchor_count,
        bridge_anchor_count=args.bridge_anchor_count,
    )
    identity_thresholds = parse_identity_thresholds(args.identity_thresholds)

    reports = []
    for role in ("strict", "bridge_only"):
        for anchor in selected[role]:
            report = neighborhood_report_for_anchor(
                anchor,
                candidate_rows,
                identity_thresholds=identity_thresholds,
                max_examples_per_threshold=args.max_examples_per_threshold,
            )
            report["opportunity"] = classify_anchor_opportunity(report)
            reports.append(report)

    opportunity_counts = Counter(str(report["opportunity"]) for report in reports)
    role_counts = Counter(str(report["anchor_role"]) for report in reports)
    summary = {
        "candidate_hit_count": len(candidate_rows),
        "anchor_source_count": len(anchor_source_rows),
        "selected_strict_anchor_count": len(selected["strict"]),
        "selected_bridge_anchor_count": len(selected["bridge_only"]),
        "identity_thresholds": identity_thresholds,
        "opportunity_counts": dict(opportunity_counts),
        "role_counts": dict(role_counts),
        "output_dir": str(output_dir),
    }

    (output_dir / "anchor_neighborhoods.json").write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    (output_dir / "anchor_neighborhood_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
