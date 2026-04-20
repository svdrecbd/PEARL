#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.strict_curricula import (
    build_stage_a_dataset,
    build_stage_b_dataset,
    canonical_purebreds,
    coverage_stats,
    dedupe_by_sequence,
    load_jsonl,
    prepare_repair_strict_rows,
    select_source_bucket_cluster_diverse_rows,
    select_source_cluster_diverse_rows,
    select_top_ranked_rows,
    write_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build strict-first union curricula from old/new family-faithful hits")
    parser.add_argument("--old-strict-path", required=True)
    parser.add_argument("--new-strict-path", required=True)
    parser.add_argument("--repair-strict-path")
    parser.add_argument("--purebred-path", required=True)
    parser.add_argument("--anchor-path", required=True)
    parser.add_argument("--stage-a-output-path", required=True)
    parser.add_argument("--stage-a-summary-path", required=True)
    parser.add_argument("--stage-b-output-path", required=True)
    parser.add_argument("--stage-b-summary-path", required=True)
    parser.add_argument("--allowed-motifs", default="GYSLG,GYSQG")
    parser.add_argument("--old-repeat", type=int, default=2)
    parser.add_argument("--new-repeat", type=int, default=2)
    parser.add_argument("--repair-repeat", type=int, default=0)
    parser.add_argument("--pure-repeat", type=int, default=1)
    parser.add_argument("--anchor-count", type=int, default=12)
    parser.add_argument("--new-top-k", type=int)
    parser.add_argument("--repair-top-k", type=int)
    parser.add_argument("--strict-selection-mode", choices=["rank", "prompt_cluster", "bucket_cap"], default="rank")
    parser.add_argument(
        "--repair-selection-mode",
        choices=["rank", "prompt_cluster", "source_cluster", "bucket_cap"],
        default="source_cluster",
    )
    parser.add_argument("--anchor-selection-mode", choices=["rank", "prompt_cluster"], default="rank")
    parser.add_argument("--strict-max-per-prompt-bucket", type=int)
    parser.add_argument("--strict-max-per-cluster", type=int, default=0)
    parser.add_argument("--repair-identity-threshold", type=float, default=0.85)
    parser.add_argument("--repair-max-per-prompt-bucket", type=int)
    parser.add_argument("--repair-max-per-source-run", type=int, default=1)
    parser.add_argument("--repair-max-per-cluster", type=int, default=1)
    parser.add_argument("--selected-new-output-path")
    parser.add_argument("--selected-repair-output-path")
    parser.add_argument("--selected-anchor-output-path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    allowed_motifs = {motif.strip() for motif in args.allowed_motifs.split(",") if motif.strip()}
    old_rows = dedupe_by_sequence(load_jsonl(Path(args.old_strict_path)))
    new_rows_all = dedupe_by_sequence(load_jsonl(Path(args.new_strict_path)))
    new_rows = select_top_ranked_rows(
        new_rows_all,
        args.new_top_k,
        selection_mode=args.strict_selection_mode,
        ranker="strict",
        label="strict",
        max_per_prompt_bucket=args.strict_max_per_prompt_bucket,
        max_per_cluster=args.strict_max_per_cluster,
    )
    repair_rows_all: list[dict[str, object]] = []
    repair_rows: list[dict[str, object]] = []
    if args.repair_strict_path:
        repair_rows_all = prepare_repair_strict_rows(
            load_jsonl(Path(args.repair_strict_path)),
            identity_threshold=args.repair_identity_threshold,
        )
        if args.repair_selection_mode == "source_cluster":
            if not args.repair_top_k or args.repair_top_k <= 0:
                raise SystemExit("--repair-top-k is required when --repair-selection-mode=source_cluster")
            repair_rows = select_source_cluster_diverse_rows(
                repair_rows_all,
                top_k=args.repair_top_k,
                ranker="strict",
                label="repair_strict",
                max_per_source=args.repair_max_per_source_run,
                max_per_cluster=args.repair_max_per_cluster,
            )
        elif args.repair_selection_mode == "bucket_cap":
            if not args.repair_top_k or args.repair_top_k <= 0:
                raise SystemExit("--repair-top-k is required when --repair-selection-mode=bucket_cap")
            if not args.repair_max_per_prompt_bucket or args.repair_max_per_prompt_bucket <= 0:
                raise SystemExit(
                    "--repair-max-per-prompt-bucket is required when --repair-selection-mode=bucket_cap"
                )
            repair_rows = select_source_bucket_cluster_diverse_rows(
                repair_rows_all,
                top_k=args.repair_top_k,
                ranker="strict",
                label="repair_strict",
                max_per_source=args.repair_max_per_source_run,
                max_per_cluster=args.repair_max_per_cluster,
                max_per_prompt_bucket=args.repair_max_per_prompt_bucket,
            )
        else:
            repair_rows = select_top_ranked_rows(
                repair_rows_all,
                args.repair_top_k,
                selection_mode=args.repair_selection_mode,
                ranker="strict",
                label="repair_strict",
                max_per_prompt_bucket=args.repair_max_per_prompt_bucket,
                max_per_cluster=args.repair_max_per_cluster,
            )
    pure_rows = canonical_purebreds(load_jsonl(Path(args.purebred_path)), allowed_motifs)
    anchor_rows_all = dedupe_by_sequence(load_jsonl(Path(args.anchor_path)))
    anchor_rows = select_top_ranked_rows(
        anchor_rows_all,
        args.anchor_count,
        selection_mode=args.anchor_selection_mode,
        ranker="anchor",
        label="anchor",
    )

    stage_a_rows, stage_a_summary = build_stage_a_dataset(
        old_rows=old_rows,
        new_rows=new_rows,
        repair_rows=repair_rows,
        pure_rows=pure_rows,
        old_repeat=args.old_repeat,
        new_repeat=args.new_repeat,
        repair_repeat=args.repair_repeat,
        pure_repeat=args.pure_repeat,
    )
    stage_b_rows, stage_b_summary = build_stage_b_dataset(
        stage_a_rows=stage_a_rows,
        anchor_rows=anchor_rows,
        anchor_count=args.anchor_count,
    )

    write_jsonl(Path(args.stage_a_output_path), stage_a_rows)
    write_jsonl(Path(args.stage_b_output_path), stage_b_rows)
    if args.selected_new_output_path:
        write_jsonl(Path(args.selected_new_output_path), new_rows)
    if args.selected_repair_output_path:
        write_jsonl(Path(args.selected_repair_output_path), repair_rows)
    if args.selected_anchor_output_path:
        write_jsonl(Path(args.selected_anchor_output_path), anchor_rows)

    stage_a_summary.update(
        {
            "old_unique_count": len(old_rows),
            "new_unique_count": len(new_rows),
            "new_unique_count_raw": len(new_rows_all),
            "new_top_k": args.new_top_k,
            "strict_selection_mode": args.strict_selection_mode,
            "strict_max_per_prompt_bucket": args.strict_max_per_prompt_bucket,
            "strict_max_per_cluster": args.strict_max_per_cluster,
            "new_selected_coverage": coverage_stats(new_rows),
            "repair_unique_count": len(repair_rows),
            "repair_unique_count_raw": len(repair_rows_all),
            "repair_top_k": args.repair_top_k,
            "repair_selection_mode": args.repair_selection_mode,
            "repair_max_per_prompt_bucket": args.repair_max_per_prompt_bucket,
            "repair_selected_coverage": coverage_stats(repair_rows),
            "canonical_purebred_unique_count": len(pure_rows),
            "allowed_motifs": sorted(allowed_motifs),
            "output_path": args.stage_a_output_path,
            "selected_new_output_path": args.selected_new_output_path,
            "selected_repair_output_path": args.selected_repair_output_path,
        }
    )
    Path(args.stage_a_summary_path).write_text(json.dumps(stage_a_summary, indent=2) + "\n")

    stage_b_summary.update(
        {
            "anchor_source_pool_count": len(anchor_rows_all),
            "anchor_selection_mode": args.anchor_selection_mode,
            "selected_anchor_output_path": args.selected_anchor_output_path,
            "output_path": args.stage_b_output_path,
        }
    )
    Path(args.stage_b_summary_path).write_text(json.dumps(stage_b_summary, indent=2) + "\n")

    print(
        json.dumps(
            {
                "stage_a_summary_path": args.stage_a_summary_path,
                "stage_b_summary_path": args.stage_b_summary_path,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
