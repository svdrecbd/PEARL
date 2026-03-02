from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_proxy import get_esm2_plddt_score
from petase_family import (
    ASP_HIS_TARGET_GAP,
    SER_ASP_TARGET_GAP,
    SERINE_MOTIF_PATTERN,
    assess_catalytic_geometry,
    compute_family_stats,
    find_serine_motifs,
    load_reference_records,
)


TIER5_TAG = "[Target: Single-Active-Site, Blueprint, Perfect-Triad]"
BLUEPRINT_PATTERN = re.compile(r"\[Blueprint:\s*S_motif@(\d+),\s*D@(\d+),\s*H@(\d+)\]")


def main() -> None:
    args = parse_args()
    audit = json.loads(Path(args.audit_path).read_text(encoding="utf-8"))
    reference_records = load_reference_records(Path(args.records_path))
    family_stats = compute_family_stats(reference_records)
    motif_library = family_stats["top_serine_motifs"][: args.motif_count]
    backbones = load_backbones(audit)

    output_rows: list[dict[str, Any]] = []
    total_variants = 0
    geometry_pass_variants = 0
    esm_evaluated_variants = 0

    for backbone in backbones:
        variants = build_backbone_variants(
            backbone=backbone,
            motif_library=motif_library,
            family_stats=family_stats,
            serine_offset_radius=args.serine_offset_radius,
            residue_offset_radius=args.residue_offset_radius,
            top_variants_per_backbone=args.top_variants_per_backbone,
        )
        total_variants += variants["variant_count"]
        geometry_pass_variants += variants["geometry_pass_count"]
        for candidate in variants["ranked_variants"]:
            esm_evaluated_variants += 1
            esm_score = get_esm2_plddt_score(candidate["sequence"])
            if esm_score < args.esm_threshold:
                continue
            output_rows.append(
                {
                    "label": "tier5_relocated_bridge",
                    "prompt": append_target_prompt(
                        prompt=backbone["prompt"],
                        target_tag=TIER5_TAG,
                        blueprint_tag=backbone["blueprint_tag"],
                    ),
                    "sequence": candidate["sequence"],
                    "esm_score": esm_score,
                    "source_step": backbone["step"],
                    "source_parent_esm_score": backbone["raw_esm_score"],
                    "source_blueprint": backbone["blueprint_tag"],
                    "source_blueprint_positions": backbone["blueprint"],
                    "source_parent_sequence": backbone["sequence"],
                    "source_parent_serine_position": backbone["serine_position"],
                    "source_original_motif": backbone["motif"],
                    "source_implanted_motif": candidate["motif"],
                    "source_strategy": candidate["strategy"],
                    "source_serine_target": candidate["serine_target"],
                    "source_aspartate_target": candidate["aspartate_target"],
                    "source_histidine_target": candidate["histidine_target"],
                    "source_mutation_count": candidate["mutation_count"],
                    "geometry": candidate["geometry"],
                }
            )

    output_rows = dedupe_rows(output_rows)
    write_jsonl(Path(args.output_path), output_rows)
    summary = {
        "audit_path": args.audit_path,
        "records_path": args.records_path,
        "output_path": args.output_path,
        "backbone_count": len(backbones),
        "motif_library": motif_library,
        "total_variants": total_variants,
        "geometry_pass_variants": geometry_pass_variants,
        "esm_evaluated_variants": esm_evaluated_variants,
        "survivor_count": len(output_rows),
        "esm_threshold": args.esm_threshold,
        "serine_offset_radius": args.serine_offset_radius,
        "residue_offset_radius": args.residue_offset_radius,
        "top_variants_per_backbone": args.top_variants_per_backbone,
    }
    if args.summary_path:
        Path(args.summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a synthetic relocation bridge set from stable single-motif backbones")
    parser.add_argument("--audit-path", required=True)
    parser.add_argument("--records-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path")
    parser.add_argument("--esm-threshold", type=float, default=85.0)
    parser.add_argument("--motif-count", type=int, default=4)
    parser.add_argument("--serine-offset-radius", type=int, default=2)
    parser.add_argument("--residue-offset-radius", type=int, default=2)
    parser.add_argument("--top-variants-per-backbone", type=int, default=4)
    return parser.parse_args()


def load_backbones(audit: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in audit["records"]:
        blueprint = parse_blueprint(str(record.get("sequence_prompt") or ""))
        if blueprint is None:
            continue
        for candidate in record["candidates"]:
            if int(candidate.get("motif_count") or 0) != 1:
                continue
            if not candidate.get("esm_gate_pass"):
                continue
            sequence = str(candidate.get("extracted_sequence") or "")
            if not sequence:
                continue
            motif_hit = find_single_motif_hit(sequence)
            if motif_hit is None:
                continue
            rows.append(
                {
                    "step": record["step"],
                    "prompt": str(record["prompt"]),
                    "sequence": sequence,
                    "raw_esm_score": float(candidate.get("raw_esm_score") or 0.0),
                    "blueprint": blueprint,
                    "blueprint_tag": format_blueprint(*blueprint),
                    "motif": motif_hit["motif"],
                    "motif_start": motif_hit["motif_start"],
                    "serine_position": motif_hit["serine_position"],
                }
            )
    return dedupe_backbones(rows)


def build_backbone_variants(
    *,
    backbone: dict[str, Any],
    motif_library: list[str],
    family_stats: dict[str, Any],
    serine_offset_radius: int,
    residue_offset_radius: int,
    top_variants_per_backbone: int,
) -> dict[str, Any]:
    blueprint_serine, blueprint_aspartate, blueprint_histidine = backbone["blueprint"]
    neutralized = neutralize_motif(
        sequence=backbone["sequence"],
        motif_start=backbone["motif_start"],
    )
    variants: list[dict[str, Any]] = []
    variant_count = 0
    geometry_pass_count = 0
    seen_sequences: set[str] = set()

    for motif_index, motif in enumerate(motif_library):
        for serine_delta in range(-serine_offset_radius, serine_offset_radius + 1):
            serine_target = blueprint_serine + serine_delta
            if not motif_fits(sequence_length=len(neutralized), serine_position=serine_target):
                continue
            motif_implanted = implant_motif(
                sequence=neutralized,
                serine_position=serine_target,
                motif=motif,
            )
            for strategy_name, aspartate_target, histidine_target in iter_target_pairs(
                blueprint=backbone["blueprint"],
                serine_target=serine_target,
                residue_offset_radius=residue_offset_radius,
            ):
                if not (1 <= aspartate_target <= len(motif_implanted)):
                    continue
                if not (1 <= histidine_target <= len(motif_implanted)):
                    continue
                if not (serine_target < aspartate_target < histidine_target):
                    continue
                candidate_sequence = mutate_sequence(
                    motif_implanted,
                    {
                        aspartate_target: "D",
                        histidine_target: "H",
                    },
                )
                variant_count += 1
                if candidate_sequence in seen_sequences:
                    continue
                seen_sequences.add(candidate_sequence)
                if len(find_serine_motifs(candidate_sequence)) != 1:
                    continue
                geometry = assess_catalytic_geometry(candidate_sequence, family_stats)
                if not geometry["passes"]:
                    continue
                geometry_pass_count += 1
                mutation_count = count_mutations(backbone["sequence"], candidate_sequence)
                variants.append(
                    {
                        "sequence": candidate_sequence,
                        "motif": motif,
                        "strategy": strategy_name,
                        "serine_target": serine_target,
                        "aspartate_target": aspartate_target,
                        "histidine_target": histidine_target,
                        "geometry": geometry,
                        "mutation_count": mutation_count,
                        "rank_key": (
                            mutation_count,
                            abs(serine_target - blueprint_serine),
                            abs(aspartate_target - blueprint_aspartate)
                            + abs(histidine_target - blueprint_histidine),
                            motif_index,
                            strategy_rank(strategy_name),
                            int(geometry["best_gap_error"]) if isinstance(geometry["best_gap_error"], int) else 999,
                        ),
                    }
                )

    variants.sort(key=lambda row: row["rank_key"])
    return {
        "variant_count": variant_count,
        "geometry_pass_count": geometry_pass_count,
        "ranked_variants": variants[:top_variants_per_backbone],
    }


def parse_blueprint(sequence_prompt: str) -> tuple[int, int, int] | None:
    match = BLUEPRINT_PATTERN.search(sequence_prompt)
    if not match:
        return None
    return tuple(int(group) for group in match.groups())


def format_blueprint(serine_position: int, aspartate_position: int, histidine_position: int) -> str:
    return f"[Blueprint: S_motif@{serine_position}, D@{aspartate_position}, H@{histidine_position}]"


def find_single_motif_hit(sequence: str) -> dict[str, Any] | None:
    hits: list[dict[str, Any]] = []
    for motif_start in range(len(sequence) - 4):
        motif = sequence[motif_start : motif_start + 5]
        if SERINE_MOTIF_PATTERN.fullmatch(motif):
            hits.append(
                {
                    "motif": motif,
                    "motif_start": motif_start,
                    "serine_position": motif_start + 3,
                }
            )
    if len(hits) != 1:
        return None
    return hits[0]


def neutralize_motif(*, sequence: str, motif_start: int) -> str:
    chars = list(sequence)
    chars[motif_start + 2] = "A"
    return "".join(chars)


def motif_fits(*, sequence_length: int, serine_position: int) -> bool:
    return 3 <= serine_position <= sequence_length - 2


def implant_motif(*, sequence: str, serine_position: int, motif: str) -> str:
    chars = list(sequence)
    start = serine_position - 3
    chars[start : start + 5] = list(motif)
    return "".join(chars)


def iter_target_pairs(
    *,
    blueprint: tuple[int, int, int],
    serine_target: int,
    residue_offset_radius: int,
) -> list[tuple[str, int, int]]:
    blueprint_serine, blueprint_aspartate, blueprint_histidine = blueprint
    pairs: list[tuple[str, int, int]] = []
    seen: set[tuple[str, int, int]] = set()
    for d_delta in range(-residue_offset_radius, residue_offset_radius + 1):
        for h_delta in range(-residue_offset_radius, residue_offset_radius + 1):
            options = [
                (
                    "blueprint_anchor",
                    blueprint_aspartate + d_delta,
                    blueprint_histidine + h_delta,
                ),
                (
                    "serine_gap_anchor",
                    serine_target + SER_ASP_TARGET_GAP + d_delta,
                    serine_target + SER_ASP_TARGET_GAP + ASP_HIS_TARGET_GAP + h_delta,
                ),
                (
                    "blueprint_relative_anchor",
                    serine_target + (blueprint_aspartate - blueprint_serine) + d_delta,
                    serine_target + (blueprint_histidine - blueprint_serine) + h_delta,
                ),
            ]
            for option in options:
                if option in seen:
                    continue
                seen.add(option)
                pairs.append(option)
    return pairs


def mutate_sequence(sequence: str, replacements: dict[int, str]) -> str:
    chars = list(sequence)
    for position, residue in replacements.items():
        chars[position - 1] = residue
    return "".join(chars)


def count_mutations(original: str, mutated: str) -> int:
    return sum(left != right for left, right in zip(original, mutated))


def strategy_rank(strategy_name: str) -> int:
    ranks = {
        "blueprint_anchor": 0,
        "blueprint_relative_anchor": 1,
        "serine_gap_anchor": 2,
    }
    return ranks.get(strategy_name, 9)


def append_target_prompt(*, prompt: str, target_tag: str, blueprint_tag: str) -> str:
    stripped = prompt.strip()
    if target_tag not in stripped:
        stripped = f"{stripped}\n{target_tag}"
    if "[Blueprint:" not in stripped:
        stripped = f"{stripped}\n{blueprint_tag}"
    return stripped


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_sequences: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in sorted(
        rows,
        key=lambda item: (
            -float(item["esm_score"]),
            int(item["source_mutation_count"]),
        ),
    ):
        sequence = str(row["sequence"])
        if sequence in seen_sequences:
            continue
        seen_sequences.add(sequence)
        deduped.append(row)
    return deduped


def dedupe_backbones(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_sequences: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        sequence = str(row["sequence"])
        if sequence in seen_sequences:
            continue
        seen_sequences.add(sequence)
        deduped.append(row)
    return deduped


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


if __name__ == "__main__":
    main()
