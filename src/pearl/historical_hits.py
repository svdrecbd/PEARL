from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pearl.family import normalized_identity, passes_normalized_identity


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def matches_any(rel_path: str, wave_name: str, globs: list[str]) -> bool:
    if not globs:
        return True
    rel_candidate = Path(rel_path)
    name_candidate = Path(wave_name)
    return any(rel_candidate.match(pattern) or name_candidate.match(pattern) for pattern in globs)


def discover_finalized_wave_dirs(
    reports_root: Path,
    *,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
) -> list[Path]:
    include_globs = include_globs or ["*"]
    exclude_globs = exclude_globs or []
    discovered: list[Path] = []
    for summary_path in sorted(reports_root.rglob("finalization_summary.json")):
        wave_dir = summary_path.parent
        rel_path = str(wave_dir.relative_to(reports_root))
        if not matches_any(rel_path, wave_dir.name, include_globs):
            continue
        if exclude_globs and matches_any(rel_path, wave_dir.name, exclude_globs):
            continue
        discovered.append(wave_dir)
    return discovered


def summarize_wave_inventory(wave_dirs: list[Path], *, reports_root: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for wave_dir in wave_dirs:
        summary_path = wave_dir / "finalization_summary.json"
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        results = payload.get("results") or []
        inventory.append(
            {
                "wave_name": str(payload.get("name") or wave_dir.name),
                "wave_dir": str(wave_dir),
                "relative_wave_dir": str(wave_dir.relative_to(reports_root)),
                "result_count": len(results),
                "functional_bridge_step_count": int(payload.get("functional_bridge_step_count") or 0),
                "family_faithful_bridge_step_count": int(payload.get("family_faithful_bridge_step_count") or 0),
            }
        )
    return inventory


def collect_hits(wave_dirs: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for wave_dir in wave_dirs:
        summary_path = wave_dir / "finalization_summary.json"
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        wave_name = str(payload.get("name") or wave_dir.name)
        for result in payload.get("results") or []:
            report_basename = Path(str(result["report_path"])).parent.name
            report_path = wave_dir / "runs" / report_basename / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            by_step = {int(record["step"]): record for record in report.get("records", [])}
            bridge_steps = sorted(
                set(int(step) for step in result.get("functional_bridge_steps", [])).union(
                    int(step) for step in result.get("family_faithful_bridge_steps", [])
                )
            )
            for step in bridge_steps:
                record = by_step.get(step)
                if record is None:
                    continue
                rows.append(extract_hit_row(wave_name=wave_name, report_run_name=report_basename, record=record))
    rows.sort(key=row_priority, reverse=True)
    return rows


def collect_report_rows(wave_dirs: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for wave_dir in wave_dirs:
        summary_path = wave_dir / "finalization_summary.json"
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        wave_name = str(payload.get("name") or wave_dir.name)
        for result in payload.get("results") or []:
            report_basename = Path(str(result["report_path"])).parent.name
            report_path = wave_dir / "runs" / report_basename / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            for record in report.get("records", []):
                rows.append(extract_report_row(wave_name=wave_name, report_run_name=report_basename, record=record))
    rows.sort(key=row_priority, reverse=True)
    return rows


def extract_hit_row(*, wave_name: str, report_run_name: str, record: dict[str, Any]) -> dict[str, Any]:
    reward_components = record.get("reward_components") or {}
    family_evaluation = record.get("family_evaluation") or {}
    catalytic_geometry = family_evaluation.get("catalytic_geometry") or {}
    selection_metadata = record.get("selection_metadata") or {}
    sequence_quality = record.get("sequence_quality") or {}
    novelty = family_evaluation.get("novelty") or {}
    serine_motifs = family_evaluation.get("serine_motifs") or []
    sequence = str(record.get("extracted_sequence") or "").strip()
    prompt = str(record.get("prompt") or "").strip()
    return {
        "wave_name": wave_name,
        "source_run": report_run_name,
        "source_step": int(record.get("step", -1)),
        "prompt": prompt,
        "prompt_bucket": normalize_prompt_bucket(prompt),
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


def extract_report_row(*, wave_name: str, report_run_name: str, record: dict[str, Any]) -> dict[str, Any]:
    row = extract_hit_row(wave_name=wave_name, report_run_name=report_run_name, record=record)
    reward_components = record.get("reward_components") or {}
    sequence_quality = record.get("sequence_quality") or {}
    row["esm_gate_pass"] = bool(reward_components.get("esm_gate_pass"))
    row["is_valid"] = bool(sequence_quality.get("is_valid"))
    row["hard_gate_pass"] = bool(sequence_quality.get("hard_gate_pass"))
    row["soft_floor_pass"] = bool(sequence_quality.get("soft_floor_pass"))
    row["is_trainable"] = bool(sequence_quality.get("is_trainable"))
    return row


def dedupe_exact_hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_sequence: dict[str, dict[str, Any]] = {}
    for row in rows:
        sequence = str(row.get("sequence") or "")
        existing = best_by_sequence.get(sequence)
        if existing is None or row_priority(row) > row_priority(existing):
            best_by_sequence[sequence] = row
    deduped = list(best_by_sequence.values())
    deduped.sort(key=row_priority, reverse=True)
    return deduped


def screen_report_rows(rows: list[dict[str, Any]], *, mode: str) -> list[dict[str, Any]]:
    screened: list[dict[str, Any]] = []
    for row in rows:
        hard_gate = bool(row.get("hard_gate_pass"))
        motif = bool(row.get("has_family_serine_motif"))
        core = bool(row.get("passes_core_screen"))
        geometry = bool(row.get("catalytic_geometry_passes"))
        esm_gate = bool(row.get("esm_gate_pass"))
        if mode == "hard_motif":
            keep = hard_gate and motif
        elif mode == "hard_motif_core_or_geom":
            keep = hard_gate and motif and (core or geometry)
        elif mode == "hard_motif_core_or_geom_or_esm":
            keep = hard_gate and motif and (core or geometry or esm_gate)
        elif mode == "hard_core_or_geom_or_esm":
            keep = hard_gate and (core or geometry or esm_gate)
        else:
            raise ValueError(f"unknown report screening mode: {mode}")
        if keep:
            screened.append(row)
    screened.sort(key=row_priority, reverse=True)
    return screened


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
        "prompt": row.get("prompt"),
        "prompt_bucket": row.get("prompt_bucket"),
        "sequence": row["sequence"],
        "length": row["length"],
        "reward": row["reward"],
        "esm_reward": row["esm_reward"],
        "functional_bridge_passes": row["functional_bridge_passes"],
        "family_faithful_bridge_passes": row["family_faithful_bridge_passes"],
        "passes_core_screen": row["passes_core_screen"],
        "hard_gate_pass": row.get("hard_gate_pass"),
        "soft_floor_pass": row.get("soft_floor_pass"),
        "esm_gate_pass": row.get("esm_gate_pass"),
        "is_trainable": row.get("is_trainable"),
        "best_gap_error": row["best_gap_error"],
        "closest_edit_identity": row["closest_edit_identity"],
        "stage1_rank": row["stage1_rank"],
        "stage2_rank": row["stage2_rank"],
        "stage2_score": row["stage2_score"],
        "cluster_id": row.get("cluster_id"),
        "cluster_size": row.get("cluster_size"),
    }


def source_contributions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_wave: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = by_wave.setdefault(
            str(row["wave_name"]),
            {
                "wave_name": str(row["wave_name"]),
                "hit_count": 0,
                "functional_count": 0,
                "family_faithful_count": 0,
            },
        )
        bucket["hit_count"] += 1
        bucket["functional_count"] += int(bool(row.get("functional_bridge_passes")))
        bucket["family_faithful_count"] += int(bool(row.get("family_faithful_bridge_passes")))
    return sorted(
        by_wave.values(),
        key=lambda row: (row["family_faithful_count"], row["functional_count"], row["hit_count"]),
        reverse=True,
    )


def select_anchor_rows(
    rows: list[dict[str, Any]],
    *,
    strict_anchor_count: int,
    bridge_anchor_count: int,
) -> dict[str, list[dict[str, Any]]]:
    strict_rows = [row for row in rows if bool(row.get("family_faithful_bridge_passes"))]
    bridge_rows = [
        row
        for row in rows
        if bool(row.get("functional_bridge_passes")) and not bool(row.get("family_faithful_bridge_passes"))
    ]
    strict_rows.sort(key=row_priority, reverse=True)
    bridge_rows.sort(key=row_priority, reverse=True)
    return {
        "strict": strict_rows[:strict_anchor_count],
        "bridge_only": bridge_rows[:bridge_anchor_count],
    }


def parse_identity_thresholds(raw: str) -> list[float]:
    values = [float(chunk.strip()) for chunk in raw.split(",") if chunk.strip()]
    return sorted(set(values), reverse=True)


def format_threshold_key(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def neighborhood_report_for_anchor(
    anchor: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
    *,
    identity_thresholds: list[float],
    max_examples_per_threshold: int,
) -> dict[str, Any]:
    anchor_sequence = str(anchor.get("sequence") or "")
    anchor_length = len(anchor_sequence)
    min_threshold = min(identity_thresholds) if identity_thresholds else 0.85
    scored_rows: list[tuple[float, dict[str, Any]]] = []
    for row in candidate_rows:
        sequence = str(row.get("sequence") or "")
        if sequence == anchor_sequence:
            continue
        max_length = max(anchor_length, len(sequence), 1)
        if abs(anchor_length - len(sequence)) / max_length > (1.0 - min_threshold):
            continue
        identity = normalized_identity(anchor_sequence, sequence)
        scored_rows.append((identity, row))
    scored_rows.sort(key=lambda item: (item[0], row_priority(item[1])), reverse=True)

    neighbors: dict[str, dict[str, Any]] = {}
    for threshold in identity_thresholds:
        key = format_threshold_key(threshold)
        rows = [row for identity, row in scored_rows if identity >= threshold]
        strict_rows = [row for row in rows if bool(row.get("family_faithful_bridge_passes"))]
        bridge_rows = [
            row for row in rows if bool(row.get("functional_bridge_passes")) and not bool(row.get("family_faithful_bridge_passes"))
        ]
        prompt_buckets = {str(row.get("prompt_bucket") or "") for row in rows if row.get("prompt_bucket")}
        clusters = {str(row.get("cluster_id")) for row in rows if row.get("cluster_id") is not None}
        neighbors[key] = {
            "identity_threshold": threshold,
            "neighbor_count": len(rows),
            "strict_neighbor_count": len(strict_rows),
            "bridge_only_neighbor_count": len(bridge_rows),
            "prompt_bucket_count": len(prompt_buckets),
            "cluster_count": len(clusters),
            "examples": [summarize_row(row) for row in rows[:max_examples_per_threshold]],
        }
    return {
        "anchor": summarize_row(anchor),
        "anchor_role": "strict" if bool(anchor.get("family_faithful_bridge_passes")) else "bridge_only",
        "neighbors_by_identity": neighbors,
    }


def classify_anchor_opportunity(report: dict[str, Any]) -> str:
    by_identity = report.get("neighbors_by_identity") or {}
    near = by_identity.get("0.95") or by_identity.get("0.98") or {}
    wide = by_identity.get("0.9") or by_identity.get("0.85") or {}
    near_total = int(near.get("neighbor_count") or 0)
    near_strict = int(near.get("strict_neighbor_count") or 0)
    near_bridge = int(near.get("bridge_only_neighbor_count") or 0)
    wide_total = int(wide.get("neighbor_count") or 0)
    if near_total >= 3 and near_strict > 0 and near_bridge > 0:
        return "green"
    if near_total >= 3 and (near_strict > 0 or near_bridge > 0):
        return "yellow"
    if near_total >= 3:
        return "yellow"
    if wide_total >= 5:
        return "yellow"
    return "red"


def normalize_prompt_bucket(prompt: str) -> str:
    lowered = prompt.lower().strip()
    if not lowered:
        return ""
    pieces: list[str] = []
    chunk = []
    for char in lowered:
        if char.isdigit():
            if not chunk or chunk[-1] != "<n>":
                if chunk:
                    pieces.append("".join(chunk))
                    chunk = []
                pieces.append("<n>")
            continue
        if char.isspace():
            if chunk:
                pieces.append("".join(chunk))
                chunk = []
            continue
        chunk.append(char)
    if chunk:
        pieces.append("".join(chunk))
    return " ".join(piece for piece in pieces if piece)


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


def summarize_shortlist(shortlist_rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = Counter(str(row.get("opportunity") or "unknown") for row in shortlist_rows)
    roles = Counter(str(row.get("anchor", {}).get("family_faithful_bridge_passes")) for row in shortlist_rows)
    return {
        "shortlist_count": len(shortlist_rows),
        "opportunity_counts": dict(labels),
        "role_counts": dict(roles),
    }
