from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


POSITIVE_TAG = "[Target: Single-Active-Site, High-Diversity]"
NEGATIVE_TAG = "[Target: Repeated-Motif-Scaffold, Low-Diversity]"
UNSTABLE_NEGATIVE_TAG = "[Target: Single-Active-Site, Unstable-Geometry]"


def main() -> None:
    args = parse_args()
    positive_rows = load_jsonl(Path(args.positive_path))
    audit = json.loads(Path(args.audit_path).read_text(encoding="utf-8"))
    unstable_audit = (
        json.loads(Path(args.unstable_audit_path).read_text(encoding="utf-8"))
        if args.unstable_audit_path
        else None
    )

    positives = [
        {
            "label": "positive",
            "prompt": append_tag(str(row["prompt"]), POSITIVE_TAG),
            "sequence": str(row["sequence"]),
            "source_accession": row.get("accession"),
            "source_prompt": row.get("prompt"),
        }
        for row in positive_rows
    ]

    negative_pool = build_negative_pool(audit)
    if not negative_pool:
        raise RuntimeError("No negative scaffold candidates were found in the candidate audit")

    negative_count = min(args.max_negative_examples, max(len(positives), args.min_negative_examples))
    negatives: list[dict[str, Any]] = []
    for index in range(negative_count):
        row = negative_pool[index % len(negative_pool)]
        negatives.append(
            {
                "label": "negative",
                "prompt": append_tag(str(row["prompt"]), NEGATIVE_TAG),
                "sequence": str(row["sequence"]),
                "source_step": row["step"],
                "source_stage1_rank": row["stage1_rank"],
                "source_motif_count": row["motif_count"],
                "source_length": row["length"],
                "source_template_penalty": row.get("template_penalty"),
            }
        )

    unstable_negatives: list[dict[str, Any]] = []
    unstable_pool = build_unstable_single_motif_pool(unstable_audit) if unstable_audit is not None else []
    unstable_count = min(args.max_unstable_negative_examples, len(unstable_pool))
    for index in range(unstable_count):
        row = unstable_pool[index]
        unstable_negatives.append(
            {
                "label": "negative_unstable_single",
                "prompt": append_tag(str(row["prompt"]), UNSTABLE_NEGATIVE_TAG),
                "sequence": str(row["sequence"]),
                "source_step": row["step"],
                "source_stage1_rank": row["stage1_rank"],
                "source_motif_count": row["motif_count"],
                "source_length": row["length"],
                "source_template_penalty": row.get("template_penalty"),
                "source_geometry_passes": row.get("geometry_passes"),
                "source_esm_gate_pass": row.get("esm_gate_pass"),
            }
        )

    output_rows = positives + negatives + unstable_negatives
    write_jsonl(Path(args.output_path), output_rows)

    summary = {
        "positive_path": args.positive_path,
        "audit_path": args.audit_path,
        "output_path": args.output_path,
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "unstable_negative_count": len(unstable_negatives),
        "unique_negative_templates": len({row["sequence"] for row in negative_pool}),
        "negative_pool_size": len(negative_pool),
        "unstable_negative_pool_size": len(unstable_pool),
        "positive_tag": POSITIVE_TAG,
        "negative_tag": NEGATIVE_TAG,
        "unstable_negative_tag": UNSTABLE_NEGATIVE_TAG,
    }
    if args.summary_path:
        Path(args.summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a control-tagged SFT dataset from good and spammy sequences")
    parser.add_argument("--positive-path", required=True)
    parser.add_argument("--audit-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path")
    parser.add_argument("--min-negative-examples", type=int, default=32)
    parser.add_argument("--max-negative-examples", type=int, default=64)
    parser.add_argument("--unstable-audit-path")
    parser.add_argument("--max-unstable-negative-examples", type=int, default=64)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_negative_pool(audit: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for record in audit["records"]:
        prompt = str(record["prompt"])
        for candidate in record["candidates"]:
            motif_count = int(candidate.get("motif_count") or count_serine_motifs(str(candidate["extracted_sequence"])))
            sequence = str(candidate["extracted_sequence"])
            if motif_count <= 1:
                continue
            if not sequence:
                continue
            key = (sequence, motif_count)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "prompt": prompt,
                    "sequence": sequence,
                    "step": record["step"],
                    "stage1_rank": int(candidate.get("stage1_rank") or 0),
                    "motif_count": motif_count,
                    "length": int(candidate.get("length") or len(sequence)),
                    "template_penalty": candidate.get("template_penalty"),
                }
            )
    rows.sort(
        key=lambda row: (
            row["stage1_rank"],
            -row["motif_count"],
            abs(row["length"] - 280),
        )
    )
    return rows


def build_unstable_single_motif_pool(audit: dict[str, Any] | None) -> list[dict[str, Any]]:
    if audit is None:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in audit["records"]:
        prompt = str(record["prompt"])
        for candidate in record["candidates"]:
            sequence = str(candidate["extracted_sequence"])
            motif_count = int(candidate.get("motif_count") or count_serine_motifs(sequence))
            if motif_count != 1:
                continue
            if candidate.get("geometry_passes"):
                continue
            if candidate.get("esm_gate_pass"):
                continue
            if not sequence or sequence in seen:
                continue
            seen.add(sequence)
            rows.append(
                {
                    "prompt": prompt,
                    "sequence": sequence,
                    "step": record["step"],
                    "stage1_rank": int(candidate.get("stage1_rank") or 0),
                    "motif_count": motif_count,
                    "length": int(candidate.get("length") or len(sequence)),
                    "template_penalty": candidate.get("template_penalty"),
                    "geometry_passes": bool(candidate.get("geometry_passes")),
                    "esm_gate_pass": bool(candidate.get("esm_gate_pass")),
                }
            )
    rows.sort(
        key=lambda row: (
            row["stage1_rank"],
            abs(row["length"] - 280),
        )
    )
    return rows


def append_tag(prompt: str, tag: str) -> str:
    stripped = prompt.strip()
    if tag in stripped:
        return stripped
    return f"{stripped}\n{tag}"


def count_serine_motifs(sequence: str) -> int:
    count = 0
    for index in range(len(sequence) - 4):
        motif = sequence[index : index + 5]
        if motif[0] == "G" and motif[2] == "S" and motif[4] == "G":
            count += 1
    return count


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


if __name__ == "__main__":
    main()
