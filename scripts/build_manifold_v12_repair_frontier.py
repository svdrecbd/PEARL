#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.family import (
    AA_PATTERN,
    ASP_HIS_TARGET_GAP,
    SER_ASP_TARGET_GAP,
    SERINE_MOTIF_PATTERN,
    compute_family_stats,
    evaluate_candidate,
    load_reference_records,
)
from pearl.paths import resolve_repo_path
from scripts.manifold_construction_experiment import (
    extract_blueprint,
    family_manifold_assessment,
    rejection_reasons,
)


DEFAULT_ALLOWED_MOTIFS = ("GYSQG", "GYSLG")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a v1.2 strict-gated offline repair frontier from v1.1 failure lanes"
    )
    parser.add_argument("--lanes-dir", required=True)
    parser.add_argument("--records-path", default="data/petase_family_expanded/petase_records.jsonl")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--allowed-motifs", default=",".join(DEFAULT_ALLOWED_MOTIFS))
    parser.add_argument("--max-input-per-lane", type=int, default=128)
    parser.add_argument("--max-output-candidates", type=int, default=5000)
    parser.add_argument("--max-prompt-length-delta", type=int, default=40)
    parser.add_argument("--relocation-step", type=int, default=4)
    parser.add_argument("--relocation-window", type=int, default=24)
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


def sequence_id(sequence: str, *, prefix: str = "v12") -> str:
    return f"{prefix}-{sha256(sequence.encode('utf-8')).hexdigest()[:16]}"


def to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def motif_hits(sequence: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for index in range(len(sequence) - 4):
        motif = sequence[index : index + 5]
        if SERINE_MOTIF_PATTERN.fullmatch(motif):
            hits.append(
                {
                    "motif": motif,
                    "motif_start": index + 1,
                    "serine_position": index + 3,
                    "motif_end": index + 5,
                }
            )
    return hits


def apply_mutations(sequence: str, mutations: list[dict[str, Any]]) -> str:
    residues = list(sequence)
    for mutation in mutations:
        position = int(mutation["position"])
        if not 1 <= position <= len(residues):
            raise ValueError(f"mutation position outside sequence: {position}")
        residues[position - 1] = str(mutation["to"])
    return "".join(residues)


def dedupe_mutations(mutations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_position: dict[int, dict[str, Any]] = {}
    for mutation in mutations:
        position = int(mutation["position"])
        previous = by_position.get(position)
        if previous is not None and previous["to"] != mutation["to"]:
            raise ValueError(f"conflicting mutation at position {position}")
        by_position[position] = mutation
    return [by_position[position] for position in sorted(by_position)]


def motif_write_mutations(sequence: str, *, motif_start: int, motif: str, reason: str) -> list[dict[str, Any]]:
    mutations: list[dict[str, Any]] = []
    for offset, residue in enumerate(motif):
        position = motif_start + offset
        if not 1 <= position <= len(sequence):
            return []
        current = sequence[position - 1]
        if current != residue:
            mutations.append(
                {
                    "position": position,
                    "from": current,
                    "to": residue,
                    "reason": reason,
                }
            )
    return mutations


def break_existing_motif_mutations(sequence: str, *, protected_starts: set[int]) -> list[dict[str, Any]]:
    mutations: list[dict[str, Any]] = []
    for hit in motif_hits(sequence):
        if int(hit["motif_start"]) in protected_starts:
            continue
        serine_position = int(hit["serine_position"])
        current = sequence[serine_position - 1]
        replacement = "A" if current != "A" else "T"
        mutations.append(
            {
                "position": serine_position,
                "from": current,
                "to": replacement,
                "reason": "break_extra_serine_motif",
            }
        )
    return mutations


def dh_repair_mutations(sequence: str, *, serine_position: int, d_shift: int, h_shift: int) -> list[dict[str, Any]] | None:
    d_position = serine_position + SER_ASP_TARGET_GAP + d_shift
    h_position = d_position + ASP_HIS_TARGET_GAP + h_shift
    if not (1 <= d_position <= len(sequence) and 1 <= h_position <= len(sequence)):
        return None
    if h_position <= d_position:
        return None
    mutations: list[dict[str, Any]] = []
    if sequence[d_position - 1] != "D":
        mutations.append(
            {
                "position": d_position,
                "from": sequence[d_position - 1],
                "to": "D",
                "reason": "repair_target_aspartate",
            }
        )
    if sequence[h_position - 1] != "H":
        mutations.append(
            {
                "position": h_position,
                "from": sequence[h_position - 1],
                "to": "H",
                "reason": "repair_target_histidine",
            }
        )
    return mutations


def target_serine_positions(
    *,
    length: int,
    family_stats: dict[str, Any],
    step: int,
    window: int,
) -> list[int]:
    low = max(3, math.ceil(float(family_stats["serine_position_range"][0]) * length))
    high = min(length - 2, math.floor(float(family_stats["serine_position_range"][1]) * length))
    if low > high:
        return []
    center = round((low + high) / 2)
    positions = {center}
    for delta in range(step, window + 1, step):
        positions.add(center - delta)
        positions.add(center + delta)
    return sorted(position for position in positions if low <= position <= high)


def candidate_record(
    *,
    source_row: dict[str, Any],
    sequence: str,
    mutations: list[dict[str, Any]],
    operation: str,
    family_stats: dict[str, Any],
    reference_records: list[dict[str, Any]],
    max_prompt_length_delta: int,
) -> dict[str, Any]:
    blueprint = extract_blueprint(sequence, family_stats)
    assessment = family_manifold_assessment(
        sequence=sequence,
        family_stats=family_stats,
        blueprint=blueprint,
    )
    core_evaluation = evaluate_candidate(
        sequence=sequence,
        family_stats=family_stats,
        reference_records=reference_records,
    )
    requested_length = to_int(source_row.get("requested_length"))
    length_delta = len(sequence) - requested_length if requested_length is not None else None
    prompt_length_ok = length_delta is None or abs(length_delta) <= max_prompt_length_delta
    return {
        "candidate_id": sequence_id(sequence),
        "sequence": sequence,
        "length": len(sequence),
        "source_lane": source_row.get("lane"),
        "source_mode": source_row.get("mode"),
        "source_seed": source_row.get("seed"),
        "source_step": source_row.get("step"),
        "source_selected": bool(source_row.get("selected")),
        "source_raw_esm_score": source_row.get("raw_esm_score"),
        "source_geometry_score": source_row.get("geometry_score"),
        "source_best_gap_error": source_row.get("best_gap_error"),
        "operation": operation,
        "mutation_count": len(mutations),
        "mutations": mutations,
        "prompt": source_row.get("prompt"),
        "requested_length": requested_length,
        "prompt_length_delta": length_delta,
        "prompt_length_ok": prompt_length_ok,
        "passes_core_screen": bool(core_evaluation["passes_core_screen"]),
        "strict_trainable_candidate": bool(
            assessment["strict_manifold_passes"]
            and prompt_length_ok
            and core_evaluation["passes_core_screen"]
        ),
        "family_manifold_passes": assessment["family_manifold_passes"],
        "strict_manifold_passes": assessment["strict_manifold_passes"],
        "rejection_reasons": rejection_reasons(assessment, blueprint),
        "family_assessment": assessment,
        "core_evaluation": core_evaluation,
        "blueprint": blueprint,
        "needs_esm_score": True,
        "esm_score": None,
    }


def add_if_valid(
    *,
    source_row: dict[str, Any],
    source_sequence: str,
    mutations: list[dict[str, Any]],
    operation: str,
    family_stats: dict[str, Any],
    reference_records: list[dict[str, Any]],
    output: list[dict[str, Any]],
    seen: set[str],
    max_prompt_length_delta: int,
) -> None:
    try:
        mutations = dedupe_mutations(mutations)
    except ValueError:
        return
    mutations = [mutation for mutation in mutations if mutation["from"] != mutation["to"]]
    sequence = apply_mutations(source_sequence, mutations) if mutations else source_sequence
    if not AA_PATTERN.fullmatch(sequence):
        return
    if sequence in seen:
        return
    record = candidate_record(
        source_row=source_row,
        sequence=sequence,
        mutations=mutations,
        operation=operation,
        family_stats=family_stats,
        reference_records=reference_records,
        max_prompt_length_delta=max_prompt_length_delta,
    )
    if not record["strict_manifold_passes"]:
        return
    seen.add(sequence)
    output.append(record)


def build_existing_motif_repairs(
    *,
    source_row: dict[str, Any],
    allowed_motifs: tuple[str, ...],
    family_stats: dict[str, Any],
    reference_records: list[dict[str, Any]],
    max_prompt_length_delta: int,
) -> list[dict[str, Any]]:
    sequence = str(source_row.get("sequence") or "").strip().upper()
    hits = motif_hits(sequence)
    if len(hits) != 1:
        return []
    hit = hits[0]
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    d_shifts = (0, -2, 2, -4, 4, -8, 8)
    h_shifts = (0, -2, 2, -4, 4)

    for motif in allowed_motifs:
        motif_mutations = motif_write_mutations(
            sequence,
            motif_start=int(hit["motif_start"]),
            motif=motif,
            reason="canonicalize_existing_motif",
        )
        add_if_valid(
            source_row=source_row,
            source_sequence=sequence,
            mutations=motif_mutations,
            operation="canonicalize_existing_motif",
            family_stats=family_stats,
            reference_records=reference_records,
            output=output,
            seen=seen,
            max_prompt_length_delta=max_prompt_length_delta,
        )
        canonical_sequence = apply_mutations(sequence, motif_mutations) if motif_mutations else sequence
        canonical_hit = motif_hits(canonical_sequence)
        if len(canonical_hit) != 1:
            continue
        serine_position = int(canonical_hit[0]["serine_position"])
        for d_shift in d_shifts:
            for h_shift in h_shifts:
                dh_mutations = dh_repair_mutations(
                    canonical_sequence,
                    serine_position=serine_position,
                    d_shift=d_shift,
                    h_shift=h_shift,
                )
                if dh_mutations is None:
                    continue
                add_if_valid(
                    source_row=source_row,
                    source_sequence=sequence,
                    mutations=motif_mutations + dh_mutations,
                    operation="canonicalize_existing_motif_repair_dh",
                    family_stats=family_stats,
                    reference_records=reference_records,
                    output=output,
                    seen=seen,
                    max_prompt_length_delta=max_prompt_length_delta,
                )
    return output


def build_motif_relocation_repairs(
    *,
    source_row: dict[str, Any],
    allowed_motifs: tuple[str, ...],
    family_stats: dict[str, Any],
    reference_records: list[dict[str, Any]],
    relocation_step: int,
    relocation_window: int,
    max_prompt_length_delta: int,
) -> list[dict[str, Any]]:
    sequence = str(source_row.get("sequence") or "").strip().upper()
    if not sequence:
        return []
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for serine_position in target_serine_positions(
        length=len(sequence),
        family_stats=family_stats,
        step=relocation_step,
        window=relocation_window,
    ):
        motif_start = serine_position - 2
        protected_starts = {motif_start}
        break_mutations = break_existing_motif_mutations(sequence, protected_starts=protected_starts)
        for motif in allowed_motifs:
            motif_mutations = motif_write_mutations(
                sequence,
                motif_start=motif_start,
                motif=motif,
                reason="write_relocated_canonical_motif",
            )
            dh_mutations = dh_repair_mutations(
                sequence,
                serine_position=serine_position,
                d_shift=0,
                h_shift=0,
            )
            if dh_mutations is None:
                continue
            add_if_valid(
                source_row=source_row,
                source_sequence=sequence,
                mutations=break_mutations + motif_mutations + dh_mutations,
                operation="relocate_motif_repair_dh",
                family_stats=family_stats,
                reference_records=reference_records,
                output=output,
                seen=seen,
                max_prompt_length_delta=max_prompt_length_delta,
            )
    return output


def row_priority(row: dict[str, Any]) -> tuple[Any, ...]:
    length_delta = abs(int(row.get("length_delta") or 0))
    return (
        int(row.get("selected") is not True),
        length_delta,
        -float(row.get("geometry_score") or 0.0),
        -float(row.get("raw_esm_score") or 0.0),
        str(row.get("sequence") or ""),
    )


def build_frontier(args: argparse.Namespace) -> dict[str, Any]:
    lanes_dir = resolved(args.lanes_dir)
    records_path = resolved(args.records_path)
    output_dir = resolved(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    allowed_motifs = tuple(
        motif.strip().upper()
        for motif in str(args.allowed_motifs).split(",")
        if motif.strip()
    )
    if not allowed_motifs:
        raise ValueError("no allowed motifs configured")

    lane_paths = {
        "geometry_valid_needs_esm": lanes_dir / "geometry_valid_needs_esm.jsonl",
        "esm_valid_needs_geometry": lanes_dir / "esm_valid_needs_geometry.jsonl",
    }
    source_rows: list[dict[str, Any]] = []
    for lane, path in lane_paths.items():
        if not path.exists():
            continue
        rows = sorted(read_jsonl(path), key=row_priority)[: int(args.max_input_per_lane)]
        source_rows.extend(rows)

    output_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_summaries: list[dict[str, Any]] = []
    rejected_existing_candidates = 0
    rejected_relocation_candidates = 0

    for source_row in source_rows:
        if len(output_rows) >= int(args.max_output_candidates):
            break
        existing_repairs = build_existing_motif_repairs(
            source_row=source_row,
            allowed_motifs=allowed_motifs,
            family_stats=family_stats,
            reference_records=reference_records,
            max_prompt_length_delta=int(args.max_prompt_length_delta),
        )
        relocation_repairs = build_motif_relocation_repairs(
            source_row=source_row,
            allowed_motifs=allowed_motifs,
            family_stats=family_stats,
            reference_records=reference_records,
            relocation_step=int(args.relocation_step),
            relocation_window=int(args.relocation_window),
            max_prompt_length_delta=int(args.max_prompt_length_delta),
        )
        accepted_existing = 0
        accepted_relocation = 0
        for row in existing_repairs + relocation_repairs:
            if len(output_rows) >= int(args.max_output_candidates):
                break
            sequence = str(row["sequence"])
            if sequence in seen:
                continue
            seen.add(sequence)
            output_rows.append(row)
            if row["operation"].startswith("canonicalize"):
                accepted_existing += 1
            else:
                accepted_relocation += 1

        rejected_existing_candidates += max(0, len(existing_repairs) - accepted_existing)
        rejected_relocation_candidates += max(0, len(relocation_repairs) - accepted_relocation)
        source_summaries.append(
            {
                "source_lane": source_row.get("lane"),
                "source_mode": source_row.get("mode"),
                "source_selected": bool(source_row.get("selected")),
                "source_length": source_row.get("length"),
                "source_length_delta": source_row.get("length_delta"),
                "accepted_existing_motif_repairs": accepted_existing,
                "accepted_relocation_repairs": accepted_relocation,
            }
        )

    trainable_rows = [row for row in output_rows if bool(row["strict_trainable_candidate"])]
    strict_path = output_dir / "strict_repair_frontier_pre_esm.jsonl"
    trainable_path = output_dir / "strict_trainable_repair_frontier_pre_esm.jsonl"
    write_jsonl(strict_path, output_rows)
    write_jsonl(trainable_path, trainable_rows)

    lane_counts = Counter(str(row.get("source_lane")) for row in output_rows)
    operation_counts = Counter(str(row.get("operation")) for row in output_rows)
    trainable_lane_counts = Counter(str(row.get("source_lane")) for row in trainable_rows)
    trainable_operation_counts = Counter(str(row.get("operation")) for row in trainable_rows)
    summary = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "lanes_dir": str(lanes_dir),
        "records_path": str(records_path),
        "output_dir": str(output_dir),
        "allowed_motifs": list(allowed_motifs),
        "config": {
            "max_input_per_lane": int(args.max_input_per_lane),
            "max_output_candidates": int(args.max_output_candidates),
            "max_prompt_length_delta": int(args.max_prompt_length_delta),
            "relocation_step": int(args.relocation_step),
            "relocation_window": int(args.relocation_window),
        },
        "input_counts": {
            "source_rows": len(source_rows),
            "geometry_valid_needs_esm": sum(
                1 for row in source_rows if row.get("lane") == "geometry_valid_needs_esm"
            ),
            "esm_valid_needs_geometry": sum(
                1 for row in source_rows if row.get("lane") == "esm_valid_needs_geometry"
            ),
        },
        "output_counts": {
            "strict_repair_frontier": len(output_rows),
            "strict_trainable_repair_frontier": len(trainable_rows),
            "strict_by_lane": dict(sorted(lane_counts.items())),
            "strict_by_operation": dict(sorted(operation_counts.items())),
            "trainable_by_lane": dict(sorted(trainable_lane_counts.items())),
            "trainable_by_operation": dict(sorted(trainable_operation_counts.items())),
            "prompt_length_ok": sum(bool(row["prompt_length_ok"]) for row in output_rows),
            "passes_core_screen": sum(bool(row["passes_core_screen"]) for row in output_rows),
            "needs_esm_score": sum(bool(row["needs_esm_score"]) for row in output_rows),
        },
        "dedupe_rejections": {
            "existing_motif_repairs": rejected_existing_candidates,
            "relocation_repairs": rejected_relocation_candidates,
        },
        "source_summaries": source_summaries,
        "outputs": {
            "strict_repair_frontier_pre_esm": str(strict_path),
            "strict_trainable_repair_frontier_pre_esm": str(trainable_path),
            "summary": str(output_dir / "repair_frontier_summary.json"),
        },
        "next_step": (
            "Score strict_trainable_repair_frontier_pre_esm.jsonl with ESM only if it is nonempty; "
            "do not launch paid Tinker work from this frontier before ESM scoring and diversity review."
        ),
    }
    Path(summary["outputs"]["summary"]).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    args = parse_args()
    print(json.dumps(build_frontier(args), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
