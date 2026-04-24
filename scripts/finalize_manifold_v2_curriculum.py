#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any


ROOT_PATH = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT_PATH / "src"
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


DEFAULT_SELECTED_PATH = (
    ROOT_PATH
    / "reports/analysis/manifold_v2_offline_constructor_20260424_batch2/v2_constructor_final_reselected.jsonl"
)
DEFAULT_PUREBRED_PATH = ROOT_PATH / "data/petase_family_expanded/kimi_micro_sft_top9_unicorn_only.jsonl"
DEFAULT_OUTPUT_DIR = ROOT_PATH / "reports/curriculum/manifold_v2_20260424"
AA_PATTERN = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")
ALLOWED_MOTIFS = ("GYSLG", "GYSQG", "GSSGG", "GHSQG")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize manifold v2 stage-A curriculum with audit metadata intact")
    parser.add_argument("--selected-path", default=str(DEFAULT_SELECTED_PATH))
    parser.add_argument("--purebred-path", default=str(DEFAULT_PUREBRED_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--output-name", default="manifold_v2_curriculum.jsonl")
    parser.add_argument("--summary-name", default="summary.json")
    parser.add_argument("--purebred-top-k", type=int, default=8)
    parser.add_argument("--esm-threshold", type=float, default=85.0)
    parser.add_argument("--min-selected-for-paid-gate", type=int, default=24)
    parser.add_argument("--min-unique-parent-sources", type=int, default=12)
    parser.add_argument("--min-unique-lengths", type=int, default=6)
    parser.add_argument("--recipe-stage", default="manifold_stage_a_v2")
    return parser.parse_args()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT_PATH / path
    return path


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def strict_manifold_passes(row: dict[str, Any]) -> bool:
    if bool(row.get("strict_manifold_passes")):
        return True
    family_assessment = row.get("family_assessment") or {}
    if isinstance(family_assessment, dict):
        return bool(family_assessment.get("strict_manifold_passes"))
    return False


def core_screen_passes(row: dict[str, Any]) -> bool:
    if bool(row.get("passes_core_screen")):
        return True
    core_evaluation = row.get("core_evaluation") or {}
    if isinstance(core_evaluation, dict):
        return bool(core_evaluation.get("passes_core_screen"))
    return False


def motif_for_row(row: dict[str, Any]) -> str:
    blueprint = row.get("blueprint") or {}
    motif = str(blueprint.get("motif") or row.get("derived_motif") or "").strip()
    if motif:
        return motif
    sequence = str(row.get("sequence") or "")
    for candidate in ALLOWED_MOTIFS:
        if candidate in sequence:
            return candidate
    return ""


def parent_source_key(row: dict[str, Any]) -> str:
    for key in ("parent_source_key", "parent_panel_id", "source_key", "parent_sequence_id"):
        value = row.get(key)
        if value:
            return str(value)
    return str(row.get("candidate_id") or row.get("sequence_id") or "")


def retargeted_prompt(*, length: int, motif: str) -> str:
    motif_clause = f" Prefer a single {motif} nucleophile motif." if motif else ""
    return (
        f"Generate a polyester-hydrolase-family cutinase sequence around {length} amino acids long."
        f"{motif_clause} Favor a PETase/cutinase-like catalytic triad with canonical serine, "
        "aspartate, and histidine spacing. Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."
    )


def selected_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(row.get("selection_rank") or 10**9),
        -float(row.get("esm_score") or 0.0),
        str(row.get("candidate_id") or row.get("sequence_id") or ""),
    )


def normalize_selected_row(row: dict[str, Any], *, rank: int, recipe_stage: str, esm_threshold: float) -> dict[str, Any]:
    sequence = str(row["sequence"]).strip().upper()
    if not AA_PATTERN.fullmatch(sequence):
        raise ValueError(f"selected row has invalid amino-acid sequence: {row.get('candidate_id')}")
    length = len(sequence)
    candidate_id = str(row.get("candidate_id") or row.get("sequence_id") or f"v2-selected-{rank}")
    prompt = str(row.get("prompt") or row.get("source_prompt") or "").strip()
    if not prompt:
        prompt = retargeted_prompt(length=length, motif=motif_for_row(row))
    payload = dict(row)
    payload.update(
        {
            "candidate_id": candidate_id,
            "sequence_id": str(row.get("sequence_id") or candidate_id),
            "sequence": sequence,
            "length": length,
            "sequence_length": length,
            "prompt": prompt,
            "source_prompt": str(row.get("source_prompt") or prompt),
            "sequence_prompt": str(row.get("sequence_prompt") or prompt),
            "prompt_source": str(row.get("prompt_source") or "synthetic_v2_length_confirming_prompt"),
            "prompt_length": length,
            "prompt_length_delta": int(row.get("prompt_length_delta") or 0),
            "requested_length": int(row.get("requested_length") or length),
            "derived_motif": motif_for_row(row),
            "finalization_rank": rank,
            "finalization_source": "manifold_v2_curriculum_finalizer",
            "source_curriculum_role": row.get("curriculum_role"),
            "curriculum_role": "v2_selected_candidate",
            "curriculum_source": "manifold_v2_constructor_reselected",
            "recipe_stage": recipe_stage,
            "strict_bucket": "v2_scored_constructor_selected",
            "parent_source_key": parent_source_key(row),
            "strict_manifold_passes": strict_manifold_passes(row),
            "passes_core_screen": core_screen_passes(row),
            "esm_gate_pass": float(row.get("esm_score") or 0.0) >= float(esm_threshold),
            "functional_bridge_passes": bool(row.get("functional_bridge_passes") or row.get("bridge_quality_passes")),
            "v2_family_faithful_proxy_passes": bool(row.get("family_faithful_proxy_passes")),
        }
    )
    return payload


def normalize_purebred_row(row: dict[str, Any], *, index: int, recipe_stage: str) -> dict[str, Any]:
    sequence = str(row["sequence"]).strip().upper()
    if not AA_PATTERN.fullmatch(sequence):
        raise ValueError(f"purebred row has invalid amino-acid sequence at index {index}")
    length = len(sequence)
    motif = motif_for_row(row)
    prompt = retargeted_prompt(length=length, motif=motif)
    candidate_id = str(row.get("accession") or row.get("candidate_id") or f"purebred_{index}")
    payload = dict(row)
    payload.update(
        {
            "candidate_id": candidate_id,
            "sequence_id": str(row.get("sequence_id") or candidate_id),
            "sequence": sequence,
            "length": length,
            "sequence_length": length,
            "prompt": prompt,
            "source_prompt": prompt,
            "sequence_prompt": prompt,
            "prompt_id": f"v2-purebred:{index}",
            "prompt_source": "synthetic_v2_purebred_prompt",
            "prompt_length": length,
            "prompt_length_delta": 0,
            "requested_length": length,
            "derived_motif": motif,
            "curriculum_role": "purebred_anchor",
            "curriculum_source": "canonical_purebred",
            "recipe_stage": recipe_stage,
            "strict_bucket": "canonical_purebred",
            "esm_score": float(row.get("esm_score") or 0.0),
            "functional_bridge_passes": True,
            "family_faithful_bridge_passes": True,
            "repeat_index": 0,
        }
    )
    return payload


def numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "mean": None, "max": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "mean": round(mean(values), 4),
        "max": round(max(values), 4),
    }


def build_summary(
    *,
    selected_rows: list[dict[str, Any]],
    purebred_rows: list[dict[str, Any]],
    output_rows: list[dict[str, Any]],
    args: argparse.Namespace,
    output_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    selected_count = len(selected_rows)
    parent_source_counts = Counter(parent_source_key(row) for row in selected_rows)
    length_counts = Counter(int(row["length"]) for row in selected_rows)
    strict_count = sum(strict_manifold_passes(row) for row in selected_rows)
    core_count = sum(core_screen_passes(row) for row in selected_rows)
    esm_count = sum(float(row.get("esm_score") or 0.0) >= float(args.esm_threshold) for row in selected_rows)
    ready = (
        selected_count >= int(args.min_selected_for_paid_gate)
        and len(parent_source_counts) >= int(args.min_unique_parent_sources)
        and len(length_counts) >= int(args.min_unique_lengths)
        and strict_count == selected_count
        and core_count == selected_count
        and esm_count == selected_count
    )
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "selected_path": str(repo_path(args.selected_path)),
        "purebred_path": str(repo_path(args.purebred_path)),
        "output_path": str(output_path),
        "summary_path": str(summary_path),
        "total_rows": len(output_rows),
        "selected_candidates": selected_count,
        "purebred_anchors": len(purebred_rows),
        "unique_sequences": len({row["sequence"] for row in output_rows}),
        "role_counts": dict(sorted(Counter(str(row["curriculum_role"]) for row in output_rows).items())),
        "selected_counts": {
            "strict_manifold_passes": strict_count,
            "passes_core_screen": core_count,
            "esm_gate_passes": esm_count,
            "family_faithful_proxy_rows": sum(bool(row.get("family_faithful_proxy_passes")) for row in selected_rows),
            "bridge_quality_rows": sum(bool(row.get("bridge_quality_passes")) for row in selected_rows),
            "unique_parent_sources": len(parent_source_counts),
            "unique_lengths": len(length_counts),
            "mutation_count_histogram": dict(
                sorted(Counter(str(row.get("mutation_count")) for row in selected_rows).items())
            ),
            "length_histogram": dict(sorted((str(key), value) for key, value in length_counts.items())),
            "parent_source_counts": dict(sorted(parent_source_counts.items())),
        },
        "score_summary": numeric_summary([float(row.get("esm_score") or 0.0) for row in selected_rows]),
        "ready_for_paid_gate": ready,
        "readiness_reason": (
            "finalized v2 curriculum preserves strict/core/ESM evidence and has enough breadth for a small p24-only paid gate"
            if ready
            else "finalized v2 curriculum is not broad or validated enough for a paid gate"
        ),
        "paid_gate_scope": "stage-A train plus p24-only diagnostic; no stage-B, p48, or broad mining from this artifact",
    }


def build_curriculum(args: argparse.Namespace) -> dict[str, Any]:
    selected_path = repo_path(args.selected_path)
    purebred_path = repo_path(args.purebred_path)
    output_dir = repo_path(args.output_dir)
    output_path = output_dir / str(args.output_name)
    summary_path = output_dir / str(args.summary_name)

    selected_input_rows = sorted(read_jsonl(selected_path), key=selected_sort_key)
    selected_rows = [
        normalize_selected_row(
            row,
            rank=index + 1,
            recipe_stage=str(args.recipe_stage),
            esm_threshold=float(args.esm_threshold),
        )
        for index, row in enumerate(selected_input_rows)
    ]
    purebred_rows = [
        normalize_purebred_row(row, index=index, recipe_stage=str(args.recipe_stage))
        for index, row in enumerate(read_jsonl(purebred_path)[: int(args.purebred_top_k)])
    ]
    output_rows = selected_rows + purebred_rows

    write_jsonl(output_path, output_rows)
    summary = build_summary(
        selected_rows=selected_rows,
        purebred_rows=purebred_rows,
        output_rows=output_rows,
        args=args,
        output_path=output_path,
        summary_path=summary_path,
    )
    write_json(summary_path, summary)
    return summary


def main() -> None:
    print(json.dumps(build_curriculum(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
