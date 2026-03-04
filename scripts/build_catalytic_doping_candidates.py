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


TARGET_TAG = "[Target: Single-Active-Site, High-Stability, Perfect-Triad]"
BLUEPRINT_PATTERN = re.compile(r"\[Blueprint:\s*S_motif@(\d+),\s*D@(\d+),\s*H@(\d+)\]")


def main() -> None:
    args = parse_args()
    reference_records = load_reference_records(Path(args.records_path))
    family_stats = compute_family_stats(reference_records)
    audits = [Path(path.strip()) for path in args.audit_paths.split(",") if path.strip()]

    backbones = load_backbones(
        audit_paths=audits,
        family_stats=family_stats,
        esm_threshold=args.min_backbone_esm,
        require_family_serine_motif=args.require_family_serine_motif,
        selected_only=args.selected_only,
    )
    if args.max_backbones is not None:
        backbones = backbones[: args.max_backbones]

    survivor_rows: list[dict[str, Any]] = []
    best_attempts: list[dict[str, Any]] = []
    total_variants = 0
    geometry_variants = 0

    for backbone in backbones:
        variants = build_backbone_variants(
            backbone=backbone,
            family_stats=family_stats,
            serine_offset_radius=args.serine_offset_radius,
            residue_offset_radius=args.residue_offset_radius,
            relocate_serine=args.relocate_serine,
        )
        total_variants += variants["variant_count"]
        geometry_variants += variants["geometry_pass_count"]

        ranked_attempts = sorted(variants["variants"], key=lambda item: item["rank_key"])[: args.top_variants_per_backbone]
        for attempt in ranked_attempts:
            esm_score = get_esm2_plddt_score(attempt["sequence"])
            row = {
                "label": "catalytic_doping_candidate",
                "prompt": append_target_prompt(backbone["prompt"], backbone["blueprint_tag"]),
                "sequence": attempt["sequence"],
                "source_audit_path": backbone["source_audit_path"],
                "source_step": backbone["step"],
                "source_parent_sequence": backbone["sequence"],
                "source_parent_esm_score": backbone["raw_esm_score"],
                "source_parent_selected": backbone["selected"],
                "source_parent_has_family_serine_motif": backbone["has_family_serine_motif"],
                "source_blueprint": backbone["blueprint_tag"],
                "source_blueprint_positions": backbone["blueprint"],
                "source_serine_position": backbone["serine_position"],
                "source_strategy": attempt["strategy"],
                "source_aspartate_target": attempt["aspartate_target"],
                "source_histidine_target": attempt["histidine_target"],
                "source_mutation_count": attempt["mutation_count"],
                "source_parent_length": len(backbone["sequence"]),
                "length": len(attempt["sequence"]),
                "esm_score": esm_score,
                "geometry": attempt["geometry"],
                "motif_count": len(find_serine_motifs(attempt["sequence"])),
            }
            if attempt["geometry"]["passes"] and esm_score >= args.min_survivor_esm:
                survivor_rows.append(row)
            else:
                best_attempts.append(row)

    survivor_rows = dedupe_rows(survivor_rows)
    best_attempts = dedupe_rows(best_attempts)[: args.max_best_attempts]

    write_jsonl(Path(args.output_path), survivor_rows)
    if args.best_attempts_path:
        write_jsonl(Path(args.best_attempts_path), best_attempts)

    summary = {
        "audit_paths": [str(path) for path in audits],
        "records_path": args.records_path,
        "output_path": args.output_path,
        "best_attempts_path": args.best_attempts_path,
        "backbone_count": len(backbones),
        "total_variants": total_variants,
        "geometry_variants": geometry_variants,
        "survivor_count": len(survivor_rows),
        "best_attempt_count": len(best_attempts),
        "min_backbone_esm": args.min_backbone_esm,
        "min_survivor_esm": args.min_survivor_esm,
        "residue_offset_radius": args.residue_offset_radius,
        "top_variants_per_backbone": args.top_variants_per_backbone,
        "require_family_serine_motif": args.require_family_serine_motif,
        "selected_only": args.selected_only,
        "max_backbones": args.max_backbones,
    }
    if args.summary_path:
        Path(args.summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build catalytic-doping candidates from stable non-geometry backbones")
    parser.add_argument("--audit-paths", required=True, help="Comma-separated candidate_audit.json paths")
    parser.add_argument("--records-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path")
    parser.add_argument("--best-attempts-path")
    parser.add_argument("--min-backbone-esm", type=float, default=95.0)
    parser.add_argument("--min-survivor-esm", type=float, default=85.0)
    parser.add_argument("--serine-offset-radius", type=int, default=2)
    parser.add_argument("--residue-offset-radius", type=int, default=2)
    parser.add_argument("--top-variants-per-backbone", type=int, default=4)
    parser.add_argument("--max-best-attempts", type=int, default=100)
    parser.add_argument("--max-backbones", type=int)
    parser.add_argument("--require-family-serine-motif", action="store_true")
    parser.add_argument("--selected-only", action="store_true")
    parser.add_argument("--relocate-serine", action="store_true")
    return parser.parse_args()


def load_backbones(
    *,
    audit_paths: list[Path],
    family_stats: dict[str, Any],
    esm_threshold: float,
    require_family_serine_motif: bool,
    selected_only: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in audit_paths:
        audit = json.loads(path.read_text(encoding="utf-8"))
        for record in audit["records"]:
            blueprint = parse_blueprint(str(record.get("sequence_prompt") or ""))
            for candidate in record["candidates"]:
                if selected_only and not bool(candidate.get("selected")):
                    continue
                if int(candidate.get("motif_count") or 0) != 1:
                    continue
                if bool(candidate.get("geometry_passes")):
                    continue
                raw_esm = float(candidate.get("raw_esm_score") or 0.0)
                if raw_esm < esm_threshold:
                    continue
                sequence = str(candidate.get("extracted_sequence") or "")
                if not sequence:
                    continue
                motif_hit = find_single_motif_hit(sequence)
                if motif_hit is None:
                    continue
                has_family_serine_motif = bool(candidate.get("has_family_serine_motif"))
                if require_family_serine_motif and not has_family_serine_motif:
                    continue
                effective_blueprint = blueprint or infer_blueprint(len(sequence), family_stats)
                rows.append(
                    {
                        "source_audit_path": str(path),
                        "step": record["step"],
                        "prompt": str(record["prompt"]),
                        "sequence": sequence,
                        "selected": bool(candidate.get("selected")),
                        "raw_esm_score": raw_esm,
                        "has_family_serine_motif": has_family_serine_motif,
                        "blueprint": effective_blueprint,
                        "blueprint_tag": format_blueprint(*effective_blueprint),
                        "serine_position": motif_hit["serine_position"],
                    }
                )
    rows.sort(
        key=lambda row: (
            -float(row["raw_esm_score"]),
            0 if row["has_family_serine_motif"] else 1,
            0 if row["selected"] else 1,
        )
    )
    return dedupe_backbones(rows)


def build_backbone_variants(
    *,
    backbone: dict[str, Any],
    family_stats: dict[str, Any],
    serine_offset_radius: int,
    residue_offset_radius: int,
    relocate_serine: bool,
) -> dict[str, Any]:
    blueprint = backbone["blueprint"]
    serine_position = backbone["serine_position"]
    variants: list[dict[str, Any]] = []
    seen_sequences: set[str] = set()
    variant_count = 0
    geometry_pass_count = 0
    base_variants = [(backbone["sequence"], serine_position, "parent_anchor")]
    if relocate_serine:
        base_variants.extend(
            build_relocated_serine_variants(
                backbone=backbone,
                family_stats=family_stats,
                serine_offset_radius=serine_offset_radius,
            )
        )

    for base_sequence, effective_serine_position, base_strategy in base_variants:
        for strategy_name, aspartate_target, histidine_target in iter_target_pairs(
            blueprint=blueprint,
            serine_position=effective_serine_position,
            residue_offset_radius=residue_offset_radius,
        ):
            if not (1 <= aspartate_target <= len(base_sequence)):
                continue
            if not (1 <= histidine_target <= len(base_sequence)):
                continue
            if not (effective_serine_position < aspartate_target < histidine_target):
                continue
            mutated = mutate_sequence(
                base_sequence,
                {
                    aspartate_target: "D",
                    histidine_target: "H",
                },
            )
            variant_count += 1
            if mutated in seen_sequences:
                continue
            seen_sequences.add(mutated)
            if len(find_serine_motifs(mutated)) != 1:
                continue
            geometry = assess_catalytic_geometry(mutated, family_stats)
            if geometry["passes"]:
                geometry_pass_count += 1
            variants.append(
                {
                    "sequence": mutated,
                    "strategy": f"{base_strategy}+{strategy_name}",
                    "aspartate_target": aspartate_target,
                    "histidine_target": histidine_target,
                    "geometry": geometry,
                    "mutation_count": count_mutations(backbone["sequence"], mutated),
                    "rank_key": rank_key(
                        backbone["blueprint"],
                        geometry,
                        aspartate_target,
                        histidine_target,
                    ),
                }
            )

    return {
        "variant_count": variant_count,
        "geometry_pass_count": geometry_pass_count,
        "variants": variants,
    }


def build_relocated_serine_variants(
    *,
    backbone: dict[str, Any],
    family_stats: dict[str, Any],
    serine_offset_radius: int,
) -> list[tuple[str, int, str]]:
    blueprint_serine, _, _ = backbone["blueprint"]
    sequence = backbone["sequence"]
    neutralized = neutralize_motif(sequence=sequence, serine_position=backbone["serine_position"])
    motif_library = family_stats["top_serine_motifs"][:4] or ["GYSQG", "GYSLG"]
    variants: list[tuple[str, int, str]] = []
    seen: set[tuple[str, int]] = set()
    for motif in motif_library:
        for delta in range(-serine_offset_radius, serine_offset_radius + 1):
            serine_target = blueprint_serine + delta
            if not motif_fits(sequence_length=len(sequence), serine_position=serine_target):
                continue
            key = (motif, serine_target)
            if key in seen:
                continue
            seen.add(key)
            implanted = implant_motif(
                sequence=neutralized,
                serine_position=serine_target,
                motif=motif,
            )
            if len(find_serine_motifs(implanted)) != 1:
                continue
            variants.append((implanted, serine_target, f"relocate:{motif}:{serine_target}"))
    return variants


def parse_blueprint(sequence_prompt: str) -> tuple[int, int, int] | None:
    match = BLUEPRINT_PATTERN.search(sequence_prompt)
    if not match:
        return None
    return tuple(int(group) for group in match.groups())


def infer_blueprint(sequence_length: int, family_stats: dict[str, Any]) -> tuple[int, int, int]:
    ser_min, ser_max = family_stats["serine_position_range"]
    asp_min, asp_max = family_stats["aspartate_position_range"]
    his_min, his_max = family_stats["histidine_position_range"]
    ser = clamp_position(round(sequence_length * ((ser_min + ser_max) / 2.0)), sequence_length)
    asp = clamp_position(round(sequence_length * ((asp_min + asp_max) / 2.0)), sequence_length)
    his = clamp_position(round(sequence_length * ((his_min + his_max) / 2.0)), sequence_length)
    if asp <= ser:
        asp = clamp_position(ser + SER_ASP_TARGET_GAP, sequence_length)
    if his <= asp:
        his = clamp_position(asp + ASP_HIS_TARGET_GAP, sequence_length)
    return ser, asp, his


def format_blueprint(serine_position: int, aspartate_position: int, histidine_position: int) -> str:
    return f"[Blueprint: S_motif@{serine_position}, D@{aspartate_position}, H@{histidine_position}]"


def append_target_prompt(prompt: str, blueprint_tag: str) -> str:
    stripped = prompt.strip()
    if TARGET_TAG not in stripped:
        stripped = f"{stripped}\n{TARGET_TAG}"
    if "[Blueprint:" not in stripped:
        stripped = f"{stripped}\n{blueprint_tag}"
    return stripped


def clamp_position(position: int, sequence_length: int) -> int:
    return max(1, min(sequence_length, position))


def find_single_motif_hit(sequence: str) -> dict[str, int] | None:
    hits: list[dict[str, int]] = []
    for motif_start in range(len(sequence) - 4):
        motif = sequence[motif_start : motif_start + 5]
        if SERINE_MOTIF_PATTERN.fullmatch(motif):
            hits.append(
                {
                    "motif_start": motif_start,
                    "serine_position": motif_start + 3,
                }
            )
    if len(hits) != 1:
        return None
    return hits[0]


def neutralize_motif(*, sequence: str, serine_position: int) -> str:
    chars = list(sequence)
    chars[serine_position - 1] = "A"
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
    serine_position: int,
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
                    serine_position + SER_ASP_TARGET_GAP + d_delta,
                    serine_position + SER_ASP_TARGET_GAP + ASP_HIS_TARGET_GAP + h_delta,
                ),
                (
                    "blueprint_relative_anchor",
                    serine_position + (blueprint_aspartate - blueprint_serine) + d_delta,
                    serine_position + (blueprint_histidine - blueprint_serine) + h_delta,
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


def rank_key(
    blueprint: tuple[int, int, int],
    geometry: dict[str, Any],
    aspartate_target: int,
    histidine_target: int,
) -> tuple[int, int, int, int]:
    _, blueprint_aspartate, blueprint_histidine = blueprint
    best_gap_error = geometry.get("best_gap_error")
    return (
        0 if geometry["passes"] else 1,
        0 if geometry["ser_asp_dyad_passes"] else 1,
        0 if geometry["ser_his_dyad_passes"] else 1,
        abs(aspartate_target - blueprint_aspartate) + abs(histidine_target - blueprint_histidine),
        int(best_gap_error) if isinstance(best_gap_error, int) else 999,
    )


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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


if __name__ == "__main__":
    main()
