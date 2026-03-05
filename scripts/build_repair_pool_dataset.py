from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any


ROLE_TIER2_HIT = "tier2_hit"
ROLE_GEOMETRY_DOMINANT = "geometry_dominant_near_miss"


def main() -> None:
    args = parse_args()
    audit_paths = resolve_audit_paths(args)
    rows = collect_repair_pool_rows(
        audit_paths=audit_paths,
        selected_only=args.selected_only,
        max_geometry_per_step=args.max_geometry_per_step,
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

    summary_path = Path(args.summary_path) if args.summary_path else output_path.with_name(output_path.stem + "_summary.json")
    summary = build_summary(
        rows=rows,
        audit_paths=audit_paths,
        output_path=output_path,
        output_audit_path=output_audit_path,
    )
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a repair pool with Tier-2 hits + geometry-dominant near misses from candidate audits."
    )
    parser.add_argument("--audit-glob", help="Glob expression for candidate_audit.json files.")
    parser.add_argument("--audit-paths", help="Comma-separated list of candidate_audit.json paths.")
    parser.add_argument("--output-path", required=True)
    parser.add_argument(
        "--output-audit-path",
        help="Optional path to write a merged candidate_audit.json built from the output rows.",
    )
    parser.add_argument("--summary-path")
    parser.add_argument(
        "--selected-only",
        action="store_true",
        default=True,
        help="Only keep the selected candidate per step (default: true).",
    )
    parser.add_argument(
        "--include-unselected",
        action="store_false",
        dest="selected_only",
        help="Include all candidates from each step.",
    )
    parser.add_argument(
        "--max-geometry-per-step",
        type=int,
        default=1,
        help="When unselected candidates are included, keep up to this many geometry-dominant rows per step.",
    )
    parser.add_argument("--max-total", type=int, help="Optional cap on total rows after dedupe/sort.")
    args = parser.parse_args()
    if args.max_geometry_per_step < 0:
        raise SystemExit("--max-geometry-per-step must be >= 0")
    if args.max_total is not None and args.max_total < 1:
        raise SystemExit("--max-total must be >= 1")
    return args


def resolve_audit_paths(args: argparse.Namespace) -> list[Path]:
    paths: list[Path] = []
    if args.audit_glob:
        paths.extend(Path(path) for path in sorted(glob.glob(args.audit_glob)))
    if args.audit_paths:
        paths.extend(Path(part.strip()) for part in args.audit_paths.split(",") if part.strip())

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
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


def collect_repair_pool_rows(
    *,
    audit_paths: list[Path],
    selected_only: bool,
    max_geometry_per_step: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for audit_path in audit_paths:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        source_run = audit_path.parent.name
        for record in audit.get("records", []):
            step = int(record.get("step", -1))
            prompt = str(record.get("prompt") or "")
            sequence_prompt = str(record.get("sequence_prompt") or "")

            candidates = record.get("candidates", [])
            if selected_only:
                candidates = [candidate for candidate in candidates if bool(candidate.get("selected"))]

            step_rows: list[dict[str, Any]] = []
            for candidate in candidates:
                sequence = str(candidate.get("extracted_sequence") or "").strip()
                if not sequence:
                    continue
                role = classify_candidate(candidate)
                if role is None:
                    continue
                step_rows.append(
                    {
                        "pool_role": role,
                        "prompt": prompt,
                        "sequence_prompt": sequence_prompt,
                        "sequence": sequence,
                        "source_run": source_run,
                        "source_audit_path": str(audit_path),
                        "step": step,
                        "selected": bool(candidate.get("selected")),
                        "stage1_rank": to_int(candidate.get("stage1_rank")),
                        "stage2_rank": to_int(candidate.get("stage2_rank")),
                        "stage1_score": to_float(candidate.get("stage1_score")),
                        "stage2_score": to_float(candidate.get("stage2_score")),
                        "esm_score": to_float(candidate.get("raw_esm_score")),
                        "geometry_score": to_float(candidate.get("geometry_score")),
                        "motif_count": to_int(candidate.get("motif_count")),
                        "has_family_serine_motif": bool(candidate.get("has_family_serine_motif")),
                        "geometry_passes": bool(candidate.get("geometry_passes")),
                        "esm_gate_pass": bool(candidate.get("esm_gate_pass")),
                        "functional_bridge_passes": bool(candidate.get("functional_bridge_passes")),
                        "family_faithful_bridge_passes": bool(candidate.get("family_faithful_bridge_passes")),
                        "length": to_int(candidate.get("length"), default=len(sequence)),
                        "sample_text": candidate.get("sample_text"),
                    }
                )

            if not step_rows:
                continue

            step_rows.sort(key=sort_key)
            geometry_rows = [row for row in step_rows if row["pool_role"] == ROLE_GEOMETRY_DOMINANT]
            tier2_rows = [row for row in step_rows if row["pool_role"] == ROLE_TIER2_HIT]
            rows.extend(tier2_rows)
            rows.extend(geometry_rows[:max_geometry_per_step])
    return rows


def classify_candidate(candidate: dict[str, Any]) -> str | None:
    motif_count = to_int(candidate.get("motif_count"))
    geometry_passes = bool(candidate.get("geometry_passes"))
    esm_gate_pass = bool(candidate.get("esm_gate_pass"))
    functional_bridge = bool(candidate.get("functional_bridge_passes"))

    tier2_pass = functional_bridge or (motif_count == 1 and geometry_passes and esm_gate_pass)
    if tier2_pass:
        return ROLE_TIER2_HIT
    if motif_count == 1 and geometry_passes and not esm_gate_pass:
        return ROLE_GEOMETRY_DOMINANT
    return None


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_sequence: dict[str, dict[str, Any]] = {}
    for row in rows:
        sequence = row["sequence"]
        existing = best_by_sequence.get(sequence)
        if existing is None or sort_key(row) < sort_key(existing):
            best_by_sequence[sequence] = row
    return list(best_by_sequence.values())


def sort_key(row: dict[str, Any]) -> tuple[float | int | str, ...]:
    role_rank = 0 if row["pool_role"] == ROLE_TIER2_HIT else 1
    return (
        role_rank,
        -to_float(row.get("esm_score")),
        -to_float(row.get("stage2_score")),
        -to_float(row.get("geometry_score")),
        str(row.get("source_run") or ""),
        to_int(row.get("step")),
    )


def build_summary(
    *,
    rows: list[dict[str, Any]],
    audit_paths: list[Path],
    output_path: Path,
    output_audit_path: Path | None,
) -> dict[str, Any]:
    role_counts = {
        ROLE_TIER2_HIT: sum(1 for row in rows if row["pool_role"] == ROLE_TIER2_HIT),
        ROLE_GEOMETRY_DOMINANT: sum(1 for row in rows if row["pool_role"] == ROLE_GEOMETRY_DOMINANT),
    }
    source_runs = sorted({row["source_run"] for row in rows})
    per_run_counts: dict[str, dict[str, int]] = {}
    for source_run in source_runs:
        source_rows = [row for row in rows if row["source_run"] == source_run]
        per_run_counts[source_run] = {
            "total": len(source_rows),
            ROLE_TIER2_HIT: sum(1 for row in source_rows if row["pool_role"] == ROLE_TIER2_HIT),
            ROLE_GEOMETRY_DOMINANT: sum(1 for row in source_rows if row["pool_role"] == ROLE_GEOMETRY_DOMINANT),
        }

    mean_esm = sum(to_float(row["esm_score"]) for row in rows) / max(1, len(rows))
    mean_geometry = sum(to_float(row["geometry_score"]) for row in rows) / max(1, len(rows))
    mean_length = sum(to_int(row["length"]) for row in rows) / max(1, len(rows))

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
    }


def build_merged_candidate_audit(*, rows: list[dict[str, Any]], audit_paths: list[Path]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        source_step = to_int(row.get("step"), default=-1)
        sequence = str(row.get("sequence") or "")
        candidate = {
            "selected": bool(row.get("selected")),
            "sample_text": row.get("sample_text"),
            "extracted_sequence": sequence,
            "sample_token_count": 0,
            "stage1_rank": to_int(row.get("stage1_rank"), default=-1),
            "stage1_score": to_float(row.get("stage1_score")),
            "in_stage2_pool": True,
            "stage2_rank": to_int(row.get("stage2_rank"), default=-1),
            "stage2_score": to_float(row.get("stage2_score")),
            "hard_gate_pass": bool(row.get("functional_bridge_passes")),
            "soft_floor_pass": bool(row.get("esm_gate_pass")),
            "is_trainable": bool(row.get("functional_bridge_passes")),
            "trainability_reason": "merged_repair_pool",
            "soft_score": to_float(row.get("esm_score")),
            "soft_trainability_threshold": 85.0,
            "soft_trainability_margin": to_float(row.get("esm_score")) - 85.0,
            "length": to_int(row.get("length"), default=len(sequence)),
            "motif_count": to_int(row.get("motif_count")),
            "geometry_score": to_float(row.get("geometry_score")),
            "raw_esm_score": to_float(row.get("esm_score")),
            "esm_gate_pass": bool(row.get("esm_gate_pass")),
            "has_family_serine_motif": bool(row.get("has_family_serine_motif")),
            "geometry_passes": bool(row.get("geometry_passes")),
            "functional_bridge_passes": bool(row.get("functional_bridge_passes")),
            "family_faithful_bridge_passes": bool(row.get("family_faithful_bridge_passes")),
            "best_gap_error": None,
            "passes_core_screen": bool(row.get("functional_bridge_passes")),
        }
        records.append(
            {
                "step": int(index),
                "prompt": str(row.get("prompt") or ""),
                "sequence_prompt": str(row.get("sequence_prompt") or row.get("prompt") or ""),
                "selection_metadata": {
                    "source_run": str(row.get("source_run") or ""),
                    "source_step": source_step,
                    "pool_role": str(row.get("pool_role") or ""),
                },
                "source_run": str(row.get("source_run") or ""),
                "source_step": source_step,
                "pool_role": str(row.get("pool_role") or ""),
                "candidates": [candidate],
            }
        )

    return {
        "source_audit_paths": [str(path) for path in audit_paths],
        "records": records,
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


def to_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    main()
