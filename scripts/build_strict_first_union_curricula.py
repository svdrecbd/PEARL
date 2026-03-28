#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.open() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def infer_canonical_motif(sequence: str, allowed_motifs: set[str]) -> str | None:
    for match in re.finditer(r"G.S.G", sequence):
        motif = match.group(0)
        if motif in allowed_motifs:
            return motif
    return None


def resolve_training_prompt(row: dict[str, Any]) -> str:
    prompt = str(row.get("prompt") or row.get("source_prompt") or "").strip()
    if prompt:
        return prompt

    length = int(row.get("length") or row.get("sequence_length") or len(str(row.get("sequence") or "")) or 300)
    motif = str(row.get("derived_motif") or "").strip()
    if not motif:
        motif = first_serine_motif(row) or ""
    motif_clause = f" with canonical serine motif {motif}" if motif else ""
    return (
        f"Generate a PETase-family esterase sequence around {length} aa"
        f"{motif_clause} while preserving catalytic bridge geometry."
    )


def first_serine_motif(row: dict[str, Any]) -> str | None:
    motifs = row.get("serine_motifs")
    if motifs:
        return str(motifs[0]).strip()
    family_eval = row.get("family_evaluation") or {}
    eval_motifs = family_eval.get("serine_motifs") or []
    if eval_motifs:
        return str(eval_motifs[0]).strip()
    raw_record = row.get("raw_record") or {}
    raw_eval = raw_record.get("family_evaluation") or {}
    raw_motifs = raw_eval.get("serine_motifs") or []
    if raw_motifs:
        return str(raw_motifs[0]).strip()
    return None


def normalize_row(
    row: dict[str, Any],
    *,
    curriculum_role: str,
    curriculum_source: str,
    recipe_stage: str,
    strict_bucket: str,
) -> dict[str, Any]:
    enriched = dict(row)
    enriched["prompt"] = resolve_training_prompt(enriched)
    enriched["sequence_prompt"] = str(enriched.get("sequence_prompt") or enriched["prompt"])
    if not enriched.get("derived_motif"):
        motif = first_serine_motif(enriched)
        if motif:
            enriched["derived_motif"] = motif
    enriched["curriculum_role"] = curriculum_role
    enriched["curriculum_source"] = curriculum_source
    enriched["recipe_stage"] = recipe_stage
    enriched["strict_bucket"] = strict_bucket
    return enriched


def dedupe_by_sequence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        sequence = str(row.get("sequence") or "")
        if not sequence or sequence in seen:
            continue
        seen.add(sequence)
        deduped.append(row)
    return deduped


def canonical_purebreds(rows: list[dict[str, Any]], allowed_motifs: set[str]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        motif = infer_canonical_motif(str(row["sequence"]), allowed_motifs)
        if motif is None:
            continue
        enriched = dict(row)
        enriched["derived_motif"] = motif
        selected.append(enriched)
    selected.sort(key=lambda row: (-float(row.get("esm_score", 0.0)), len(str(row.get("sequence", "")))))
    return dedupe_by_sequence(selected)


def ranked_anchor_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = dedupe_by_sequence(rows)
    ranked.sort(
        key=lambda row: (
            -float(row.get("reward", 0.0)),
            -float(row.get("esm_reward", row.get("esm_score", 0.0))),
            float(row.get("best_gap_error", 999)),
            len(str(row.get("sequence", ""))),
        )
    )
    return ranked


def repeated_rows(
    rows: list[dict[str, Any]],
    *,
    repeat_count: int,
    curriculum_source: str,
    strict_bucket: str,
    recipe_stage: str,
) -> list[dict[str, Any]]:
    repeated: list[dict[str, Any]] = []
    for row in rows:
        for repeat_index in range(repeat_count):
            enriched = normalize_row(
                row,
                curriculum_role="tier1_pull",
                curriculum_source=curriculum_source,
                recipe_stage=recipe_stage,
                strict_bucket=strict_bucket,
            )
            enriched["repeat_index"] = repeat_index
            repeated.append(enriched)
    return repeated


def build_stage_a_dataset(
    *,
    old_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
    pure_rows: list[dict[str, Any]],
    old_repeat: int,
    new_repeat: int,
    pure_repeat: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    dataset = (
        repeated_rows(
            old_rows,
            repeat_count=old_repeat,
            curriculum_source="a_run_family_faithful",
            strict_bucket="old_family_faithful",
            recipe_stage="strict_stage_a",
        )
        + repeated_rows(
            new_rows,
            repeat_count=new_repeat,
            curriculum_source="softmotif_family_faithful",
            strict_bucket="new_family_faithful",
            recipe_stage="strict_stage_a",
        )
        + repeated_rows(
            pure_rows,
            repeat_count=pure_repeat,
            curriculum_source="purebred_canonical",
            strict_bucket="canonical_purebred",
            recipe_stage="strict_stage_a",
        )
    )
    summary = {
        "dataset_count": len(dataset),
        "unique_sequence_count": len({row["sequence"] for row in dataset}),
        "source_counts": dict(Counter(row["curriculum_source"] for row in dataset)),
        "bucket_counts": dict(Counter(row["strict_bucket"] for row in dataset)),
        "repeat_config": {
            "old_family_faithful_repeat": old_repeat,
            "new_family_faithful_repeat": new_repeat,
            "canonical_purebred_repeat": pure_repeat,
        },
    }
    return dataset, summary


def build_stage_b_dataset(
    *,
    stage_a_rows: list[dict[str, Any]],
    anchor_rows: list[dict[str, Any]],
    anchor_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected_anchors = []
    for anchor_index, row in enumerate(anchor_rows[:anchor_count]):
        enriched = normalize_row(
            row,
            curriculum_role="tier2_anchor",
            curriculum_source="softmotif_bridge_anchor_top",
            recipe_stage="strict_stage_b",
            strict_bucket="bridge_anchor_small",
        )
        enriched["anchor_rank"] = anchor_index + 1
        selected_anchors.append(enriched)

    stage_b_rows = [dict(row, recipe_stage="strict_stage_b") for row in stage_a_rows] + selected_anchors
    summary = {
        "dataset_count": len(stage_b_rows),
        "unique_sequence_count": len({row["sequence"] for row in stage_b_rows}),
        "anchor_count": len(selected_anchors),
        "source_counts": dict(Counter(row["curriculum_source"] for row in stage_b_rows)),
        "role_counts": dict(Counter(row["curriculum_role"] for row in stage_b_rows)),
    }
    return stage_b_rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build strict-first union curricula from old/new family-faithful hits")
    parser.add_argument("--old-strict-path", required=True)
    parser.add_argument("--new-strict-path", required=True)
    parser.add_argument("--purebred-path", required=True)
    parser.add_argument("--anchor-path", required=True)
    parser.add_argument("--stage-a-output-path", required=True)
    parser.add_argument("--stage-a-summary-path", required=True)
    parser.add_argument("--stage-b-output-path", required=True)
    parser.add_argument("--stage-b-summary-path", required=True)
    parser.add_argument("--allowed-motifs", default="GYSLG,GYSQG")
    parser.add_argument("--old-repeat", type=int, default=2)
    parser.add_argument("--new-repeat", type=int, default=2)
    parser.add_argument("--pure-repeat", type=int, default=1)
    parser.add_argument("--anchor-count", type=int, default=12)
    args = parser.parse_args()

    allowed_motifs = {motif.strip() for motif in args.allowed_motifs.split(",") if motif.strip()}
    old_rows = dedupe_by_sequence(load_jsonl(Path(args.old_strict_path)))
    new_rows = dedupe_by_sequence(load_jsonl(Path(args.new_strict_path)))
    pure_rows = canonical_purebreds(load_jsonl(Path(args.purebred_path)), allowed_motifs)
    anchor_rows = ranked_anchor_rows(load_jsonl(Path(args.anchor_path)))

    stage_a_rows, stage_a_summary = build_stage_a_dataset(
        old_rows=old_rows,
        new_rows=new_rows,
        pure_rows=pure_rows,
        old_repeat=args.old_repeat,
        new_repeat=args.new_repeat,
        pure_repeat=args.pure_repeat,
    )
    stage_b_rows, stage_b_summary = build_stage_b_dataset(
        stage_a_rows=stage_a_rows,
        anchor_rows=anchor_rows,
        anchor_count=args.anchor_count,
    )

    write_jsonl(Path(args.stage_a_output_path), stage_a_rows)
    write_jsonl(Path(args.stage_b_output_path), stage_b_rows)

    stage_a_summary.update(
        {
            "old_unique_count": len(old_rows),
            "new_unique_count": len(new_rows),
            "canonical_purebred_unique_count": len(pure_rows),
            "allowed_motifs": sorted(allowed_motifs),
            "output_path": args.stage_a_output_path,
        }
    )
    Path(args.stage_a_summary_path).write_text(json.dumps(stage_a_summary, indent=2) + "\n")

    stage_b_summary.update(
        {
            "anchor_source_pool_count": len(anchor_rows),
            "output_path": args.stage_b_output_path,
        }
    )
    Path(args.stage_b_summary_path).write_text(json.dumps(stage_b_summary, indent=2) + "\n")

    print(
        json.dumps(
            {
                "stage_a_summary_path": args.stage_a_summary_path,
                "stage_b_summary_path": args.stage_b_summary_path,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
