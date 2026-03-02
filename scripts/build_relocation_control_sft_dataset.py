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

from petase_family import SERINE_MOTIF_PATTERN


WRONG_SERINE_TAG = "[Target: Single-Active-Site, Wrong-Serine-Position]"
BLUEPRINT_PATTERN = re.compile(r"\[Blueprint:\s*S_motif@(\d+),\s*D@(\d+),\s*H@(\d+)\]")


def main() -> None:
    args = parse_args()
    base_rows = load_jsonl(Path(args.base_dataset_path))
    tier5_rows = load_jsonl(Path(args.tier5_path))
    audit = json.loads(Path(args.audit_path).read_text(encoding="utf-8"))

    selected_tier5 = select_tier5_rows(
        rows=tier5_rows,
        max_rows=args.max_tier5,
        max_per_parent=args.max_tier5_per_parent,
    )
    wrong_serine_rows, wrong_serine_pool_size = build_wrong_serine_rows(
        audit=audit,
        max_rows=args.max_wrong_serine,
    )

    output_rows = base_rows + selected_tier5 + wrong_serine_rows
    write_jsonl(Path(args.output_path), output_rows)

    summary = {
        "base_dataset_path": args.base_dataset_path,
        "tier5_path": args.tier5_path,
        "audit_path": args.audit_path,
        "output_path": args.output_path,
        "base_count": len(base_rows),
        "tier5_pool_count": len(tier5_rows),
        "tier5_selected_count": len(selected_tier5),
        "wrong_serine_pool_count": wrong_serine_pool_size,
        "wrong_serine_selected_count": len(wrong_serine_rows),
        "total_count": len(output_rows),
        "max_tier5": args.max_tier5,
        "max_tier5_per_parent": args.max_tier5_per_parent,
        "max_wrong_serine": args.max_wrong_serine,
    }
    if args.summary_path:
        Path(args.summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an SFT dataset with relocation bridge positives and wrong-serine negatives")
    parser.add_argument("--base-dataset-path", required=True)
    parser.add_argument("--tier5-path", required=True)
    parser.add_argument("--audit-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path")
    parser.add_argument("--max-tier5", type=int, default=256)
    parser.add_argument("--max-tier5-per-parent", type=int, default=2)
    parser.add_argument("--max-wrong-serine", type=int, default=128)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def select_tier5_rows(
    *,
    rows: list[dict[str, Any]],
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
        selected.append(row)
        if len(selected) >= max_rows:
            break
    return selected


def build_wrong_serine_rows(
    *,
    audit: dict[str, Any],
    max_rows: int,
) -> tuple[list[dict[str, Any]], int]:
    pool: list[dict[str, Any]] = []
    for record in audit["records"]:
        blueprint = parse_blueprint(str(record.get("sequence_prompt") or ""))
        if blueprint is None:
            continue
        for candidate in record["candidates"]:
            if int(candidate.get("motif_count") or 0) != 1:
                continue
            sequence = str(candidate.get("extracted_sequence") or "")
            if not sequence:
                continue
            serine_position = find_single_serine_position(sequence)
            if serine_position is None:
                continue
            if serine_position == blueprint[0]:
                continue
            pool.append(
                {
                    "label": "tier_wrong_serine_position",
                    "prompt": append_wrong_serine_prompt(
                        prompt=str(record["prompt"]),
                        blueprint_tag=format_blueprint(*blueprint),
                    ),
                    "sequence": sequence,
                    "source_step": record["step"],
                    "source_stage1_rank": int(candidate.get("stage1_rank") or 0),
                    "source_raw_esm_score": float(candidate.get("raw_esm_score") or 0.0),
                    "source_serine_position": serine_position,
                    "source_blueprint": format_blueprint(*blueprint),
                    "source_blueprint_serine": blueprint[0],
                    "source_serine_distance": abs(serine_position - blueprint[0]),
                }
            )
    pool.sort(
        key=lambda row: (
            -float(row["source_raw_esm_score"]),
            -int(row["source_serine_distance"]),
            int(row["source_stage1_rank"]),
        )
    )
    return pool[:max_rows], len(pool)


def parse_blueprint(sequence_prompt: str) -> tuple[int, int, int] | None:
    match = BLUEPRINT_PATTERN.search(sequence_prompt)
    if not match:
        return None
    return tuple(int(group) for group in match.groups())


def format_blueprint(serine_position: int, aspartate_position: int, histidine_position: int) -> str:
    return f"[Blueprint: S_motif@{serine_position}, D@{aspartate_position}, H@{histidine_position}]"


def append_wrong_serine_prompt(*, prompt: str, blueprint_tag: str) -> str:
    stripped = prompt.strip()
    if WRONG_SERINE_TAG not in stripped:
        stripped = f"{stripped}\n{WRONG_SERINE_TAG}"
    if "[Blueprint:" not in stripped:
        stripped = f"{stripped}\n{blueprint_tag}"
    return stripped


def find_single_serine_position(sequence: str) -> int | None:
    positions: list[int] = []
    for motif_start in range(len(sequence) - 4):
        motif = sequence[motif_start : motif_start + 5]
        if SERINE_MOTIF_PATTERN.fullmatch(motif):
            positions.append(motif_start + 3)
    if len(positions) != 1:
        return None
    return positions[0]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


if __name__ == "__main__":
    main()
