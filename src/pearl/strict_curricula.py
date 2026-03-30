from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


PROMPT_BUCKET_NUMBER_RE = re.compile(r"\d+")
PROMPT_BUCKET_WS_RE = re.compile(r"\s+")


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


def normalize_prompt_bucket(prompt: str) -> str:
    prompt = prompt.lower().strip()
    prompt = PROMPT_BUCKET_NUMBER_RE.sub("<n>", prompt)
    prompt = PROMPT_BUCKET_WS_RE.sub(" ", prompt)
    return prompt


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


def prompt_key(row: dict[str, Any]) -> str:
    return resolve_training_prompt(row)


def prompt_bucket_key(row: dict[str, Any]) -> str:
    return normalize_prompt_bucket(prompt_key(row))


def cluster_key(row: dict[str, Any]) -> str:
    cluster_id = row.get("cluster_id")
    if cluster_id is None:
        return f"missing::{str(row.get('sequence') or '')}"
    return str(cluster_id)


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
            float(row.get("best_gap_error", 999.0) or 999.0),
            len(str(row.get("sequence", ""))),
        )
    )
    return ranked


def ranked_strict_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = dedupe_by_sequence(rows)
    ranked.sort(
        key=lambda row: (
            -int(bool(row.get("family_faithful_bridge_passes"))),
            -int(bool(row.get("passes_core_screen"))),
            -int(bool(row.get("catalytic_geometry_passes"))),
            -float(row.get("reward", 0.0)),
            -float(row.get("esm_reward", row.get("esm_score", 0.0) or 0.0)),
            float(row.get("best_gap_error", 999.0) or 999.0),
            int(row.get("stage2_rank", 9999) or 9999),
            int(row.get("stage1_rank", 9999) or 9999),
            int(row.get("cluster_size", 9999) or 9999),
            len(str(row.get("sequence", ""))),
        )
    )
    return ranked


def coverage_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    prompts = [prompt_key(row) for row in rows]
    prompt_buckets = [prompt_bucket_key(row) for row in rows]
    clusters = [cluster_key(row) for row in rows]
    cluster_counts = Counter(clusters)
    largest_cluster_size = max(cluster_counts.values(), default=0)
    return {
        "prompt_count": len(set(prompts)),
        "prompt_bucket_count": len(set(prompt_buckets)),
        "cluster_count": len(set(clusters)),
        "largest_cluster_size": largest_cluster_size,
        "largest_cluster_share": (largest_cluster_size / len(rows)) if rows else 0.0,
    }


def select_prompt_cluster_diverse_rows(
    rows: list[dict[str, Any]],
    *,
    top_k: int,
    ranker: str,
    label: str,
) -> list[dict[str, Any]]:
    if ranker == "strict":
        ranked = ranked_strict_rows(rows)
    elif ranker == "anchor":
        ranked = ranked_anchor_rows(rows)
    else:
        raise ValueError(f"unknown ranker: {ranker}")

    selected: list[dict[str, Any]] = []
    seen_prompts: set[str] = set()
    seen_prompt_buckets: set[str] = set()
    seen_clusters: set[str] = set()

    for row in ranked:
        prompt = prompt_key(row)
        prompt_bucket = prompt_bucket_key(row)
        cluster = cluster_key(row)
        if prompt in seen_prompts or prompt_bucket in seen_prompt_buckets or cluster in seen_clusters:
            continue
        selected.append(row)
        seen_prompts.add(prompt)
        seen_prompt_buckets.add(prompt_bucket)
        seen_clusters.add(cluster)
        if len(selected) == top_k:
            return selected

    pool_stats = coverage_stats(ranked)
    raise SystemExit(
        f"{label} selection shortfall: needed {top_k}, selected {len(selected)} under hard "
        f"prompt/prompt-bucket/cluster diversity constraints. "
        f"pool_prompt_count={pool_stats['prompt_count']} "
        f"pool_prompt_bucket_count={pool_stats['prompt_bucket_count']} "
        f"pool_cluster_count={pool_stats['cluster_count']}"
    )


def select_top_ranked_rows(
    rows: list[dict[str, Any]],
    top_k: int | None,
    *,
    selection_mode: str,
    ranker: str,
    label: str,
) -> list[dict[str, Any]]:
    ranked = ranked_strict_rows(rows) if ranker == "strict" else ranked_anchor_rows(rows)
    if top_k is None or top_k <= 0:
        return ranked
    if selection_mode == "rank":
        return ranked[:top_k]
    if selection_mode == "prompt_cluster":
        return select_prompt_cluster_diverse_rows(rows, top_k=top_k, ranker=ranker, label=label)
    raise ValueError(f"unknown selection mode: {selection_mode}")


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
        "anchor_coverage": coverage_stats(selected_anchors),
    }
    return stage_b_rows, summary
