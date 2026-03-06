from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_repair_pool_dataset import build_merged_candidate_audit, write_jsonl


ROLE_TIER2_HIT = "tier2_hit"
ROLE_GEOMETRY_EDGE = "geometry_edge_near_miss"
ROLE_STABILITY_EDGE = "stability_edge_near_miss"
ROLE_PRIORITY = {
    ROLE_TIER2_HIT: 0,
    ROLE_GEOMETRY_EDGE: 1,
    ROLE_STABILITY_EDGE: 2,
}


def main() -> None:
    args = parse_args()
    audit_paths = resolve_audit_paths(args)
    rows = collect_intersection_rows(
        audit_paths=audit_paths,
        selected_only=args.selected_only,
        max_tier2_per_step=args.max_tier2_per_step,
        max_geometry_per_step=args.max_geometry_per_step,
        max_stability_per_step=args.max_stability_per_step,
        min_geometry_raw_esm=args.min_geometry_raw_esm,
        min_stability_geometry_score=args.min_stability_geometry_score,
    )
    rows = dedupe_rows(rows)
    rows.sort(key=sort_key)

    if args.max_total is not None:
        rows = rows[: args.max_total]

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_path, rows)

    output_audit_path: Path | None = None
    if args.output_audit_path:
        output_audit_path = Path(args.output_audit_path)
        output_audit_path.parent.mkdir(parents=True, exist_ok=True)
        merged_audit_payload = build_merged_candidate_audit(rows=rows, audit_paths=audit_paths)
        output_audit_path.write_text(json.dumps(merged_audit_payload, indent=2), encoding="utf-8")

    summary = build_summary(
        rows=rows,
        audit_paths=audit_paths,
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
            "Build an intersection-leaning repair pool from candidate audits using geometry-high-ESM and "
            "stability-high-geometry near misses."
        )
    )
    parser.add_argument(
        "--audit-glob",
        action="append",
        default=[],
        help="Glob expression for candidate_audit.json files. Can be passed multiple times.",
    )
    parser.add_argument("--audit-paths", help="Comma-separated list of candidate_audit.json paths.")
    parser.add_argument("--output-path", required=True)
    parser.add_argument(
        "--output-audit-path",
        help="Optional path to write a merged candidate_audit.json from the output rows.",
    )
    parser.add_argument("--summary-path")
    parser.add_argument(
        "--selected-only",
        action="store_true",
        default=False,
        help="Only keep selected candidates from each step (default: false).",
    )
    parser.add_argument(
        "--max-tier2-per-step",
        type=int,
        default=2,
        help="Maximum Tier-2 candidates to keep per step.",
    )
    parser.add_argument(
        "--max-geometry-per-step",
        type=int,
        default=1,
        help="Maximum geometry-edge near misses to keep per step.",
    )
    parser.add_argument(
        "--max-stability-per-step",
        type=int,
        default=1,
        help="Maximum stability-edge near misses to keep per step.",
    )
    parser.add_argument(
        "--min-geometry-raw-esm",
        type=float,
        default=45.65,
        help="Minimum raw ESM score for geometry-edge near misses.",
    )
    parser.add_argument(
        "--min-stability-geometry-score",
        type=float,
        default=0.1512,
        help="Minimum geometry score for stability-edge near misses.",
    )
    parser.add_argument("--max-total", type=int, help="Optional cap on total rows after dedupe/sort.")
    args = parser.parse_args()

    if args.max_tier2_per_step < 0:
        raise SystemExit("--max-tier2-per-step must be >= 0")
    if args.max_geometry_per_step < 0:
        raise SystemExit("--max-geometry-per-step must be >= 0")
    if args.max_stability_per_step < 0:
        raise SystemExit("--max-stability-per-step must be >= 0")
    if args.max_total is not None and args.max_total < 1:
        raise SystemExit("--max-total must be >= 1")
    return args


def resolve_audit_paths(args: argparse.Namespace) -> list[Path]:
    raw_paths: list[Path] = []
    for audit_glob in args.audit_glob:
        raw_paths.extend(Path(path) for path in sorted(glob.glob(audit_glob)))
    if args.audit_paths:
        raw_paths.extend(Path(part.strip()) for part in args.audit_paths.split(",") if part.strip())

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in raw_paths:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        if not resolved.exists():
            raise SystemExit(f"Audit path does not exist: {resolved}")
        if resolved.name != "candidate_audit.json":
            raise SystemExit(f"Expected candidate_audit.json, got: {resolved}")
        seen.add(resolved)
        unique.append(resolved)

    if not unique:
        raise SystemExit("No candidate_audit.json files found; provide --audit-glob or --audit-paths")
    return unique


def collect_intersection_rows(
    *,
    audit_paths: list[Path],
    selected_only: bool,
    max_tier2_per_step: int,
    max_geometry_per_step: int,
    max_stability_per_step: int,
    min_geometry_raw_esm: float,
    min_stability_geometry_score: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for audit_path in audit_paths:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        source_run = audit_path.parent.name
        for record in audit.get("records", []):
            step = to_int(record.get("step"), default=-1)
            prompt = str(record.get("prompt") or "")
            sequence_prompt = str(record.get("sequence_prompt") or "")
            candidates = list(record.get("candidates", []))
            if selected_only:
                candidates = [candidate for candidate in candidates if bool(candidate.get("selected"))]

            tier2_rows: list[dict[str, Any]] = []
            geometry_rows: list[dict[str, Any]] = []
            stability_rows: list[dict[str, Any]] = []
            for candidate in candidates:
                row = candidate_to_row(
                    candidate=candidate,
                    source_run=source_run,
                    source_audit_path=audit_path,
                    step=step,
                    prompt=prompt,
                    sequence_prompt=sequence_prompt,
                    min_geometry_raw_esm=min_geometry_raw_esm,
                    min_stability_geometry_score=min_stability_geometry_score,
                )
                if row is None:
                    continue
                role = str(row["pool_role"])
                if role == ROLE_TIER2_HIT:
                    tier2_rows.append(row)
                elif role == ROLE_GEOMETRY_EDGE:
                    geometry_rows.append(row)
                elif role == ROLE_STABILITY_EDGE:
                    stability_rows.append(row)

            tier2_rows.sort(key=tier2_sort_key)
            geometry_rows.sort(key=geometry_sort_key)
            stability_rows.sort(key=stability_sort_key)

            rows.extend(tier2_rows[:max_tier2_per_step])
            rows.extend(geometry_rows[:max_geometry_per_step])
            rows.extend(stability_rows[:max_stability_per_step])
    return rows


def candidate_to_row(
    *,
    candidate: dict[str, Any],
    source_run: str,
    source_audit_path: Path,
    step: int,
    prompt: str,
    sequence_prompt: str,
    min_geometry_raw_esm: float,
    min_stability_geometry_score: float,
) -> dict[str, Any] | None:
    sequence = str(candidate.get("extracted_sequence") or "").strip()
    if not sequence:
        return None

    motif_count = to_int(candidate.get("motif_count"))
    geometry_passes = bool(candidate.get("geometry_passes"))
    esm_gate_pass = bool(candidate.get("esm_gate_pass"))
    functional_bridge_passes = bool(candidate.get("functional_bridge_passes"))
    family_faithful_bridge_passes = bool(candidate.get("family_faithful_bridge_passes"))
    geometry_score = to_float(candidate.get("geometry_score"))
    esm_score = to_float(candidate.get("raw_esm_score"))

    if motif_count != 1:
        return None

    role: str | None = None
    if functional_bridge_passes or family_faithful_bridge_passes or (geometry_passes and esm_gate_pass):
        role = ROLE_TIER2_HIT
    elif geometry_passes and not esm_gate_pass and esm_score >= min_geometry_raw_esm:
        role = ROLE_GEOMETRY_EDGE
    elif esm_gate_pass and not geometry_passes and geometry_score >= min_stability_geometry_score:
        role = ROLE_STABILITY_EDGE

    if role is None:
        return None

    return {
        "pool_role": role,
        "prompt": prompt,
        "sequence_prompt": sequence_prompt,
        "sequence": sequence,
        "source_run": source_run,
        "source_audit_path": str(source_audit_path),
        "step": step,
        "selected": bool(candidate.get("selected")),
        "stage1_rank": to_int(candidate.get("stage1_rank"), default=-1),
        "stage2_rank": to_int(candidate.get("stage2_rank"), default=-1),
        "stage1_score": to_float(candidate.get("stage1_score")),
        "stage2_score": to_float(candidate.get("stage2_score")),
        "esm_score": esm_score,
        "geometry_score": geometry_score,
        "motif_count": motif_count,
        "has_family_serine_motif": bool(candidate.get("has_family_serine_motif")),
        "geometry_passes": geometry_passes,
        "esm_gate_pass": esm_gate_pass,
        "functional_bridge_passes": functional_bridge_passes,
        "family_faithful_bridge_passes": family_faithful_bridge_passes,
        "length": to_int(candidate.get("length"), default=len(sequence)),
        "sample_text": candidate.get("sample_text"),
    }


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_sequence: dict[str, dict[str, Any]] = {}
    for row in rows:
        sequence = str(row.get("sequence") or "")
        if not sequence:
            continue
        existing = best_by_sequence.get(sequence)
        if existing is None or sort_key(row) < sort_key(existing):
            best_by_sequence[sequence] = row
    return list(best_by_sequence.values())


def tier2_sort_key(row: dict[str, Any]) -> tuple[float | int, ...]:
    return (
        -to_float(row.get("stage2_score")),
        -to_float(row.get("esm_score")),
        -to_float(row.get("geometry_score")),
    )


def geometry_sort_key(row: dict[str, Any]) -> tuple[float | int, ...]:
    return (
        -to_float(row.get("esm_score")),
        -to_float(row.get("stage2_score")),
        -to_float(row.get("geometry_score")),
    )


def stability_sort_key(row: dict[str, Any]) -> tuple[float | int, ...]:
    return (
        -to_float(row.get("geometry_score")),
        -to_float(row.get("stage2_score")),
        -to_float(row.get("esm_score")),
    )


def sort_key(row: dict[str, Any]) -> tuple[float | int | str, ...]:
    role_rank = ROLE_PRIORITY.get(str(row.get("pool_role") or ""), 9)
    if str(row.get("pool_role") or "") == ROLE_GEOMETRY_EDGE:
        primary_metric = -to_float(row.get("esm_score"))
    elif str(row.get("pool_role") or "") == ROLE_STABILITY_EDGE:
        primary_metric = -to_float(row.get("geometry_score"))
    else:
        primary_metric = -to_float(row.get("stage2_score"))
    return (
        role_rank,
        primary_metric,
        -to_float(row.get("stage2_score")),
        -to_float(row.get("esm_score")),
        -to_float(row.get("geometry_score")),
        str(row.get("source_run") or ""),
        to_int(row.get("step"), default=10**9),
        str(row.get("sequence") or ""),
    )


def build_summary(
    *,
    rows: list[dict[str, Any]],
    audit_paths: list[Path],
    output_path: Path,
    output_audit_path: Path | None,
    args: argparse.Namespace,
) -> dict[str, Any]:
    role_counts = {
        ROLE_TIER2_HIT: sum(1 for row in rows if row.get("pool_role") == ROLE_TIER2_HIT),
        ROLE_GEOMETRY_EDGE: sum(1 for row in rows if row.get("pool_role") == ROLE_GEOMETRY_EDGE),
        ROLE_STABILITY_EDGE: sum(1 for row in rows if row.get("pool_role") == ROLE_STABILITY_EDGE),
    }
    source_runs = sorted({str(row.get("source_run") or "") for row in rows})
    per_run_counts: dict[str, dict[str, int]] = {}
    for source_run in source_runs:
        source_rows = [row for row in rows if str(row.get("source_run") or "") == source_run]
        per_run_counts[source_run] = {
            "total": len(source_rows),
            ROLE_TIER2_HIT: sum(1 for row in source_rows if row.get("pool_role") == ROLE_TIER2_HIT),
            ROLE_GEOMETRY_EDGE: sum(1 for row in source_rows if row.get("pool_role") == ROLE_GEOMETRY_EDGE),
            ROLE_STABILITY_EDGE: sum(1 for row in source_rows if row.get("pool_role") == ROLE_STABILITY_EDGE),
        }

    mean_esm = sum(to_float(row.get("esm_score")) for row in rows) / max(1, len(rows))
    mean_geometry = sum(to_float(row.get("geometry_score")) for row in rows) / max(1, len(rows))
    mean_length = sum(to_int(row.get("length")) for row in rows) / max(1, len(rows))

    return {
        "output_path": str(output_path),
        "output_audit_path": str(output_audit_path) if output_audit_path else None,
        "source_audit_count": len(audit_paths),
        "source_audit_paths": [str(path) for path in audit_paths],
        "source_run_count": len(source_runs),
        "source_runs": source_runs,
        "total_rows": len(rows),
        "role_counts": role_counts,
        "per_run_counts": per_run_counts,
        "mean_esm_score": round(mean_esm, 4),
        "mean_geometry_score": round(mean_geometry, 4),
        "mean_length": round(mean_length, 2),
        "thresholds": {
            "min_geometry_raw_esm": args.min_geometry_raw_esm,
            "min_stability_geometry_score": args.min_stability_geometry_score,
            "max_tier2_per_step": args.max_tier2_per_step,
            "max_geometry_per_step": args.max_geometry_per_step,
            "max_stability_per_step": args.max_stability_per_step,
            "selected_only": bool(args.selected_only),
            "max_total": args.max_total,
        },
    }


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
