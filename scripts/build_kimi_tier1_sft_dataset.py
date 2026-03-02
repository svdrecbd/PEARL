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

from scripts.build_hierarchical_control_sft_dataset import build_blueprint_tag


TIER1_TAG = "[Target: Single-Active-Site, High-Stability, Perfect-Triad]"
TIER4_TAG = "[Target: Repeated-Motif-Scaffold, Low-Diversity]"
BLUEPRINT_PATTERN = re.compile(r"\[Blueprint:\s*S_motif@\d+,\s*D@\d+,\s*H@\d+\]")


def main() -> None:
    args = parse_args()
    perfect_rows = load_jsonl(Path(args.perfect_path))
    relocation_rows = load_jsonl(Path(args.relocation_path))
    negative_rows = (
        json.loads(Path(args.negative_audit_path).read_text(encoding="utf-8"))
        if args.negative_audit_path
        else None
    )

    tier1_perfect = build_perfect_rows(perfect_rows)
    tier1_relocation = build_relocation_rows(
        relocation_rows,
        max_rows=args.max_relocation,
        max_per_parent=args.max_relocation_per_parent,
    )
    tier4_negative = build_negative_rows(
        negative_rows,
        max_rows=args.max_negative,
    ) if negative_rows is not None else []

    output_rows = tier1_perfect + tier1_relocation + tier4_negative
    write_jsonl(Path(args.output_path), output_rows)

    summary = {
        "perfect_path": args.perfect_path,
        "relocation_path": args.relocation_path,
        "output_path": args.output_path,
        "perfect_count": len(tier1_perfect),
        "relocation_pool_count": len(relocation_rows),
        "relocation_selected_count": len(tier1_relocation),
        "negative_audit_path": args.negative_audit_path,
        "negative_selected_count": len(tier4_negative),
        "total_count": len(output_rows),
        "max_relocation": args.max_relocation,
        "max_relocation_per_parent": args.max_relocation_per_parent,
        "max_negative": args.max_negative,
    }
    if args.summary_path:
        Path(args.summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a lean Tier 1 SFT dataset for Kimi")
    parser.add_argument("--perfect-path", required=True)
    parser.add_argument("--relocation-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path")
    parser.add_argument("--max-relocation", type=int, default=192)
    parser.add_argument("--max-relocation-per-parent", type=int, default=2)
    parser.add_argument("--negative-audit-path")
    parser.add_argument("--max-negative", type=int, default=0)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_perfect_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [row for row in rows if float(row.get("esm_score", 0.0)) >= 85.0]
    output_rows: list[dict[str, Any]] = []
    for row in selected:
        blueprint_tag = build_blueprint_tag(row)
        output_rows.append(
            {
                "label": "kimi_tier1_perfect_wildtype",
                "prompt": append_tier1_prompt(str(row["prompt"]), blueprint_tag),
                "sequence": str(row["sequence"]),
                "accession": row.get("accession"),
                "esm_score": row.get("esm_score"),
                "source_kind": "perfect_wildtype",
                "source_blueprint": blueprint_tag,
            }
        )
    return output_rows


def build_relocation_rows(
    rows: list[dict[str, Any]],
    *,
    max_rows: int,
    max_per_parent: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    parent_counts: dict[str, int] = {}
    for row in sorted(
        rows,
        key=lambda item: (
            -float(item.get("esm_score", 0.0)),
            int(item.get("source_mutation_count", 999)),
            int((item.get("geometry") or {}).get("best_gap_error") or 999),
        ),
    ):
        parent_sequence = str(row.get("source_parent_sequence") or "")
        if parent_counts.get(parent_sequence, 0) >= max_per_parent:
            continue
        parent_counts[parent_sequence] = parent_counts.get(parent_sequence, 0) + 1
        blueprint_tag = extract_or_build_blueprint(str(row["prompt"]), str(row.get("source_blueprint") or ""))
        selected.append(
            {
                "label": "kimi_tier1_relocation_positive",
                "prompt": append_tier1_prompt(str(row["prompt"]), blueprint_tag),
                "sequence": str(row["sequence"]),
                "esm_score": row.get("esm_score"),
                "source_kind": "relocation_positive",
                "source_parent_esm_score": row.get("source_parent_esm_score"),
                "source_mutation_count": row.get("source_mutation_count"),
                "source_blueprint": blueprint_tag,
            }
        )
        if len(selected) >= max_rows:
            break
    return selected


def build_negative_rows(
    audit: dict[str, Any],
    *,
    max_rows: int,
) -> list[dict[str, Any]]:
    if max_rows <= 0:
        return []
    rows: list[dict[str, Any]] = []
    for record in audit["records"]:
        blueprint_tag = extract_or_build_blueprint(
            str(record.get("sequence_prompt") or ""),
            "",
        )
        for candidate in record["candidates"]:
            motif_count = int(candidate.get("motif_count") or 0)
            if motif_count <= 1:
                continue
            sequence = str(candidate.get("extracted_sequence") or "")
            if not sequence:
                continue
            rows.append(
                {
                    "label": "kimi_tier4_negative",
                    "prompt": append_negative_prompt(str(record["prompt"]), blueprint_tag),
                    "sequence": sequence,
                    "source_kind": "kimi_motif_spam_negative",
                    "source_step": record["step"],
                    "source_stage1_rank": int(candidate.get("stage1_rank") or 0),
                    "source_motif_count": motif_count,
                    "source_geometry_passes": bool(candidate.get("geometry_passes")),
                    "source_template_penalty": float(candidate.get("template_penalty") or 0.0),
                }
            )
    rows.sort(
        key=lambda item: (
            not bool(item["source_geometry_passes"]),
            -int(item["source_motif_count"]),
            int(item["source_stage1_rank"]),
        )
    )
    return rows[:max_rows]


def append_tier1_prompt(prompt: str, blueprint_tag: str) -> str:
    stripped = prompt.strip()
    stripped = BLUEPRINT_PATTERN.sub("", stripped).strip()
    stripped = re.sub(r"\[Target:[^\]]+\]", "", stripped).strip()
    stripped = "\n".join(line for line in stripped.splitlines() if line.strip())
    stripped = f"{stripped}\n{TIER1_TAG}"
    if blueprint_tag and "[Blueprint:" not in stripped:
        stripped = f"{stripped}\n{blueprint_tag}"
    return stripped


def append_negative_prompt(prompt: str, blueprint_tag: str) -> str:
    stripped = prompt.strip()
    stripped = BLUEPRINT_PATTERN.sub("", stripped).strip()
    stripped = re.sub(r"\[Target:[^\]]+\]", "", stripped).strip()
    stripped = "\n".join(line for line in stripped.splitlines() if line.strip())
    stripped = f"{stripped}\n{TIER4_TAG}"
    if blueprint_tag and "[Blueprint:" not in stripped:
        stripped = f"{stripped}\n{blueprint_tag}"
    return stripped


def extract_or_build_blueprint(prompt: str, fallback_blueprint: str) -> str:
    match = BLUEPRINT_PATTERN.search(prompt)
    if match:
        return match.group(0)
    return fallback_blueprint


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


if __name__ == "__main__":
    main()
