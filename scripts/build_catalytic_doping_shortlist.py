#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


MOTIF_PRIORITY = {
    "GYSLG": 4,
    "GYSQG": 3,
    "GFSQG": 2,
    "GHSMG": 1,
}


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.open()]


def extract_gxsxg_motif(row: dict[str, Any]) -> str | None:
    strategy = row.get("source_strategy") or ""
    strategy_match = re.search(r"relocate:([A-Z]{5}):", strategy)
    if strategy_match:
        return strategy_match.group(1)
    seq = row["sequence"]
    hits = (row.get("geometry") or {}).get("serine_hits") or []
    for ser_pos in hits:
        start = ser_pos - 2
        end = ser_pos + 3
        if start >= 0 and end <= len(seq):
            motif = seq[start:end]
            if len(motif) == 5 and motif[0] == "G" and motif[2] == "S" and motif[4] == "G":
                return motif
    for i in range(len(seq) - 4):
        motif = seq[i : i + 5]
        if motif[0] == "G" and motif[2] == "S" and motif[4] == "G":
            return motif
    return None


def coarse_cluster_key(row: dict[str, Any]) -> tuple[int, str]:
    seq = row["sequence"]
    return (row["length"], seq[:80])


def parent_key(row: dict[str, Any]) -> tuple[str | None, int | None]:
    return (row.get("source_audit_path"), row.get("source_step"))


def score_row(row: dict[str, Any]) -> tuple[float, float, int, int]:
    geometry = row.get("geometry") or {}
    best_gap_error = geometry.get("best_gap_error")
    gap_penalty = 0 if best_gap_error is None else best_gap_error
    motif = extract_gxsxg_motif(row)
    motif_bonus = MOTIF_PRIORITY.get(motif or "", 0)
    return (
        float(row["esm_score"]),
        float(row.get("source_parent_esm_score") or 0.0),
        motif_bonus,
        -gap_penalty,
    )


def build_shortlist(
    rows: list[dict[str, Any]],
    target_count: int,
    max_per_parent: int,
    max_per_cluster: int,
    max_per_motif: int,
    allowed_motifs: set[str] | None,
    require_faithful_parent: bool,
) -> list[dict[str, Any]]:
    enriched = []
    for row in rows:
        motif = extract_gxsxg_motif(row)
        if allowed_motifs is not None and motif not in allowed_motifs:
            continue
        if require_faithful_parent and not bool(row.get("source_parent_has_family_serine_motif")):
            continue
        cluster = coarse_cluster_key(row)
        parent = parent_key(row)
        scored = dict(row)
        scored["derived_motif"] = motif
        scored["coarse_cluster"] = {"length": cluster[0], "prefix80": cluster[1]}
        scored["selection_score"] = list(score_row(row))
        enriched.append(scored)

    enriched.sort(key=score_row, reverse=True)

    parent_counts: Counter[tuple[str | None, int | None]] = Counter()
    cluster_counts: Counter[tuple[int, str]] = Counter()
    motif_counts: Counter[str | None] = Counter()

    chosen: list[dict[str, Any]] = []
    for row in enriched:
        motif = row["derived_motif"]
        parent = parent_key(row)
        cluster = coarse_cluster_key(row)
        if parent_counts[parent] >= max_per_parent:
            continue
        if cluster_counts[cluster] >= max_per_cluster:
            continue
        if motif_counts[motif] >= max_per_motif:
            continue
        chosen.append(row)
        parent_counts[parent] += 1
        cluster_counts[cluster] += 1
        motif_counts[motif] += 1
        if len(chosen) >= target_count:
            break
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path", required=True)
    parser.add_argument("--target-count", type=int, default=32)
    parser.add_argument("--max-per-parent", type=int, default=1)
    parser.add_argument("--max-per-cluster", type=int, default=1)
    parser.add_argument("--max-per-motif", type=int, default=8)
    parser.add_argument("--allowed-motifs", default="")
    parser.add_argument("--require-faithful-parent", action="store_true")
    args = parser.parse_args()

    rows = load_rows(Path(args.input_path))
    allowed_motifs = {
        motif.strip()
        for motif in args.allowed_motifs.split(",")
        if motif.strip()
    } or None
    shortlist = build_shortlist(
        rows=rows,
        target_count=args.target_count,
        max_per_parent=args.max_per_parent,
        max_per_cluster=args.max_per_cluster,
        max_per_motif=args.max_per_motif,
        allowed_motifs=allowed_motifs,
        require_faithful_parent=args.require_faithful_parent,
    )

    Path(args.output_path).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.output_path).open("w") as handle:
        for row in shortlist:
            handle.write(json.dumps(row) + "\n")

    motif_counts = Counter(row["derived_motif"] for row in shortlist)
    parent_counts = Counter(parent_key(row) for row in shortlist)
    summary = {
        "input_path": args.input_path,
        "output_path": args.output_path,
        "input_count": len(rows),
        "shortlist_count": len(shortlist),
        "target_count": args.target_count,
        "max_per_parent": args.max_per_parent,
        "max_per_cluster": args.max_per_cluster,
        "max_per_motif": args.max_per_motif,
        "allowed_motifs": sorted(allowed_motifs) if allowed_motifs is not None else None,
        "require_faithful_parent": bool(args.require_faithful_parent),
        "unique_parent_steps": len(parent_counts),
        "motif_counts": dict(motif_counts),
        "top_rows": [
            {
                "esm_score": row["esm_score"],
                "source_parent_esm_score": row.get("source_parent_esm_score"),
                "derived_motif": row["derived_motif"],
                "source_step": row.get("source_step"),
                "source_strategy": row.get("source_strategy"),
                "source_blueprint_positions": row.get("source_blueprint_positions"),
            }
            for row in shortlist[:10]
        ],
    }
    Path(args.summary_path).write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
