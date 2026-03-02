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
from petase_family import compute_family_stats, load_reference_records, assess_catalytic_geometry

SERINE_MOTIF_PATTERN = re.compile(r"G[A-Z]S[A-Z]G")


def main() -> None:
    args = parse_args()
    records = load_reference_records(Path(args.records_path))
    prompt_by_accession = load_prompt_map(Path(args.prompts_path))
    family_stats = compute_family_stats(records)

    candidates: list[dict[str, Any]] = []
    for record in records:
        accession = record["accession"]
        prompt_row = prompt_by_accession.get(accession)
        if prompt_row is None:
            continue
        if int(record.get("relevance_score", 0)) < args.min_relevance:
            continue
        if not bool(record.get("reviewed", False)):
            continue
        if float(record.get("annotation_score") or 0.0) < args.min_annotation_score:
            continue
        sequence = str(record.get("sequence") or "")
        if not sequence or not (args.min_length <= len(sequence) <= args.max_length):
            continue
        if args.require_single_motif and count_serine_motifs(sequence) != 1:
            continue
        if not has_sdh_active_sites(record, sequence):
            continue

        catalytic_geometry = assess_catalytic_geometry(sequence, family_stats)
        if not catalytic_geometry["passes"]:
            continue

        candidates.append(
            {
                "accession": accession,
                "prompt": prompt_row["prompt"],
                "sequence": sequence,
                "length": len(sequence),
                "protein_name": record.get("protein_name"),
                "organism_name": record.get("organism_name"),
                "relevance_score": int(record.get("relevance_score", 0)),
                "annotation_score": float(record.get("annotation_score") or 0.0),
                "reviewed": bool(record.get("reviewed", False)),
                "is_thermophile_hint": bool(record.get("is_thermophile_hint", False)),
                "catalytic_geometry": catalytic_geometry,
            }
        )

    candidates.sort(
        key=lambda row: (
            row["annotation_score"],
            row["relevance_score"],
            row["is_thermophile_hint"],
            -abs(int(row["length"]) - 280),
        ),
        reverse=True,
    )
    shortlist = candidates[: args.candidate_limit]
    for row in shortlist:
        row["esm_score"] = get_esm2_plddt_score(row["sequence"])

    selected = [row for row in shortlist if float(row["esm_score"]) >= args.min_esm_score]
    if args.allow_esm_shortfall_fallback and len(selected) < args.max_examples:
        selected = shortlist
    selected = sorted(
        selected,
        key=lambda row: (
            float(row["esm_score"]),
            row["annotation_score"],
            row["relevance_score"],
        ),
        reverse=True,
    )[: args.max_examples]

    output_rows = [
        {
            "accession": row["accession"],
            "prompt": row["prompt"],
            "sequence": row["sequence"],
            "length": row["length"],
            "protein_name": row["protein_name"],
            "organism_name": row["organism_name"],
            "relevance_score": row["relevance_score"],
            "annotation_score": row["annotation_score"],
            "reviewed": row["reviewed"],
            "is_thermophile_hint": row["is_thermophile_hint"],
            "esm_score": round(float(row["esm_score"]), 2),
            "catalytic_geometry": row["catalytic_geometry"],
        }
        for row in selected
    ]
    write_jsonl(Path(args.output_path), output_rows)

    summary = {
        "records_path": args.records_path,
        "prompts_path": args.prompts_path,
        "output_path": args.output_path,
        "candidate_count": len(candidates),
        "shortlist_count": len(shortlist),
        "selected_count": len(output_rows),
        "min_relevance": args.min_relevance,
        "min_annotation_score": args.min_annotation_score,
        "min_esm_score": args.min_esm_score,
        "require_single_motif": args.require_single_motif,
        "mean_esm_score": round(sum(row["esm_score"] for row in output_rows) / max(1, len(output_rows)), 2),
        "mean_length": round(sum(row["length"] for row in output_rows) / max(1, len(output_rows)), 2),
        "accessions": [row["accession"] for row in output_rows],
    }
    if args.summary_path:
        Path(args.summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a geometry-positive supervised warm-start dataset")
    parser.add_argument("--records-path", required=True)
    parser.add_argument("--prompts-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path")
    parser.add_argument("--max-examples", type=int, default=64)
    parser.add_argument("--candidate-limit", type=int, default=96)
    parser.add_argument("--min-relevance", type=int, default=10)
    parser.add_argument("--min-annotation-score", type=float, default=3.0)
    parser.add_argument("--min-esm-score", type=float, default=85.0)
    parser.add_argument("--min-length", type=int, default=180)
    parser.add_argument("--max-length", type=int, default=360)
    parser.add_argument("--require-single-motif", action="store_true")
    parser.add_argument("--allow-esm-shortfall-fallback", action="store_true")
    return parser.parse_args()


def load_prompt_map(path: Path) -> dict[str, dict[str, Any]]:
    prompt_by_accession: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            accession = row.get("accession")
            if isinstance(accession, str) and accession not in prompt_by_accession:
                prompt_by_accession[accession] = row
    return prompt_by_accession


def has_sdh_active_sites(record: dict[str, Any], sequence: str) -> bool:
    active_sites = record.get("active_sites") or []
    if len(active_sites) < 3:
        return False
    residues: list[str] = []
    for site in active_sites[:3]:
        position = site.get("start")
        if not isinstance(position, int) or position < 1 or position > len(sequence):
            return False
        residues.append(sequence[position - 1])
    return residues == ["S", "D", "H"]


def count_serine_motifs(sequence: str) -> int:
    return len(SERINE_MOTIF_PATTERN.findall(sequence))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


if __name__ == "__main__":
    main()
