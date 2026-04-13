#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pearl.family import passes_normalized_identity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build an exact-deduped, lineage-aware bundle from finalized mining waves. "
            "The output keeps one representative per identity cluster and splits strict "
            "family-faithful representatives from bridge-only representatives."
        )
    )
    parser.add_argument(
        "--wave-dir",
        action="append",
        required=True,
        help="Finalized wave directory containing finalization_summary.json",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--identity-threshold", type=float, default=0.85)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    wave_dirs = [Path(raw).expanduser().resolve() for raw in args.wave_dir]
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    hits = collect_hits(wave_dirs)
    exact_hits = dedupe_exact(hits)
    clusters = cluster_rows(exact_hits, identity_threshold=args.identity_threshold)

    cluster_reps: list[dict[str, Any]] = []
    strict_reps: list[dict[str, Any]] = []
    bridge_only_reps: list[dict[str, Any]] = []
    cluster_rows_json: list[dict[str, Any]] = []

    for cluster_index, cluster in enumerate(clusters, start=1):
        representative = cluster[0]
        cluster_reps.append(representative)

        strict_rows = [row for row in cluster if bool(row["family_faithful_bridge_passes"])]
        if strict_rows:
            strict_reps.append(strict_rows[0])
        else:
            bridge_only_reps.append(representative)

        cluster_rows_json.append(
            {
                "cluster_id": cluster_index,
                "cluster_size": len(cluster),
                "contains_family_faithful": any(bool(row["family_faithful_bridge_passes"]) for row in cluster),
                "contains_bridge_only": any(
                    bool(row["functional_bridge_passes"]) and not bool(row["family_faithful_bridge_passes"])
                    for row in cluster
                ),
                "representative": summarize_row(representative),
                "members": [summarize_row(row) for row in cluster],
            }
        )

    strict_reps.sort(key=row_priority, reverse=True)
    bridge_only_reps.sort(key=row_priority, reverse=True)
    cluster_reps.sort(key=row_priority, reverse=True)

    functional_hits = [row for row in exact_hits if bool(row["functional_bridge_passes"])]
    family_hits = [row for row in exact_hits if bool(row["family_faithful_bridge_passes"])]

    write_jsonl(output_dir / "all_functional_hits_exact.jsonl", functional_hits)
    write_jsonl(output_dir / "all_family_faithful_hits_exact.jsonl", family_hits)
    write_jsonl(output_dir / "lineage_cluster_representatives.jsonl", cluster_reps)
    write_jsonl(output_dir / "lineage_family_representatives.jsonl", strict_reps)
    write_jsonl(output_dir / "lineage_bridge_only_representatives.jsonl", bridge_only_reps)
    (output_dir / "lineage_clusters.json").write_text(json.dumps(cluster_rows_json, indent=2) + "\n", encoding="utf-8")

    summary = {
        "wave_dirs": [str(path) for path in wave_dirs],
        "identity_threshold": args.identity_threshold,
        "input_hit_count": len(hits),
        "functional_step_count": sum(1 for row in hits if bool(row["functional_bridge_passes"])),
        "family_faithful_step_count": sum(1 for row in hits if bool(row["family_faithful_bridge_passes"])),
        "exact_unique_hit_count": len(exact_hits),
        "exact_unique_functional_count": len(functional_hits),
        "exact_unique_family_faithful_count": len(family_hits),
        "cluster_count": len(clusters),
        "cluster_representative_count": len(cluster_reps),
        "strict_family_cluster_count": len(strict_reps),
        "bridge_only_cluster_count": len(bridge_only_reps),
        "largest_cluster_size": max((len(cluster) for cluster in clusters), default=0),
        "output_dir": str(output_dir),
    }
    (output_dir / "bundle_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


def collect_hits(wave_dirs: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for wave_dir in wave_dirs:
        summary_path = wave_dir / "finalization_summary.json"
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        wave_name = str(payload.get("name") or wave_dir.name)
        for result in payload.get("results", []):
            report_basename = Path(str(result["report_path"])).parent.name
            report_path = wave_dir / "runs" / report_basename / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            by_step = {int(record["step"]): record for record in report.get("records", [])}

            bridge_steps = sorted(
                set(int(step) for step in result.get("functional_bridge_steps", []))
                | set(int(step) for step in result.get("family_faithful_bridge_steps", []))
            )
            for step in bridge_steps:
                record = by_step.get(step)
                if record is None:
                    continue
                row = extract_hit_row(
                    wave_name=wave_name,
                    report_run_name=report_basename,
                    record=record,
                )
                rows.append(row)
    rows.sort(key=row_priority, reverse=True)
    return rows


def extract_hit_row(*, wave_name: str, report_run_name: str, record: dict[str, Any]) -> dict[str, Any]:
    reward_components = record.get("reward_components") or {}
    family_evaluation = record.get("family_evaluation") or {}
    catalytic_geometry = family_evaluation.get("catalytic_geometry") or {}
    selection_metadata = record.get("selection_metadata") or {}
    sequence_quality = record.get("sequence_quality") or {}

    sequence = str(record.get("extracted_sequence") or "").strip()
    serine_motifs = family_evaluation.get("serine_motifs") or []
    novelty = family_evaluation.get("novelty") or {}
    return {
        "wave_name": wave_name,
        "source_run": report_run_name,
        "source_step": int(record.get("step", -1)),
        "prompt": str(record.get("prompt") or "").strip(),
        "sequence": sequence,
        "length": int(family_evaluation.get("length") or len(sequence)),
        "reward": to_float(record.get("reward")),
        "esm_reward": to_float(reward_components.get("esm_reward")),
        "functional_bridge_passes": bool(reward_components.get("functional_bridge_passes")),
        "family_faithful_bridge_passes": bool(reward_components.get("family_faithful_bridge_passes")),
        "passes_core_screen": bool(family_evaluation.get("passes_core_screen")),
        "has_family_serine_motif": bool(family_evaluation.get("has_family_serine_motif")),
        "serine_motifs": serine_motifs,
        "motif_count": int(reward_components.get("motif_count") or sequence_quality.get("motif_count") or 0),
        "best_gap_error": to_optional_int(catalytic_geometry.get("best_gap_error")),
        "catalytic_geometry_passes": bool(catalytic_geometry.get("passes")),
        "closest_edit_identity": to_float(novelty.get("closest_edit_identity")),
        "stage1_rank": to_optional_int(selection_metadata.get("stage1_rank")),
        "stage2_rank": to_optional_int(selection_metadata.get("stage2_rank")),
        "stage2_score": to_float(selection_metadata.get("stage2_score")),
        "raw_record": record,
    }


def dedupe_exact(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_sequence: dict[str, dict[str, Any]] = {}
    for row in rows:
        existing = best_by_sequence.get(row["sequence"])
        if existing is None or row_priority(row) > row_priority(existing):
            best_by_sequence[row["sequence"]] = row
    deduped = list(best_by_sequence.values())
    deduped.sort(key=row_priority, reverse=True)
    return deduped


def cluster_rows(rows: list[dict[str, Any]], *, identity_threshold: float) -> list[list[dict[str, Any]]]:
    if not rows:
        return []

    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left in range(len(rows)):
        left_sequence = rows[left]["sequence"]
        for right in range(left + 1, len(rows)):
            right_sequence = rows[right]["sequence"]
            if passes_normalized_identity(left_sequence, right_sequence, identity_threshold):
                union(left, right)

    grouped: dict[int, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        grouped.setdefault(find(index), []).append(row)

    clusters = list(grouped.values())
    for cluster_index, cluster in enumerate(clusters, start=1):
        cluster.sort(key=row_priority, reverse=True)
        for row in cluster:
            row["cluster_id"] = cluster_index
            row["cluster_size"] = len(cluster)
    clusters.sort(key=lambda cluster: (len(cluster), row_priority(cluster[0])), reverse=True)
    return clusters


def row_priority(row: dict[str, Any]) -> tuple[float, ...]:
    strict_rank = 1.0 if bool(row.get("family_faithful_bridge_passes")) else 0.0
    functional_rank = 1.0 if bool(row.get("functional_bridge_passes")) else 0.0
    core_screen_rank = 1.0 if bool(row.get("passes_core_screen")) else 0.0
    geometry_rank = 1.0 if bool(row.get("catalytic_geometry_passes")) else 0.0
    gap_bonus = 0.0
    best_gap_error = row.get("best_gap_error")
    if isinstance(best_gap_error, int):
        gap_bonus = 1.0 / (1.0 + max(best_gap_error, 0))
    novelty_bonus = 1.0 - to_float(row.get("closest_edit_identity"))
    return (
        strict_rank,
        functional_rank,
        core_screen_rank,
        geometry_rank,
        to_float(row.get("esm_reward")),
        to_float(row.get("reward")),
        to_float(row.get("stage2_score")),
        gap_bonus,
        novelty_bonus,
        -int(row.get("length") or 0),
    )


def summarize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "wave_name": row["wave_name"],
        "source_run": row["source_run"],
        "source_step": row["source_step"],
        "sequence": row["sequence"],
        "length": row["length"],
        "reward": row["reward"],
        "esm_reward": row["esm_reward"],
        "functional_bridge_passes": row["functional_bridge_passes"],
        "family_faithful_bridge_passes": row["family_faithful_bridge_passes"],
        "passes_core_screen": row["passes_core_screen"],
        "best_gap_error": row["best_gap_error"],
        "closest_edit_identity": row["closest_edit_identity"],
        "stage1_rank": row["stage1_rank"],
        "stage2_rank": row["stage2_rank"],
        "stage2_score": row["stage2_score"],
        "cluster_id": row.get("cluster_id"),
        "cluster_size": row.get("cluster_size"),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
