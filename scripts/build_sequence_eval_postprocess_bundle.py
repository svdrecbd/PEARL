from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, TextIO


def main() -> None:
    args = parse_args()
    wave_dirs = resolve_wave_dirs(args.inputs)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    runs = collect_run_dirs(wave_dirs)
    if not runs:
        raise SystemExit("No run directories with summary.json found under the provided wave directories")

    temp_audit_rows_dir = output_dir / "_candidate_audit_rows"
    temp_audit_rows_dir.mkdir(parents=True, exist_ok=True)

    merged_scored_path = output_dir / "all_scored_candidates.jsonl"
    merged_bridges_path = output_dir / "all_functional_bridges.jsonl"
    family_faithful_path = output_dir / "family_faithful_bridges.jsonl"
    family_faithful_fasta_path = output_dir / "family_faithful_bridges.fasta"
    summary_path = output_dir / "bundle_summary.json"
    audits_root = output_dir / "candidate_audits"
    audits_root.mkdir(parents=True, exist_ok=True)

    wave_stats: dict[str, dict[str, Any]] = {}
    totals = {
        "summaries": 0,
        "records_evaluated": 0,
        "geometry_pass_count": 0,
        "functional_bridge_count": 0,
        "family_faithful_bridge_count": 0,
        "scored_candidate_rows": 0,
        "functional_bridge_rows": 0,
        "family_faithful_rows": 0,
    }
    source_run_counts: dict[str, int] = defaultdict(int)

    with (
        merged_scored_path.open("w", encoding="utf-8") as merged_scored_handle,
        merged_bridges_path.open("w", encoding="utf-8") as merged_bridges_handle,
        family_faithful_path.open("w", encoding="utf-8") as family_faithful_handle,
        family_faithful_fasta_path.open("w", encoding="utf-8") as family_faithful_fasta_handle,
    ):
        for wave_dir, run_dir in runs:
            wave_name = wave_dir.name
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            stats = summary["stats"]
            wave_totals = wave_stats.setdefault(
                wave_name,
                {
                    "summaries": 0,
                    "records_evaluated": 0,
                    "geometry_pass_count": 0,
                    "functional_bridge_count": 0,
                    "family_faithful_bridge_count": 0,
                    "scored_candidate_rows": 0,
                    "functional_bridge_rows": 0,
                    "family_faithful_rows": 0,
                },
            )
            for key in (
                "records_evaluated",
                "geometry_pass_count",
                "functional_bridge_count",
                "family_faithful_bridge_count",
            ):
                value = int(stats.get(key) or 0)
                totals[key] += value
                wave_totals[key] += value
            totals["summaries"] += 1
            wave_totals["summaries"] += 1

            scored_rows = stream_scored_candidates(
                run_dir=run_dir,
                merged_scored_handle=merged_scored_handle,
                temp_audit_rows_dir=temp_audit_rows_dir,
                source_run_counts=source_run_counts,
            )
            bridge_rows, faithful_rows = stream_bridge_rows(
                run_dir=run_dir,
                merged_bridges_handle=merged_bridges_handle,
                family_faithful_handle=family_faithful_handle,
                family_faithful_fasta_handle=family_faithful_fasta_handle,
            )
            totals["scored_candidate_rows"] += scored_rows
            totals["functional_bridge_rows"] += bridge_rows
            totals["family_faithful_rows"] += faithful_rows
            wave_totals["scored_candidate_rows"] += scored_rows
            wave_totals["functional_bridge_rows"] += bridge_rows
            wave_totals["family_faithful_rows"] += faithful_rows

    audit_paths = write_candidate_audits(temp_audit_rows_dir=temp_audit_rows_dir, audits_root=audits_root)

    summary = {
        "wave_dirs": [str(path) for path in wave_dirs],
        "run_dir_count": len(runs),
        "wave_stats": wave_stats,
        "totals": totals,
        "source_run_count": len(source_run_counts),
        "source_run_counts": dict(sorted(source_run_counts.items())),
        "paths": {
            "all_scored_candidates_jsonl": str(merged_scored_path),
            "all_functional_bridges_jsonl": str(merged_bridges_path),
            "family_faithful_bridges_jsonl": str(family_faithful_path),
            "family_faithful_bridges_fasta": str(family_faithful_fasta_path),
            "candidate_audits_root": str(audits_root),
            "candidate_audit_paths": [str(path) for path in audit_paths],
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bundle finished sequence-eval wave outputs into merged bridge files and synthetic candidate_audit inputs."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Wave directories (for example reports/nebius_sequence_eval/topoff1m-a-shard1-h100-20260325).",
    )
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def resolve_wave_dirs(inputs: list[str]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for raw in inputs:
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"Input path does not exist: {path}")
        if not path.is_dir():
            raise SystemExit(f"Expected a wave directory, got: {path}")
        if path in seen:
            continue
        seen.add(path)
        resolved.append(path)
    return resolved


def collect_run_dirs(wave_dirs: list[Path]) -> list[tuple[Path, Path]]:
    runs: list[tuple[Path, Path]] = []
    for wave_dir in wave_dirs:
        for summary_path in sorted((wave_dir / "runs").glob("*/summary.json")):
            runs.append((wave_dir, summary_path.parent))
    return runs


def stream_scored_candidates(
    *,
    run_dir: Path,
    merged_scored_handle: TextIO,
    temp_audit_rows_dir: Path,
    source_run_counts: dict[str, int],
) -> int:
    scored_path = run_dir / "scored_candidates.jsonl"
    rows = 0
    with scored_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            merged_scored_handle.write(line)
            merged_scored_handle.write("\n")

            row = json.loads(line)
            source_run = str(row.get("run_name") or "unknown_run")
            source_run_counts[source_run] += 1
            audit_row_path = temp_audit_rows_dir / source_run / "rows.jsonl"
            audit_row_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_row_path.open("a", encoding="utf-8") as audit_row_handle:
                audit_row_handle.write(json.dumps(build_synthetic_audit_record(row), sort_keys=True))
                audit_row_handle.write("\n")
            rows += 1
    return rows


def stream_bridge_rows(
    *,
    run_dir: Path,
    merged_bridges_handle: TextIO,
    family_faithful_handle: TextIO,
    family_faithful_fasta_handle: TextIO,
) -> tuple[int, int]:
    bridge_path = run_dir / "functional_bridges.jsonl"
    bridge_rows = 0
    faithful_rows = 0
    with bridge_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            merged_bridges_handle.write(line)
            merged_bridges_handle.write("\n")
            bridge_rows += 1

            row = json.loads(line)
            if not bool(row.get("family_faithful_bridge_passes")):
                continue
            faithful_rows += 1
            family_faithful_handle.write(line)
            family_faithful_handle.write("\n")
            header = row.get("candidate_id") or f"faithful_{faithful_rows}"
            sequence = str(row.get("sequence") or "")
            family_faithful_fasta_handle.write(f">{header}\n{sequence}\n")
    return bridge_rows, faithful_rows


def build_synthetic_audit_record(row: dict[str, Any]) -> dict[str, Any]:
    prompt = build_prompt_label(row)
    sequence = str(row.get("sequence") or "")
    raw_esm_score = to_float(row.get("raw_esm_score"))
    geometry_passes = bool(row.get("geometry_passes"))
    esm_gate_pass = bool(row.get("esm_gate_pass"))
    functional_bridge_passes = bool(row.get("functional_bridge_passes"))
    family_faithful_bridge_passes = bool(row.get("family_faithful_bridge_passes"))
    has_family_serine_motif = bool(row.get("has_family_serine_motif"))
    family_reward = to_float(row.get("family_reward"))
    near_dup_cluster = str(row.get("near_dup_cluster") or "")

    candidate = {
        "selected": True,
        "sample_text": row.get("raw_text"),
        "extracted_sequence": sequence,
        "sample_token_count": 0,
        "stage1_rank": -1,
        "stage1_score": raw_esm_score,
        "in_stage2_pool": True,
        "stage2_rank": -1,
        "stage2_score": family_reward,
        "hard_gate_pass": functional_bridge_passes,
        "soft_floor_pass": esm_gate_pass,
        "is_trainable": functional_bridge_passes,
        "trainability_reason": "sequence_eval_bundle",
        "soft_score": raw_esm_score,
        "soft_trainability_threshold": 85.0,
        "soft_trainability_margin": raw_esm_score - 85.0,
        "length": to_int(row.get("sequence_length"), default=len(sequence)),
        "motif_count": to_int(row.get("motif_count")),
        "geometry_score": 1.0 if geometry_passes else 0.0,
        "raw_esm_score": raw_esm_score,
        "esm_gate_pass": esm_gate_pass,
        "has_family_serine_motif": has_family_serine_motif,
        "geometry_passes": geometry_passes,
        "functional_bridge_passes": functional_bridge_passes,
        "family_faithful_bridge_passes": family_faithful_bridge_passes,
        "best_gap_error": None,
        "passes_core_screen": functional_bridge_passes,
        "candidate_id": row.get("candidate_id"),
        "near_dup_cluster": near_dup_cluster,
    }
    return {
        "source_run": str(row.get("run_name") or ""),
        "source_file": str(row.get("source_file") or ""),
        "source_line": to_int(row.get("source_line"), default=-1),
        "prompt": prompt,
        "sequence_prompt": str(row.get("source_input_file") or prompt),
        "prompt_index": to_int(row.get("prompt_index"), default=-1),
        "request_index": to_int(row.get("request_index"), default=-1),
        "sample_index": to_int(row.get("sample_index"), default=-1),
        "candidates": [candidate],
    }


def build_prompt_label(row: dict[str, Any]) -> str:
    source_file = str(row.get("source_file") or "unknown_source")
    source_line = to_int(row.get("source_line"), default=-1)
    prompt_index = to_int(row.get("prompt_index"), default=-1)
    request_index = to_int(row.get("request_index"), default=-1)
    sample_index = to_int(row.get("sample_index"), default=-1)
    return (
        f"{source_file}:{source_line} "
        f"(prompt_index={prompt_index}, request_index={request_index}, sample_index={sample_index})"
    )


def write_candidate_audits(*, temp_audit_rows_dir: Path, audits_root: Path) -> list[Path]:
    audit_paths: list[Path] = []
    for rows_path in sorted(temp_audit_rows_dir.glob("*/rows.jsonl")):
        source_run = rows_path.parent.name
        records = []
        with rows_path.open("r", encoding="utf-8") as handle:
            for index, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                record = json.loads(line)
                record["step"] = index
                records.append(record)
        output_path = audits_root / source_run / "candidate_audit.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": "sequence_eval_postprocess_bundle_v1",
            "source_run": source_run,
            "record_count": len(records),
            "records": records,
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        audit_paths.append(output_path)
    return audit_paths


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
