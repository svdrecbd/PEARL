from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from petase_family import levenshtein


SOURCE_TYPE_SURVIVOR = "repair_survivor"
SOURCE_TYPE_NEAR_MISS = "geometry_near_miss"


def main() -> None:
    args = parse_args()
    survivors = load_survivors(Path(args.survivors_path))
    near_misses = load_near_misses(
        path=Path(args.near_miss_path),
        min_esm=args.near_miss_min_esm,
    )
    merged = dedupe_by_sequence(survivors + near_misses)
    clusters = cluster_rows(merged, identity_threshold=args.identity_threshold)
    assign_cluster_metadata(rows=merged, clusters=clusters)

    selected = curate_rows(
        rows=merged,
        max_total=args.max_total,
        max_near_miss=args.max_near_miss,
        max_per_source_step=args.max_per_source_step,
        max_per_cluster=args.max_per_cluster,
    )

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_path, selected)

    summary = build_summary(
        selected_rows=selected,
        all_rows=merged,
        clusters=clusters,
        output_path=output_path,
        args=args,
    )
    summary_path = Path(args.summary_path) if args.summary_path else output_path.with_name(output_path.stem + "_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a diversity-capped repair18 warmstart dataset from repair survivors "
            "plus top geometry-only near misses."
        )
    )
    parser.add_argument("--survivors-path", required=True)
    parser.add_argument("--near-miss-path", required=True, help="Path to repair_pool_selected.jsonl")
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path")
    parser.add_argument("--max-total", type=int, default=24)
    parser.add_argument("--max-near-miss", type=int, default=6)
    parser.add_argument("--near-miss-min-esm", type=float, default=60.0)
    parser.add_argument("--max-per-source-step", type=int, default=2)
    parser.add_argument("--max-per-cluster", type=int, default=2)
    parser.add_argument("--identity-threshold", type=float, default=0.80)
    args = parser.parse_args()

    if args.max_total < 1:
        raise SystemExit("--max-total must be >= 1")
    if args.max_near_miss < 0:
        raise SystemExit("--max-near-miss must be >= 0")
    if args.max_per_source_step < 1:
        raise SystemExit("--max-per-source-step must be >= 1")
    if args.max_per_cluster < 1:
        raise SystemExit("--max-per-cluster must be >= 1")
    if not (0.0 < args.identity_threshold <= 1.0):
        raise SystemExit("--identity-threshold must be in (0,1]")
    return args


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_survivors(path: Path) -> list[dict[str, Any]]:
    rows = load_jsonl(path)
    result: list[dict[str, Any]] = []
    for row in rows:
        sequence = str(row.get("sequence") or "").strip()
        prompt = str(row.get("prompt") or "").strip()
        if not sequence or not prompt:
            continue
        source_step = to_int(row.get("source_step"), default=-1)
        result.append(
            {
                "label": str(row.get("label") or "repair18_survivor"),
                "prompt": prompt,
                "sequence": sequence,
                "esm_score": to_float(row.get("esm_score")),
                "source_type": SOURCE_TYPE_SURVIVOR,
                "source_run": "repair_wave1",
                "source_step": source_step,
                "source_step_key": f"{SOURCE_TYPE_SURVIVOR}:step={source_step}",
                "geometry_passes": bool((row.get("geometry") or {}).get("passes", True)),
                "best_gap_error": to_optional_int((row.get("geometry") or {}).get("best_gap_error")),
            }
        )
    return result


def load_near_misses(*, path: Path, min_esm: float) -> list[dict[str, Any]]:
    rows = load_jsonl(path)
    result: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("pool_role") or "") != "geometry_dominant_near_miss":
            continue
        sequence = str(row.get("sequence") or "").strip()
        prompt = str(row.get("prompt") or "").strip()
        if not sequence or not prompt:
            continue
        esm_score = to_float(row.get("esm_score"))
        if esm_score < min_esm:
            continue
        source_run = str(row.get("source_run") or "unknown")
        source_step = to_int(row.get("step"), default=-1)
        result.append(
            {
                "label": "repair18_near_miss_geometry_only",
                "prompt": prompt,
                "sequence": sequence,
                "esm_score": esm_score,
                "source_type": SOURCE_TYPE_NEAR_MISS,
                "source_run": source_run,
                "source_step": source_step,
                "source_step_key": f"{SOURCE_TYPE_NEAR_MISS}:{source_run}:step={source_step}",
                "geometry_passes": bool(row.get("geometry_passes")),
                "best_gap_error": to_optional_int(row.get("best_gap_error")),
            }
        )
    return result


def dedupe_by_sequence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_sequence: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["sequence"]
        existing = best_by_sequence.get(key)
        if existing is None or row_priority(row) > row_priority(existing):
            best_by_sequence[key] = row
    return list(best_by_sequence.values())


def row_priority(row: dict[str, Any]) -> tuple[float, ...]:
    source_rank = 1.0 if row["source_type"] == SOURCE_TYPE_SURVIVOR else 0.0
    geometry_rank = 1.0 if bool(row.get("geometry_passes")) else 0.0
    gap_bonus = 0.0
    best_gap_error = row.get("best_gap_error")
    if isinstance(best_gap_error, int):
        gap_bonus = 1.0 / (1.0 + max(best_gap_error, 0))
    return (
        source_rank,
        geometry_rank,
        to_float(row.get("esm_score")),
        gap_bonus,
        -len(str(row.get("sequence") or "")),
    )


def cluster_rows(rows: list[dict[str, Any]], identity_threshold: float) -> list[list[dict[str, Any]]]:
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
            if normalized_identity(left_sequence, right_sequence) >= identity_threshold:
                union(left, right)

    grouped: dict[int, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        grouped.setdefault(find(index), []).append(row)

    clusters = list(grouped.values())
    for cluster in clusters:
        cluster.sort(key=row_priority, reverse=True)
    clusters.sort(key=len, reverse=True)
    return clusters


def assign_cluster_metadata(*, rows: list[dict[str, Any]], clusters: list[list[dict[str, Any]]]) -> None:
    for cluster_index, cluster in enumerate(clusters, start=1):
        cluster_size = len(cluster)
        for row in cluster:
            row["cluster_id"] = cluster_index
            row["cluster_size"] = cluster_size


def curate_rows(
    *,
    rows: list[dict[str, Any]],
    max_total: int,
    max_near_miss: int,
    max_per_source_step: int,
    max_per_cluster: int,
) -> list[dict[str, Any]]:
    survivors = sorted(
        [row for row in rows if row["source_type"] == SOURCE_TYPE_SURVIVOR],
        key=row_priority,
        reverse=True,
    )
    near_misses = sorted(
        [row for row in rows if row["source_type"] == SOURCE_TYPE_NEAR_MISS],
        key=row_priority,
        reverse=True,
    )

    selected: list[dict[str, Any]] = []
    selected_sequences: set[str] = set()
    source_step_counts: dict[str, int] = {}
    cluster_counts: dict[int, int] = {}

    def can_add(row: dict[str, Any]) -> bool:
        if row["sequence"] in selected_sequences:
            return False
        source_step_key = str(row["source_step_key"])
        if source_step_counts.get(source_step_key, 0) >= max_per_source_step:
            return False
        cluster_id = int(row.get("cluster_id") or -1)
        if cluster_counts.get(cluster_id, 0) >= max_per_cluster:
            return False
        return True

    def add_row(row: dict[str, Any]) -> None:
        selected.append(row)
        selected_sequences.add(row["sequence"])
        source_step_key = str(row["source_step_key"])
        source_step_counts[source_step_key] = source_step_counts.get(source_step_key, 0) + 1
        cluster_id = int(row.get("cluster_id") or -1)
        cluster_counts[cluster_id] = cluster_counts.get(cluster_id, 0) + 1

    for row in survivors:
        if len(selected) >= max_total:
            break
        if can_add(row):
            add_row(row)

    near_miss_selected = 0
    for row in near_misses:
        if len(selected) >= max_total:
            break
        if near_miss_selected >= max_near_miss:
            break
        if can_add(row):
            add_row(row)
            near_miss_selected += 1

    selected.sort(
        key=lambda row: (
            0 if row["source_type"] == SOURCE_TYPE_SURVIVOR else 1,
            -to_float(row.get("esm_score")),
            int(row.get("cluster_id") or 9999),
            str(row.get("source_step_key") or ""),
        )
    )
    return selected


def build_summary(
    *,
    selected_rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    clusters: list[list[dict[str, Any]]],
    output_path: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    selected_survivors = [row for row in selected_rows if row["source_type"] == SOURCE_TYPE_SURVIVOR]
    selected_near_misses = [row for row in selected_rows if row["source_type"] == SOURCE_TYPE_NEAR_MISS]
    source_step_counts: dict[str, int] = {}
    for row in selected_rows:
        key = str(row["source_step_key"])
        source_step_counts[key] = source_step_counts.get(key, 0) + 1

    selected_cluster_counts: dict[str, int] = {}
    for row in selected_rows:
        key = str(row.get("cluster_id"))
        selected_cluster_counts[key] = selected_cluster_counts.get(key, 0) + 1

    esm_values = [to_float(row.get("esm_score")) for row in selected_rows]
    return {
        "output_path": str(output_path),
        "input_survivors_path": str(Path(args.survivors_path).expanduser().resolve()),
        "input_near_miss_path": str(Path(args.near_miss_path).expanduser().resolve()),
        "input_count_total": len(all_rows),
        "input_count_survivor": sum(1 for row in all_rows if row["source_type"] == SOURCE_TYPE_SURVIVOR),
        "input_count_near_miss": sum(1 for row in all_rows if row["source_type"] == SOURCE_TYPE_NEAR_MISS),
        "selected_count_total": len(selected_rows),
        "selected_count_survivor": len(selected_survivors),
        "selected_count_near_miss": len(selected_near_misses),
        "cluster_count_input": len(clusters),
        "cluster_count_selected": len(selected_cluster_counts),
        "largest_selected_cluster_size": max(selected_cluster_counts.values(), default=0),
        "selected_tier2_like_count": len(selected_survivors),
        "selected_near_miss_count": len(selected_near_misses),
        "selected_esm_min": round(min(esm_values), 4) if esm_values else 0.0,
        "selected_esm_max": round(max(esm_values), 4) if esm_values else 0.0,
        "selected_esm_mean": round(sum(esm_values) / max(1, len(esm_values)), 4),
        "source_step_counts": dict(sorted(source_step_counts.items())),
        "config": {
            "max_total": args.max_total,
            "max_near_miss": args.max_near_miss,
            "near_miss_min_esm": args.near_miss_min_esm,
            "max_per_source_step": args.max_per_source_step,
            "max_per_cluster": args.max_per_cluster,
            "identity_threshold": args.identity_threshold,
        },
    }


def normalized_identity(left: str, right: str) -> float:
    denominator = max(len(left), len(right), 1)
    return 1.0 - (levenshtein(left, right) / denominator)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


if __name__ == "__main__":
    main()
