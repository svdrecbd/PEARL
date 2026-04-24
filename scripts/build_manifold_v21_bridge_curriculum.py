#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from glob import glob
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


ROOT_PATH = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT_PATH / "src"
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.strict_curricula import infer_canonical_motif


DEFAULT_SELECTED_PATH = (
    ROOT_PATH
    / "reports/analysis/manifold_v2_offline_constructor_20260424_batch2/v2_constructor_final_reselected.jsonl"
)
DEFAULT_V12_AUDIT_PATH = ROOT_PATH / "reports/analysis/manifold_v12_gate_audit_20260423/audit.json"
DEFAULT_V2_AUDIT_PATTERN = str(
    ROOT_PATH / "reports/ablations/pearl-topoff1m-a-manifold-v2-stagea-gate-p24-c128-p24-t0p8-s*/candidate_audit.json"
)
DEFAULT_SUPPORT_PATHS = [
    ROOT_PATH / "reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/family_faithful_bridges.jsonl",
    ROOT_PATH / "reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_selected_new_family_faithful.jsonl",
    ROOT_PATH / "reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_selected_repair_family_faithful.jsonl",
]
DEFAULT_PUREBRED_PATH = ROOT_PATH / "data/petase_family_expanded/kimi_micro_sft_top9_unicorn_only.jsonl"
DEFAULT_OUTPUT_DIR = ROOT_PATH / "reports/curriculum/manifold_v21_20260424"

AA_PATTERN = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")
ALLOWED_MOTIFS = {"GYSLG", "GYSQG", "GSSGG", "GHSQG", "GFSQG"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build manifold v2.1 bridge-weighted stage-A curriculum from v2 strict breadth, "
            "v12/v2 measured bridge hits, p24 support prompts, and historical family-faithful positives."
        )
    )
    parser.add_argument("--selected-path", default=str(DEFAULT_SELECTED_PATH))
    parser.add_argument("--v12-audit-path", default=str(DEFAULT_V12_AUDIT_PATH))
    parser.add_argument("--v2-candidate-audit-path", action="append", dest="v2_candidate_audit_paths")
    parser.add_argument("--support-positive-path", action="append", dest="support_positive_paths")
    parser.add_argument("--purebred-path", default=str(DEFAULT_PUREBRED_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--output-name", default="manifold_v21_bridge_curriculum.jsonl")
    parser.add_argument("--summary-name", default="summary.json")
    parser.add_argument("--max-v2-selected", type=int, default=28)
    parser.add_argument("--max-support-prompts", type=int, default=12)
    parser.add_argument("--support-window", type=int, default=45)
    parser.add_argument("--max-historical-support", type=int, default=16)
    parser.add_argument("--purebred-top-k", type=int, default=4)
    parser.add_argument("--v12-family-hit-repeat", type=int, default=5)
    parser.add_argument("--v12-bridge-hit-repeat", type=int, default=3)
    parser.add_argument("--v2-bridge-hit-repeat", type=int, default=2)
    parser.add_argument("--support-prompt-repeat", type=int, default=1)
    parser.add_argument("--historical-support-repeat", type=int, default=1)
    parser.add_argument("--purebred-repeat", type=int, default=1)
    parser.add_argument("--min-v2-selected", type=int, default=24)
    parser.add_argument("--min-measured-bridge-replay-rows", type=int, default=8)
    parser.add_argument("--min-family-faithful-replay-rows", type=int, default=6)
    parser.add_argument("--min-support-prompts", type=int, default=8)
    parser.add_argument("--recipe-stage", default="manifold_stage_a_v21_bridge")
    return parser.parse_args()


def repo_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = ROOT_PATH / path
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def sequence_id(sequence: str, *, prefix: str = "v21") -> str:
    return f"{prefix}-{hashlib.sha1(sequence.encode('utf-8')).hexdigest()[:16]}"


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def bool_value(value: Any) -> bool:
    return bool(value)


def pick_sequence(row: dict[str, Any]) -> str:
    sequence = row.get("sequence") or row.get("extracted_sequence") or row.get("sample_text")
    if sequence is None and isinstance(row.get("selected_candidate"), dict):
        sequence = row["selected_candidate"].get("sequence") or row["selected_candidate"].get("extracted_sequence")
    return str(sequence or "").strip().upper()


def validate_sequence(sequence: str, *, source: str) -> str:
    if not AA_PATTERN.fullmatch(sequence):
        raise ValueError(f"invalid amino-acid sequence from {source}")
    return sequence


def row_length(row: dict[str, Any]) -> int:
    return int(row.get("length") or row.get("sequence_length") or len(pick_sequence(row)))


def motif_for_row(row: dict[str, Any]) -> str:
    blueprint = row.get("blueprint") or {}
    motif = str(blueprint.get("motif") or row.get("derived_motif") or "").strip()
    if motif:
        return motif
    family_evaluation = row.get("family_evaluation") or row.get("family_assessment") or {}
    serine_motifs = family_evaluation.get("serine_motifs") if isinstance(family_evaluation, dict) else None
    if serine_motifs:
        return str(serine_motifs[0])
    return infer_canonical_motif(pick_sequence(row), ALLOWED_MOTIFS) or ""


def infer_requested_length(prompt: str | None) -> int | None:
    if not prompt:
        return None
    patterns = (
        r"length\s+(?:about|around|near)\s+(\d+)\s+aa",
        r"around\s+(\d+)\s+amino acids",
        r"near\s+(\d+)\s+aa",
        r"near\s+(\d+)\s+amino acids",
        r"about\s+(\d+)\s+aa",
    )
    for pattern in patterns:
        match = re.search(pattern, prompt, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def default_prompt(*, length: int, motif: str) -> str:
    motif_clause = f" Prefer a single {motif} nucleophile motif." if motif else ""
    return (
        f"Generate a polyester-hydrolase-family cutinase sequence around {length} amino acids long."
        f"{motif_clause} Favor a PETase/cutinase-like catalytic triad with canonical serine, "
        "aspartate, and histidine spacing. Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."
    )


def with_repeat(prompt_id: str, repeat_index: int) -> str:
    return f"{prompt_id}:repeat-{repeat_index}" if repeat_index else prompt_id


def selected_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(row.get("selection_rank") or 10**9),
        -float(row.get("esm_score") or row.get("raw_esm_score") or 0.0),
        str(row.get("candidate_id") or row.get("sequence_id") or ""),
    )


def source_key(row: dict[str, Any]) -> str:
    for key in ("parent_source_key", "parent_panel_id", "source_key", "candidate_id", "sequence_id"):
        value = row.get(key)
        if value:
            return str(value)
    return sequence_id(pick_sequence(row), prefix="source")


def normalize_v2_selected_row(row: dict[str, Any], *, rank: int, recipe_stage: str) -> dict[str, Any]:
    sequence = validate_sequence(pick_sequence(row), source=f"v2 selected rank {rank}")
    length = len(sequence)
    motif = motif_for_row(row)
    prompt = str(row.get("prompt") or row.get("source_prompt") or default_prompt(length=length, motif=motif))
    payload = dict(row)
    payload.update(
        {
            "candidate_id": str(row.get("candidate_id") or row.get("sequence_id") or sequence_id(sequence)),
            "sequence_id": str(row.get("sequence_id") or row.get("candidate_id") or sequence_id(sequence)),
            "sequence": sequence,
            "length": length,
            "sequence_length": length,
            "prompt": prompt,
            "source_prompt": str(row.get("source_prompt") or prompt),
            "sequence_prompt": str(row.get("sequence_prompt") or prompt),
            "prompt_id": f"v21-v2-selected:{rank}",
            "prompt_source": str(row.get("prompt_source") or "synthetic_v2_length_confirming_prompt"),
            "derived_motif": motif,
            "curriculum_role": "v2_strict_breadth_anchor",
            "curriculum_source": "v2_constructor_scored_reselected",
            "recipe_stage": recipe_stage,
            "strict_bucket": "v2_strict_core_esm_breadth",
            "repeat_index": 0,
            "v21_source_rank": rank,
            "parent_source_key": source_key(row),
            "measured_bridge_replay": False,
            "measured_family_faithful_replay": False,
            "v2_family_faithful_proxy_passes": bool(row.get("family_faithful_proxy_passes")),
            "functional_bridge_passes": bool(row.get("functional_bridge_passes") or row.get("bridge_quality_passes")),
            "family_faithful_bridge_passes": bool(row.get("family_faithful_bridge_passes") or row.get("family_faithful_proxy_passes")),
        }
    )
    return payload


def extract_v12_hits(audit: dict[str, Any], *, recipe_stage: str, family_repeat: int, bridge_repeat: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordered_hits = sorted(
        [
            record
            for record in audit.get("hit_seed_records", [])
            if bool_value((record.get("selected_candidate") or {}).get("functional_bridge_passes"))
        ],
        key=lambda record: (
            -int(bool_value((record.get("selected_candidate") or {}).get("family_faithful_bridge_passes"))),
            int(record.get("step") or 10**9),
            int(record.get("seed") or 10**9),
        ),
    )
    for hit_index, record in enumerate(ordered_hits):
        candidate = record.get("selected_candidate") or {}
        sequence = validate_sequence(pick_sequence(candidate), source=f"v12 hit {hit_index}")
        family_faithful = bool_value(candidate.get("family_faithful_bridge_passes"))
        repeat_count = family_repeat if family_faithful else bridge_repeat
        prompt = str(record.get("prompt") or default_prompt(length=len(sequence), motif=motif_for_row(candidate)))
        for repeat_index in range(repeat_count):
            rows.append(
                {
                    "candidate_id": f"v21-v12-hit:step-{record.get('step')}:seed-{record.get('seed')}:repeat-{repeat_index}",
                    "sequence_id": sequence_id(sequence, prefix="v21-v12-hit"),
                    "sequence": sequence,
                    "length": len(sequence),
                    "sequence_length": len(sequence),
                    "prompt": prompt,
                    "source_prompt": prompt,
                    "sequence_prompt": prompt,
                    "prompt_id": with_repeat(
                        f"v21-v12-hit:p24:step-{record.get('step')}:seed-{record.get('seed')}",
                        repeat_index,
                    ),
                    "prompt_source": "v12_p24_measured_bridge_hit",
                    "derived_motif": motif_for_row(candidate),
                    "curriculum_role": "v12_family_hit_replay" if family_faithful else "v12_bridge_hit_replay",
                    "curriculum_source": "v12_gate_measured_hit_replay",
                    "recipe_stage": recipe_stage,
                    "strict_bucket": "v12_family_faithful_hit" if family_faithful else "v12_functional_bridge_hit",
                    "functional_bridge_passes": True,
                    "family_faithful_bridge_passes": family_faithful,
                    "esm_gate_pass": bool_value(candidate.get("esm_gate_pass")),
                    "geometry_passes": bool_value(candidate.get("geometry_passes")),
                    "passes_core_screen": bool_value(candidate.get("passes_core_screen")),
                    "esm_score": float_or_none(candidate.get("raw_esm_score") or candidate.get("esm_score")),
                    "best_gap_error": int_or_none(candidate.get("best_gap_error")),
                    "requested_length": int_or_none(record.get("requested_length")) or infer_requested_length(prompt),
                    "anchor_length_delta": len(sequence) - int(record["requested_length"])
                    if record.get("requested_length") is not None
                    else None,
                    "source_run": record.get("run_name"),
                    "source_seed": int_or_none(record.get("seed")),
                    "source_step": int_or_none(record.get("step")),
                    "repeat_index": repeat_index,
                    "measured_bridge_replay": True,
                    "measured_family_faithful_replay": family_faithful,
                    "source_candidate": candidate,
                }
            )
    return rows


def default_v2_audit_paths() -> list[Path]:
    return [Path(path) for path in sorted(glob(DEFAULT_V2_AUDIT_PATTERN))]


def seed_from_path(path: Path) -> int | None:
    match = re.search(r"-s(\d+)(?:/candidate_audit\.json)?$", str(path))
    return int(match.group(1)) if match else None


def extract_v2_gate_hits(paths: list[Path], *, recipe_stage: str, repeat_count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_hit_keys: set[tuple[str, str, int | None]] = set()
    for path in paths:
        audit = read_json(path)
        seed = seed_from_path(path)
        run_name = path.parent.name
        for record in audit.get("records", []):
            for candidate in record.get("candidates", []):
                if not bool_value(candidate.get("selected")):
                    continue
                if not bool_value(candidate.get("functional_bridge_passes")):
                    continue
                sequence = validate_sequence(pick_sequence(candidate), source=f"v2 gate hit {path}")
                step = int_or_none(record.get("step"))
                key = (sequence, run_name, step)
                if key in seen_hit_keys:
                    continue
                seen_hit_keys.add(key)
                prompt = str(record.get("prompt") or default_prompt(length=len(sequence), motif=motif_for_row(candidate)))
                family_faithful = bool_value(candidate.get("family_faithful_bridge_passes"))
                for repeat_index in range(repeat_count):
                    rows.append(
                        {
                            "candidate_id": f"v21-v2-hit:step-{step}:seed-{seed}:repeat-{repeat_index}",
                            "sequence_id": sequence_id(sequence, prefix="v21-v2-hit"),
                            "sequence": sequence,
                            "length": len(sequence),
                            "sequence_length": len(sequence),
                            "prompt": prompt,
                            "source_prompt": prompt,
                            "sequence_prompt": prompt,
                            "prompt_id": with_repeat(f"v21-v2-hit:p24:step-{step}:seed-{seed}", repeat_index),
                            "prompt_source": "v2_p24_measured_bridge_hit",
                            "derived_motif": motif_for_row(candidate),
                            "curriculum_role": "v2_family_hit_replay" if family_faithful else "v2_bridge_hit_replay",
                            "curriculum_source": "v2_gate_measured_hit_replay",
                            "recipe_stage": recipe_stage,
                            "strict_bucket": "v2_family_faithful_hit" if family_faithful else "v2_functional_bridge_hit",
                            "functional_bridge_passes": True,
                            "family_faithful_bridge_passes": family_faithful,
                            "esm_gate_pass": bool_value(candidate.get("esm_gate_pass")),
                            "geometry_passes": bool_value(candidate.get("geometry_passes")),
                            "passes_core_screen": bool_value(candidate.get("passes_core_screen")),
                            "esm_score": float_or_none(candidate.get("raw_esm_score") or candidate.get("esm_score")),
                            "best_gap_error": int_or_none(candidate.get("best_gap_error")),
                            "requested_length": infer_requested_length(prompt),
                            "anchor_length_delta": len(sequence) - infer_requested_length(prompt)
                            if infer_requested_length(prompt) is not None
                            else None,
                            "source_run": run_name,
                            "source_seed": seed,
                            "source_step": step,
                            "repeat_index": repeat_index,
                            "measured_bridge_replay": True,
                            "measured_family_faithful_replay": family_faithful,
                            "source_candidate": candidate,
                        }
                    )
    return rows


def support_prompt_sort_key(record: dict[str, Any], *, hit_lengths: list[int]) -> tuple[Any, ...]:
    requested_length = int(record.get("requested_length") or 0)
    nearest_hit_delta = min((abs(requested_length - length) for length in hit_lengths), default=10**9)
    return (
        nearest_hit_delta,
        -int(bool(record.get("selected_any_geometry")) and bool(record.get("selected_any_esm"))),
        -int(bool(record.get("selected_any_geometry")) or bool(record.get("selected_any_esm"))),
        float(record.get("mean_abs_selected_length_delta") or 10**9),
        int(record.get("step") or 10**9),
    )


def select_support_prompts(audit: dict[str, Any], *, limit: int, support_window: int) -> list[dict[str, Any]]:
    hit_steps = {int(step) for step in audit.get("hit_prompt_steps", [])}
    hit_lengths = [int(length) for length in audit.get("hit_prompt_lengths", [])]
    candidates = []
    for record in audit.get("prompt_records", []):
        requested = int_or_none(record.get("requested_length"))
        if requested is None:
            continue
        if int(record.get("step") or -1) in hit_steps:
            continue
        if min((abs(requested - length) for length in hit_lengths), default=10**9) > support_window:
            continue
        if not (
            bool(record.get("selected_any_geometry"))
            or bool(record.get("selected_any_esm"))
            or bool(record.get("all_any_geometry"))
            or bool(record.get("all_any_esm"))
        ):
            continue
        candidates.append(record)
    return sorted(candidates, key=lambda record: support_prompt_sort_key(record, hit_lengths=hit_lengths))[:limit]


def support_anchor_key(row: dict[str, Any]) -> str:
    return str(row.get("sequence_id") or row.get("candidate_id") or sequence_id(pick_sequence(row), prefix="anchor"))


def load_support_anchors(selected_rows: list[dict[str, Any]], support_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchors: dict[str, dict[str, Any]] = {}
    for row in selected_rows + support_rows:
        sequence = pick_sequence(row)
        if not sequence or not AA_PATTERN.fullmatch(sequence):
            continue
        if not (
            bool(row.get("family_faithful_bridge_passes"))
            or bool(row.get("family_faithful_proxy_passes"))
            or bool(row.get("strict_family"))
        ):
            continue
        payload = dict(row)
        payload["sequence"] = sequence
        payload["length"] = len(sequence)
        anchors.setdefault(sequence, payload)
    return list(anchors.values())


def core_family_positive(row: dict[str, Any]) -> bool:
    if bool(row.get("passes_core_screen") or row.get("strict_family")):
        return True
    family_evaluation = row.get("family_evaluation") or {}
    if isinstance(family_evaluation, dict):
        return bool(
            family_evaluation.get("passes_core_screen")
            and family_evaluation.get("length_in_family_band")
            and family_evaluation.get("has_family_serine_motif")
        )
    return False


def choose_anchor(anchors: list[dict[str, Any]], *, requested_length: int, usage: Counter[str]) -> dict[str, Any]:
    if not anchors:
        raise ValueError("no support anchors available for bridge prompt replay")
    return min(
        anchors,
        key=lambda row: (
            usage[support_anchor_key(row)],
            abs(row_length(row) - requested_length),
            -int(bool(row.get("family_faithful_bridge_passes") or row.get("strict_family"))),
            -float(row.get("esm_score") or row.get("esm_reward") or row.get("raw_esm_score") or 0.0),
            support_anchor_key(row),
        ),
    )


def build_support_prompt_rows(
    *,
    audit: dict[str, Any],
    anchors: list[dict[str, Any]],
    recipe_stage: str,
    limit: int,
    support_window: int,
    repeat_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prompts = select_support_prompts(audit, limit=limit, support_window=support_window)
    usage: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    for prompt_record in prompts:
        requested = int(prompt_record["requested_length"])
        prompt = str(prompt_record["prompt"])
        for repeat_index in range(repeat_count):
            anchor = choose_anchor(anchors, requested_length=requested, usage=usage)
            anchor_key = support_anchor_key(anchor)
            usage[anchor_key] += 1
            sequence = validate_sequence(pick_sequence(anchor), source=f"support prompt step {prompt_record.get('step')}")
            rows.append(
                {
                    **anchor,
                    "candidate_id": f"v21-support-prompt:step-{prompt_record.get('step')}:repeat-{repeat_index}",
                    "sequence_id": str(anchor.get("sequence_id") or anchor.get("candidate_id") or sequence_id(sequence)),
                    "sequence": sequence,
                    "length": len(sequence),
                    "sequence_length": len(sequence),
                    "prompt": prompt,
                    "source_prompt": prompt,
                    "sequence_prompt": prompt,
                    "prompt_id": with_repeat(f"v21-support-prompt:p24:step-{prompt_record.get('step')}", repeat_index),
                    "prompt_source": "v12_p24_support_prompt_replay",
                    "derived_motif": motif_for_row(anchor),
                    "curriculum_role": "v21_bridge_prompt_anchor",
                    "curriculum_source": "v12_gate_support_prompt_replay",
                    "recipe_stage": recipe_stage,
                    "strict_bucket": "support_prompt_family_faithful_anchor",
                    "functional_bridge_passes": bool(anchor.get("functional_bridge_passes") or anchor.get("bridge_quality_passes")),
                    "family_faithful_bridge_passes": bool(
                        anchor.get("family_faithful_bridge_passes") or anchor.get("family_faithful_proxy_passes")
                    ),
                    "requested_length": requested,
                    "anchor_length_delta": len(sequence) - requested,
                    "source_prompt_count": int(prompt_record.get("prompt_count") or 24),
                    "source_step": int_or_none(prompt_record.get("step")),
                    "repeat_index": repeat_index,
                    "measured_bridge_replay": False,
                    "measured_family_faithful_replay": False,
                    "support_selected_any_geometry": bool(prompt_record.get("selected_any_geometry")),
                    "support_selected_any_esm": bool(prompt_record.get("selected_any_esm")),
                    "support_selected_mode_counts": prompt_record.get("selected_mode_counts"),
                }
            )
    return rows, prompts


def support_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int_or_none(row.get("best_gap_error")) if int_or_none(row.get("best_gap_error")) is not None else 10**9,
        -float(row.get("esm_score") or row.get("esm_reward") or row.get("raw_esm_score") or 0.0),
        abs(row_length(row) - 300),
        str(row.get("source_run") or ""),
        str(row.get("candidate_id") or row.get("sequence") or ""),
    )


def load_historical_support_rows(paths: list[Path], *, max_rows: int) -> list[dict[str, Any]]:
    per_path_limit = max(1, max_rows // max(1, len(paths)))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        candidates = []
        for row in read_jsonl(path):
            sequence = pick_sequence(row)
            if not sequence or sequence in seen or not AA_PATTERN.fullmatch(sequence):
                continue
            if not bool(row.get("family_faithful_bridge_passes") or row.get("strict_family")):
                continue
            if not core_family_positive(row):
                continue
            candidates.append({**row, "sequence": sequence, "length": len(sequence), "source_path": str(path)})
        for row in sorted(candidates, key=support_sort_key)[:per_path_limit]:
            rows.append(row)
            seen.add(str(row["sequence"]))
            if len(rows) >= max_rows:
                break
        if len(rows) >= max_rows:
            break
    return rows


def normalize_historical_support_row(
    row: dict[str, Any],
    *,
    index: int,
    repeat_index: int,
    recipe_stage: str,
) -> dict[str, Any]:
    sequence = validate_sequence(pick_sequence(row), source=f"historical support {index}")
    length = len(sequence)
    motif = motif_for_row(row)
    prompt = str(row.get("prompt") or row.get("source_prompt") or default_prompt(length=length, motif=motif))
    return {
        **row,
        "candidate_id": f"v21-historical-support:{index}:repeat-{repeat_index}",
        "sequence_id": str(row.get("sequence_id") or row.get("candidate_id") or sequence_id(sequence, prefix="v21-support")),
        "sequence": sequence,
        "length": length,
        "sequence_length": length,
        "prompt": prompt,
        "source_prompt": str(row.get("source_prompt") or prompt),
        "sequence_prompt": prompt,
        "prompt_id": with_repeat(f"v21-historical-support:{index}", repeat_index),
        "prompt_source": "historical_family_faithful_bridge_prompt",
        "derived_motif": motif,
        "curriculum_role": "historical_family_faithful_anchor",
        "curriculum_source": "historical_family_faithful_bridge_support",
        "recipe_stage": recipe_stage,
        "strict_bucket": "historical_family_faithful_bridge",
        "functional_bridge_passes": True,
        "family_faithful_bridge_passes": True,
        "passes_core_screen": bool(row.get("passes_core_screen") or row.get("strict_family")),
        "esm_score": float_or_none(row.get("esm_score") or row.get("esm_reward") or row.get("raw_esm_score")),
        "repeat_index": repeat_index,
        "measured_bridge_replay": False,
        "measured_family_faithful_replay": False,
    }


def normalize_purebred_row(row: dict[str, Any], *, index: int, repeat_index: int, recipe_stage: str) -> dict[str, Any]:
    sequence = validate_sequence(pick_sequence(row), source=f"purebred {index}")
    length = len(sequence)
    motif = motif_for_row(row)
    prompt = default_prompt(length=length, motif=motif)
    return {
        **row,
        "candidate_id": str(row.get("accession") or row.get("candidate_id") or f"purebred:{index}"),
        "sequence_id": str(row.get("sequence_id") or row.get("accession") or f"purebred:{index}"),
        "sequence": sequence,
        "length": length,
        "sequence_length": length,
        "prompt": prompt,
        "source_prompt": prompt,
        "sequence_prompt": prompt,
        "prompt_id": with_repeat(f"v21-purebred:{index}", repeat_index),
        "prompt_source": "synthetic_v21_purebred_prompt",
        "derived_motif": motif,
        "curriculum_role": "purebred_anchor",
        "curriculum_source": "canonical_purebred",
        "recipe_stage": recipe_stage,
        "strict_bucket": "canonical_purebred",
        "functional_bridge_passes": True,
        "family_faithful_bridge_passes": True,
        "repeat_index": repeat_index,
        "measured_bridge_replay": False,
        "measured_family_faithful_replay": False,
    }


def numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "mean": None, "max": None}
    return {"count": len(values), "min": round(min(values), 4), "mean": round(mean(values), 4), "max": round(max(values), 4)}


def build_summary(
    *,
    output_rows: list[dict[str, Any]],
    support_prompts: list[dict[str, Any]],
    selected_path: Path,
    v12_audit_path: Path,
    v2_audit_paths: list[Path],
    support_paths: list[Path],
    output_path: Path,
    summary_path: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    role_counts = Counter(str(row.get("curriculum_role") or "") for row in output_rows)
    source_counts = Counter(str(row.get("curriculum_source") or "") for row in output_rows)
    length_counts = Counter(int(row.get("length") or 0) for row in output_rows)
    sequence_counts = Counter(str(row.get("sequence") or "") for row in output_rows)
    measured_bridge_rows = [row for row in output_rows if bool(row.get("measured_bridge_replay"))]
    measured_family_rows = [row for row in output_rows if bool(row.get("measured_family_faithful_replay"))]
    anchor_deltas = [int(row["anchor_length_delta"]) for row in output_rows if row.get("anchor_length_delta") is not None]
    ready_for_stage_a = (
        role_counts.get("v2_strict_breadth_anchor", 0) >= int(args.min_v2_selected)
        and len(measured_bridge_rows) >= int(args.min_measured_bridge_replay_rows)
        and len(measured_family_rows) >= int(args.min_family_faithful_replay_rows)
        and len(support_prompts) >= int(args.min_support_prompts)
    )
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "selected_path": str(selected_path),
        "v12_audit_path": str(v12_audit_path),
        "v2_candidate_audit_paths": [str(path) for path in v2_audit_paths],
        "support_positive_paths": [str(path) for path in support_paths],
        "purebred_path": str(repo_path(args.purebred_path)) if args.purebred_path else None,
        "output_path": str(output_path),
        "summary_path": str(summary_path),
        "dataset_count": len(output_rows),
        "unique_sequence_count": len(sequence_counts),
        "max_sequence_repeat": max(sequence_counts.values(), default=0),
        "role_counts": dict(sorted(role_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "length_histogram": dict(sorted((str(key), value) for key, value in length_counts.items())),
        "measured_bridge_replay_rows": len(measured_bridge_rows),
        "measured_family_faithful_replay_rows": len(measured_family_rows),
        "support_prompt_steps": [int(record["step"]) for record in support_prompts],
        "support_prompt_lengths": [int(record["requested_length"]) for record in support_prompts],
        "anchor_length_delta": {
            "count": len(anchor_deltas),
            "min": min(anchor_deltas) if anchor_deltas else None,
            "max": max(anchor_deltas) if anchor_deltas else None,
            "mean_abs": round(mean([abs(value) for value in anchor_deltas]), 3) if anchor_deltas else None,
        },
        "esm_score_summary": numeric_summary(
            [float(row["esm_score"]) for row in output_rows if row.get("esm_score") is not None]
        ),
        "repeat_config": {
            "v12_family_hit_repeat": int(args.v12_family_hit_repeat),
            "v12_bridge_hit_repeat": int(args.v12_bridge_hit_repeat),
            "v2_bridge_hit_repeat": int(args.v2_bridge_hit_repeat),
            "support_prompt_repeat": int(args.support_prompt_repeat),
            "historical_support_repeat": int(args.historical_support_repeat),
            "purebred_repeat": int(args.purebred_repeat),
        },
        "readiness": {
            "ready_for_stage_a_diagnostic_train": ready_for_stage_a,
            "ready_for_broad_paid_gate": False,
            "reason": (
                "v2.1 curriculum has strict breadth plus explicit measured bridge replay for a p24-only diagnostic"
                if ready_for_stage_a
                else "v2.1 curriculum does not yet meet minimum bridge-replay/support breadth thresholds"
            ),
            "scope": "stage-A warmstart plus p24/c128 diagnostic only; no p48 or broad mining until p24 durability improves",
        },
    }


def build_curriculum(args: argparse.Namespace) -> dict[str, Any]:
    selected_path = repo_path(args.selected_path)
    v12_audit_path = repo_path(args.v12_audit_path)
    purebred_path = repo_path(args.purebred_path)
    output_dir = repo_path(args.output_dir)
    assert selected_path is not None
    assert v12_audit_path is not None
    assert output_dir is not None

    v2_audit_paths = [repo_path(path) for path in (args.v2_candidate_audit_paths or [])] or default_v2_audit_paths()
    v2_audit_paths = [path for path in v2_audit_paths if path is not None and path.exists()]
    support_paths = [repo_path(path) for path in (args.support_positive_paths or DEFAULT_SUPPORT_PATHS)]
    support_paths = [path for path in support_paths if path is not None and path.exists()]

    selected_input_rows = sorted(read_jsonl(selected_path), key=selected_sort_key)
    selected_rows = [
        normalize_v2_selected_row(row, rank=index + 1, recipe_stage=str(args.recipe_stage))
        for index, row in enumerate(selected_input_rows[: int(args.max_v2_selected)])
    ]
    v12_audit = read_json(v12_audit_path)
    v12_hit_rows = extract_v12_hits(
        v12_audit,
        recipe_stage=str(args.recipe_stage),
        family_repeat=int(args.v12_family_hit_repeat),
        bridge_repeat=int(args.v12_bridge_hit_repeat),
    )
    v2_hit_rows = extract_v2_gate_hits(
        v2_audit_paths,
        recipe_stage=str(args.recipe_stage),
        repeat_count=int(args.v2_bridge_hit_repeat),
    )
    historical_support_inputs = load_historical_support_rows(support_paths, max_rows=int(args.max_historical_support))
    anchors = load_support_anchors(selected_rows, historical_support_inputs)
    support_prompt_rows, support_prompts = build_support_prompt_rows(
        audit=v12_audit,
        anchors=anchors,
        recipe_stage=str(args.recipe_stage),
        limit=int(args.max_support_prompts),
        support_window=int(args.support_window),
        repeat_count=int(args.support_prompt_repeat),
    )
    historical_support_rows = [
        normalize_historical_support_row(
            row,
            index=index,
            repeat_index=repeat_index,
            recipe_stage=str(args.recipe_stage),
        )
        for index, row in enumerate(historical_support_inputs)
        for repeat_index in range(int(args.historical_support_repeat))
    ]
    purebred_rows: list[dict[str, Any]] = []
    if purebred_path is not None and purebred_path.exists() and int(args.purebred_top_k) > 0:
        for index, row in enumerate(read_jsonl(purebred_path)[: int(args.purebred_top_k)]):
            for repeat_index in range(int(args.purebred_repeat)):
                purebred_rows.append(normalize_purebred_row(row, index=index, repeat_index=repeat_index, recipe_stage=str(args.recipe_stage)))

    output_rows = selected_rows + v12_hit_rows + v2_hit_rows + support_prompt_rows + historical_support_rows + purebred_rows
    output_path = output_dir / str(args.output_name)
    summary_path = output_dir / str(args.summary_name)
    write_jsonl(output_path, output_rows)
    summary = build_summary(
        output_rows=output_rows,
        support_prompts=support_prompts,
        selected_path=selected_path,
        v12_audit_path=v12_audit_path,
        v2_audit_paths=v2_audit_paths,
        support_paths=support_paths,
        output_path=output_path,
        summary_path=summary_path,
        args=args,
    )
    write_json(summary_path, summary)
    return summary


def main() -> None:
    print(json.dumps(build_curriculum(parse_args()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
