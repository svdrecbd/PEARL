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

from pearl.historical_hits import (
    cluster_rows,
    collect_hits,
    dedupe_exact_hits,
    discover_finalized_wave_dirs,
    source_contributions,
    summarize_row,
    summarize_wave_inventory,
    write_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a flat historical finalized-hit universe from mining waves")
    parser.add_argument("--reports-root", required=True)
    parser.add_argument("--wave-dir", action="append", default=[])
    parser.add_argument("--include-glob", action="append", default=[])
    parser.add_argument("--exclude-glob", action="append", default=[])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--identity-threshold", type=float, default=0.85)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reports_root = Path(args.reports_root).expanduser().resolve()
    wave_dirs = [Path(raw).expanduser().resolve() for raw in args.wave_dir]
    if not wave_dirs:
        wave_dirs = discover_finalized_wave_dirs(
            reports_root,
            include_globs=args.include_glob,
            exclude_globs=args.exclude_glob,
        )

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    hits = collect_hits(wave_dirs)
    exact_hits = dedupe_exact_hits(hits)
    clusters = cluster_rows(exact_hits, identity_threshold=args.identity_threshold)
    cluster_representatives = [cluster[0] for cluster in clusters]
    strict_hits = [row for row in exact_hits if bool(row.get("family_faithful_bridge_passes"))]
    bridge_hits = [
        row
        for row in exact_hits
        if bool(row.get("functional_bridge_passes")) and not bool(row.get("family_faithful_bridge_passes"))
    ]

    cluster_rows_json = []
    for cluster_index, cluster in enumerate(clusters, start=1):
        cluster_rows_json.append(
            {
                "cluster_id": cluster_index,
                "cluster_size": len(cluster),
                "contains_family_faithful": any(bool(row.get("family_faithful_bridge_passes")) for row in cluster),
                "contains_bridge_only": any(
                    bool(row.get("functional_bridge_passes")) and not bool(row.get("family_faithful_bridge_passes"))
                    for row in cluster
                ),
                "representative": summarize_row(cluster[0]),
                "members": [summarize_row(row) for row in cluster],
            }
        )

    inventory = summarize_wave_inventory(wave_dirs, reports_root=reports_root)
    contributions = source_contributions(exact_hits)

    write_jsonl(output_dir / "all_hit_steps.jsonl", hits)
    write_jsonl(output_dir / "exact_unique_hits.jsonl", exact_hits)
    write_jsonl(output_dir / "exact_unique_family_faithful_hits.jsonl", strict_hits)
    write_jsonl(output_dir / "exact_unique_bridge_only_hits.jsonl", bridge_hits)
    write_jsonl(output_dir / "lineage_cluster_representatives.jsonl", cluster_representatives)
    (output_dir / "lineage_clusters.json").write_text(json.dumps(cluster_rows_json, indent=2) + "\n", encoding="utf-8")
    (output_dir / "wave_inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    (output_dir / "source_contributions.json").write_text(
        json.dumps(contributions, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = {
        "reports_root": str(reports_root),
        "wave_count": len(wave_dirs),
        "identity_threshold": args.identity_threshold,
        "input_hit_count": len(hits),
        "exact_unique_hit_count": len(exact_hits),
        "exact_unique_functional_count": sum(int(bool(row.get("functional_bridge_passes"))) for row in exact_hits),
        "exact_unique_family_faithful_count": len(strict_hits),
        "exact_unique_bridge_only_count": len(bridge_hits),
        "cluster_count": len(clusters),
        "largest_cluster_size": max((len(cluster) for cluster in clusters), default=0),
        "output_dir": str(output_dir),
    }
    (output_dir / "universe_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
