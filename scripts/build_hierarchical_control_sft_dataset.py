from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TIER1_TAG = "[Target: Single-Active-Site, High-Stability, Perfect-Triad]"
TIER2_TAG = "[Target: Single-Active-Site, Moderate-Stability, Partial-Triad]"
TIER3_TAG = "[Target: Single-Active-Site, High-Stability, Missing-Triad]"
TIER4_TAG = "[Target: Repeated-Motif-Scaffold, Low-Diversity]"
SER_ASP_TARGET_GAP = 55
ASP_HIS_TARGET_GAP = 13


def main() -> None:
    args = parse_args()
    positive_rows = load_jsonl(Path(args.positive_path))
    tier3_audit = json.loads(Path(args.tier3_audit_path).read_text(encoding="utf-8"))
    tier4_audit = json.loads(Path(args.tier4_audit_path).read_text(encoding="utf-8"))

    tier1_rows = [
        row for row in positive_rows
        if float(row.get("esm_score", 0.0)) >= args.tier1_min_esm
    ]
    tier2_rows = [
        row for row in positive_rows
        if float(row.get("esm_score", 0.0)) < args.tier1_min_esm
    ]

    tier1: list[dict[str, Any]] = []
    for row in tier1_rows:
        for copy_index in range(args.tier1_repeat):
            blueprint = build_blueprint_tag(row)
            tier1.append(
                {
                    "label": "tier1_perfect_triad",
                    "prompt": append_blueprint_tag(append_tag(str(row["prompt"]), TIER1_TAG), blueprint),
                    "sequence": str(row["sequence"]),
                    "source_accession": row.get("accession"),
                    "source_esm_score": row.get("esm_score"),
                    "source_best_gap_error": row.get("catalytic_geometry", {}).get("best_gap_error"),
                    "source_copy_index": copy_index,
                    "source_blueprint": blueprint,
                }
            )
    tier2 = [
        {
            "label": "tier2_partial_triad",
            "prompt": append_tag(str(row["prompt"]), TIER2_TAG),
            "sequence": str(row["sequence"]),
            "source_accession": row.get("accession"),
            "source_esm_score": row.get("esm_score"),
            "source_best_gap_error": row.get("catalytic_geometry", {}).get("best_gap_error"),
        }
        for row in tier2_rows
    ]

    tier3_pool = build_tier3_pool(
        tier3_audit,
        require_blueprint=args.tier3_require_blueprint,
    )
    tier4_pool = build_tier4_pool(
        tier4_audit,
        require_blueprint=args.tier4_require_blueprint,
        require_geometry_pass=args.tier4_require_geometry_pass,
    )

    tier3 = [
        {
            "label": "tier3_missing_triad",
            "prompt": maybe_append_blueprint(
                append_tag(str(row["prompt"]), TIER3_TAG),
                row.get("blueprint"),
            ),
            "sequence": str(row["sequence"]),
            "source_step": row["step"],
            "source_stage1_rank": row["stage1_rank"],
            "source_motif_count": row["motif_count"],
            "source_length": row["length"],
            "source_esm_gate_pass": row["esm_gate_pass"],
            "source_geometry_passes": row["geometry_passes"],
            "source_blueprint": row.get("blueprint"),
        }
        for row in tier3_pool[: args.tier3_count]
    ]
    tier4 = [
        {
            "label": "tier4_repeated_scaffold",
            "prompt": maybe_append_blueprint(
                append_tag(str(row["prompt"]), TIER4_TAG),
                row.get("blueprint"),
            ),
            "sequence": str(row["sequence"]),
            "source_step": row["step"],
            "source_stage1_rank": row["stage1_rank"],
            "source_motif_count": row["motif_count"],
            "source_length": row["length"],
            "source_geometry_passes": row["geometry_passes"],
            "source_blueprint": row.get("blueprint"),
        }
        for row in tier4_pool[: args.tier4_count]
    ]

    output_rows = tier1 + tier2 + tier3 + tier4
    write_jsonl(Path(args.output_path), output_rows)

    summary = {
        "positive_path": args.positive_path,
        "tier3_audit_path": args.tier3_audit_path,
        "tier4_audit_path": args.tier4_audit_path,
        "output_path": args.output_path,
        "tier1_count": len(tier1),
        "tier2_count": len(tier2),
        "tier3_count": len(tier3),
        "tier4_count": len(tier4),
        "tier3_pool_size": len(tier3_pool),
        "tier4_pool_size": len(tier4_pool),
        "tier1_min_esm": args.tier1_min_esm,
        "tier1_repeat": args.tier1_repeat,
        "tier3_require_blueprint": args.tier3_require_blueprint,
        "tier4_require_blueprint": args.tier4_require_blueprint,
        "tier4_require_geometry_pass": args.tier4_require_geometry_pass,
        "tags": {
            "tier1": TIER1_TAG,
            "tier2": TIER2_TAG,
            "tier3": TIER3_TAG,
            "tier4": TIER4_TAG,
        },
    }
    if args.summary_path:
        Path(args.summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a hierarchical control-tag SFT dataset")
    parser.add_argument("--positive-path", required=True)
    parser.add_argument("--tier3-audit-path", required=True)
    parser.add_argument("--tier4-audit-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path")
    parser.add_argument("--tier1-min-esm", type=float, default=85.0)
    parser.add_argument("--tier1-repeat", type=int, default=1)
    parser.add_argument("--tier3-count", type=int, default=44)
    parser.add_argument("--tier4-count", type=int, default=44)
    parser.add_argument("--tier3-require-blueprint", action="store_true")
    parser.add_argument("--tier4-require-blueprint", action="store_true")
    parser.add_argument("--tier4-require-geometry-pass", action="store_true")
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_tier3_pool(
    audit: dict[str, Any],
    require_blueprint: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in audit["records"]:
        prompt = str(record["prompt"])
        blueprint = extract_blueprint_tag_from_record(record)
        if require_blueprint and not blueprint:
            continue
        for candidate in record["candidates"]:
            if int(candidate.get("motif_count") or 0) != 1:
                continue
            if not candidate.get("esm_gate_pass"):
                continue
            if candidate.get("geometry_passes"):
                continue
            sequence = str(candidate["extracted_sequence"])
            if not sequence:
                continue
            rows.append(
                {
                    "prompt": prompt,
                    "sequence": sequence,
                    "step": record["step"],
                    "stage1_rank": int(candidate.get("stage1_rank") or 0),
                    "motif_count": int(candidate.get("motif_count") or 0),
                    "length": int(candidate.get("length") or len(sequence)),
                    "esm_gate_pass": bool(candidate.get("esm_gate_pass")),
                    "geometry_passes": bool(candidate.get("geometry_passes")),
                    "blueprint": blueprint,
                }
            )
    rows.sort(
        key=lambda row: (
            row["stage1_rank"],
            abs(row["length"] - 280),
        )
    )
    return rows


def build_tier4_pool(
    audit: dict[str, Any],
    require_blueprint: bool = False,
    require_geometry_pass: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in audit["records"]:
        prompt = str(record["prompt"])
        blueprint = extract_blueprint_tag_from_record(record)
        if require_blueprint and not blueprint:
            continue
        for candidate in record["candidates"]:
            motif_count = int(candidate.get("motif_count") or 0)
            if motif_count <= 1:
                continue
            if require_geometry_pass and not candidate.get("geometry_passes"):
                continue
            sequence = str(candidate["extracted_sequence"])
            if not sequence:
                continue
            rows.append(
                {
                    "prompt": prompt,
                    "sequence": sequence,
                    "step": record["step"],
                    "stage1_rank": int(candidate.get("stage1_rank") or 0),
                    "motif_count": motif_count,
                    "length": int(candidate.get("length") or len(sequence)),
                    "geometry_passes": bool(candidate.get("geometry_passes")),
                    "blueprint": blueprint,
                }
            )
    rows.sort(
        key=lambda row: (
            not row["geometry_passes"],
            row["stage1_rank"],
            -row["motif_count"],
            abs(row["length"] - 280),
        )
    )
    return rows


def append_tag(prompt: str, tag: str) -> str:
    stripped = prompt.strip()
    if tag in stripped:
        return stripped
    return f"{stripped}\n{tag}"


def append_blueprint_tag(prompt: str, blueprint: str) -> str:
    stripped = prompt.strip()
    if "[Blueprint:" in stripped:
        return stripped
    return f"{stripped}\n{blueprint}"


def maybe_append_blueprint(prompt: str, blueprint: str | None) -> str:
    if not blueprint:
        return prompt.strip()
    return append_blueprint_tag(prompt, blueprint)


def build_blueprint_tag(row: dict[str, Any]) -> str:
    catalytic_geometry = row.get("catalytic_geometry") or {}
    serine_hits = catalytic_geometry.get("serine_hits") or []
    aspartate_hits = catalytic_geometry.get("aspartate_hits") or []
    histidine_hits = catalytic_geometry.get("histidine_hits") or []
    serine_pos, aspartate_pos, histidine_pos = select_best_triad_positions(
        serine_hits,
        aspartate_hits,
        histidine_hits,
    )
    return f"[Blueprint: S_motif@{serine_pos}, D@{aspartate_pos}, H@{histidine_pos}]"


def extract_blueprint_tag_from_record(record: dict[str, Any]) -> str | None:
    sequence_prompt = str(record.get("sequence_prompt") or "")
    marker = "[Blueprint:"
    if marker not in sequence_prompt:
        return None
    blueprint_body = sequence_prompt.split(marker, 1)[1].split("]", 1)[0].strip()
    return f"{marker} {blueprint_body}]"


def select_best_triad_positions(
    serine_hits: list[int],
    aspartate_hits: list[int],
    histidine_hits: list[int],
) -> tuple[int, int, int]:
    best: tuple[int, int, int] | None = None
    best_error: int | None = None
    for serine_pos in serine_hits:
        for aspartate_pos in aspartate_hits:
            if aspartate_pos <= serine_pos:
                continue
            for histidine_pos in histidine_hits:
                if histidine_pos <= aspartate_pos:
                    continue
                error = abs((aspartate_pos - serine_pos) - SER_ASP_TARGET_GAP) + abs(
                    (histidine_pos - aspartate_pos) - ASP_HIS_TARGET_GAP
                )
                if best_error is None or error < best_error:
                    best = (serine_pos, aspartate_pos, histidine_pos)
                    best_error = error
    if best is None:
        raise RuntimeError("Tier 1 row is missing a valid catalytic triad ordering")
    return best


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


if __name__ == "__main__":
    main()
