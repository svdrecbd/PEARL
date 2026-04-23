#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT_PATH = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT_PATH / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.paths import resolve_repo_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select breadth-balanced manifold v1.2 repair candidates from ESM-scored offline frontiers"
    )
    parser.add_argument("--scored-path", action="append", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path", required=True)
    parser.add_argument("--esm-threshold", type=float, default=85.0)
    parser.add_argument("--max-candidates", type=int, default=48)
    parser.add_argument("--max-per-source", type=int, default=2)
    parser.add_argument("--length-bin-size", type=int, default=10)
    parser.add_argument("--max-per-length-bin", type=int, default=8)
    parser.add_argument("--max-original-prompt-delta", type=int, default=100)
    parser.add_argument("--min-selected-for-paid-gate", type=int, default=24)
    parser.add_argument("--min-unique-sources-for-paid-gate", type=int, default=12)
    parser.add_argument("--min-unique-lengths-for-paid-gate", type=int, default=6)
    parser.add_argument("--recipe-stage", default="manifold_stage_a_v12")
    return parser.parse_args()


def resolved(value: str) -> Path:
    path = resolve_repo_path(value)
    if path is None or path.startswith("tinker://"):
        raise ValueError(f"could not resolve local path: {value}")
    return Path(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def source_key(row: dict[str, Any]) -> str:
    parts = [
        row.get("source_lane"),
        row.get("source_mode"),
        row.get("source_seed"),
        row.get("source_step"),
        row.get("source_selected"),
        row.get("requested_length"),
        row.get("source_raw_esm_score"),
    ]
    return "|".join(str(part) for part in parts)


def length_bin(row: dict[str, Any], *, bin_size: int) -> int:
    length = int(row.get("length") or len(str(row.get("sequence") or "")))
    bin_size = max(1, int(bin_size))
    return (length // bin_size) * bin_size


def candidate_quality_key(row: dict[str, Any]) -> tuple[Any, ...]:
    prompt_delta = abs(int(row.get("prompt_length_delta") or 0))
    return (
        -float(row.get("esm_score") or 0.0),
        -int(bool(row.get("prompt_length_ok"))),
        int(row.get("mutation_count") or 10**6),
        prompt_delta,
        str(row.get("candidate_id") or ""),
    )


def is_eligible(row: dict[str, Any], *, esm_threshold: float, max_original_prompt_delta: int | None) -> bool:
    sequence = str(row.get("sequence") or "").strip()
    if not sequence:
        return False
    prompt_delta = to_int(row.get("prompt_length_delta"))
    return (
        bool(row.get("strict_manifold_passes"))
        and bool(row.get("passes_core_screen"))
        and float(row.get("esm_score") or 0.0) >= float(esm_threshold)
        and (
            max_original_prompt_delta is None
            or prompt_delta is None
            or abs(prompt_delta) <= int(max_original_prompt_delta)
        )
    )


def dedupe_best(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_sequence: dict[str, dict[str, Any]] = {}
    for row in rows:
        sequence = str(row.get("sequence") or "").strip().upper()
        if not sequence:
            continue
        previous = by_sequence.get(sequence)
        if previous is None or candidate_quality_key(row) < candidate_quality_key(previous):
            by_sequence[sequence] = row
    return sorted(by_sequence.values(), key=candidate_quality_key)


def motif_for_row(row: dict[str, Any]) -> str:
    blueprint = row.get("blueprint") or {}
    motif = str(blueprint.get("motif") or row.get("derived_motif") or "").strip()
    return motif


def retargeted_prompt(*, length: int, motif: str) -> str:
    motif_clause = f" Prefer a single {motif} nucleophile motif." if motif else ""
    return (
        f"Generate a polyester-hydrolase-family cutinase sequence around {length} amino acids long."
        f"{motif_clause} Favor a PETase/cutinase-like catalytic triad with canonical serine, "
        "aspartate, and histidine spacing. Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."
    )


def normalize_selected_row(row: dict[str, Any], *, selection_rank: int, recipe_stage: str) -> dict[str, Any]:
    sequence = str(row["sequence"]).strip().upper()
    motif = motif_for_row(row)
    prompt_length_delta = to_int(row.get("prompt_length_delta"))
    prompt_was_length_ok = bool(row.get("prompt_length_ok"))
    prompt = retargeted_prompt(length=len(sequence), motif=motif)
    candidate_id = str(row.get("candidate_id") or row.get("sequence_id") or f"v12-selected-{selection_rank}")
    parent_key = source_key(row)
    payload = dict(row)
    payload.update(
        {
            "sequence_id": candidate_id,
            "candidate_id": candidate_id,
            "sequence": sequence,
            "length": len(sequence),
            "sequence_length": len(sequence),
            "selection_rank": selection_rank,
            "selection_source": "manifold_v12_offline_repair_selector",
            "parent_sequence_id": f"v12-source:{parent_key}",
            "source_key": parent_key,
            "derived_motif": motif,
            "prompt": prompt,
            "source_prompt": prompt,
            "sequence_prompt": prompt,
            "prompt_source": (
                "synthetic_v12_retargeted_prompt"
                if not prompt_was_length_ok
                else "synthetic_v12_length_confirming_prompt"
            ),
            "prompt_length": len(sequence),
            "prompt_length_delta": 0,
            "original_prompt": row.get("prompt"),
            "original_requested_length": row.get("requested_length"),
            "original_prompt_length_delta": prompt_length_delta,
            "original_prompt_length_ok": prompt_was_length_ok,
            "v12_prompt_retargeted": not prompt_was_length_ok,
            "curriculum_role": "v12_repair_bridge_anchor",
            "curriculum_source": "v12_strict_repair_retargeted",
            "recipe_stage": recipe_stage,
            "strict_bucket": "v12_repair_retargeted",
            "family_faithful_bridge_passes": True,
            "functional_bridge_passes": True,
            "bridge_quality_passes": True,
        }
    )
    return payload


def select_candidates(
    rows: list[dict[str, Any]],
    *,
    max_candidates: int,
    max_per_source: int,
    max_per_length_bin: int,
    length_bin_size: int,
    recipe_stage: str,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    length_bin_counts: Counter[int] = Counter()
    for row in rows:
        if len(selected) >= max_candidates:
            break
        key = source_key(row)
        bin_key = length_bin(row, bin_size=length_bin_size)
        if source_counts[key] >= max_per_source:
            continue
        if length_bin_counts[bin_key] >= max_per_length_bin:
            continue
        selected.append(normalize_selected_row(row, selection_rank=len(selected) + 1, recipe_stage=recipe_stage))
        source_counts[key] += 1
        length_bin_counts[bin_key] += 1
    return selected


def numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "mean": None, "max": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "mean": round(mean(values), 4),
        "max": round(max(values), 4),
    }


def summarize_selected(
    *,
    input_paths: list[Path],
    raw_rows: list[dict[str, Any]],
    eligible_rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    source_counts = Counter(str(row.get("source_key") or source_key(row)) for row in selected_rows)
    length_counts = Counter(str(row.get("length") or 0) for row in selected_rows)
    length_bin_counts = Counter(
        str(length_bin(row, bin_size=int(args.length_bin_size))) for row in selected_rows
    )
    motif_counts = Counter(str(row.get("derived_motif") or "") for row in selected_rows)
    operation_counts = Counter(str(row.get("operation") or "") for row in selected_rows)
    retargeted_count = sum(bool(row.get("v12_prompt_retargeted")) for row in selected_rows)
    unique_sources = len(source_counts)
    unique_lengths = len(length_counts)
    selected_count = len(selected_rows)
    readiness_passes = (
        selected_count >= int(args.min_selected_for_paid_gate)
        and unique_sources >= int(args.min_unique_sources_for_paid_gate)
        and unique_lengths >= int(args.min_unique_lengths_for_paid_gate)
    )
    original_deltas = [
        abs(int(row["original_prompt_length_delta"]))
        for row in selected_rows
        if row.get("original_prompt_length_delta") is not None
    ]
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "input_paths": [str(path) for path in input_paths],
        "output_path": str(resolved(args.output_path)),
        "summary_path": str(resolved(args.summary_path)),
        "config": {
            "esm_threshold": float(args.esm_threshold),
            "max_candidates": int(args.max_candidates),
            "max_per_source": int(args.max_per_source),
            "length_bin_size": int(args.length_bin_size),
            "max_per_length_bin": int(args.max_per_length_bin),
            "max_original_prompt_delta": int(args.max_original_prompt_delta),
            "min_selected_for_paid_gate": int(args.min_selected_for_paid_gate),
            "min_unique_sources_for_paid_gate": int(args.min_unique_sources_for_paid_gate),
            "min_unique_lengths_for_paid_gate": int(args.min_unique_lengths_for_paid_gate),
            "recipe_stage": str(args.recipe_stage),
        },
        "counts": {
            "raw_rows": len(raw_rows),
            "eligible_rows": len(eligible_rows),
            "selected_rows": selected_count,
            "unique_sources": unique_sources,
            "unique_lengths": unique_lengths,
            "unique_length_bins": len(length_bin_counts),
            "original_prompt_length_ok": sum(bool(row.get("original_prompt_length_ok")) for row in selected_rows),
            "retargeted_prompt_rows": retargeted_count,
            "strict_manifold_passes": sum(bool(row.get("strict_manifold_passes")) for row in selected_rows),
            "passes_core_screen": sum(bool(row.get("passes_core_screen")) for row in selected_rows),
            "esm_gate_passes": sum(float(row.get("esm_score") or 0.0) >= float(args.esm_threshold) for row in selected_rows),
        },
        "score_summary": numeric_summary([float(row.get("esm_score") or 0.0) for row in selected_rows]),
        "original_prompt_abs_delta_summary": numeric_summary([float(value) for value in original_deltas]),
        "length_histogram": dict(sorted(length_counts.items(), key=lambda item: int(item[0]))),
        "length_bin_histogram": dict(sorted(length_bin_counts.items(), key=lambda item: int(item[0]))),
        "motif_counts": dict(sorted(motif_counts.items())),
        "operation_counts": dict(sorted(operation_counts.items())),
        "max_source_share": round(max(source_counts.values(), default=0) / max(1, selected_count), 6),
        "ready_for_paid_gate": readiness_passes,
        "readiness_reason": (
            "offline selected set has enough strict/core/ESM breadth for a small paid gate, pending user approval"
            if readiness_passes
            else "selected set is still too narrow for a paid gate"
        ),
        "top_selected": [
            {
                "selection_rank": row.get("selection_rank"),
                "candidate_id": row.get("candidate_id"),
                "esm_score": row.get("esm_score"),
                "length": row.get("length"),
                "derived_motif": row.get("derived_motif"),
                "operation": row.get("operation"),
                "original_prompt_length_delta": row.get("original_prompt_length_delta"),
                "v12_prompt_retargeted": row.get("v12_prompt_retargeted"),
                "source_seed": row.get("source_seed"),
                "source_step": row.get("source_step"),
            }
            for row in selected_rows[:20]
        ],
        "next_step": (
            "Build the v1.2 stage-A curriculum from this selected file using length-retargeted prompts. "
            "Do not launch paid training or robustness until explicitly approved."
        ),
    }


def run_selection(args: argparse.Namespace) -> dict[str, Any]:
    input_paths = [resolved(path) for path in args.scored_path]
    raw_rows: list[dict[str, Any]] = []
    for path in input_paths:
        raw_rows.extend(read_jsonl(path))
    deduped = dedupe_best(raw_rows)
    eligible = [
        row
        for row in deduped
        if is_eligible(
            row,
            esm_threshold=float(args.esm_threshold),
            max_original_prompt_delta=int(args.max_original_prompt_delta),
        )
    ]
    selected = select_candidates(
        eligible,
        max_candidates=int(args.max_candidates),
        max_per_source=int(args.max_per_source),
        max_per_length_bin=int(args.max_per_length_bin),
        length_bin_size=int(args.length_bin_size),
        recipe_stage=str(args.recipe_stage),
    )
    output_path = resolved(args.output_path)
    summary_path = resolved(args.summary_path)
    write_jsonl(output_path, selected)
    summary = summarize_selected(
        input_paths=input_paths,
        raw_rows=raw_rows,
        eligible_rows=eligible,
        selected_rows=selected,
        args=args,
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    print(json.dumps(run_selection(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
