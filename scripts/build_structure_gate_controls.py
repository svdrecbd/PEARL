#!/usr/bin/env python3
"""Build paired natural-positive and composition-matched structure controls."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AA_PATTERN = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")
SERINE_MOTIF = re.compile(r"G.S.G")


def active_site_positions(record: dict) -> tuple[int, int, int] | None:
    sequence = record.get("sequence", "")
    sites = sorted(
        site["start"]
        for site in record.get("active_sites", [])
        if isinstance(site.get("start"), int) and 1 <= site["start"] <= len(sequence)
    )
    if len(sites) < 3:
        return None
    ser, asp, his = sites[:3]
    if [sequence[pos - 1] for pos in (ser, asp, his)] != ["S", "D", "H"]:
        return None
    if not SERINE_MOTIF.fullmatch(sequence[ser - 3 : ser + 2]):
        return None
    return ser, asp, his


def kmers(sequence: str, size: int = 3) -> set[str]:
    return {sequence[index : index + size] for index in range(len(sequence) - size + 1)}


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def choose_diverse(records: list[dict], count: int, *, anchor_accession: str) -> list[dict]:
    ordered = sorted(
        records,
        key=lambda row: (
            -int(row.get("relevance_score", 0)),
            -float(row.get("annotation_score", 0.0)),
            str(row.get("accession", "")),
        ),
    )
    anchor_index = next(
        (index for index, row in enumerate(ordered) if row.get("accession") == anchor_accession),
        None,
    )
    if anchor_index is None:
        raise ValueError(f"Anchor accession {anchor_accession!r} is not eligible")
    selected = [ordered.pop(anchor_index)]
    selected_kmers = [kmers(selected[0]["sequence"])]
    candidate_kmers = {row["sequence_sha256"]: kmers(row["sequence"]) for row in ordered}
    while ordered and len(selected) < count:
        best_index = min(
            range(len(ordered)),
            key=lambda index: (
                max(
                    jaccard(candidate_kmers[ordered[index]["sequence_sha256"]], chosen)
                    for chosen in selected_kmers
                ),
                -int(ordered[index].get("relevance_score", 0)),
                str(ordered[index].get("accession", "")),
            ),
        )
        row = ordered.pop(best_index)
        selected.append(row)
        selected_kmers.append(candidate_kmers[row["sequence_sha256"]])
    if len(selected) != count:
        raise ValueError(f"Requested {count} controls but found {len(selected)} eligible records")
    return selected


def hard_negative(sequence: str, sites: tuple[int, int, int], rng: random.Random) -> str:
    ser, asp, his = sites
    protected = {ser - 1, asp - 1, his - 1}
    protected.update(range(ser - 3, ser + 2))
    movable_indices = [index for index in range(len(sequence)) if index not in protected]
    movable_residues = [sequence[index] for index in movable_indices]
    shuffled = movable_residues[:]
    for _ in range(100):
        rng.shuffle(shuffled)
        if shuffled != movable_residues:
            break
    result = list(sequence)
    for index, residue in zip(movable_indices, shuffled, strict=True):
        result[index] = residue
    negative = "".join(result)
    if sorted(negative) != sorted(sequence):
        raise AssertionError("Hard negative changed amino-acid composition")
    if [negative[pos - 1] for pos in sites] != ["S", "D", "H"]:
        raise AssertionError("Hard negative changed annotated catalytic residues")
    if negative[ser - 3 : ser + 2] != sequence[ser - 3 : ser + 2]:
        raise AssertionError("Hard negative changed the catalytic serine motif")
    return negative


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--records",
        type=Path,
        default=ROOT / "data" / "petase_family_expanded" / "petase_records.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "methods_evaluation" / "structure-gate-controls-v1",
    )
    parser.add_argument("--count", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--anchor-accession", default="Q47RJ6")
    args = parser.parse_args()

    eligible: list[dict] = []
    seen_sequences: set[str] = set()
    with args.records.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            sequence = record.get("sequence", "")
            if (
                not record.get("reviewed")
                or not AA_PATTERN.fullmatch(sequence)
                or not 180 <= len(sequence) <= 400
                or active_site_positions(record) is None
                or sequence in seen_sequences
            ):
                continue
            seen_sequences.add(sequence)
            eligible.append(record)

    selected = choose_diverse(eligible, args.count, anchor_accession=args.anchor_accession)
    positives: list[dict] = []
    negatives: list[dict] = []
    pairs: list[dict] = []
    for index, record in enumerate(selected):
        sequence = record["sequence"]
        sites = active_site_positions(record)
        assert sites is not None
        negative = hard_negative(sequence, sites, random.Random(args.seed + index))
        pair_id = f"control-{index + 1:02d}-{record['accession']}"
        positives.append(
            {
                "name": f"positive:{pair_id}",
                "sequence": sequence,
                "pair_id": pair_id,
                "source_accession": record["accession"],
            }
        )
        negatives.append(
            {
                "name": f"negative:{pair_id}",
                "sequence": negative,
                "pair_id": pair_id,
                "source_accession": record["accession"],
            }
        )
        pairs.append(
            {
                "pair_id": pair_id,
                "source_accession": record["accession"],
                "uniprot_id": record.get("uniprot_id"),
                "organism": record.get("organism_name"),
                "protein_name": record.get("protein_name"),
                "length": len(sequence),
                "active_sites": {"ser": sites[0], "asp": sites[1], "his": sites[2]},
                "motif": sequence[sites[0] - 3 : sites[0] + 2],
                "positive_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                "negative_sha256": hashlib.sha256(negative.encode()).hexdigest(),
            }
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    positive_path = args.output_dir / "positive-controls.jsonl"
    negative_path = args.output_dir / "negative-controls.jsonl"
    write_jsonl(positive_path, positives)
    write_jsonl(negative_path, negatives)
    manifest = {
        "contract": "pearl.structure-gate-controls/1",
        "seed": args.seed,
        "anchor_accession": args.anchor_accession,
        "selection": "reviewed, annotated S-D-H, GxSxG-centered, 180-400 aa, greedy 3-mer diversity",
        "negative_control": "composition-preserving shuffle with GxSxG motif and annotated S-D-H positions frozen",
        "count_per_arm": args.count,
        "positive_panel_sha256": sha256(positive_path),
        "negative_panel_sha256": sha256(negative_path),
        "pairs": pairs,
    }
    manifest_path = args.output_dir / "control-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in manifest.items() if key != "pairs"}, indent=2))
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
