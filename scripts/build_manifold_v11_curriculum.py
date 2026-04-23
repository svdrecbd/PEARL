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
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.paths import resolve_repo_path
from pearl.strict_curricula import infer_canonical_motif


ALLOWED_MOTIFS = {"GYSLG", "GYSQG"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build manifold v1.1 prompt-hole replay curriculum")
    parser.add_argument("--selected-path", required=True)
    parser.add_argument("--scaffold-bank-path", required=True)
    parser.add_argument("--audit-path", required=True)
    parser.add_argument("--prompts-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path", required=True)
    parser.add_argument("--purebred-path")
    parser.add_argument("--base-selected-count", type=int, default=160)
    parser.add_argument("--base-max-per-length", type=int, default=24)
    parser.add_argument("--base-max-per-parent", type=int, default=3)
    parser.add_argument("--p24-replay-repeat", type=int, default=2)
    parser.add_argument("--hit-replay-repeat", type=int, default=0)
    parser.add_argument("--purebred-top-k", type=int, default=4)
    parser.add_argument("--purebred-repeat", type=int, default=2)
    parser.add_argument("--recipe-stage", default="manifold_stage_a_v11")
    return parser.parse_args()


def resolved(value: str | None) -> Path | None:
    path = resolve_repo_path(value)
    if path is None:
        return None
    if path.startswith("tinker://"):
        raise ValueError(f"could not resolve local path: {value}")
    return Path(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def row_length(row: dict[str, Any]) -> int:
    return int(row.get("length") or row.get("sequence_length") or len(str(row.get("sequence") or "")))


def row_motif(row: dict[str, Any]) -> str:
    blueprint = row.get("blueprint") or {}
    motif = str(blueprint.get("motif") or row.get("derived_motif") or "").strip()
    if motif:
        return motif
    sequence = str(row.get("sequence") or "")
    return infer_canonical_motif(sequence, ALLOWED_MOTIFS) or ""


def selected_sort_key(row: dict[str, Any]) -> tuple[int, int, int, float, str]:
    return (
        -int(bool(row.get("bridge_quality_passes"))),
        int(row.get("mutation_count") or 0),
        int(row.get("selection_rank") or 10**9),
        -float(row.get("esm_score") or 0.0),
        str(row.get("sequence_id") or ""),
    )


def balanced_selected_rows(
    rows: list[dict[str, Any]],
    *,
    max_count: int,
    max_per_length: int,
    max_per_parent: int,
) -> list[dict[str, Any]]:
    by_length: dict[int, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=selected_sort_key):
        by_length.setdefault(row_length(row), []).append(row)

    length_counts: Counter[int] = Counter()
    parent_counts: Counter[str] = Counter()
    selected: list[dict[str, Any]] = []
    made_progress = True
    while len(selected) < max_count and made_progress:
        made_progress = False
        for length in sorted(by_length):
            if len(selected) >= max_count:
                break
            if length_counts[length] >= max_per_length:
                continue
            bucket = by_length[length]
            chosen_index = None
            for index, row in enumerate(bucket):
                parent = str(row.get("parent_sequence_id") or row.get("selection_cluster_id") or row.get("sequence_id") or "")
                if parent_counts[parent] < max_per_parent:
                    chosen_index = index
                    break
            if chosen_index is None:
                continue
            row = bucket.pop(chosen_index)
            if not bucket:
                by_length[length] = []
            selected.append(row)
            length_counts[length] += 1
            parent = str(row.get("parent_sequence_id") or row.get("selection_cluster_id") or row.get("sequence_id") or "")
            parent_counts[parent] += 1
            made_progress = True
    return selected


def normalize_selected_row(
    row: dict[str, Any],
    *,
    prompt: str,
    prompt_id: str,
    curriculum_role: str,
    curriculum_source: str,
    repeat_index: int,
    recipe_stage: str,
) -> dict[str, Any]:
    sequence = str(row["sequence"]).strip().upper()
    motif = row_motif(row)
    payload = dict(row)
    payload.update(
        {
            "candidate_id": str(row.get("sequence_id") or row.get("candidate_id") or ""),
            "sequence": sequence,
            "length": row_length(row),
            "sequence_length": len(sequence),
            "prompt": prompt,
            "prompt_id": prompt_id,
            "prompt_source": curriculum_source,
            "source_prompt": prompt,
            "sequence_prompt": prompt,
            "derived_motif": motif,
            "curriculum_role": curriculum_role,
            "curriculum_source": curriculum_source,
            "recipe_stage": recipe_stage,
            "strict_bucket": "manifold_bridge_quality" if row.get("bridge_quality_passes") else "manifold_strict",
            "functional_bridge_passes": True,
            "family_faithful_bridge_passes": True,
            "repeat_index": repeat_index,
        }
    )
    return payload


def normalize_scaffold_anchor(
    row: dict[str, Any],
    *,
    prompt_record: dict[str, Any],
    repeat_index: int,
    recipe_stage: str,
) -> dict[str, Any]:
    sequence = str(row["sequence"]).strip().upper()
    requested_length = prompt_record.get("requested_length")
    length = row_length(row)
    prompt = str(prompt_record["prompt"])
    replay_role = str(prompt_record.get("replay_role") or "p24_hole")
    curriculum_role = "p24_weak_hit_anchor" if replay_role == "p24_weak_hit" else "p24_hole_anchor"
    payload = dict(row)
    payload.update(
        {
            "candidate_id": str(row.get("sequence_id") or ""),
            "sequence": sequence,
            "length": length,
            "sequence_length": len(sequence),
            "prompt": prompt,
            "prompt_id": f"v1-p24-replay:step-{prompt_record['step']}:repeat-{repeat_index}",
            "prompt_source": "v1_p24_prompt_replay",
            "source_prompt": prompt,
            "sequence_prompt": prompt,
            "derived_motif": row_motif(row),
            "curriculum_role": curriculum_role,
            "curriculum_source": "strict_scaffold_p24_replay",
            "recipe_stage": recipe_stage,
            "strict_bucket": "strict_scaffold_anchor_no_esm",
            "functional_bridge_passes": False,
            "family_faithful_bridge_passes": bool(row.get("strict_manifold_passes")),
            "esm_score": float(row.get("esm_score") or 0.0),
            "requested_length": requested_length,
            "anchor_length_delta": length - int(requested_length) if requested_length is not None else None,
            "v1_replay_role": replay_role,
            "repeat_index": repeat_index,
        }
    )
    return payload


def normalize_gate_hit(
    hit: dict[str, Any],
    *,
    prompt_record: dict[str, Any],
    repeat_index: int,
    recipe_stage: str,
) -> dict[str, Any]:
    candidate = hit["selected_candidate"]
    sequence = str(candidate["sequence"]).strip().upper()
    prompt = str(prompt_record["prompt"])
    return {
        "candidate_id": f"v1-hit:p{prompt_record['prompt_count']}:step-{prompt_record['step']}:seed-{hit['seed']}",
        "sequence": sequence,
        "length": len(sequence),
        "sequence_length": len(sequence),
        "prompt": prompt,
        "prompt_id": f"v1-hit:p{prompt_record['prompt_count']}:step-{prompt_record['step']}:seed-{hit['seed']}:repeat-{repeat_index}",
        "prompt_source": "v1_gate_hit_prompt",
        "source_prompt": prompt,
        "sequence_prompt": prompt,
        "derived_motif": infer_canonical_motif(sequence, ALLOWED_MOTIFS) or "",
        "curriculum_role": "gate_hit_replay",
        "curriculum_source": "v1_gate_hit_replay",
        "recipe_stage": recipe_stage,
        "strict_bucket": "v1_functional_hit",
        "functional_bridge_passes": bool(candidate.get("functional_bridge_passes")),
        "family_faithful_bridge_passes": bool(candidate.get("family_faithful_bridge_passes")),
        "esm_gate_pass": bool(candidate.get("esm_gate_pass")),
        "geometry_passes": bool(candidate.get("geometry_passes")),
        "esm_score": float(candidate.get("raw_esm_score") or 0.0),
        "requested_length": prompt_record.get("requested_length"),
        "anchor_length_delta": len(sequence) - int(prompt_record["requested_length"])
        if prompt_record.get("requested_length") is not None
        else None,
        "source_prompt_count": int(prompt_record["prompt_count"]),
        "source_seed": int(hit["seed"]),
        "source_step": int(prompt_record["step"]),
        "repeat_index": repeat_index,
    }


def strict_scaffold_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("strict_manifold_passes")
        and not row.get("negative_example")
        and infer_canonical_motif(str(row.get("sequence") or ""), ALLOWED_MOTIFS)
    ]


def scaffold_sort_key(row: dict[str, Any], *, requested_length: int, usage_count: int) -> tuple[int, int, int, int, str]:
    blueprint = row.get("blueprint") or {}
    gap_error = int(blueprint.get("gap_error") or 10**6)
    source_roles = set(str(role) for role in (row.get("source_roles") or []))
    source_rank = 0 if "strict_positive" in source_roles else 1 if "candidate_scaffold" in source_roles else 2
    return (usage_count, abs(row_length(row) - requested_length), source_rank, gap_error, str(row.get("sequence_id") or ""))


def choose_scaffold_anchor(
    rows: list[dict[str, Any]],
    *,
    requested_length: int,
    usage: Counter[str],
) -> dict[str, Any]:
    if not rows:
        raise ValueError("strict scaffold bank has no usable rows")
    return min(
        rows,
        key=lambda row: scaffold_sort_key(
            row,
            requested_length=requested_length,
            usage_count=usage[str(row.get("sequence_id") or row.get("sequence") or "")],
        ),
    )


def default_prompt_for_row(row: dict[str, Any]) -> str:
    length = row_length(row)
    motif = row_motif(row)
    motif_clause = f" Prefer a single {motif} nucleophile motif." if motif else ""
    return (
        f"Generate a polyester-hydrolase-family cutinase sequence around {length} amino acids long."
        f"{motif_clause} Favor a PETase/cutinase-like catalytic triad. "
        "Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."
    )


def normalize_purebred_row(
    row: dict[str, Any],
    *,
    repeat_index: int,
    recipe_stage: str,
    index: int,
) -> dict[str, Any]:
    sequence = str(row["sequence"]).strip().upper()
    prompt = default_prompt_for_row(row)
    return {
        **row,
        "candidate_id": str(row.get("accession") or f"purebred:{index}"),
        "sequence": sequence,
        "length": row_length(row),
        "sequence_length": len(sequence),
        "prompt": prompt,
        "prompt_id": f"purebred:{index}:repeat-{repeat_index}",
        "prompt_source": "synthetic_purebred_anchor",
        "source_prompt": prompt,
        "sequence_prompt": prompt,
        "derived_motif": row_motif(row),
        "esm_score": float(row.get("esm_score") or 0.0),
        "curriculum_role": "purebred_anchor",
        "curriculum_source": "canonical_purebred",
        "recipe_stage": recipe_stage,
        "strict_bucket": "canonical_purebred",
        "functional_bridge_passes": True,
        "family_faithful_bridge_passes": True,
        "repeat_index": repeat_index,
    }


def build_base_rows(args: argparse.Namespace, selected_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = balanced_selected_rows(
        selected_rows,
        max_count=args.base_selected_count,
        max_per_length=args.base_max_per_length,
        max_per_parent=args.base_max_per_parent,
    )
    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            normalize_selected_row(
                row,
                prompt=default_prompt_for_row(row),
                prompt_id=f"phase2-balanced:{row.get('sequence_id')}",
                curriculum_role="balanced_phase2_anchor",
                curriculum_source="manifold_phase2_selected_balanced",
                repeat_index=0,
                recipe_stage=args.recipe_stage,
            )
        )
    return output


def build_p24_replay_rows(
    args: argparse.Namespace,
    *,
    audit: dict[str, Any],
    scaffold_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    usage: Counter[str] = Counter()
    output: list[dict[str, Any]] = []
    prompt_records = [
        record
        for record in audit.get("prompt_records", [])
        if int(record.get("prompt_count") or 0) == 24 and record.get("requested_length") is not None
    ]
    prompt_records.sort(key=lambda record: (str(record.get("replay_role")), int(record["step"])))
    for record in prompt_records:
        requested = int(record["requested_length"])
        for repeat_index in range(args.p24_replay_repeat):
            anchor = choose_scaffold_anchor(scaffold_rows, requested_length=requested, usage=usage)
            anchor_id = str(anchor.get("sequence_id") or anchor.get("sequence") or "")
            usage[anchor_id] += 1
            output.append(
                normalize_scaffold_anchor(
                    anchor,
                    prompt_record=record,
                    repeat_index=repeat_index,
                    recipe_stage=args.recipe_stage,
                )
            )
    return output


def build_hit_replay_rows(args: argparse.Namespace, *, audit: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in audit.get("prompt_records", []):
        hits = [
            seed_record
            for seed_record in record.get("seed_records", [])
            if bool(seed_record.get("selected_candidate", {}).get("functional_bridge_passes"))
        ]
        for hit in hits:
            for repeat_index in range(args.hit_replay_repeat):
                output.append(
                    normalize_gate_hit(
                        hit,
                        prompt_record=record,
                        repeat_index=repeat_index,
                        recipe_stage=args.recipe_stage,
                    )
                )
    return output


def build_purebred_rows(args: argparse.Namespace, purebred_path: Path | None) -> list[dict[str, Any]]:
    if purebred_path is None or args.purebred_top_k <= 0:
        return []
    purebreds = [
        row
        for row in read_jsonl(purebred_path)
        if infer_canonical_motif(str(row.get("sequence") or ""), ALLOWED_MOTIFS)
    ][: args.purebred_top_k]
    output: list[dict[str, Any]] = []
    for index, row in enumerate(purebreds):
        for repeat_index in range(args.purebred_repeat):
            output.append(
                normalize_purebred_row(
                    row,
                    repeat_index=repeat_index,
                    recipe_stage=args.recipe_stage,
                    index=index,
                )
            )
    return output


def build_curriculum(args: argparse.Namespace) -> dict[str, Any]:
    selected_path = resolved(args.selected_path)
    scaffold_bank_path = resolved(args.scaffold_bank_path)
    audit_path = resolved(args.audit_path)
    prompts_path = resolved(args.prompts_path)
    output_path = resolved(args.output_path)
    summary_path = resolved(args.summary_path)
    purebred_path = resolved(args.purebred_path)

    assert selected_path is not None
    assert scaffold_bank_path is not None
    assert audit_path is not None
    assert prompts_path is not None
    assert output_path is not None
    assert summary_path is not None
    if not prompts_path.exists():
        raise FileNotFoundError(prompts_path)

    selected_rows = read_jsonl(selected_path)
    scaffold_rows = strict_scaffold_rows(read_jsonl(scaffold_bank_path))
    audit = read_json(audit_path)

    output_rows: list[dict[str, Any]] = []
    base_rows = build_base_rows(args, selected_rows)
    replay_rows = build_p24_replay_rows(args, audit=audit, scaffold_rows=scaffold_rows)
    hit_rows = build_hit_replay_rows(args, audit=audit)
    purebred_rows = build_purebred_rows(args, purebred_path)
    output_rows.extend(base_rows)
    output_rows.extend(replay_rows)
    output_rows.extend(hit_rows)
    output_rows.extend(purebred_rows)

    write_jsonl(output_path, output_rows)

    source_counts = Counter(str(row.get("curriculum_source") or "") for row in output_rows)
    role_counts = Counter(str(row.get("curriculum_role") or "") for row in output_rows)
    length_counts = Counter(str(row.get("length") or 0) for row in output_rows)
    requested_deltas = [
        int(row["anchor_length_delta"])
        for row in output_rows
        if row.get("anchor_length_delta") is not None
    ]
    sequence_counts = Counter(str(row.get("sequence") or "") for row in output_rows)
    parent_counts = Counter(str(row.get("parent_sequence_id") or row.get("candidate_id") or "") for row in output_rows)
    summary = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "selected_path": str(selected_path),
        "scaffold_bank_path": str(scaffold_bank_path),
        "audit_path": str(audit_path),
        "prompts_path": str(prompts_path),
        "purebred_path": str(purebred_path) if purebred_path else None,
        "output_path": str(output_path),
        "dataset_count": len(output_rows),
        "unique_sequence_count": len(sequence_counts),
        "source_counts": dict(sorted(source_counts.items())),
        "role_counts": dict(sorted(role_counts.items())),
        "length_histogram": dict(sorted(length_counts.items(), key=lambda item: int(item[0]))),
        "base_selected_rows": len(base_rows),
        "p24_replay_rows": len(replay_rows),
        "gate_hit_replay_rows": len(hit_rows),
        "purebred_rows": len(purebred_rows),
        "repeat_config": {
            "p24_replay_repeat": args.p24_replay_repeat,
            "hit_replay_repeat": args.hit_replay_repeat,
            "purebred_repeat": args.purebred_repeat,
        },
        "base_selection_config": {
            "base_selected_count": args.base_selected_count,
            "base_max_per_length": args.base_max_per_length,
            "base_max_per_parent": args.base_max_per_parent,
        },
        "anchor_length_delta": {
            "count": len(requested_deltas),
            "min": min(requested_deltas) if requested_deltas else None,
            "max": max(requested_deltas) if requested_deltas else None,
            "mean_abs": round(sum(abs(value) for value in requested_deltas) / max(1, len(requested_deltas)), 3),
        },
        "max_sequence_repeat": max(sequence_counts.values(), default=0),
        "max_parent_or_candidate_share": round(
            max(parent_counts.values(), default=0) / max(1, len(output_rows)),
            6,
        ),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    print(json.dumps(build_curriculum(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
