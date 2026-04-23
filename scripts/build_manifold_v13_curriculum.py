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

from scripts import build_manifold_v11_curriculum as v11


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build manifold v1.3 stage-A curriculum from v1.2 breadth anchors plus recovered p24 hit/support replay"
    )
    parser.add_argument("--base-selected-path", required=True)
    parser.add_argument("--scaffold-bank-path", required=True)
    parser.add_argument("--audit-path", required=True)
    parser.add_argument("--prompts-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path", required=True)
    parser.add_argument("--purebred-path")
    parser.add_argument("--base-selected-count", type=int, default=64)
    parser.add_argument("--base-max-per-length", type=int, default=4)
    parser.add_argument("--base-max-per-parent", type=int, default=2)
    parser.add_argument("--support-window", type=int, default=25)
    parser.add_argument("--support-prompt-limit", type=int, default=8)
    parser.add_argument("--support-max-per-requested-length", type=int, default=1)
    parser.add_argument("--support-replay-repeat", type=int, default=1)
    parser.add_argument("--hit-replay-repeat", type=int, default=3)
    parser.add_argument("--purebred-top-k", type=int, default=4)
    parser.add_argument("--purebred-repeat", type=int, default=2)
    parser.add_argument("--recipe-stage", default="manifold_stage_a_v13")
    return parser.parse_args()


def read_audit(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def prompt_id_with_repeat(prompt_id: str, repeat_index: int) -> str:
    return f"{prompt_id}:repeat-{repeat_index}" if repeat_index > 0 else prompt_id


def normalize_base_selected_row(
    row: dict[str, Any],
    *,
    repeat_index: int,
    recipe_stage: str,
) -> dict[str, Any]:
    sequence = str(row["sequence"]).strip().upper()
    prompt = str(row.get("prompt") or v11.default_prompt_for_row(row))
    prompt_id = str(row.get("prompt_id") or f"v13-base:{row.get('sequence_id') or row.get('candidate_id')}")
    payload = dict(row)
    payload.update(
        {
            "candidate_id": str(row.get("candidate_id") or row.get("sequence_id") or ""),
            "sequence": sequence,
            "length": v11.row_length(row),
            "sequence_length": len(sequence),
            "prompt": prompt,
            "prompt_id": prompt_id_with_repeat(prompt_id, repeat_index),
            "source_prompt": prompt,
            "sequence_prompt": prompt,
            "derived_motif": str(row.get("derived_motif") or v11.row_motif(row)),
            "curriculum_role": "v12_breadth_anchor",
            "curriculum_source": "v12_breadth_base",
            "recipe_stage": recipe_stage,
            "repeat_index": repeat_index,
        }
    )
    return payload


def nearest_hit_distance(*, requested_length: int, hit_lengths: list[int]) -> int:
    if not hit_lengths:
        return 10**9
    return min(abs(int(requested_length) - int(length)) for length in hit_lengths)


def support_prompt_sort_key(record: dict[str, Any], *, hit_lengths: list[int]) -> tuple[Any, ...]:
    requested_length = int(record.get("requested_length") or 0)
    selected_any_geometry = bool(record.get("selected_any_geometry"))
    selected_any_esm = bool(record.get("selected_any_esm"))
    all_any_geometry = bool(record.get("all_any_geometry"))
    all_any_esm = bool(record.get("all_any_esm"))
    return (
        nearest_hit_distance(requested_length=requested_length, hit_lengths=hit_lengths),
        -int(selected_any_geometry and selected_any_esm),
        -int(selected_any_geometry or selected_any_esm),
        -int(all_any_geometry and all_any_esm),
        float(record.get("mean_abs_selected_length_delta") or 10**9),
        int(record.get("step") or 0),
    )


def select_support_prompts(
    audit: dict[str, Any],
    *,
    support_window: int,
    support_prompt_limit: int,
    support_max_per_requested_length: int,
) -> list[dict[str, Any]]:
    hit_prompt_steps = {int(step) for step in audit.get("hit_prompt_steps", [])}
    hit_lengths = [int(length) for length in audit.get("hit_prompt_lengths", [])]
    if not hit_lengths:
        return []

    selected: list[dict[str, Any]] = []
    requested_counts: Counter[int] = Counter()
    candidates = [
        record
        for record in audit.get("prompt_records", [])
        if record.get("requested_length") is not None
        and int(record.get("step") or 0) not in hit_prompt_steps
        and nearest_hit_distance(requested_length=int(record["requested_length"]), hit_lengths=hit_lengths)
        <= int(support_window)
        and (
            bool(record.get("selected_any_geometry"))
            or bool(record.get("selected_any_esm"))
            or bool(record.get("all_any_geometry"))
            or bool(record.get("all_any_esm"))
        )
    ]
    for record in sorted(candidates, key=lambda record: support_prompt_sort_key(record, hit_lengths=hit_lengths)):
        requested_length = int(record["requested_length"])
        if requested_counts[requested_length] >= int(support_max_per_requested_length):
            continue
        selected.append(record)
        requested_counts[requested_length] += 1
        if len(selected) >= int(support_prompt_limit):
            break
    return selected


def normalize_support_anchor(
    anchor: dict[str, Any],
    *,
    prompt_record: dict[str, Any],
    repeat_index: int,
    recipe_stage: str,
    hit_lengths: list[int],
) -> dict[str, Any]:
    sequence = str(anchor["sequence"]).strip().upper()
    prompt = str(prompt_record["prompt"])
    requested_length = int(prompt_record["requested_length"])
    step = int(prompt_record["step"])
    return {
        **anchor,
        "candidate_id": f"v13-support:step-{step}:repeat-{repeat_index}",
        "sequence": sequence,
        "length": v11.row_length(anchor),
        "sequence_length": len(sequence),
        "prompt": prompt,
        "prompt_id": f"v13-support:p24:step-{step}:repeat-{repeat_index}",
        "prompt_source": "v12_p24_support_prompt_replay",
        "source_prompt": prompt,
        "sequence_prompt": prompt,
        "derived_motif": v11.row_motif(anchor),
        "curriculum_role": "support_prompt_anchor",
        "curriculum_source": "v13_p24_support_replay",
        "recipe_stage": recipe_stage,
        "strict_bucket": "strict_scaffold_support_anchor",
        "functional_bridge_passes": False,
        "family_faithful_bridge_passes": bool(anchor.get("strict_manifold_passes")),
        "requested_length": requested_length,
        "anchor_length_delta": v11.row_length(anchor) - requested_length,
        "support_distance_to_hit": nearest_hit_distance(
            requested_length=requested_length,
            hit_lengths=hit_lengths,
        ),
        "support_selected_any_geometry": bool(prompt_record.get("selected_any_geometry")),
        "support_selected_any_esm": bool(prompt_record.get("selected_any_esm")),
        "source_prompt_count": int(prompt_record.get("prompt_count") or 0),
        "source_step": step,
        "repeat_index": repeat_index,
    }


def normalize_hit_row(
    hit_record: dict[str, Any],
    *,
    repeat_index: int,
    recipe_stage: str,
) -> dict[str, Any]:
    candidate = hit_record["selected_candidate"]
    sequence = str(candidate["sequence"]).strip().upper()
    requested_length = hit_record.get("requested_length")
    family_faithful = bool(candidate.get("family_faithful_bridge_passes"))
    curriculum_role = "family_hit_replay" if family_faithful else "bridge_hit_replay"
    strict_bucket = "v12_gate_family_hit" if family_faithful else "v12_gate_bridge_hit"
    return {
        "candidate_id": (
            f"v13-hit:p24:step-{hit_record['step']}:seed-{hit_record['seed']}:repeat-{repeat_index}"
        ),
        "sequence": sequence,
        "length": len(sequence),
        "sequence_length": len(sequence),
        "prompt": str(hit_record["prompt"]),
        "prompt_id": f"v13-hit:p24:step-{hit_record['step']}:seed-{hit_record['seed']}:repeat-{repeat_index}",
        "prompt_source": "v12_gate_hit_prompt",
        "source_prompt": str(hit_record["prompt"]),
        "sequence_prompt": str(hit_record["prompt"]),
        "derived_motif": v11.row_motif({"sequence": sequence}),
        "curriculum_role": curriculum_role,
        "curriculum_source": "v12_gate_hit_replay",
        "recipe_stage": recipe_stage,
        "strict_bucket": strict_bucket,
        "functional_bridge_passes": bool(candidate.get("functional_bridge_passes")),
        "family_faithful_bridge_passes": family_faithful,
        "esm_gate_pass": bool(candidate.get("esm_gate_pass")),
        "geometry_passes": bool(candidate.get("geometry_passes")),
        "esm_score": float(candidate.get("raw_esm_score") or 0.0),
        "requested_length": requested_length,
        "anchor_length_delta": len(sequence) - int(requested_length)
        if requested_length is not None
        else None,
        "source_prompt_count": 24,
        "source_seed": int(hit_record["seed"]),
        "source_step": int(hit_record["step"]),
        "repeat_index": repeat_index,
    }


def build_base_rows(args: argparse.Namespace, base_selected_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = v11.balanced_selected_rows(
        base_selected_rows,
        max_count=int(args.base_selected_count),
        max_per_length=int(args.base_max_per_length),
        max_per_parent=int(args.base_max_per_parent),
    )
    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            normalize_base_selected_row(
                row,
                repeat_index=0,
                recipe_stage=args.recipe_stage,
            )
        )
    return output


def build_support_rows(
    args: argparse.Namespace,
    *,
    audit: dict[str, Any],
    scaffold_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    usage: Counter[str] = Counter()
    support_prompts = select_support_prompts(
        audit,
        support_window=int(args.support_window),
        support_prompt_limit=int(args.support_prompt_limit),
        support_max_per_requested_length=int(args.support_max_per_requested_length),
    )
    hit_lengths = [int(length) for length in audit.get("hit_prompt_lengths", [])]
    output: list[dict[str, Any]] = []
    for prompt_record in support_prompts:
        requested_length = int(prompt_record["requested_length"])
        for repeat_index in range(int(args.support_replay_repeat)):
            anchor = v11.choose_scaffold_anchor(scaffold_rows, requested_length=requested_length, usage=usage)
            anchor_id = str(anchor.get("sequence_id") or anchor.get("sequence") or "")
            usage[anchor_id] += 1
            output.append(
                normalize_support_anchor(
                    anchor,
                    prompt_record=prompt_record,
                    repeat_index=repeat_index,
                    recipe_stage=args.recipe_stage,
                    hit_lengths=hit_lengths,
                )
            )
    return output, support_prompts


def build_hit_rows(args: argparse.Namespace, *, audit: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for hit_record in audit.get("hit_seed_records", []):
        for repeat_index in range(int(args.hit_replay_repeat)):
            output.append(
                normalize_hit_row(
                    hit_record,
                    repeat_index=repeat_index,
                    recipe_stage=args.recipe_stage,
                )
            )
    return output


def build_curriculum(args: argparse.Namespace) -> dict[str, Any]:
    base_selected_path = v11.resolved(args.base_selected_path)
    scaffold_bank_path = v11.resolved(args.scaffold_bank_path)
    audit_path = v11.resolved(args.audit_path)
    prompts_path = v11.resolved(args.prompts_path)
    output_path = v11.resolved(args.output_path)
    summary_path = v11.resolved(args.summary_path)
    purebred_path = v11.resolved(args.purebred_path)

    assert base_selected_path is not None
    assert scaffold_bank_path is not None
    assert audit_path is not None
    assert prompts_path is not None
    assert output_path is not None
    assert summary_path is not None
    if not prompts_path.exists():
        raise FileNotFoundError(prompts_path)

    base_selected_rows = v11.read_jsonl(base_selected_path)
    scaffold_rows = v11.strict_scaffold_rows(v11.read_jsonl(scaffold_bank_path))
    audit = read_audit(audit_path)

    output_rows: list[dict[str, Any]] = []
    base_rows = build_base_rows(args, base_selected_rows)
    support_rows, support_prompts = build_support_rows(args, audit=audit, scaffold_rows=scaffold_rows)
    hit_rows = build_hit_rows(args, audit=audit)
    purebred_rows = v11.build_purebred_rows(args, purebred_path)
    output_rows.extend(base_rows)
    output_rows.extend(support_rows)
    output_rows.extend(hit_rows)
    output_rows.extend(purebred_rows)

    v11.write_jsonl(output_path, output_rows)

    source_counts = Counter(str(row.get("curriculum_source") or "") for row in output_rows)
    role_counts = Counter(str(row.get("curriculum_role") or "") for row in output_rows)
    length_counts = Counter(str(row.get("length") or 0) for row in output_rows)
    sequence_counts = Counter(str(row.get("sequence") or "") for row in output_rows)
    requested_deltas = [
        int(row["anchor_length_delta"])
        for row in output_rows
        if row.get("anchor_length_delta") is not None
    ]
    summary = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "base_selected_path": str(base_selected_path),
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
        "base_rows": len(base_rows),
        "support_prompt_rows": len(support_rows),
        "gate_hit_rows": len(hit_rows),
        "purebred_rows": len(purebred_rows),
        "repeat_config": {
            "support_replay_repeat": int(args.support_replay_repeat),
            "hit_replay_repeat": int(args.hit_replay_repeat),
            "purebred_repeat": int(args.purebred_repeat),
        },
        "base_selection_config": {
            "base_selected_count": int(args.base_selected_count),
            "base_max_per_length": int(args.base_max_per_length),
            "base_max_per_parent": int(args.base_max_per_parent),
        },
        "support_prompt_config": {
            "support_window": int(args.support_window),
            "support_prompt_limit": int(args.support_prompt_limit),
            "support_max_per_requested_length": int(args.support_max_per_requested_length),
        },
        "hit_prompt_steps": list(audit.get("hit_prompt_steps", [])),
        "hit_prompt_lengths": list(audit.get("hit_prompt_lengths", [])),
        "support_prompt_steps": [int(record["step"]) for record in support_prompts],
        "support_prompt_lengths": [int(record["requested_length"]) for record in support_prompts],
        "support_prompt_records": [
            {
                "step": int(record["step"]),
                "requested_length": int(record["requested_length"]),
                "selected_mode_counts": record.get("selected_mode_counts"),
                "all_candidate_mode_counts": record.get("all_candidate_mode_counts"),
                "selected_any_geometry": bool(record.get("selected_any_geometry")),
                "selected_any_esm": bool(record.get("selected_any_esm")),
                "mean_abs_selected_length_delta": float(record.get("mean_abs_selected_length_delta") or 0.0),
            }
            for record in support_prompts
        ],
        "anchor_length_delta": {
            "count": len(requested_deltas),
            "min": min(requested_deltas) if requested_deltas else None,
            "max": max(requested_deltas) if requested_deltas else None,
            "mean_abs": round(sum(abs(value) for value in requested_deltas) / max(1, len(requested_deltas)), 3),
        },
        "max_sequence_repeat": max(sequence_counts.values(), default=0),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    print(json.dumps(build_curriculum(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
