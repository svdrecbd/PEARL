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

from petase_family import (
    ASP_HIS_TARGET_GAP,
    SER_ASP_TARGET_GAP,
    SERINE_MOTIF_PATTERN,
    compute_family_stats,
    load_reference_records,
)


TIER1_TAG = "[Target: Single-Active-Site, High-Stability, Perfect-Triad]"
BLUEPRINT_PATTERN = re.compile(r"\[Blueprint:\s*S_motif@(\d+),\s*D@(\d+),\s*H@(\d+)\]")


def main() -> None:
    args = parse_args()
    reference_records = load_reference_records(Path(args.records_path))
    family_stats = compute_family_stats(reference_records)
    perfect_rows = load_perfect_wildtypes(Path(args.perfect_path), family_stats)
    unicorn_rows = load_unicorns_from_paths(
        [Path(path.strip()) for path in args.unicorn_audit_paths.split(",") if path.strip()],
        family_stats,
    )

    if len(perfect_rows) < args.perfect_count:
        raise RuntimeError(f"Expected at least {args.perfect_count} perfect wildtypes, found {len(perfect_rows)}")
    if len(unicorn_rows) < args.unicorn_count:
        raise RuntimeError(f"Expected at least {args.unicorn_count} unicorns, found {len(unicorn_rows)}")

    output_rows = perfect_rows[: args.perfect_count] + unicorn_rows[: args.unicorn_count]
    write_jsonl(Path(args.output_path), output_rows)
    summary = {
        "output_path": args.output_path,
        "records_path": args.records_path,
        "perfect_path": args.perfect_path,
        "unicorn_audit_paths": [path.strip() for path in args.unicorn_audit_paths.split(",") if path.strip()],
        "perfect_count": args.perfect_count,
        "unicorn_count": args.unicorn_count,
        "total_count": len(output_rows),
        "items": [
            {
                "label": row["label"],
                "accession": row.get("accession"),
                "source_step": row.get("source_step"),
                "esm_score": row.get("esm_score"),
                "blueprint": extract_blueprint(row["prompt"]),
            }
            for row in output_rows
        ],
    }
    if args.summary_path:
        Path(args.summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a tiny Kimi-native micro-SFT set from unicorns and perfect wildtypes")
    parser.add_argument("--records-path", required=True)
    parser.add_argument("--perfect-path", required=True)
    parser.add_argument("--unicorn-audit-paths", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path")
    parser.add_argument("--perfect-count", type=int, default=3)
    parser.add_argument("--unicorn-count", type=int, default=2)
    return parser.parse_args()


def load_perfect_wildtypes(path: Path, family_stats: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if float(row.get("esm_score", 0.0)) >= 85.0]
    rows.sort(key=lambda row: float(row.get("esm_score", 0.0)), reverse=True)
    output: list[dict[str, Any]] = []
    for row in rows:
        sequence = str(row["sequence"])
        blueprint = best_triad_positions(sequence, family_stats)
        if blueprint is None:
            continue
        prompt = append_tier1_prompt(str(row["prompt"]), blueprint)
        output.append(
            {
                "label": "perfect_wildtype_tier1",
                "accession": row.get("accession"),
                "prompt": prompt,
                "sequence": sequence,
                "esm_score": float(row["esm_score"]),
            }
        )
    return output


def load_unicorns_from_paths(paths: list[Path], family_stats: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        audit = json.loads(path.read_text(encoding="utf-8"))
        for record in audit["records"]:
            for candidate in record["candidates"]:
                if int(candidate.get("motif_count") or 0) != 1:
                    continue
                if not bool(candidate.get("geometry_passes")):
                    continue
                if not bool(candidate.get("esm_gate_pass")):
                    continue
                sequence = str(candidate.get("extracted_sequence") or "")
                if not sequence:
                    continue
                blueprint = best_triad_positions(sequence, family_stats)
                if blueprint is None:
                    continue
                prompt = append_tier1_prompt(str(record["prompt"]), blueprint)
                rows.append(
                    {
                        "label": "kimi_unicorn_tier1",
                        "source_audit_path": str(path),
                        "source_step": int(record["step"]),
                        "prompt": prompt,
                        "sequence": sequence,
                        "esm_score": float(candidate.get("raw_esm_score") or 0.0),
                    }
                )
    rows.sort(key=lambda row: float(row["esm_score"]), reverse=True)
    return dedupe_rows(rows)


def best_triad_positions(sequence: str, family_stats: dict[str, Any]) -> tuple[int, int, int] | None:
    serine_window = family_stats["serine_position_range"]
    aspartate_window = family_stats["aspartate_position_range"]
    histidine_window = family_stats["histidine_position_range"]
    serine_hits = [
        index + 3
        for index in range(len(sequence) - 4)
        if SERINE_MOTIF_PATTERN.fullmatch(sequence[index : index + 5])
        and serine_window[0] <= (index + 3) / len(sequence) <= serine_window[1]
    ]
    aspartate_hits = [
        index + 1
        for index, residue in enumerate(sequence)
        if residue == "D" and aspartate_window[0] <= (index + 1) / len(sequence) <= aspartate_window[1]
    ]
    histidine_hits = [
        index + 1
        for index, residue in enumerate(sequence)
        if residue == "H" and histidine_window[0] <= (index + 1) / len(sequence) <= histidine_window[1]
    ]
    best: tuple[int, int, int] | None = None
    best_error: int | None = None
    for serine in serine_hits:
        for aspartate in aspartate_hits:
            if aspartate <= serine:
                continue
            for histidine in histidine_hits:
                if histidine <= aspartate:
                    continue
                error = abs((aspartate - serine) - SER_ASP_TARGET_GAP) + abs((histidine - aspartate) - ASP_HIS_TARGET_GAP)
                if best_error is None or error < best_error:
                    best_error = error
                    best = (serine, aspartate, histidine)
    return best


def append_tier1_prompt(prompt: str, blueprint: tuple[int, int, int]) -> str:
    stripped = prompt.strip()
    if TIER1_TAG not in stripped:
        stripped = f"{stripped}\n{TIER1_TAG}"
    blueprint_tag = format_blueprint(*blueprint)
    if "[Blueprint:" not in stripped:
        stripped = f"{stripped}\n{blueprint_tag}"
    return stripped


def format_blueprint(serine: int, aspartate: int, histidine: int) -> str:
    return f"[Blueprint: S_motif@{serine}, D@{aspartate}, H@{histidine}]"


def extract_blueprint(prompt: str) -> tuple[int, int, int] | None:
    match = BLUEPRINT_PATTERN.search(prompt)
    if not match:
        return None
    return tuple(int(group) for group in match.groups())


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
