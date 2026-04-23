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

from pearl.paths import REPO_ROOT, resolve_repo_path
from pearl.strict_curricula import infer_canonical_motif


ALLOWED_MOTIFS = {"GYSLG", "GYSQG"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a strict stage-A curriculum from manifold-selected rows")
    parser.add_argument("--selected-path", required=True)
    parser.add_argument("--prompts-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path", required=True)
    parser.add_argument("--purebred-path")
    parser.add_argument("--max-selected", type=int, default=230)
    parser.add_argument("--selected-repeat", type=int, default=1)
    parser.add_argument("--purebred-top-k", type=int, default=4)
    parser.add_argument("--purebred-repeat", type=int, default=2)
    parser.add_argument("--recipe-stage", default="manifold_stage_a")
    parser.add_argument("--max-prompt-length-delta", type=int, default=35)
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


def selected_sort_key(row: dict[str, Any]) -> tuple[int, int, float, str]:
    return (
        int(row.get("selection_rank") or 10**9),
        int(row.get("mutation_count") or 0),
        -float(row.get("esm_score") or 0.0),
        str(row.get("sequence_id") or ""),
    )


def row_motif(row: dict[str, Any]) -> str:
    blueprint = row.get("blueprint") or {}
    motif = str(blueprint.get("motif") or row.get("derived_motif") or "").strip()
    if motif:
        return motif
    sequence = str(row.get("sequence") or "")
    return infer_canonical_motif(sequence, ALLOWED_MOTIFS) or ""


def prompt_sort_key(prompt: dict[str, Any], *, target_length: int) -> tuple[int, int, str]:
    prompt_length = int(prompt.get("length") or 0)
    relevance = int(prompt.get("relevance_score") or 0)
    return (abs(prompt_length - target_length), -relevance, str(prompt.get("prompt_id") or ""))


def assign_prompt(
    *,
    row: dict[str, Any],
    prompts: list[dict[str, Any]],
    used_prompt_ids: set[str],
    max_prompt_length_delta: int,
) -> dict[str, Any]:
    target_length = int(row.get("length") or len(str(row.get("sequence") or "")))
    available = [prompt for prompt in prompts if str(prompt.get("prompt_id") or "") not in used_prompt_ids]
    if not available:
        available = prompts
    available.sort(key=lambda prompt: prompt_sort_key(prompt, target_length=target_length))
    chosen = available[0] if available else None
    motif = row_motif(row)

    if chosen is None:
        return synthetic_prompt(target_length=target_length, motif=motif)

    prompt_length = int(chosen.get("length") or target_length)
    if abs(prompt_length - target_length) > max_prompt_length_delta:
        return synthetic_prompt(target_length=target_length, motif=motif)

    prompt_id = str(chosen.get("prompt_id") or "")
    if prompt_id:
        used_prompt_ids.add(prompt_id)
    return {
        "prompt": str(chosen["prompt"]),
        "prompt_id": prompt_id,
        "prompt_length": prompt_length,
        "prompt_length_delta": prompt_length - target_length,
        "prompt_source": "nearest_train_prompt",
    }


def synthetic_prompt(*, target_length: int, motif: str) -> dict[str, Any]:
    motif_clause = f" Prefer a single {motif} nucleophile motif." if motif else ""
    return {
        "prompt": (
            f"Generate a polyester-hydrolase-family cutinase sequence around {target_length} amino acids long."
            f"{motif_clause} Favor a PETase/cutinase-like GxSxG nucleophile motif and compatible catalytic residues. "
            "Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."
        ),
        "prompt_id": f"synthetic:{target_length}:{motif or 'motif'}",
        "prompt_length": target_length,
        "prompt_length_delta": 0,
        "prompt_source": "synthetic_manifold_prompt",
    }


def normalize_selected_row(
    row: dict[str, Any],
    *,
    prompt_payload: dict[str, Any],
    repeat_index: int,
    recipe_stage: str,
) -> dict[str, Any]:
    sequence = str(row["sequence"]).strip().upper()
    motif = row_motif(row)
    strict_bucket = "manifold_bridge_quality" if row.get("bridge_quality_passes") else "manifold_strict"
    payload = dict(row)
    payload.update(prompt_payload)
    payload.update(
        {
            "candidate_id": str(row.get("sequence_id") or ""),
            "sequence": sequence,
            "length": int(row.get("length") or len(sequence)),
            "sequence_length": len(sequence),
            "source_prompt": prompt_payload["prompt"],
            "sequence_prompt": prompt_payload["prompt"],
            "derived_motif": motif,
            "curriculum_role": "tier1_pull",
            "curriculum_source": "manifold_phase2_selected",
            "recipe_stage": recipe_stage,
            "strict_bucket": strict_bucket,
            "functional_bridge_passes": True,
            "family_faithful_bridge_passes": True,
            "repeat_index": repeat_index,
        }
    )
    return payload


def normalize_purebred_row(
    row: dict[str, Any],
    *,
    prompt_payload: dict[str, Any],
    repeat_index: int,
    recipe_stage: str,
    index: int,
) -> dict[str, Any]:
    sequence = str(row["sequence"]).strip().upper()
    motif = row_motif(row)
    payload = dict(row)
    payload.update(prompt_payload)
    payload.update(
        {
            "candidate_id": str(row.get("accession") or f"purebred:{index}"),
            "sequence": sequence,
            "length": int(row.get("length") or len(sequence)),
            "sequence_length": len(sequence),
            "source_prompt": prompt_payload["prompt"],
            "sequence_prompt": prompt_payload["prompt"],
            "derived_motif": motif,
            "esm_score": float(row.get("esm_score") or 0.0),
            "curriculum_role": "tier1_pull",
            "curriculum_source": "canonical_purebred",
            "recipe_stage": recipe_stage,
            "strict_bucket": "canonical_purebred",
            "functional_bridge_passes": True,
            "family_faithful_bridge_passes": True,
            "repeat_index": repeat_index,
        }
    )
    return payload


def build_curriculum(args: argparse.Namespace) -> dict[str, Any]:
    selected_path = resolved(args.selected_path)
    prompts_path = resolved(args.prompts_path)
    output_path = resolved(args.output_path)
    summary_path = resolved(args.summary_path)
    purebred_path = resolved(args.purebred_path) if args.purebred_path else None

    selected_rows = sorted(read_jsonl(selected_path), key=selected_sort_key)[: args.max_selected]
    prompts = read_jsonl(prompts_path)
    used_prompt_ids: set[str] = set()
    output_rows: list[dict[str, Any]] = []

    for row in selected_rows:
        prompt_payload = assign_prompt(
            row=row,
            prompts=prompts,
            used_prompt_ids=used_prompt_ids,
            max_prompt_length_delta=args.max_prompt_length_delta,
        )
        for repeat_index in range(args.selected_repeat):
            output_rows.append(
                normalize_selected_row(
                    row,
                    prompt_payload=prompt_payload,
                    repeat_index=repeat_index,
                    recipe_stage=args.recipe_stage,
                )
            )

    purebred_rows: list[dict[str, Any]] = []
    if purebred_path is not None and args.purebred_top_k > 0:
        purebreds = [
            row
            for row in read_jsonl(purebred_path)
            if infer_canonical_motif(str(row.get("sequence") or ""), ALLOWED_MOTIFS)
        ][: args.purebred_top_k]
        for index, row in enumerate(purebreds):
            prompt_payload = assign_prompt(
                row=row,
                prompts=prompts,
                used_prompt_ids=used_prompt_ids,
                max_prompt_length_delta=args.max_prompt_length_delta,
            )
            for repeat_index in range(args.purebred_repeat):
                purebred_rows.append(
                    normalize_purebred_row(
                        row,
                        prompt_payload=prompt_payload,
                        repeat_index=repeat_index,
                        recipe_stage=args.recipe_stage,
                        index=index,
                    )
                )
    output_rows.extend(purebred_rows)

    write_jsonl(output_path, output_rows)

    source_counts = Counter(str(row.get("curriculum_source") or "") for row in output_rows)
    length_counts = Counter(str(row.get("length") or 0) for row in output_rows)
    prompt_source_counts = Counter(str(row.get("prompt_source") or "") for row in output_rows)
    selected_unique = {str(row.get("sequence_id") or row.get("candidate_id") or "") for row in selected_rows}
    output_unique = {str(row.get("sequence") or "") for row in output_rows}
    summary = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "selected_path": str(selected_path),
        "prompts_path": str(prompts_path),
        "purebred_path": str(purebred_path) if purebred_path else None,
        "output_path": str(output_path),
        "dataset_count": len(output_rows),
        "unique_sequence_count": len(output_unique),
        "selected_unique_count": len(selected_unique),
        "selected_dataset_rows": len(selected_rows) * args.selected_repeat,
        "purebred_dataset_rows": len(purebred_rows),
        "repeat_config": {
            "selected_repeat": args.selected_repeat,
            "purebred_repeat": args.purebred_repeat,
        },
        "source_counts": dict(sorted(source_counts.items())),
        "prompt_source_counts": dict(sorted(prompt_source_counts.items())),
        "length_histogram": dict(sorted(length_counts.items(), key=lambda item: int(item[0]))),
        "mutation_count_histogram": dict(
            sorted(
                Counter(str(row.get("mutation_count") or 0) for row in selected_rows).items(),
                key=lambda item: int(item[0]),
            )
        ),
        "bridge_quality_selected_count": sum(bool(row.get("bridge_quality_passes")) for row in selected_rows),
        "max_prompt_length_delta": max(
            (abs(int(row.get("prompt_length_delta") or 0)) for row in output_rows),
            default=0,
        ),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    print(json.dumps(build_curriculum(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
