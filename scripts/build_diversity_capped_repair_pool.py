from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from petase_family import levenshtein
from scripts.build_repair_pool_dataset import build_merged_candidate_audit, write_jsonl


ROLE_TIER2_HIT = "tier2_hit"


def main() -> None:
    args = parse_args()
    rows = load_jsonl(Path(args.input_path))
    if not rows:
        raise SystemExit(f"No rows found in {args.input_path}")

    deduped_rows = dedupe_rows(rows)
    clusters = cluster_rows(deduped_rows, identity_threshold=args.cluster_identity_threshold)
    assign_cluster_ids(deduped_rows=deduped_rows, clusters=clusters)

    selected_rows = select_diverse_rows(
        rows=deduped_rows,
        max_total=args.max_total,
        max_per_source_run=args.max_per_source_run,
        max_per_cluster=args.max_per_cluster,
    )
    selected_rows.sort(key=row_priority_key)

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_path, selected_rows)

    output_audit_path: Path | None = None
    if args.output_audit_path:
        output_audit_path = Path(args.output_audit_path)
        output_audit_path.parent.mkdir(parents=True, exist_ok=True)
        source_audit_paths = unique_source_audit_paths(selected_rows)
        merged_audit_payload = build_merged_candidate_audit(rows=selected_rows, audit_paths=source_audit_paths)
        output_audit_path.write_text(json.dumps(merged_audit_payload, indent=2), encoding="utf-8")

    summary = build_summary(
        input_rows=rows,
        deduped_rows=deduped_rows,
        selected_rows=selected_rows,
        clusters=clusters,
        output_path=output_path,
        output_audit_path=output_audit_path,
        args=args,
    )
    summary_path = Path(args.summary_path) if args.summary_path else output_path.with_name(output_path.stem + "_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Diversity-cap a repair pool by source run and sequence cluster before generating repair candidates."
        )
    )
    parser.add_argument("--input-path", required=True, help="Path to repair_pool_selected*.jsonl")
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--output-audit-path", help="Optional merged candidate_audit.json for downstream repair script.")
    parser.add_argument("--summary-path")
    parser.add_argument("--max-total", type=int, default=48)
    parser.add_argument("--max-per-source-run", type=int, default=3)
    parser.add_argument("--max-per-cluster", type=int, default=2)
    parser.add_argument("--cluster-identity-threshold", type=float, default=0.85)
    args = parser.parse_args()

    if args.max_total < 1:
        raise SystemExit("--max-total must be >= 1")
    if args.max_per_source_run < 1:
        raise SystemExit("--max-per-source-run must be >= 1")
    if args.max_per_cluster < 1:
        raise SystemExit("--max-per-cluster must be >= 1")
    if not (0.0 < args.cluster_identity_threshold <= 1.0):
        raise SystemExit("--cluster-identity-threshold must be in (0,1]")
    return args


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_sequence: dict[str, dict[str, Any]] = {}
    for row in rows:
        sequence = str(row.get("sequence") or "")
        if not sequence:
            continue
        existing = best_by_sequence.get(sequence)
        if existing is None or row_priority_key(row) < row_priority_key(existing):
            best_by_sequence[sequence] = row
    return list(best_by_sequence.values())


def row_priority_key(row: dict[str, Any]) -> tuple[Any, ...]:
    role_rank = 0 if str(row.get("pool_role") or "") == ROLE_TIER2_HIT else 1
    return (
        role_rank,
        -to_float(row.get("esm_score")),
        -to_float(row.get("stage2_score")),
        -to_float(row.get("geometry_score")),
        str(row.get("source_run") or ""),
        to_int(row.get("step"), default=10**9),
        str(row.get("sequence") or ""),
    )


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
        left_sequence = str(rows[left].get("sequence") or "")
        for right in range(left + 1, len(rows)):
            right_sequence = str(rows[right].get("sequence") or "")
            if normalized_identity(left_sequence, right_sequence) >= identity_threshold:
                union(left, right)

    grouped: dict[int, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        grouped.setdefault(find(index), []).append(row)

    clusters = list(grouped.values())
    for cluster in clusters:
        cluster.sort(key=row_priority_key)
    clusters.sort(key=len, reverse=True)
    return clusters


def normalized_identity(left: str, right: str) -> float:
    denominator = max(len(left), len(right), 1)
    return 1.0 - (levenshtein(left, right) / denominator)


def assign_cluster_ids(*, deduped_rows: list[dict[str, Any]], clusters: list[list[dict[str, Any]]]) -> None:
    for cluster_index, cluster in enumerate(clusters, start=1):
        cluster_size = len(cluster)
        for row in cluster:
            row["cluster_id"] = cluster_index
            row["cluster_size"] = cluster_size


def select_diverse_rows(
    *,
    rows: list[dict[str, Any]],
    max_total: int,
    max_per_source_run: int,
    max_per_cluster: int,
) -> list[dict[str, Any]]:
    grouped_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        source_run = str(row.get("source_run") or "unknown")
        grouped_rows.setdefault(source_run, []).append(row)
    for source_run in grouped_rows:
        grouped_rows[source_run].sort(key=row_priority_key)

    source_runs = sorted(grouped_rows.keys())
    source_indexes = {source_run: 0 for source_run in source_runs}
    source_counts: dict[str, int] = {source_run: 0 for source_run in source_runs}
    cluster_counts: dict[int, int] = {}
    seen_sequences: set[str] = set()
    selected: list[dict[str, Any]] = []

    while len(selected) < max_total:
        progress_made = False
        for source_run in source_runs:
            if source_counts[source_run] >= max_per_source_run:
                continue

            source_rows = grouped_rows[source_run]
            index = source_indexes[source_run]
            chosen_row: dict[str, Any] | None = None

            while index < len(source_rows):
                row = source_rows[index]
                index += 1
                sequence = str(row.get("sequence") or "")
                if not sequence or sequence in seen_sequences:
                    continue
                cluster_id = int(row.get("cluster_id") or -1)
                if cluster_counts.get(cluster_id, 0) >= max_per_cluster:
                    continue
                chosen_row = row
                break

            source_indexes[source_run] = index
            if chosen_row is None:
                continue

            chosen_sequence = str(chosen_row.get("sequence") or "")
            chosen_cluster_id = int(chosen_row.get("cluster_id") or -1)
            seen_sequences.add(chosen_sequence)
            source_counts[source_run] += 1
            cluster_counts[chosen_cluster_id] = cluster_counts.get(chosen_cluster_id, 0) + 1
            selected.append(chosen_row)
            progress_made = True

            if len(selected) >= max_total:
                break
        if not progress_made:
            break

    return selected


def unique_source_audit_paths(rows: list[dict[str, Any]]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for row in rows:
        raw = str(row.get("source_audit_path") or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def build_summary(
    *,
    input_rows: list[dict[str, Any]],
    deduped_rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
    clusters: list[list[dict[str, Any]]],
    output_path: Path,
    output_audit_path: Path | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    input_role_counts = role_counts(input_rows)
    deduped_role_counts = role_counts(deduped_rows)
    selected_role_counts = role_counts(selected_rows)
    selected_by_source_run: dict[str, int] = {}
    for row in selected_rows:
        source_run = str(row.get("source_run") or "unknown")
        selected_by_source_run[source_run] = selected_by_source_run.get(source_run, 0) + 1
    selected_by_cluster: dict[str, int] = {}
    for row in selected_rows:
        cluster_id = str(row.get("cluster_id"))
        selected_by_cluster[cluster_id] = selected_by_cluster.get(cluster_id, 0) + 1

    return {
        "input_path": str(Path(args.input_path).expanduser().resolve()),
        "output_path": str(output_path),
        "output_audit_path": str(output_audit_path) if output_audit_path else None,
        "input_count": len(input_rows),
        "deduped_count": len(deduped_rows),
        "selected_count": len(selected_rows),
        "input_role_counts": input_role_counts,
        "deduped_role_counts": deduped_role_counts,
        "selected_role_counts": selected_role_counts,
        "cluster_count_input": len(clusters),
        "cluster_count_selected": len(selected_by_cluster),
        "largest_selected_cluster_size": max(selected_by_cluster.values(), default=0),
        "selected_by_source_run": dict(sorted(selected_by_source_run.items())),
        "selected_by_cluster": dict(sorted(selected_by_cluster.items(), key=lambda item: int(item[0]))),
        "constraints": {
            "max_total": args.max_total,
            "max_per_source_run": args.max_per_source_run,
            "max_per_cluster": args.max_per_cluster,
            "cluster_identity_threshold": args.cluster_identity_threshold,
        },
    }


def role_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {ROLE_TIER2_HIT: 0, "geometry_dominant_near_miss": 0}
    for row in rows:
        role = str(row.get("pool_role") or "")
        counts[role] = counts.get(role, 0) + 1
    return counts


def to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    main()
