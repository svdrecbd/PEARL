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


PARTIAL_TAG = "[Target: Single-Active-Site, Blueprint, Partial-Triad]"
FULL_TAG = "[Target: Single-Active-Site, Blueprint, Perfect-Triad]"
BLUEPRINT_PATTERN = re.compile(r"\[Blueprint:\s*S_motif@(\d+),\s*D@(\d+),\s*H@(\d+)\]")


def main() -> None:
    args = parse_args()
    audit = json.loads(Path(args.audit_path).read_text(encoding="utf-8"))
    reference_records = load_reference_records(Path(args.records_path))
    family_stats = compute_family_stats(reference_records)

    backbone_rows = load_backbones(audit)
    synthetic_rows: list[dict[str, Any]] = []
    variant_count = 0
    bridge_variant_count = 0

    for backbone in backbone_rows:
        sequence = backbone["sequence"]
        motif_positions = find_serine_positions(sequence)
        if len(motif_positions) != 1:
            continue
        serine_pos = motif_positions[0]
        blueprint = backbone["blueprint"]
        candidate_variants: dict[str, dict[str, Any]] = {}
        for strategy_name, d_pos, h_pos in iter_target_pairs(
            blueprint=blueprint,
            serine_pos=serine_pos,
            sequence_length=len(sequence),
            offset_radius=args.offset_radius,
        ):
            if not (1 <= d_pos <= len(sequence) and 1 <= h_pos <= len(sequence)):
                continue
            if d_pos <= serine_pos or h_pos <= d_pos:
                continue
            variant = mutate_sequence(sequence, {d_pos: "D", h_pos: "H"})
            if variant == sequence:
                variant_key = f"{strategy_name}:{d_pos}:{h_pos}:noop"
            else:
                variant_key = f"{strategy_name}:{d_pos}:{h_pos}"
            if variant_key in candidate_variants:
                continue
            variant_count += 1
            motif_count = len(find_serine_motifs(variant))
            if motif_count != 1:
                continue
            geometry = assess_catalytic_geometry(variant, family_stats)
            if not (
                geometry["passes"]
                or geometry["ser_asp_dyad_passes"]
                or geometry["ser_his_dyad_passes"]
            ):
                continue
            bridge_variant_count += 1
            candidate_variants[variant_key] = {
                "sequence": variant,
                "strategy": strategy_name,
                "d_position": d_pos,
                "h_position": h_pos,
                "motif_count": motif_count,
                "geometry": geometry,
                "quality_key": rank_key(geometry),
            }

        ranked_variants = sorted(
            candidate_variants.values(),
            key=lambda row: row["quality_key"],
        )[: args.top_variants_per_backbone]
        for variant in ranked_variants:
            esm_score = get_esm2_plddt_score(variant["sequence"])
            if esm_score < args.esm_threshold:
                continue
            geometry = variant["geometry"]
            label = "tier5_synthetic_full_triad" if geometry["passes"] else "tier5_synthetic_partial_triad"
            target_tag = FULL_TAG if geometry["passes"] else PARTIAL_TAG
            synthetic_rows.append(
                {
                    "label": label,
                    "prompt": append_blueprint_prompt(
                        prompt=backbone["prompt"],
                        target_tag=target_tag,
                        blueprint_tag=backbone["blueprint_tag"],
                    ),
                    "sequence": variant["sequence"],
                    "source_step": backbone["step"],
                    "source_strategy": variant["strategy"],
                    "source_parent_esm_score": backbone["raw_esm_score"],
                    "esm_score": esm_score,
                    "motif_count": variant["motif_count"],
                    "length": len(variant["sequence"]),
                    "geometry": geometry,
                    "source_blueprint": backbone["blueprint_tag"],
                    "source_serine_position": serine_pos,
                    "source_blueprint_positions": backbone["blueprint"],
                    "source_parent_sequence": sequence,
                }
            )

    synthetic_rows = dedupe_rows(synthetic_rows)
    write_jsonl(Path(args.output_path), synthetic_rows)

    summary = {
        "audit_path": args.audit_path,
        "records_path": args.records_path,
        "output_path": args.output_path,
        "backbone_count": len(backbone_rows),
        "variant_count": variant_count,
        "bridge_variant_count": bridge_variant_count,
        "synthetic_row_count": len(synthetic_rows),
        "synthetic_full_triad_count": sum(row["geometry"]["passes"] for row in synthetic_rows),
        "synthetic_partial_only_count": sum(not row["geometry"]["passes"] for row in synthetic_rows),
        "esm_threshold": args.esm_threshold,
        "offset_radius": args.offset_radius,
        "top_variants_per_backbone": args.top_variants_per_backbone,
    }
    if args.summary_path:
        Path(args.summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a synthetic Tier 5 bridge set from blueprint-conditioned audits")
    parser.add_argument("--audit-path", required=True)
    parser.add_argument("--records-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path")
    parser.add_argument("--esm-threshold", type=float, default=85.0)
    parser.add_argument("--offset-radius", type=int, default=2)
    parser.add_argument("--top-variants-per-backbone", type=int, default=3)
    return parser.parse_args()


def load_backbones(audit: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in audit["records"]:
        blueprint = parse_blueprint(record.get("sequence_prompt") or "")
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
            rows.append(
                {
                    "step": record["step"],
                    "prompt": str(record["prompt"]),
                    "sequence": sequence,
                    "raw_esm_score": float(candidate.get("raw_esm_score") or 0.0),
                    "blueprint": blueprint,
                    "blueprint_tag": format_blueprint(*blueprint),
                }
            )
    return dedupe_backbones(rows)


def parse_blueprint(sequence_prompt: str) -> tuple[int, int, int] | None:
    match = BLUEPRINT_PATTERN.search(sequence_prompt)
    if not match:
        return None
    return tuple(int(group) for group in match.groups())


def format_blueprint(serine_pos: int, aspartate_pos: int, histidine_pos: int) -> str:
    return f"[Blueprint: S_motif@{serine_pos}, D@{aspartate_pos}, H@{histidine_pos}]"


def append_blueprint_prompt(prompt: str, target_tag: str, blueprint_tag: str) -> str:
    stripped = prompt.strip()
    if "[Target:" not in stripped:
        stripped = f"{stripped}\n{target_tag}"
    elif target_tag not in stripped:
        stripped = f"{stripped}\n{target_tag}"
    if "[Blueprint:" not in stripped:
        stripped = f"{stripped}\n{blueprint_tag}"
    return stripped


def find_serine_positions(sequence: str) -> list[int]:
    positions: list[int] = []
    for index in range(len(sequence) - 4):
        if SERINE_MOTIF_PATTERN.fullmatch(sequence[index : index + 5]):
            positions.append(index + 3)
    return positions


def iter_target_pairs(
    *,
    blueprint: tuple[int, int, int],
    serine_pos: int,
    sequence_length: int,
    offset_radius: int,
) -> list[tuple[str, int, int]]:
    blueprint_serine, blueprint_aspartate, blueprint_histidine = blueprint
    pairs: list[tuple[str, int, int]] = []
    for d_offset in range(-offset_radius, offset_radius + 1):
        for h_offset in range(-offset_radius, offset_radius + 1):
            pairs.append(("blueprint_anchor", blueprint_aspartate + d_offset, blueprint_histidine + h_offset))
            serine_anchored_d = serine_pos + SER_ASP_TARGET_GAP + d_offset
            serine_anchored_h = serine_pos + SER_ASP_TARGET_GAP + ASP_HIS_TARGET_GAP + h_offset
            pairs.append(("serine_gap_anchor", serine_anchored_d, serine_anchored_h))
            blueprint_relative_d = max(1, serine_pos + (blueprint_aspartate - blueprint_serine) + d_offset)
            blueprint_relative_h = max(1, serine_pos + (blueprint_histidine - blueprint_serine) + h_offset)
            pairs.append(("blueprint_relative_anchor", blueprint_relative_d, blueprint_relative_h))
    filtered_pairs: list[tuple[str, int, int]] = []
    seen: set[tuple[str, int, int]] = set()
    for strategy_name, d_pos, h_pos in pairs:
        if not (1 <= d_pos <= sequence_length and 1 <= h_pos <= sequence_length):
            continue
        key = (strategy_name, d_pos, h_pos)
        if key in seen:
            continue
        seen.add(key)
        filtered_pairs.append(key)
    return filtered_pairs


def mutate_sequence(sequence: str, replacements: dict[int, str]) -> str:
    chars = list(sequence)
    for position, residue in replacements.items():
        chars[position - 1] = residue
    return "".join(chars)


def rank_key(geometry: dict[str, Any]) -> tuple[int, int, int, int]:
    best_gap_error = geometry.get("best_gap_error")
    return (
        0 if geometry["passes"] else 1,
        0 if geometry["ser_asp_dyad_passes"] else 1,
        0 if geometry["ser_his_dyad_passes"] else 1,
        int(best_gap_error) if isinstance(best_gap_error, int) else 999,
    )


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_sequences: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in sorted(
        rows,
        key=lambda item: (
            0 if item["geometry"]["passes"] else 1,
            -(item["esm_score"]),
            item["length"],
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
        sequence = row["sequence"]
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
