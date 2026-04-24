#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


ROOT_PATH = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT_PATH / "src"
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.family import (
    AA_PATTERN,
    compute_family_stats,
    evaluate_candidate,
    load_reference_records,
    precompute_novelty_cache,
)
from scripts.manifold_construction_experiment import (
    edit_mask_for_blueprint,
    extract_blueprint,
    family_manifold_assessment,
    rejection_reasons,
)


DEFAULT_PANEL_DIR = ROOT_PATH / "reports/analysis/manifold_v2_objective_panel_20260424"
DEFAULT_OUTPUT_DIR = ROOT_PATH / "reports/analysis/manifold_v2_offline_constructor_20260424"
DEFAULT_RECORDS_PATH = ROOT_PATH / "data/petase_family_expanded/petase_records.jsonl"

POSITIVE_ROLES = {"positive_anchor", "support_positive"}
NEGATIVE_ROLES = {"hard_negative", "drift_negative"}
ROLE_WEIGHTS = {
    "positive_anchor": 8.0,
    "support_positive": 2.0,
    "hard_negative": 5.0,
    "drift_negative": 1.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a manifold v2 offline constructor frontier from the v2 objective panel. "
            "The constructor proposes same-length edits from positive/support residue profiles while "
            "penalizing hard/drift-negative residue profiles."
        )
    )
    parser.add_argument("--panel-dir", default=str(DEFAULT_PANEL_DIR))
    parser.add_argument("--records-path", default=str(DEFAULT_RECORDS_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-parents", type=int, default=64)
    parser.add_argument("--max-frontier-candidates", type=int, default=384)
    parser.add_argument("--max-selected-candidates", type=int, default=64)
    parser.add_argument("--max-proposals-per-parent", type=int, default=96)
    parser.add_argument("--max-candidates-per-parent", type=int, default=8)
    parser.add_argument("--max-selected-per-parent", type=int, default=2)
    parser.add_argument("--max-selected-per-length", type=int, default=16)
    parser.add_argument("--relative-profile-bins", type=int, default=200)
    parser.add_argument("--max-mutable-positions-per-parent", type=int, default=24)
    parser.add_argument("--residues-per-position", type=int, default=3)
    parser.add_argument("--mutation-depths", default="1,2")
    parser.add_argument("--min-positive-frequency", type=float, default=0.01)
    parser.add_argument("--max-negative-frequency", type=float, default=0.65)
    parser.add_argument("--min-objective-score", type=float, default=-0.25)
    parser.add_argument("--readiness-min-selected", type=int, default=32)
    parser.add_argument("--readiness-min-parents", type=int, default=16)
    parser.add_argument("--readiness-min-lengths", type=int, default=6)
    parser.add_argument("--readiness-min-two-mutants", type=int, default=8)
    return parser.parse_args()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT_PATH / path
    return path


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


def sequence_id(sequence: str, *, prefix: str = "v2") -> str:
    return f"{prefix}-{sha256(sequence.encode('utf-8')).hexdigest()[:16]}"


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


def relative_bin(position: int, length: int, bin_count: int) -> int:
    if length <= 1:
        return 0
    return min(bin_count - 1, int(((position - 1) / (length - 1)) * bin_count))


def length_bin(length: int, *, bin_size: int = 10) -> int:
    return (length // bin_size) * bin_size


def load_panel(panel_dir: Path) -> list[dict[str, Any]]:
    paths = [
        panel_dir / "v2_positive_anchors.jsonl",
        panel_dir / "v2_support_positives.jsonl",
        panel_dir / "v2_hard_negatives.jsonl",
        panel_dir / "v2_drift_negatives.jsonl",
    ]
    rows: list[dict[str, Any]] = []
    for path in paths:
        for row in read_jsonl(path):
            sequence = str(row.get("sequence") or "").strip().upper()
            if not sequence:
                continue
            payload = dict(row)
            payload["sequence"] = sequence
            payload["length"] = len(sequence)
            payload["panel_file"] = path.name
            rows.append(payload)
    return rows


def weighted_profiles(
    rows: list[dict[str, Any]],
    *,
    bin_count: int,
) -> tuple[dict[int, dict[int, Counter[str]]], dict[int, Counter[str]]]:
    exact: dict[int, dict[int, Counter[str]]] = {}
    relative: dict[int, Counter[str]] = {}
    for row in rows:
        sequence = str(row["sequence"])
        weight = int(round(ROLE_WEIGHTS.get(str(row.get("panel_role")), 1.0)))
        for index, residue in enumerate(sequence, start=1):
            exact.setdefault(len(sequence), {}).setdefault(index, Counter())[residue] += weight
            relative.setdefault(relative_bin(index, len(sequence), bin_count), Counter())[residue] += weight
    return exact, relative


def counter_for_position(
    sequence: str,
    position: int,
    exact: dict[int, dict[int, Counter[str]]],
    relative: dict[int, Counter[str]],
    *,
    bin_count: int,
) -> tuple[Counter[str], str]:
    by_length = exact.get(len(sequence), {})
    counter = by_length.get(position)
    if counter:
        return counter, "exact_length"
    return relative.get(relative_bin(position, len(sequence), bin_count), Counter()), "relative"


def frequency(counter: Counter[str], residue: str) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    return float(counter.get(residue, 0)) / float(total)


def row_source_key(row: dict[str, Any]) -> str:
    parts = [
        row.get("panel_source"),
        row.get("source_run"),
        row.get("source_seed"),
        row.get("source_step"),
        row.get("requested_length"),
    ]
    return "|".join(str(part) for part in parts)


def hamming_identity(left: str, right: str) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    matches = sum(left_aa == right_aa for left_aa, right_aa in zip(left, right, strict=True))
    return matches / len(left)


def nearest_same_length_negative_identity(sequence: str, negatives_by_length: dict[int, list[str]]) -> float | None:
    negatives = negatives_by_length.get(len(sequence), [])
    if not negatives:
        return None
    return max(hamming_identity(sequence, negative) for negative in negatives)


def retargeted_prompt(*, length: int, motif: str) -> str:
    motif_clause = f" Prefer one canonical {motif} serine hydrolase motif." if motif else ""
    return (
        f"Generate a PETase/cutinase-family polyester hydrolase around {length} amino acids long."
        f"{motif_clause} Preserve a PETase-like serine, aspartate, and histidine catalytic blueprint. "
        "Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."
    )


def parent_priority(row: dict[str, Any]) -> tuple[Any, ...]:
    role = str(row.get("panel_role"))
    source = str(row.get("panel_source") or "")
    esm = float_or_none(row.get("esm_score")) or 0.0
    return (
        0 if role == "positive_anchor" else 1,
        0 if "repair_validated_strict" in source else 1,
        -esm,
        len(str(row.get("sequence") or "")),
        str(row.get("panel_id") or row.get("sequence")),
    )


def hard_gate_assessment(
    sequence: str,
    *,
    family_stats: dict[str, Any],
    reference_records: list[dict[str, Any]],
    parent_blueprint: dict[str, Any],
) -> dict[str, Any]:
    blueprint = extract_blueprint(sequence, family_stats)
    assessment = family_manifold_assessment(sequence=sequence, family_stats=family_stats, blueprint=blueprint)
    core_evaluation = evaluate_candidate(
        sequence=sequence,
        family_stats=family_stats,
        reference_records=reference_records,
    )
    preserved_positions = all(
        blueprint.get(key) == parent_blueprint.get(key)
        for key in ("motif_start", "motif_end", "serine_position", "aspartate_position", "histidine_position")
        if parent_blueprint.get(key) is not None
    )
    preserved_motif = blueprint.get("motif") == parent_blueprint.get("motif")
    reasons = rejection_reasons(assessment, blueprint)
    if not preserved_positions:
        reasons.append("catalytic_blueprint_positions_changed")
    if not preserved_motif:
        reasons.append("family_motif_identity_changed")
    if not bool(core_evaluation.get("passes_core_screen")):
        reasons.append("fails_family_core_screen")
    hard_gate_passes = bool(
        assessment["strict_manifold_passes"]
        and core_evaluation.get("passes_core_screen")
        and preserved_positions
        and preserved_motif
    )
    return {
        "blueprint": blueprint,
        "family_assessment": assessment,
        "core_evaluation": core_evaluation,
        "hard_gate_passes": hard_gate_passes,
        "rejection_reasons": sorted(set(reasons)),
    }


def apply_mutations(sequence: str, mutations: list[dict[str, Any]]) -> str:
    residues = list(sequence)
    for mutation in mutations:
        position = int(mutation["position"])
        residues[position - 1] = str(mutation["to"])
    return "".join(residues)


def mutation_suggestions(
    parent: dict[str, Any],
    *,
    positive_exact: dict[int, dict[int, Counter[str]]],
    positive_relative: dict[int, Counter[str]],
    negative_exact: dict[int, dict[int, Counter[str]]],
    negative_relative: dict[int, Counter[str]],
    bin_count: int,
    max_positions: int,
    residues_per_position: int,
    min_positive_frequency: float,
    max_negative_frequency: float,
) -> list[dict[str, Any]]:
    sequence = str(parent["sequence"])
    parent_blueprint = parent["blueprint"]
    mask = edit_mask_for_blueprint(sequence, parent_blueprint)
    suggestions: list[dict[str, Any]] = []
    for position in mask["mutable_positions"]:
        current = sequence[position - 1]
        positive_counter, positive_source = counter_for_position(
            sequence,
            int(position),
            positive_exact,
            positive_relative,
            bin_count=bin_count,
        )
        negative_counter, negative_source = counter_for_position(
            sequence,
            int(position),
            negative_exact,
            negative_relative,
            bin_count=bin_count,
        )
        if not positive_counter:
            continue
        current_positive_frequency = frequency(positive_counter, current)
        current_negative_frequency = frequency(negative_counter, current)
        alternatives: list[dict[str, Any]] = []
        for residue, support in positive_counter.most_common():
            if residue == current or not AA_PATTERN.fullmatch(residue):
                continue
            positive_frequency = frequency(positive_counter, residue)
            negative_frequency = frequency(negative_counter, residue)
            if positive_frequency < min_positive_frequency:
                continue
            if negative_frequency > max_negative_frequency:
                continue
            residue_score = (
                (positive_frequency - current_positive_frequency)
                - 0.75 * (negative_frequency - current_negative_frequency)
                + math.log1p(float(support)) * 0.02
            )
            alternatives.append(
                {
                    "residue": residue,
                    "support": support,
                    "positive_frequency": round(positive_frequency, 6),
                    "negative_frequency": round(negative_frequency, 6),
                    "current_positive_frequency": round(current_positive_frequency, 6),
                    "current_negative_frequency": round(current_negative_frequency, 6),
                    "residue_objective_score": round(residue_score, 6),
                }
            )
        alternatives.sort(key=lambda item: float(item["residue_objective_score"]), reverse=True)
        alternatives = alternatives[:residues_per_position]
        if not alternatives:
            continue
        suggestions.append(
            {
                "position": int(position),
                "from": current,
                "positive_profile_source": positive_source,
                "negative_profile_source": negative_source,
                "positive_support": sum(positive_counter.values()),
                "negative_support": sum(negative_counter.values()),
                "alternatives": alternatives,
                "best_score": alternatives[0]["residue_objective_score"],
            }
        )
    suggestions.sort(
        key=lambda item: (
            float(item["best_score"]),
            int(item["positive_support"]),
            -int(item["position"]),
        ),
        reverse=True,
    )
    return suggestions[:max_positions]


def mutation_sets(
    suggestions: list[dict[str, Any]],
    *,
    depths: list[int],
    max_proposals: int,
) -> list[list[dict[str, Any]]]:
    proposals: list[list[dict[str, Any]]] = []
    if 1 in depths:
        for suggestion in suggestions:
            for alternative in suggestion["alternatives"]:
                proposals.append(
                    [
                        {
                            "position": suggestion["position"],
                            "from": suggestion["from"],
                            "to": alternative["residue"],
                            "positive_profile_source": suggestion["positive_profile_source"],
                            "negative_profile_source": suggestion["negative_profile_source"],
                            "positive_frequency": alternative["positive_frequency"],
                            "negative_frequency": alternative["negative_frequency"],
                            "support": alternative["support"],
                            "residue_objective_score": alternative["residue_objective_score"],
                        }
                    ]
                )
                if len(proposals) >= max_proposals:
                    return proposals
    if 2 in depths:
        for left, right in itertools.combinations(suggestions, 2):
            for left_alt in left["alternatives"]:
                for right_alt in right["alternatives"]:
                    proposals.append(
                        [
                            {
                                "position": left["position"],
                                "from": left["from"],
                                "to": left_alt["residue"],
                                "positive_profile_source": left["positive_profile_source"],
                                "negative_profile_source": left["negative_profile_source"],
                                "positive_frequency": left_alt["positive_frequency"],
                                "negative_frequency": left_alt["negative_frequency"],
                                "support": left_alt["support"],
                                "residue_objective_score": left_alt["residue_objective_score"],
                            },
                            {
                                "position": right["position"],
                                "from": right["from"],
                                "to": right_alt["residue"],
                                "positive_profile_source": right["positive_profile_source"],
                                "negative_profile_source": right["negative_profile_source"],
                                "positive_frequency": right_alt["positive_frequency"],
                                "negative_frequency": right_alt["negative_frequency"],
                                "support": right_alt["support"],
                                "residue_objective_score": right_alt["residue_objective_score"],
                            },
                        ]
                    )
                    if len(proposals) >= max_proposals:
                        return proposals
    return proposals


def proposal_objective_score(
    mutations: list[dict[str, Any]],
    *,
    nearest_negative_identity: float | None,
    gap_error: int | None,
) -> float:
    residue_score = sum(float(mutation.get("residue_objective_score") or 0.0) for mutation in mutations)
    positive_frequency = sum(float(mutation.get("positive_frequency") or 0.0) for mutation in mutations)
    negative_frequency = sum(float(mutation.get("negative_frequency") or 0.0) for mutation in mutations)
    gap_bonus = max(0.0, 14.0 - float(gap_error if gap_error is not None else 14.0)) * 0.01
    negative_identity_penalty = 0.0 if nearest_negative_identity is None else nearest_negative_identity * 0.15
    return round(
        residue_score
        + 0.20 * positive_frequency
        - 0.25 * negative_frequency
        + gap_bonus
        - negative_identity_penalty
        - 0.03 * len(mutations),
        6,
    )


def approximate_mutation_objective_score(mutations: list[dict[str, Any]]) -> float:
    return round(
        sum(float(mutation.get("residue_objective_score") or 0.0) for mutation in mutations)
        + 0.20 * sum(float(mutation.get("positive_frequency") or 0.0) for mutation in mutations)
        - 0.25 * sum(float(mutation.get("negative_frequency") or 0.0) for mutation in mutations)
        - 0.03 * len(mutations),
        6,
    )


def build_candidate_row(
    *,
    parent: dict[str, Any],
    sequence: str,
    mutations: list[dict[str, Any]],
    hard_gate: dict[str, Any],
    negatives_by_length: dict[int, list[str]],
) -> dict[str, Any]:
    blueprint = hard_gate["blueprint"]
    assessment = hard_gate["family_assessment"]
    core_evaluation = hard_gate["core_evaluation"]
    geometry = assessment.get("catalytic_geometry") or {}
    gap_error = geometry.get("best_gap_error")
    nearest_negative_identity = nearest_same_length_negative_identity(sequence, negatives_by_length)
    objective_score = proposal_objective_score(
        mutations,
        nearest_negative_identity=nearest_negative_identity,
        gap_error=gap_error if isinstance(gap_error, int) else None,
    )
    motif = str(blueprint.get("motif") or "")
    candidate_id = sequence_id(sequence)
    return {
        "candidate_id": candidate_id,
        "sequence_id": candidate_id,
        "sequence": sequence,
        "length": len(sequence),
        "parent_panel_id": parent.get("panel_id"),
        "parent_panel_role": parent.get("panel_role"),
        "parent_panel_source": parent.get("panel_source"),
        "parent_source_key": row_source_key(parent),
        "parent_sequence": parent.get("sequence"),
        "mutation_count": len(mutations),
        "mutations": mutations,
        "blueprint": blueprint,
        "family_assessment": assessment,
        "core_evaluation": core_evaluation,
        "hard_gate_passes": bool(hard_gate["hard_gate_passes"]),
        "rejection_reasons": hard_gate["rejection_reasons"],
        "objective_score": objective_score,
        "positive_profile_score": round(sum(float(m["positive_frequency"]) for m in mutations), 6),
        "negative_profile_score": round(sum(float(m["negative_frequency"]) for m in mutations), 6),
        "nearest_same_length_negative_identity": (
            round(nearest_negative_identity, 6) if nearest_negative_identity is not None else None
        ),
        "prompt": retargeted_prompt(length=len(sequence), motif=motif),
        "source_prompt": retargeted_prompt(length=len(sequence), motif=motif),
        "prompt_source": "synthetic_v2_exact_length_prompt",
        "requested_length": len(sequence),
        "prompt_length_delta": 0,
        "prompt_length_ok": True,
        "family_faithful_proxy_passes": bool(
            hard_gate["hard_gate_passes"]
            and objective_score >= 0.0
            and (nearest_negative_identity is None or nearest_negative_identity < 0.995)
        ),
        "bridge_quality_passes": isinstance(gap_error, int) and gap_error <= 14,
        "needs_esm_score": True,
        "esm_score": None,
        "constructor_stage": "manifold_v2_offline_pre_esm",
    }


def candidate_priority(row: dict[str, Any]) -> tuple[Any, ...]:
    gap_error = (
        (row.get("family_assessment") or {}).get("catalytic_geometry") or {}
    ).get("best_gap_error")
    gap_value = int(gap_error) if isinstance(gap_error, int) else 10**9
    nearest_negative_identity = row.get("nearest_same_length_negative_identity")
    return (
        -float(row.get("objective_score") or 0.0),
        0 if bool(row.get("family_faithful_proxy_passes")) else 1,
        gap_value,
        float(nearest_negative_identity) if nearest_negative_identity is not None else 0.0,
        int(row.get("mutation_count") or 0),
        str(row.get("candidate_id") or ""),
    )


def select_candidates(
    frontier_rows: list[dict[str, Any]],
    *,
    max_selected: int,
    max_per_parent: int,
    max_per_length: int,
    min_two_mutants: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    parent_counts: Counter[str] = Counter()
    length_counts: Counter[int] = Counter()
    seen: set[str] = set()

    def try_add(row: dict[str, Any]) -> bool:
        if len(selected) >= max_selected:
            return False
        sequence = str(row["sequence"])
        parent_key = str(row["parent_panel_id"] or row["parent_source_key"])
        length = int(row["length"])
        if sequence in seen:
            return False
        if parent_counts[parent_key] >= max_per_parent:
            return False
        if length_counts[length] >= max_per_length:
            return False
        payload = dict(row)
        payload["selection_rank"] = len(selected) + 1
        payload["selection_source"] = "manifold_v2_offline_constructor"
        selected.append(payload)
        seen.add(sequence)
        parent_counts[parent_key] += 1
        length_counts[length] += 1
        return True

    ordered_rows = sorted(frontier_rows, key=candidate_priority)
    for row in ordered_rows:
        if sum(int(item.get("mutation_count") or 0) == 2 for item in selected) >= min_two_mutants:
            break
        if int(row.get("mutation_count") or 0) == 2:
            try_add(row)

    for row in ordered_rows:
        if len(selected) >= max_selected:
            break
        try_add(row)
    return selected


def numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "mean": None, "max": None}
    return {
        "count": len(values),
        "min": round(min(values), 6),
        "mean": round(mean(values), 6),
        "max": round(max(values), 6),
    }


def check(name: str, observed: Any, threshold: Any, passed: bool) -> dict[str, Any]:
    return {
        "name": name,
        "observed": observed,
        "threshold": threshold,
        "passed": bool(passed),
    }


def summarize(
    *,
    panel_rows: list[dict[str, Any]],
    parents: list[dict[str, Any]],
    frontier_rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
    rejection_counts: Counter[str],
    parent_summaries: list[dict[str, Any]],
    output_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    selected_parent_counts = Counter(str(row["parent_panel_id"] or row["parent_source_key"]) for row in selected_rows)
    selected_length_counts = Counter(int(row["length"]) for row in selected_rows)
    selected_depth_counts = Counter(int(row["mutation_count"]) for row in selected_rows)
    source_counts = Counter(str(row.get("parent_panel_source")) for row in selected_rows)
    role_counts = Counter(str(row.get("parent_panel_role")) for row in selected_rows)
    proxy_rows = [row for row in selected_rows if bool(row.get("family_faithful_proxy_passes"))]
    bridge_rows = [row for row in selected_rows if bool(row.get("bridge_quality_passes"))]
    selected_count = len(selected_rows)

    checks = [
        check(
            "min_selected",
            selected_count,
            int(args.readiness_min_selected),
            selected_count >= int(args.readiness_min_selected),
        ),
        check(
            "min_parent_scaffolds",
            len(selected_parent_counts),
            int(args.readiness_min_parents),
            len(selected_parent_counts) >= int(args.readiness_min_parents),
        ),
        check(
            "min_unique_lengths",
            len(selected_length_counts),
            int(args.readiness_min_lengths),
            len(selected_length_counts) >= int(args.readiness_min_lengths),
        ),
        check(
            "min_two_mutants",
            selected_depth_counts.get(2, 0),
            int(args.readiness_min_two_mutants),
            selected_depth_counts.get(2, 0) >= int(args.readiness_min_two_mutants),
        ),
        check(
            "all_selected_hard_gates",
            sum(bool(row.get("hard_gate_passes")) for row in selected_rows),
            selected_count,
            selected_count > 0 and all(bool(row.get("hard_gate_passes")) for row in selected_rows),
        ),
        check(
            "all_prompt_length_obedient",
            sum(bool(row.get("prompt_length_ok")) for row in selected_rows),
            selected_count,
            selected_count > 0 and all(bool(row.get("prompt_length_ok")) for row in selected_rows),
        ),
        check(
            "min_family_faithful_proxy_rows",
            len(proxy_rows),
            max(1, int(args.readiness_min_selected) // 2),
            len(proxy_rows) >= max(1, int(args.readiness_min_selected) // 2),
        ),
        check(
            "min_bridge_quality_rows",
            len(bridge_rows),
            max(1, int(args.readiness_min_selected) // 2),
            len(bridge_rows) >= max(1, int(args.readiness_min_selected) // 2),
        ),
    ]

    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "panel_dir": str(repo_path(args.panel_dir)),
        "records_path": str(repo_path(args.records_path)),
        "output_dir": str(output_dir),
        "config": {
            "max_parents": int(args.max_parents),
            "max_frontier_candidates": int(args.max_frontier_candidates),
            "max_selected_candidates": int(args.max_selected_candidates),
            "max_proposals_per_parent": int(args.max_proposals_per_parent),
            "max_candidates_per_parent": int(args.max_candidates_per_parent),
            "max_selected_per_parent": int(args.max_selected_per_parent),
            "max_selected_per_length": int(args.max_selected_per_length),
            "relative_profile_bins": int(args.relative_profile_bins),
            "max_mutable_positions_per_parent": int(args.max_mutable_positions_per_parent),
            "residues_per_position": int(args.residues_per_position),
            "mutation_depths": str(args.mutation_depths),
            "min_positive_frequency": float(args.min_positive_frequency),
            "max_negative_frequency": float(args.max_negative_frequency),
            "min_objective_score": float(args.min_objective_score),
        },
        "input_counts": {
            "panel_rows": len(panel_rows),
            "panel_role_counts": dict(sorted(Counter(str(row.get("panel_role")) for row in panel_rows).items())),
            "selected_parent_rows": len(parents),
        },
        "frontier_counts": {
            "frontier_candidates": len(frontier_rows),
            "parent_scaffolds": len({str(row.get("parent_panel_id")) for row in frontier_rows}),
            "unique_lengths": len({int(row["length"]) for row in frontier_rows}),
            "family_faithful_proxy_rows": sum(bool(row.get("family_faithful_proxy_passes")) for row in frontier_rows),
            "bridge_quality_rows": sum(bool(row.get("bridge_quality_passes")) for row in frontier_rows),
            "mutation_count_histogram": dict(
                sorted(Counter(str(row.get("mutation_count")) for row in frontier_rows).items())
            ),
        },
        "selected_counts": {
            "selected": selected_count,
            "parent_scaffolds": len(selected_parent_counts),
            "unique_lengths": len(selected_length_counts),
            "family_faithful_proxy_rows": len(proxy_rows),
            "bridge_quality_rows": len(bridge_rows),
            "mutation_count_histogram": dict(sorted((str(key), value) for key, value in selected_depth_counts.items())),
            "length_histogram": dict(sorted((str(key), value) for key, value in selected_length_counts.items())),
            "length_bin_10aa_histogram": dict(
                sorted(
                    Counter(str(length_bin(int(row["length"]))) for row in selected_rows).items(),
                    key=lambda item: int(item[0]),
                )
            ),
            "parent_source_counts": dict(sorted(source_counts.items())),
            "parent_role_counts": dict(sorted(role_counts.items())),
            "max_parent_share": round(max(selected_parent_counts.values(), default=0) / max(1, selected_count), 6),
            "max_length_share": round(max(selected_length_counts.values(), default=0) / max(1, selected_count), 6),
        },
        "score_summary": {
            "objective_score": numeric_summary([float(row["objective_score"]) for row in selected_rows]),
            "positive_profile_score": numeric_summary([float(row["positive_profile_score"]) for row in selected_rows]),
            "negative_profile_score": numeric_summary([float(row["negative_profile_score"]) for row in selected_rows]),
            "nearest_same_length_negative_identity": numeric_summary(
                [
                    float(row["nearest_same_length_negative_identity"])
                    for row in selected_rows
                    if row.get("nearest_same_length_negative_identity") is not None
                ]
            ),
        },
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "parent_summaries": parent_summaries,
        "checks": checks,
        "ready_for_esm_scoring": all(bool(item["passed"]) for item in checks),
        "ready_for_paid_gate": False,
        "paid_gate_blocker": "pre-ESM offline constructor output; score and reselect before any Tinker gate",
        "outputs": {
            "frontier": str(output_dir / "v2_constructor_frontier_pre_esm.jsonl"),
            "selected": str(output_dir / "v2_constructor_selected_pre_esm.jsonl"),
            "summary": str(output_dir / "v2_constructor_summary.json"),
        },
        "next_step": (
            "ESM-score v2_constructor_selected_pre_esm.jsonl, then rebuild a scored selection; "
            "do not train or gate until ESM and diversity checks pass."
        ),
    }


def build_constructor(args: argparse.Namespace) -> dict[str, Any]:
    panel_dir = repo_path(args.panel_dir)
    records_path = repo_path(args.records_path)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    panel_rows = load_panel(panel_dir)
    positive_rows = [row for row in panel_rows if row.get("panel_role") in POSITIVE_ROLES]
    negative_rows = [row for row in panel_rows if row.get("panel_role") in NEGATIVE_ROLES]
    reference_records = load_reference_records(records_path)
    precompute_novelty_cache(reference_records)
    family_stats = compute_family_stats(reference_records)

    positive_exact, positive_relative = weighted_profiles(
        positive_rows,
        bin_count=int(args.relative_profile_bins),
    )
    negative_exact, negative_relative = weighted_profiles(
        negative_rows,
        bin_count=int(args.relative_profile_bins),
    )
    negatives_by_length: dict[int, list[str]] = {}
    for row in negative_rows:
        negatives_by_length.setdefault(int(row["length"]), []).append(str(row["sequence"]))

    parent_rows: list[dict[str, Any]] = []
    parent_rejection_counts: Counter[str] = Counter()
    for row in positive_rows:
        sequence = str(row["sequence"])
        blueprint = extract_blueprint(sequence, family_stats)
        assessment = family_manifold_assessment(sequence=sequence, family_stats=family_stats, blueprint=blueprint)
        core_evaluation = evaluate_candidate(
            sequence=sequence,
            family_stats=family_stats,
            reference_records=reference_records,
        )
        if not assessment["strict_manifold_passes"]:
            parent_rejection_counts.update(rejection_reasons(assessment, blueprint) or ["failed_strict_parent_gate"])
            continue
        if not core_evaluation.get("passes_core_screen"):
            parent_rejection_counts["parent_fails_family_core_screen"] += 1
            continue
        payload = dict(row)
        payload["blueprint"] = blueprint
        payload["family_assessment"] = assessment
        payload["core_evaluation"] = core_evaluation
        parent_rows.append(payload)
    parent_rows = sorted(parent_rows, key=parent_priority)[: int(args.max_parents)]

    depths = [int(item) for item in str(args.mutation_depths).split(",") if item.strip()]
    known_sequences = {str(row["sequence"]) for row in panel_rows}
    generated_sequences: set[str] = set()
    frontier_rows: list[dict[str, Any]] = []
    rejection_counts = Counter(parent_rejection_counts)
    parent_summaries: list[dict[str, Any]] = []

    for parent in parent_rows:
        if len(frontier_rows) >= int(args.max_frontier_candidates):
            break
        suggestions = mutation_suggestions(
            parent,
            positive_exact=positive_exact,
            positive_relative=positive_relative,
            negative_exact=negative_exact,
            negative_relative=negative_relative,
            bin_count=int(args.relative_profile_bins),
            max_positions=int(args.max_mutable_positions_per_parent),
            residues_per_position=int(args.residues_per_position),
            min_positive_frequency=float(args.min_positive_frequency),
            max_negative_frequency=float(args.max_negative_frequency),
        )
        proposals = mutation_sets(
            suggestions,
            depths=depths,
            max_proposals=int(args.max_proposals_per_parent),
        )
        accepted = 0
        attempted = 0
        for mutations in proposals:
            if len(frontier_rows) >= int(args.max_frontier_candidates):
                break
            if accepted >= int(args.max_candidates_per_parent):
                break
            attempted += 1
            if approximate_mutation_objective_score(mutations) < float(args.min_objective_score) - 0.2:
                rejection_counts["approx_objective_score_below_prefilter"] += 1
                continue
            sequence = apply_mutations(str(parent["sequence"]), mutations)
            if sequence in known_sequences:
                rejection_counts["duplicate_panel_sequence"] += 1
                continue
            if sequence in generated_sequences:
                rejection_counts["duplicate_generated_sequence"] += 1
                continue
            if not AA_PATTERN.fullmatch(sequence):
                rejection_counts["invalid_amino_acids"] += 1
                continue
            hard_gate = hard_gate_assessment(
                sequence,
                family_stats=family_stats,
                reference_records=reference_records,
                parent_blueprint=parent["blueprint"],
            )
            if not hard_gate["hard_gate_passes"]:
                rejection_counts.update(hard_gate["rejection_reasons"] or ["failed_hard_gate"])
                continue
            row = build_candidate_row(
                parent=parent,
                sequence=sequence,
                mutations=mutations,
                hard_gate=hard_gate,
                negatives_by_length=negatives_by_length,
            )
            if float(row["objective_score"]) < float(args.min_objective_score):
                rejection_counts["objective_score_below_minimum"] += 1
                continue
            generated_sequences.add(sequence)
            frontier_rows.append(row)
            accepted += 1

        parent_summaries.append(
            {
                "parent_panel_id": parent.get("panel_id"),
                "parent_panel_role": parent.get("panel_role"),
                "parent_panel_source": parent.get("panel_source"),
                "length": parent.get("length"),
                "suggested_positions": len(suggestions),
                "proposals": len(proposals),
                "attempted": attempted,
                "accepted": accepted,
            }
        )

    selected_rows = select_candidates(
        frontier_rows,
        max_selected=int(args.max_selected_candidates),
        max_per_parent=int(args.max_selected_per_parent),
        max_per_length=int(args.max_selected_per_length),
        min_two_mutants=int(args.readiness_min_two_mutants),
    )

    frontier_path = output_dir / "v2_constructor_frontier_pre_esm.jsonl"
    selected_path = output_dir / "v2_constructor_selected_pre_esm.jsonl"
    summary_path = output_dir / "v2_constructor_summary.json"
    write_jsonl(frontier_path, sorted(frontier_rows, key=candidate_priority))
    write_jsonl(selected_path, selected_rows)
    summary = summarize(
        panel_rows=panel_rows,
        parents=parent_rows,
        frontier_rows=frontier_rows,
        selected_rows=selected_rows,
        rejection_counts=rejection_counts,
        parent_summaries=parent_summaries,
        output_dir=output_dir,
        args=args,
    )
    write_json(summary_path, summary)
    return summary


def main() -> None:
    summary = build_constructor(parse_args())
    print(json.dumps(summary["selected_counts"], indent=2, sort_keys=True))
    print(json.dumps({"ready_for_esm_scoring": summary["ready_for_esm_scoring"]}, sort_keys=True))
    print(summary["outputs"]["frontier"])
    print(summary["outputs"]["selected"])
    print(summary["outputs"]["summary"])


if __name__ == "__main__":
    main()
