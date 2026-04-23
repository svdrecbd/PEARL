#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_PATH = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT_PATH / "src"
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.paths import resolve_repo_path
from scripts import audit_manifold_v11_gate


LANE_FILENAMES = {
    "geometry_valid_needs_esm": "geometry_valid_needs_esm.jsonl",
    "esm_valid_needs_geometry": "esm_valid_needs_geometry.jsonl",
    "single_motif_background_negatives": "single_motif_background_negatives.jsonl",
    "motif_failure_negatives": "motif_failure_negatives.jsonl",
    "length_offtarget_selected": "length_offtarget_selected.jsonl",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build manifold v1.2 offline failure/repair lanes from v1.1 audits")
    parser.add_argument("--robustness-summary-path", required=True)
    parser.add_argument("--ablation-root", default="reports/ablations")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-per-lane", type=int, default=512)
    parser.add_argument("--length-delta-threshold", type=int, default=40)
    return parser.parse_args()


def resolved(value: str) -> Path:
    path = resolve_repo_path(value)
    if path is None or path.startswith("tinker://"):
        raise ValueError(f"could not resolve local path: {value}")
    return Path(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def lane_base_record(record: dict[str, Any], candidate: dict[str, Any], lane: str) -> dict[str, Any]:
    length_delta = record.get("candidate_length_delta", record.get("selected_length_delta"))
    return {
        "lane": lane,
        "run_name": record.get("run_name"),
        "prompt_count": record.get("prompt_count"),
        "temperature": record.get("temperature"),
        "seed": record.get("seed"),
        "step": record.get("step"),
        "prompt": record.get("prompt"),
        "requested_length": record.get("requested_length"),
        "length": candidate.get("length"),
        "length_delta": length_delta,
        "selected": bool(record.get("selected", True)),
        "sequence": candidate.get("sequence"),
        "mode": candidate.get("mode"),
        "stage1_rank": candidate.get("stage1_rank"),
        "stage2_rank": candidate.get("stage2_rank"),
        "stage2_score": candidate.get("stage2_score"),
        "raw_esm_score": candidate.get("raw_esm_score"),
        "geometry_score": candidate.get("geometry_score"),
        "best_gap_error": candidate.get("best_gap_error"),
        "ser_asp_gap_error": candidate.get("ser_asp_gap_error"),
        "asp_his_gap_error": candidate.get("asp_his_gap_error"),
        "ser_his_gap_error": candidate.get("ser_his_gap_error"),
        "motif_count": candidate.get("motif_count"),
        "has_family_serine_motif": candidate.get("has_family_serine_motif"),
        "geometry_passes": candidate.get("geometry_passes"),
        "esm_gate_pass": candidate.get("esm_gate_pass"),
        "passes_core_screen": candidate.get("passes_core_screen"),
        "functional_bridge_passes": candidate.get("functional_bridge_passes"),
        "family_faithful_bridge_passes": candidate.get("family_faithful_bridge_passes"),
        "trainability_reason": candidate.get("trainability_reason"),
        "candidate_audit_path": record.get("candidate_audit_path"),
    }


def sequence_key(row: dict[str, Any]) -> str:
    return str(row.get("sequence") or "")


def dedupe_and_limit(rows: list[dict[str, Any]], *, max_rows: int, sort_key: Any) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=sort_key):
        key = sequence_key(row)
        if not key or key in deduped:
            continue
        deduped[key] = row
        if len(deduped) >= max_rows:
            break
    return list(deduped.values())


def geometry_lane_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -to_float(row.get("geometry_score")),
        -to_float(row.get("stage2_score")),
        -to_float(row.get("raw_esm_score")),
        abs(int(row.get("length_delta") or 0)),
        str(row.get("sequence") or ""),
    )


def esm_lane_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -to_float(row.get("raw_esm_score")),
        -to_float(row.get("stage2_score")),
        abs(int(row.get("length_delta") or 0)),
        str(row.get("sequence") or ""),
    )


def background_lane_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -to_float(row.get("stage2_score")),
        -to_float(row.get("raw_esm_score")),
        abs(int(row.get("length_delta") or 0)),
        str(row.get("sequence") or ""),
    )


def motif_failure_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(row.get("motif_count") or 0) == 0,
        -to_float(row.get("stage2_score")),
        abs(int(row.get("length_delta") or 0)),
        str(row.get("sequence") or ""),
    )


def length_lane_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -abs(int(row.get("length_delta") or 0)),
        str(row.get("mode") or ""),
        str(row.get("sequence") or ""),
    )


def assign_candidate_lane(record: dict[str, Any]) -> str | None:
    candidate = record["candidate"]
    mode = str(candidate.get("mode") or "")
    if mode == "geometry_only":
        return "geometry_valid_needs_esm"
    if mode == "stability_only":
        return "esm_valid_needs_geometry"
    if mode == "single_motif_no_geom_no_esm":
        return "single_motif_background_negatives"
    if mode in {"missing_motif", "motif_spam"}:
        return "motif_failure_negatives"
    return None


def build_lanes(args: argparse.Namespace) -> dict[str, Any]:
    summary_path = resolved(args.robustness_summary_path)
    ablation_root = resolved(args.ablation_root)
    output_dir = resolved(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    records = audit_manifold_v11_gate.collect_candidate_records(summary_path, ablation_root)
    raw_records = records["candidate_records"]
    selected_records = records["selected_records"]

    lane_candidates: dict[str, list[dict[str, Any]]] = {lane: [] for lane in LANE_FILENAMES}
    raw_lane_counts: Counter[str] = Counter()
    for record in raw_records:
        lane = assign_candidate_lane(record)
        if lane is None:
            continue
        raw_lane_counts[lane] += 1
        lane_candidates[lane].append(lane_base_record(record, record["candidate"], lane))

    for record in selected_records:
        delta = record.get("selected_length_delta")
        if delta is None or abs(int(delta)) <= int(args.length_delta_threshold):
            continue
        lane = "length_offtarget_selected"
        raw_lane_counts[lane] += 1
        lane_candidates[lane].append(lane_base_record(record, record["selected_candidate"], lane))

    sort_keys = {
        "geometry_valid_needs_esm": geometry_lane_key,
        "esm_valid_needs_geometry": esm_lane_key,
        "single_motif_background_negatives": background_lane_key,
        "motif_failure_negatives": motif_failure_key,
        "length_offtarget_selected": length_lane_key,
    }
    selected_lanes: dict[str, list[dict[str, Any]]] = {}
    for lane, rows in lane_candidates.items():
        selected_lanes[lane] = dedupe_and_limit(rows, max_rows=int(args.max_per_lane), sort_key=sort_keys[lane])
        write_jsonl(output_dir / LANE_FILENAMES[lane], selected_lanes[lane])

    summary = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "robustness_summary_path": str(summary_path),
        "ablation_root": str(ablation_root),
        "output_dir": str(output_dir),
        "config": {
            "max_per_lane": int(args.max_per_lane),
            "length_delta_threshold": int(args.length_delta_threshold),
        },
        "input_counts": {
            "raw_candidate_records": len(raw_records),
            "selected_records": len(selected_records),
            "missing_audits": len(records["missing_audits"]),
        },
        "raw_lane_counts": dict(sorted(raw_lane_counts.items())),
        "selected_lane_counts": {lane: len(rows) for lane, rows in selected_lanes.items()},
        "outputs": {lane: str(output_dir / filename) for lane, filename in LANE_FILENAMES.items()},
        "next_step": (
            "Use these lanes for offline v1.2 constructor work only. Do not launch paid training until "
            "offline replay produces nonzero single-motif plus geometry plus ESM candidates."
        ),
    }
    summary_path_out = output_dir / "v12_offline_lanes_summary.json"
    summary["outputs"]["summary"] = str(summary_path_out)
    summary_path_out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    args = parse_args()
    print(json.dumps(build_lanes(args), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
