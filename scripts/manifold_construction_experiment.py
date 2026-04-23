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
from typing import Any

ROOT_PATH = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT_PATH / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.family import (
    AA_PATTERN,
    ASP_HIS_TARGET_GAP,
    SER_ASP_TARGET_GAP,
    SERINE_MOTIF_PATTERN,
    assess_catalytic_geometry,
    compute_family_stats,
    find_serine_motifs,
    load_reference_records,
)
from pearl.paths import REPO_ROOT, resolve_repo_path


ROOT = REPO_ROOT
STRICT_SOURCE_ROLES = {"strict_positive"}
NEGATIVE_SOURCE_ROLES = {"negative"}
SOURCE_STRICT_FLAGS = {
    "strict_family",
    "strict_bridge",
    "strict_consensus",
    "validated_strict",
    "family_faithful_bridge_passes",
    "family_faithful_passes",
}
SCORE_KEYS = ("esm_score", "raw_esm_score", "esm_reward", "reward", "score")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validator-first PETase/cutinase manifold constructor")
    parser.add_argument("--config", required=True, help="Manifold construction config JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    describe = subparsers.add_parser("describe", help="Print resolved constructor config")
    describe.add_argument("--pretty", action="store_true")

    subparsers.add_parser("build-bank", help="Build scaffold bank with blueprints and masks")
    subparsers.add_parser("validate-roundtrip", help="Validate Phase 1 round-trip readiness")
    subparsers.add_parser(
        "build-phase2-frontier",
        help="Build same-length strict-manifold candidate frontier and stop before ESM scoring",
    )
    score_phase2 = subparsers.add_parser("score-phase2-esm", help="Score the Phase 2 frontier with ESM")
    score_phase2.add_argument("--limit", type=int, default=None, help="Optional candidate limit for smoke scoring")
    subparsers.add_parser("select-phase2", help="Build diversity/readiness selection from scored Phase 2 frontier")
    subparsers.add_parser("launch-pad", help="Run Phase 1 bank build and round-trip validation")
    return parser.parse_args()


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["_config_path"] = str(config_path)
    return payload


def resolved_path(value: str | None) -> Path | None:
    resolved = resolve_repo_path(value)
    return Path(resolved) if resolved is not None else None


def experiment_dir(config: dict[str, Any]) -> Path:
    output_root = resolved_path(str(config.get("output_dir", "reports/manifold")))
    assert output_root is not None
    return output_root / str(config["name"])


def output_paths(config: dict[str, Any]) -> dict[str, Path]:
    root = experiment_dir(config)
    return {
        "experiment_dir": root,
        "scaffold_bank": root / "scaffold_bank.jsonl",
        "summary": root / "summary.json",
        "roundtrip_report": root / "roundtrip_report.json",
        "phase2_frontier": root / "phase2_pre_esm_frontier.jsonl",
        "phase2_summary": root / "phase2_pre_esm_summary.json",
        "phase2_scored": root / "phase2_esm_scored.jsonl",
        "phase2_score_summary": root / "phase2_esm_score_summary.json",
        "phase2_selected": root / "phase2_selected_strict.jsonl",
        "phase2_selection_summary": root / "phase2_selection_summary.json",
    }


def load_family_inputs(config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records_path = resolved_path(str(config["records_path"]))
    assert records_path is not None
    records = load_reference_records(records_path)
    return records, compute_family_stats(records)


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def sequence_id(sequence: str) -> str:
    return sha256(sequence.encode("utf-8")).hexdigest()[:16]


def source_row_id(row: dict[str, Any], source_name: str, index: int) -> str:
    for key in ("accession", "id", "sequence_id", "candidate_id", "parent_id"):
        value = row.get(key)
        if value:
            return str(value)
    return f"{source_name}:{index}"


def source_score(row: dict[str, Any]) -> float | None:
    for key in SCORE_KEYS:
        value = row.get(key)
        if isinstance(value, int | float):
            return float(value)
    return None


def source_has_strict_flag(row: dict[str, Any]) -> bool:
    return any(bool(row.get(flag)) for flag in SOURCE_STRICT_FLAGS)


def family_manifold_assessment(
    *,
    sequence: str,
    family_stats: dict[str, Any],
    blueprint: dict[str, Any],
) -> dict[str, Any]:
    sequence = sequence.upper()
    motifs = find_serine_motifs(sequence)
    motif_counts = Counter(motifs)
    family_motif_count = sum(
        count for motif, count in motif_counts.items() if motif in family_stats["top_serine_motifs"]
    )
    geometry = assess_catalytic_geometry(sequence, family_stats)
    passes = (
        bool(AA_PATTERN.fullmatch(sequence))
        and family_stats["length_min"] <= len(sequence) <= family_stats["length_max"]
        and family_motif_count >= 1
        and bool(blueprint.get("passes"))
        and bool(geometry["passes"])
    )
    strict_passes = passes and len(motifs) == 1
    return {
        "valid_amino_acids": bool(AA_PATTERN.fullmatch(sequence)),
        "length": len(sequence),
        "length_in_family_band": family_stats["length_min"] <= len(sequence) <= family_stats["length_max"],
        "serine_motifs": motifs,
        "serine_motif_count": len(motifs),
        "family_serine_motif_count": family_motif_count,
        "has_family_serine_motif": family_motif_count >= 1,
        "single_serine_motif": len(motifs) == 1,
        "catalytic_geometry": geometry,
        "family_manifold_passes": passes,
        "strict_manifold_passes": strict_passes,
    }


def extract_blueprint(sequence: str, family_stats: dict[str, Any]) -> dict[str, Any]:
    sequence = sequence.upper()
    serine_window = family_stats["serine_position_range"]
    aspartate_window = family_stats["aspartate_position_range"]
    histidine_window = family_stats["histidine_position_range"]

    serine_hits: list[dict[str, Any]] = []
    for idx in range(len(sequence) - 4):
        motif = sequence[idx : idx + 5]
        position = idx + 3
        if not SERINE_MOTIF_PATTERN.fullmatch(motif):
            continue
        if not serine_window[0] <= position / len(sequence) <= serine_window[1]:
            continue
        serine_hits.append(
            {
                "position": position,
                "motif": motif,
                "motif_start": position - 2,
                "motif_end": position + 2,
                "is_family_motif": motif in family_stats["top_serine_motifs"],
            }
        )

    aspartate_hits = [
        idx + 1
        for idx, residue in enumerate(sequence)
        if residue == "D" and aspartate_window[0] <= (idx + 1) / len(sequence) <= aspartate_window[1]
    ]
    histidine_hits = [
        idx + 1
        for idx, residue in enumerate(sequence)
        if residue == "H" and histidine_window[0] <= (idx + 1) / len(sequence) <= histidine_window[1]
    ]

    best: dict[str, Any] | None = None
    for serine in serine_hits:
        ser_pos = int(serine["position"])
        for asp_pos in aspartate_hits:
            if asp_pos <= ser_pos:
                continue
            for his_pos in histidine_hits:
                if his_pos <= asp_pos:
                    continue
                gap_error = abs((asp_pos - ser_pos) - SER_ASP_TARGET_GAP) + abs(
                    (his_pos - asp_pos) - ASP_HIS_TARGET_GAP
                )
                candidate = {
                    "serine_position": ser_pos,
                    "aspartate_position": asp_pos,
                    "histidine_position": his_pos,
                    "ser_asp_gap": asp_pos - ser_pos,
                    "asp_his_gap": his_pos - asp_pos,
                    "gap_error": gap_error,
                    "motif": serine["motif"],
                    "motif_start": serine["motif_start"],
                    "motif_end": serine["motif_end"],
                    "family_motif": serine["is_family_motif"],
                }
                if best is None or (not bool(candidate["family_motif"]), gap_error) < (
                    not bool(best["family_motif"]),
                    int(best["gap_error"]),
                ):
                    best = candidate

    payload: dict[str, Any] = {
        "length": len(sequence),
        "target_ser_asp_gap": SER_ASP_TARGET_GAP,
        "target_asp_his_gap": ASP_HIS_TARGET_GAP,
        "serine_hits": serine_hits[:8],
        "aspartate_hits": aspartate_hits[:8],
        "histidine_hits": histidine_hits[:8],
        "passes": best is not None and bool(best["family_motif"]),
    }
    if best is not None:
        payload.update(best)
    return payload


def edit_mask_for_blueprint(sequence: str, blueprint: dict[str, Any]) -> dict[str, Any]:
    locked_positions: set[int] = set()
    motif_start = blueprint.get("motif_start")
    motif_end = blueprint.get("motif_end")
    if isinstance(motif_start, int) and isinstance(motif_end, int):
        locked_positions.update(range(motif_start, motif_end + 1))
    for key in ("aspartate_position", "histidine_position"):
        position = blueprint.get(key)
        if isinstance(position, int):
            locked_positions.add(position)

    locked = sorted(pos for pos in locked_positions if 1 <= pos <= len(sequence))
    mutable = [pos for pos in range(1, len(sequence) + 1) if pos not in locked_positions]
    return {
        "position_indexing": "one_based",
        "locked_positions": locked,
        "mutable_positions": mutable,
        "locked_count": len(locked),
        "mutable_count": len(mutable),
    }


def rejection_reasons(assessment: dict[str, Any], blueprint: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not assessment["valid_amino_acids"]:
        reasons.append("invalid_amino_acids")
    if not assessment["length_in_family_band"]:
        reasons.append("outside_family_length_band")
    if not assessment["has_family_serine_motif"]:
        reasons.append("missing_family_serine_motif")
    if not assessment["single_serine_motif"]:
        reasons.append("not_single_serine_motif")
    if not blueprint.get("passes"):
        reasons.append("missing_family_catalytic_blueprint")
    elif not assessment["catalytic_geometry"]["passes"]:
        reasons.append("geometry_gap_error_too_high")
    return reasons


def build_bank(config: dict[str, Any]) -> dict[str, Any]:
    reference_records, family_stats = load_family_inputs(config)
    paths = output_paths(config)
    paths["experiment_dir"].mkdir(parents=True, exist_ok=True)

    by_sequence: dict[str, dict[str, Any]] = {}
    source_summaries: dict[str, dict[str, Any]] = {}
    missing_required_sources: list[str] = []
    missing_optional_sources: list[str] = []

    for source in config.get("sources", []):
        source_name = str(source["name"])
        source_role = str(source.get("role", "candidate_scaffold"))
        source_path = resolved_path(str(source["path"]))
        assert source_path is not None
        required = bool(source.get("required", False))
        summary = {
            "path": str(source_path),
            "role": source_role,
            "required": required,
            "exists": source_path.exists(),
            "rows": 0,
            "sequence_rows": 0,
            "accepted_unique_sequences": 0,
            "duplicate_sequences": 0,
        }
        source_summaries[source_name] = summary

        if not source_path.exists():
            if required:
                missing_required_sources.append(source_name)
            else:
                missing_optional_sources.append(source_name)
            continue

        rows = iter_jsonl(source_path)
        summary["rows"] = len(rows)
        for index, row in enumerate(rows):
            raw_sequence = row.get("sequence")
            if not isinstance(raw_sequence, str) or not raw_sequence.strip():
                continue
            sequence = raw_sequence.strip().upper()
            summary["sequence_rows"] += 1
            seq_id = sequence_id(sequence)
            score = source_score(row)
            source_entry = {
                "source_name": source_name,
                "source_role": source_role,
                "source_row_id": source_row_id(row, source_name, index),
                "source_index": index,
                "source_score": score,
                "source_strict_flag": source_has_strict_flag(row),
            }

            if seq_id in by_sequence:
                summary["duplicate_sequences"] += 1
                existing = by_sequence[seq_id]
                existing["sources"].append(source_entry)
                existing["source_names"] = sorted({*existing["source_names"], source_name})
                existing["source_roles"] = sorted({*existing["source_roles"], source_role})
                if score is not None:
                    existing["source_scores"].append(score)
                continue

            blueprint = extract_blueprint(sequence, family_stats)
            assessment = family_manifold_assessment(
                sequence=sequence,
                family_stats=family_stats,
                blueprint=blueprint,
            )
            mask = edit_mask_for_blueprint(sequence, blueprint)
            row_payload = {
                "sequence_id": seq_id,
                "sequence": sequence,
                "length": len(sequence),
                "source_names": [source_name],
                "source_roles": [source_role],
                "sources": [source_entry],
                "source_scores": [] if score is None else [score],
                "family_manifold_passes": assessment["family_manifold_passes"],
                "strict_manifold_passes": assessment["strict_manifold_passes"],
                "strict_candidate_passes": False,
                "negative_example": source_role in NEGATIVE_SOURCE_ROLES,
                "family_assessment": assessment,
                "blueprint": blueprint,
                "edit_mask": mask,
                "rejection_reasons": rejection_reasons(assessment, blueprint),
            }
            by_sequence[seq_id] = row_payload
            summary["accepted_unique_sequences"] += 1

    for row in by_sequence.values():
        roles = set(row["source_roles"])
        source_strict = any(bool(source["source_strict_flag"]) for source in row["sources"])
        strict_source_role = bool(roles & STRICT_SOURCE_ROLES)
        row["strict_candidate_passes"] = bool(
            row["strict_manifold_passes"] and (source_strict or strict_source_role)
        )
        row["negative_example"] = bool(roles & NEGATIVE_SOURCE_ROLES)

    bank_rows = sorted(by_sequence.values(), key=lambda row: (row["source_names"], row["sequence_id"]))
    with paths["scaffold_bank"].open("w", encoding="utf-8") as handle:
        for row in bank_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    role_counts = Counter(role for row in bank_rows for role in row["source_roles"])
    summary_payload = {
        "name": config["name"],
        "config_path": config["_config_path"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "family_stats": family_stats,
        "source_summaries": source_summaries,
        "missing_required_sources": missing_required_sources,
        "missing_optional_sources": missing_optional_sources,
        "counts": {
            "unique_sequences": len(bank_rows),
            "family_manifold_scaffolds": sum(bool(row["family_manifold_passes"]) for row in bank_rows),
            "strict_manifold_scaffolds": sum(bool(row["strict_manifold_passes"]) for row in bank_rows),
            "strict_candidate_positives": sum(bool(row["strict_candidate_passes"]) for row in bank_rows),
            "negative_examples": sum(bool(row["negative_example"]) for row in bank_rows),
            "negative_family_manifold_passes": sum(
                bool(row["negative_example"] and row["family_manifold_passes"]) for row in bank_rows
            ),
        },
        "role_counts": dict(sorted(role_counts.items())),
        "outputs": {key: str(value) for key, value in paths.items()},
    }
    paths["summary"].write_text(json.dumps(summary_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary_payload


def read_bank(path: Path) -> list[dict[str, Any]]:
    return iter_jsonl(path)


def load_or_build_bank(config: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    paths = output_paths(config)
    if not paths["scaffold_bank"].exists() or not paths["summary"].exists():
        summary = build_bank(config)
    else:
        summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    return summary, read_bank(paths["scaffold_bank"])


def validate_roundtrip(config: dict[str, Any]) -> dict[str, Any]:
    paths = output_paths(config)
    summary, bank_rows = load_or_build_bank(config)
    validation = dict(config.get("validation", {}))
    strict_positive_rows = [
        row for row in bank_rows if bool(set(row["source_roles"]) & STRICT_SOURCE_ROLES)
    ]
    negative_rows = [
        row for row in bank_rows if bool(set(row["source_roles"]) & NEGATIVE_SOURCE_ROLES)
    ]
    strict_positive_rejects = [
        row for row in strict_positive_rows if not bool(row["strict_candidate_passes"])
    ]
    negative_family_passes = [
        row for row in negative_rows if bool(row["family_manifold_passes"])
    ]

    failures: list[str] = []
    counts = summary["counts"]
    if counts["family_manifold_scaffolds"] < int(validation.get("min_family_manifold_scaffolds", 1)):
        failures.append("too_few_family_manifold_scaffolds")
    if counts["strict_manifold_scaffolds"] < int(validation.get("min_strict_manifold_scaffolds", 1)):
        failures.append("too_few_strict_manifold_scaffolds")
    if counts["strict_candidate_positives"] < int(validation.get("min_strict_candidate_positives", 1)):
        failures.append("too_few_strict_candidate_positives")
    max_positive_rejects = int(validation.get("max_strict_positive_rejects", 0))
    if len(strict_positive_rejects) > max_positive_rejects:
        failures.append("strict_positive_roundtrip_rejects")
    max_negative_passes = int(validation.get("max_negative_family_manifold_passes", 0))
    if len(negative_family_passes) > max_negative_passes:
        failures.append("negative_examples_entered_family_manifold")
    if validation.get("require_negative_rows_if_source_exists", True):
        for source_name, source_summary in summary["source_summaries"].items():
            if source_summary["role"] in NEGATIVE_SOURCE_ROLES and source_summary["exists"]:
                if source_summary["sequence_rows"] == 0:
                    failures.append(f"negative_source_empty:{source_name}")

    report = {
        "name": config["name"],
        "config_path": config["_config_path"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "ready": not failures,
        "failures": failures,
        "counts": counts,
        "roundtrip": {
            "strict_positive_rows": len(strict_positive_rows),
            "strict_positive_passes": len(strict_positive_rows) - len(strict_positive_rejects),
            "strict_positive_rejects": len(strict_positive_rejects),
            "negative_rows": len(negative_rows),
            "negative_family_manifold_passes": len(negative_family_passes),
        },
        "examples": {
            "strict_positive_reject_ids": [row["sequence_id"] for row in strict_positive_rejects[:10]],
            "negative_family_pass_ids": [row["sequence_id"] for row in negative_family_passes[:10]],
        },
        "outputs": {key: str(value) for key, value in paths.items()},
    }
    paths["roundtrip_report"].write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def relative_bin(position: int, length: int, bin_count: int) -> int:
    if length <= 1:
        return 0
    return min(bin_count - 1, int(((position - 1) / (length - 1)) * bin_count))


def build_position_profiles(
    bank_rows: list[dict[str, Any]],
    *,
    bin_count: int,
) -> tuple[dict[int, dict[int, Counter[str]]], dict[int, Counter[str]]]:
    length_profiles: dict[int, dict[int, Counter[str]]] = {}
    relative_profiles: dict[int, Counter[str]] = {}
    for row in bank_rows:
        if not row.get("strict_manifold_passes"):
            continue
        sequence = str(row["sequence"])
        length_profile = length_profiles.setdefault(len(sequence), {})
        for idx, residue in enumerate(sequence, start=1):
            length_profile.setdefault(idx, Counter())[residue] += 1
            relative_profiles.setdefault(relative_bin(idx, len(sequence), bin_count), Counter())[residue] += 1
    return length_profiles, relative_profiles


def parent_sort_key(row: dict[str, Any]) -> tuple[int, float, int, str]:
    scores = [float(value) for value in row.get("source_scores", []) if isinstance(value, int | float)]
    return (
        1 if row.get("strict_candidate_passes") else 0,
        max(scores) if scores else -1.0,
        len(row.get("sources", [])),
        str(row["sequence_id"]),
    )


def choose_phase2_parents(bank_rows: list[dict[str, Any]], phase2: dict[str, Any]) -> list[dict[str, Any]]:
    mode = str(phase2.get("parent_source", "strict_candidate_passes"))
    if mode == "strict_candidate_passes":
        parents = [row for row in bank_rows if row.get("strict_candidate_passes")]
    elif mode == "strict_manifold_passes":
        parents = [row for row in bank_rows if row.get("strict_manifold_passes")]
    elif mode == "family_manifold_passes":
        parents = [row for row in bank_rows if row.get("family_manifold_passes")]
    else:
        raise ValueError(f"unknown phase2 parent_source: {mode}")

    parents = sorted(parents, key=parent_sort_key, reverse=True)
    max_parents = int(phase2.get("max_parent_scaffolds", 96))
    return parents[:max_parents]


def mutation_suggestions_for_parent(
    parent: dict[str, Any],
    length_profiles: dict[int, dict[int, Counter[str]]],
    relative_profiles: dict[int, Counter[str]],
    phase2: dict[str, Any],
) -> list[dict[str, Any]]:
    sequence = str(parent["sequence"])
    length = len(sequence)
    length_profile = length_profiles.get(length, {})
    bin_count = int(phase2.get("relative_profile_bins", 200))
    min_support = int(phase2.get("min_position_support", 2))
    residues_per_position = int(phase2.get("residues_per_position", 3))
    max_positions = int(phase2.get("max_mutable_positions_per_scaffold", 24))

    suggestions: list[dict[str, Any]] = []
    for position in parent["edit_mask"].get("mutable_positions", []):
        if not isinstance(position, int) or not 1 <= position <= length:
            continue
        current_residue = sequence[position - 1]
        counter = length_profile.get(position)
        profile_source = "same_length"
        if counter is None or sum(counter.values()) < min_support:
            counter = relative_profiles.get(relative_bin(position, length, bin_count), Counter())
            profile_source = "relative"
        alternatives = [
            (residue, count)
            for residue, count in counter.most_common()
            if residue != current_residue and AA_PATTERN.fullmatch(residue)
        ][:residues_per_position]
        if not alternatives:
            continue
        support = sum(counter.values())
        alt_support = sum(count for _, count in alternatives)
        suggestions.append(
            {
                "position": position,
                "current_residue": current_residue,
                "alternatives": [
                    {
                        "residue": residue,
                        "support": count,
                        "frequency": round(count / support, 4) if support else 0.0,
                    }
                    for residue, count in alternatives
                ],
                "support": support,
                "alt_support": alt_support,
                "profile_source": profile_source,
            }
        )

    suggestions.sort(
        key=lambda item: (
            item["alt_support"] / max(item["support"], 1),
            item["alt_support"],
            -item["position"],
        ),
        reverse=True,
    )
    return suggestions[:max_positions]


def apply_mutations(sequence: str, mutations: list[dict[str, Any]]) -> str:
    residues = list(sequence)
    for mutation in mutations:
        residues[int(mutation["position"]) - 1] = str(mutation["to"])
    return "".join(residues)


def mutation_set_id(parent_id: str, mutations: list[dict[str, Any]]) -> str:
    suffix = ",".join(f"{item['from']}{item['position']}{item['to']}" for item in mutations)
    return f"{parent_id}:{suffix}"


def iter_phase2_mutation_sets(
    suggestions: list[dict[str, Any]],
    phase2: dict[str, Any],
) -> list[list[dict[str, Any]]]:
    depths = [int(depth) for depth in phase2.get("mutation_depths", [1, 2])]
    max_proposals = int(phase2.get("max_proposals_per_scaffold", 1500))
    mutation_sets: list[list[dict[str, Any]]] = []

    if 1 in depths:
        for suggestion in suggestions:
            for alternative in suggestion["alternatives"]:
                mutation_sets.append(
                    [
                        {
                            "position": suggestion["position"],
                            "from": suggestion["current_residue"],
                            "to": alternative["residue"],
                            "profile_source": suggestion["profile_source"],
                            "support": alternative["support"],
                            "frequency": alternative["frequency"],
                        }
                    ]
                )
                if len(mutation_sets) >= max_proposals:
                    return mutation_sets

    if 2 in depths:
        for left, right in itertools.combinations(suggestions, 2):
            for left_alt in left["alternatives"]:
                for right_alt in right["alternatives"]:
                    mutation_sets.append(
                        [
                            {
                                "position": left["position"],
                                "from": left["current_residue"],
                                "to": left_alt["residue"],
                                "profile_source": left["profile_source"],
                                "support": left_alt["support"],
                                "frequency": left_alt["frequency"],
                            },
                            {
                                "position": right["position"],
                                "from": right["current_residue"],
                                "to": right_alt["residue"],
                                "profile_source": right["profile_source"],
                                "support": right_alt["support"],
                                "frequency": right_alt["frequency"],
                            },
                        ]
                    )
                    if len(mutation_sets) >= max_proposals:
                        return mutation_sets
    return mutation_sets


def build_phase2_frontier(config: dict[str, Any]) -> dict[str, Any]:
    summary, bank_rows = load_or_build_bank(config)
    reference_records, family_stats = load_family_inputs(config)
    del reference_records

    phase2 = dict(config.get("phase2", {}))
    bin_count = int(phase2.get("relative_profile_bins", 200))
    max_candidates = int(phase2.get("max_frontier_candidates", 10000))
    max_per_parent = int(phase2.get("max_candidates_per_parent", 128))
    require_strict = bool(phase2.get("require_strict_manifold", True))

    paths = output_paths(config)
    parents = choose_phase2_parents(bank_rows, phase2)
    known_sequence_ids = {str(row["sequence_id"]) for row in bank_rows}
    generated_ids: set[str] = set()
    length_profiles, relative_profiles = build_position_profiles(bank_rows, bin_count=bin_count)
    frontier_rows: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    parent_summaries: list[dict[str, Any]] = []

    for parent in parents:
        if len(frontier_rows) >= max_candidates:
            break

        suggestions = mutation_suggestions_for_parent(parent, length_profiles, relative_profiles, phase2)
        mutation_sets = iter_phase2_mutation_sets(suggestions, phase2)
        accepted_for_parent = 0
        attempted_for_parent = 0
        rejected_for_parent = 0

        for mutations in mutation_sets:
            if len(frontier_rows) >= max_candidates or accepted_for_parent >= max_per_parent:
                break
            attempted_for_parent += 1
            sequence = apply_mutations(str(parent["sequence"]), mutations)
            seq_id = sequence_id(sequence)
            if seq_id in known_sequence_ids:
                rejection_counts["duplicate_existing_bank_sequence"] += 1
                rejected_for_parent += 1
                continue
            if seq_id in generated_ids:
                rejection_counts["duplicate_generated_sequence"] += 1
                rejected_for_parent += 1
                continue

            blueprint = extract_blueprint(sequence, family_stats)
            assessment = family_manifold_assessment(
                sequence=sequence,
                family_stats=family_stats,
                blueprint=blueprint,
            )
            reasons = rejection_reasons(assessment, blueprint)
            if require_strict and not assessment["strict_manifold_passes"]:
                rejection_counts.update(reasons or ["failed_strict_manifold_gate"])
                rejected_for_parent += 1
                continue
            if not require_strict and not assessment["family_manifold_passes"]:
                rejection_counts.update(reasons or ["failed_family_manifold_gate"])
                rejected_for_parent += 1
                continue

            generated_ids.add(seq_id)
            accepted_for_parent += 1
            frontier_rows.append(
                {
                    "sequence_id": seq_id,
                    "parent_sequence_id": parent["sequence_id"],
                    "parent_source_names": parent["source_names"],
                    "sequence": sequence,
                    "length": len(sequence),
                    "mutations": mutations,
                    "mutation_count": len(mutations),
                    "mutation_set_id": mutation_set_id(str(parent["sequence_id"]), mutations),
                    "family_manifold_passes": assessment["family_manifold_passes"],
                    "strict_manifold_passes": assessment["strict_manifold_passes"],
                    "family_assessment": assessment,
                    "blueprint": blueprint,
                    "needs_esm_score": True,
                    "esm_score": None,
                    "phase": "phase2_pre_esm_frontier",
                }
            )

        parent_summaries.append(
            {
                "parent_sequence_id": parent["sequence_id"],
                "parent_source_names": parent["source_names"],
                "suggested_positions": len(suggestions),
                "proposals": len(mutation_sets),
                "attempted": attempted_for_parent,
                "accepted": accepted_for_parent,
                "rejected": rejected_for_parent,
            }
        )

    with paths["phase2_frontier"].open("w", encoding="utf-8") as handle:
        for row in frontier_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    report = {
        "name": config["name"],
        "config_path": config["_config_path"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "phase": "phase2_pre_esm_frontier",
        "stopped_before_esm_scoring": True,
        "phase1_counts": summary["counts"],
        "phase2_config": phase2,
        "counts": {
            "selected_parent_scaffolds": len(parents),
            "processed_parent_scaffolds": len(parent_summaries),
            "contributing_parent_scaffolds": sum(1 for item in parent_summaries if item["accepted"] > 0),
            "frontier_candidates": len(frontier_rows),
            "mutation_count_histogram": dict(
                sorted(Counter(str(row["mutation_count"]) for row in frontier_rows).items())
            ),
            "unique_lengths": len({row["length"] for row in frontier_rows}),
        },
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "parent_summaries": parent_summaries,
        "outputs": {key: str(value) for key, value in paths.items()},
        "next_step": "offload phase2_pre_esm_frontier.jsonl for ESM/stability scoring; do not train from this frontier before scoring and diversity selection",
    }
    paths["phase2_summary"].write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def score_phase2_esm(config: dict[str, Any], *, limit: int | None = None) -> dict[str, Any]:
    from pearl.esm_proxy import get_esm2_plddt_scores, prewarm_esm2_model

    paths = output_paths(config)
    if not paths["phase2_frontier"].exists():
        build_phase2_frontier(config)

    started_at = datetime.now(UTC)
    phase2 = dict(config.get("phase2", {}))
    score_batch_size = max(1, int(phase2.get("esm_score_batch_size", 64)))
    scored_rows: list[dict[str, Any]] = []
    esm_info = prewarm_esm2_model()

    pending_rows: list[dict[str, Any]] = []
    pending_sequences: list[str] = []
    with paths["phase2_frontier"].open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if limit is not None and index >= limit:
                break
            if not line.strip():
                continue
            row = json.loads(line)
            pending_rows.append(row)
            pending_sequences.append(str(row["sequence"]))
            if len(pending_rows) >= score_batch_size:
                scored_rows.extend(score_phase2_batch(pending_rows, pending_sequences))
                pending_rows = []
                pending_sequences = []

    if pending_rows:
        scored_rows.extend(score_phase2_batch(pending_rows, pending_sequences))

    with paths["phase2_scored"].open("w", encoding="utf-8") as handle:
        for row in scored_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    scores = [float(row["esm_score"]) for row in scored_rows]
    top_rows = sorted(scored_rows, key=lambda row: float(row["esm_score"]), reverse=True)[:20]
    summary = {
        "name": config["name"],
        "config_path": config["_config_path"],
        "phase": "phase2_esm_score",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "duration_seconds": round((datetime.now(UTC) - started_at).total_seconds(), 3),
        "input_path": str(paths["phase2_frontier"]),
        "output_path": str(paths["phase2_scored"]),
        "line_limit": limit,
        "esm_info": esm_info,
        "counts": {
            "scored_candidates": len(scored_rows),
            "score_batch_size": score_batch_size,
            "esm_ge_85": sum(score >= 85.0 for score in scores),
            "esm_ge_90": sum(score >= 90.0 for score in scores),
            "esm_ge_95": sum(score >= 95.0 for score in scores),
        },
        "score_summary": {
            "min": round(min(scores), 4) if scores else None,
            "mean": round(sum(scores) / len(scores), 4) if scores else None,
            "max": round(max(scores), 4) if scores else None,
        },
        "top_rows": [
            {
                "sequence_id": row["sequence_id"],
                "parent_sequence_id": row["parent_sequence_id"],
                "mutation_count": row["mutation_count"],
                "esm_score": row["esm_score"],
            }
            for row in top_rows
        ],
        "outputs": {key: str(value) for key, value in paths.items()},
    }
    paths["phase2_score_summary"].write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def score_phase2_batch(rows: list[dict[str, Any]], sequences: list[str]) -> list[dict[str, Any]]:
    from pearl.esm_proxy import get_esm2_plddt_scores

    scores = get_esm2_plddt_scores(sequences)
    scored: list[dict[str, Any]] = []
    for row, score in zip(rows, scores, strict=True):
        payload = dict(row)
        payload["esm_score"] = round(float(score), 4)
        payload["needs_esm_score"] = False
        payload["phase"] = "phase2_esm_scored"
        scored.append(payload)
    return scored


def select_phase2(config: dict[str, Any]) -> dict[str, Any]:
    paths = output_paths(config)
    if not paths["phase2_scored"].exists():
        raise FileNotFoundError(
            f"missing scored Phase 2 frontier: {paths['phase2_scored']}; run score-phase2-esm first"
        )

    selection = dict(config.get("phase2_selection", {}))
    max_selected = int(selection.get("max_selected", 240))
    min_esm_score = float(selection.get("min_esm_score", 95.0))
    bridge_gap_error_max = int(selection.get("bridge_gap_error_max", 14))
    max_per_parent = int(selection.get("max_per_parent", 3))
    max_length_share = float(selection.get("max_length_share", 0.25))
    max_per_length = int(selection.get("max_per_length", math.ceil(max_selected * max_length_share)))
    max_per_mutation_depth = {
        int(key): int(value)
        for key, value in dict(selection.get("max_per_mutation_depth", {"1": 160, "2": 160})).items()
    }
    max_per_parent_mutation_depth = {
        int(key): int(value)
        for key, value in dict(selection.get("max_per_parent_mutation_depth", {"1": 2, "2": 2})).items()
    }

    candidates = [
        row
        for row in read_bank(paths["phase2_scored"])
        if row.get("strict_manifold_passes")
        and float(row.get("esm_score") or 0.0) >= min_esm_score
    ]
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        by_parent.setdefault(str(row["parent_sequence_id"]), []).append(row)
    for parent_rows in by_parent.values():
        parent_rows.sort(key=phase2_selection_priority)

    parent_order = sorted(
        by_parent,
        key=lambda parent_id: phase2_selection_priority(by_parent[parent_id][0]),
    )
    parent_indexes = {parent_id: 0 for parent_id in parent_order}
    parent_counts: Counter[str] = Counter()
    parent_depth_counts: Counter[tuple[str, int]] = Counter()
    length_counts: Counter[int] = Counter()
    mutation_depth_counts: Counter[int] = Counter()
    selected: list[dict[str, Any]] = []
    seen_sequences: set[str] = set()

    while len(selected) < max_selected:
        progress = False
        for parent_id in parent_order:
            if len(selected) >= max_selected:
                break
            if parent_counts[parent_id] >= max_per_parent:
                continue

            parent_rows = by_parent[parent_id]
            index = parent_indexes[parent_id]
            chosen: dict[str, Any] | None = None
            while index < len(parent_rows):
                row = parent_rows[index]
                index += 1
                sequence_id = str(row["sequence_id"])
                length = int(row["length"])
                mutation_depth = int(row["mutation_count"])
                if sequence_id in seen_sequences:
                    continue
                if length_counts[length] >= max_per_length:
                    continue
                if mutation_depth_counts[mutation_depth] >= max_per_mutation_depth.get(
                    mutation_depth,
                    max_selected,
                ):
                    continue
                if parent_depth_counts[(parent_id, mutation_depth)] >= max_per_parent_mutation_depth.get(
                    mutation_depth,
                    max_per_parent,
                ):
                    continue
                chosen = row
                break
            parent_indexes[parent_id] = index
            if chosen is None:
                continue

            seen_sequences.add(str(chosen["sequence_id"]))
            parent_counts[parent_id] += 1
            parent_depth_counts[(parent_id, int(chosen["mutation_count"]))] += 1
            length_counts[int(chosen["length"])] += 1
            mutation_depth_counts[int(chosen["mutation_count"])] += 1
            selected.append(annotate_selected_phase2_row(chosen, len(selected) + 1, bridge_gap_error_max))
            progress = True

        if not progress:
            break

    selected.sort(key=lambda row: int(row["selection_rank"]))
    with paths["phase2_selected"].open("w", encoding="utf-8") as handle:
        for row in selected:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    parent_counts = Counter(str(row["parent_sequence_id"]) for row in selected)
    length_counts = Counter(int(row["length"]) for row in selected)
    mutation_depth_counts = Counter(int(row["mutation_count"]) for row in selected)
    bridge_rows = [row for row in selected if bool(row["bridge_quality_passes"])]
    bridge_parent_count = len({str(row["parent_sequence_id"]) for row in bridge_rows})
    selected_count = len(selected)

    readiness_thresholds = dict(selection.get("readiness", {}))
    checks = [
        readiness_check(
            "min_selected",
            selected_count,
            int(readiness_thresholds.get("min_selected", 200)),
            observed_passes=selected_count >= int(readiness_thresholds.get("min_selected", 200)),
        ),
        readiness_check(
            "min_parent_scaffolds",
            len(parent_counts),
            int(readiness_thresholds.get("min_parent_scaffolds", 64)),
            observed_passes=len(parent_counts) >= int(readiness_thresholds.get("min_parent_scaffolds", 64)),
        ),
        readiness_check(
            "min_unique_lengths",
            len(length_counts),
            int(readiness_thresholds.get("min_unique_lengths", 6)),
            observed_passes=len(length_counts) >= int(readiness_thresholds.get("min_unique_lengths", 6)),
        ),
        readiness_check(
            "min_bridge_quality_rows",
            len(bridge_rows),
            int(readiness_thresholds.get("min_bridge_quality_rows", 96)),
            observed_passes=len(bridge_rows) >= int(readiness_thresholds.get("min_bridge_quality_rows", 96)),
        ),
        readiness_check(
            "min_bridge_quality_parents",
            bridge_parent_count,
            int(readiness_thresholds.get("min_bridge_quality_parents", 24)),
            observed_passes=bridge_parent_count
            >= int(readiness_thresholds.get("min_bridge_quality_parents", 24)),
        ),
        readiness_check(
            "min_two_mutants",
            mutation_depth_counts.get(2, 0),
            int(readiness_thresholds.get("min_two_mutants", 60)),
            observed_passes=mutation_depth_counts.get(2, 0)
            >= int(readiness_thresholds.get("min_two_mutants", 60)),
        ),
    ]

    max_parent_share_observed = max(parent_counts.values(), default=0) / max(1, selected_count)
    max_length_share_observed = max(length_counts.values(), default=0) / max(1, selected_count)
    max_parent_share_threshold = float(readiness_thresholds.get("max_parent_share", 0.05))
    max_length_share_threshold = float(readiness_thresholds.get("max_length_share", 0.25))
    checks.extend(
        [
            readiness_check(
                "max_parent_share",
                round(max_parent_share_observed, 6),
                max_parent_share_threshold,
                observed_passes=max_parent_share_observed <= max_parent_share_threshold,
            ),
            readiness_check(
                "max_length_share",
                round(max_length_share_observed, 6),
                max_length_share_threshold,
                observed_passes=max_length_share_observed <= max_length_share_threshold,
            ),
        ]
    )

    report = {
        "name": config["name"],
        "config_path": config["_config_path"],
        "phase": "phase2_selection",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "selection_config": selection,
        "input_counts": {
            "scored_candidates": count_jsonl_rows(paths["phase2_scored"]),
            "eligible_candidates": len(candidates),
            "eligible_parent_scaffolds": len(by_parent),
        },
        "selected_counts": {
            "selected": selected_count,
            "parent_scaffolds": len(parent_counts),
            "unique_lengths": len(length_counts),
            "bridge_quality_rows": len(bridge_rows),
            "bridge_quality_parents": bridge_parent_count,
            "mutation_count_histogram": dict(sorted((str(k), v) for k, v in mutation_depth_counts.items())),
            "length_histogram": dict(sorted((str(k), v) for k, v in length_counts.items())),
            "max_parent_share": round(max_parent_share_observed, 6),
            "max_length_share": round(max_length_share_observed, 6),
        },
        "score_summary": summarize_selected_scores(selected),
        "checks": checks,
        "ready_for_curriculum_build": all(bool(check["passed"]) for check in checks),
        "outputs": {key: str(value) for key, value in paths.items()},
    }
    paths["phase2_selection_summary"].write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def phase2_selection_priority(row: dict[str, Any]) -> tuple[Any, ...]:
    geometry = row.get("family_assessment", {}).get("catalytic_geometry", {})
    gap_error = geometry.get("best_gap_error")
    gap_value = int(gap_error) if isinstance(gap_error, int) else 10**9
    mutation_count = int(row.get("mutation_count") or 0)
    support = sum(float(mutation.get("support") or 0.0) for mutation in row.get("mutations", []))
    frequency = sum(float(mutation.get("frequency") or 0.0) for mutation in row.get("mutations", []))
    return (
        0 if gap_value <= 14 else 1,
        gap_value,
        mutation_count,
        -float(row.get("esm_score") or 0.0),
        -support,
        -frequency,
        str(row.get("sequence_id") or ""),
    )


def count_jsonl_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def annotate_selected_phase2_row(
    row: dict[str, Any],
    rank: int,
    bridge_gap_error_max: int,
) -> dict[str, Any]:
    payload = dict(row)
    geometry = row.get("family_assessment", {}).get("catalytic_geometry", {})
    gap_error = geometry.get("best_gap_error")
    payload["selection_rank"] = rank
    payload["selection_cluster_id"] = str(row["parent_sequence_id"])
    payload["bridge_quality_passes"] = isinstance(gap_error, int) and gap_error <= bridge_gap_error_max
    payload["selection_notes"] = {
        "parent_scaffold_cluster": "parent_sequence_id",
        "bridge_gap_error_max": bridge_gap_error_max,
        "best_gap_error": gap_error,
    }
    return payload


def readiness_check(name: str, observed: Any, threshold: Any, *, observed_passes: bool) -> dict[str, Any]:
    return {
        "name": name,
        "observed": observed,
        "threshold": threshold,
        "passed": bool(observed_passes),
    }


def summarize_selected_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [float(row["esm_score"]) for row in rows if row.get("esm_score") is not None]
    if not scores:
        return {"min": None, "mean": None, "max": None}
    return {
        "min": round(min(scores), 4),
        "mean": round(sum(scores) / len(scores), 4),
        "max": round(max(scores), 4),
    }


def describe(config: dict[str, Any]) -> dict[str, Any]:
    paths = output_paths(config)
    source_status = {}
    for source in config.get("sources", []):
        source_path = resolved_path(str(source["path"]))
        assert source_path is not None
        source_status[str(source["name"])] = {
            "path": str(source_path),
            "role": str(source.get("role", "candidate_scaffold")),
            "required": bool(source.get("required", False)),
            "exists": source_path.exists(),
        }
    return {
        "name": config["name"],
        "records_path": str(resolved_path(str(config["records_path"]))),
        "sources": source_status,
        "validation": config.get("validation", {}),
        "outputs": {key: str(value) for key, value in paths.items()},
        "commands": {
            "build_bank": [
                sys.executable,
                "scripts/manifold_construction_experiment.py",
                "--config",
                config["_config_path"],
                "build-bank",
            ],
            "validate_roundtrip": [
                sys.executable,
                "scripts/manifold_construction_experiment.py",
                "--config",
                config["_config_path"],
                "validate-roundtrip",
            ],
            "launch_pad": [
                sys.executable,
                "scripts/manifold_construction_experiment.py",
                "--config",
                config["_config_path"],
                "launch-pad",
            ],
            "build_phase2_frontier": [
                sys.executable,
                "scripts/manifold_construction_experiment.py",
                "--config",
                config["_config_path"],
                "build-phase2-frontier",
            ],
            "score_phase2_esm": [
                sys.executable,
                "scripts/manifold_construction_experiment.py",
                "--config",
                config["_config_path"],
                "score-phase2-esm",
            ],
            "select_phase2": [
                sys.executable,
                "scripts/manifold_construction_experiment.py",
                "--config",
                config["_config_path"],
                "select-phase2",
            ],
        },
    }


def main() -> None:
    args = parse_args()
    config = load_config(args.config)

    if args.command == "describe":
        payload = describe(config)
        print(json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True))
        return
    if args.command == "build-bank":
        print(json.dumps(build_bank(config), indent=2, sort_keys=True))
        return
    if args.command == "validate-roundtrip":
        print(json.dumps(validate_roundtrip(config), indent=2, sort_keys=True))
        return
    if args.command == "build-phase2-frontier":
        print(json.dumps(build_phase2_frontier(config), indent=2, sort_keys=True))
        return
    if args.command == "score-phase2-esm":
        print(json.dumps(score_phase2_esm(config, limit=args.limit), indent=2, sort_keys=True))
        return
    if args.command == "select-phase2":
        print(json.dumps(select_phase2(config), indent=2, sort_keys=True))
        return
    if args.command == "launch-pad":
        build_bank(config)
        print(json.dumps(validate_roundtrip(config), indent=2, sort_keys=True))
        return
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
