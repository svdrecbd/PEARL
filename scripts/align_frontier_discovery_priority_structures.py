#!/usr/bin/env python3
"""Align the two frozen discovery leads to fixed public natural references."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from biotite.sequence import ProteinSequence
from biotite.structure.io.pdb import PDBFile
import biotite.structure as struc


LEAD_SHUFFLED = "02e7e4519c13b33e09bcd126e95be40b6a84a2fd3ea451e260a9b1b1160c2f5f"
LEAD_TRUE = "0faeecc54e3ed5bf1009e7821eaf77ed7d73a91d1e7b3faa216b507ecfc40a6d"
REFERENCE_FILES = {
    "A0A1L7CWZ9": "AF-A0A1L7CWZ9-F1-model_v6.pdb",
    "Q47RJ6": "AF-Q47RJ6-F1-model_v6.pdb",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_value(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def pdb_sequence(path: Path) -> str:
    atoms = PDBFile.read(path).get_structure(model=1)
    _, residue_names = struc.get_residues(atoms)
    return "".join(ProteinSequence.convert_letter_3to1(str(name)) for name in residue_names)


def load_references(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            accession = str(row["accession"])
            if accession in {"A0A1L7CWZ9", "A0ABT1GWL0", "Q47RJ6"}:
                rows[accession] = row
    if set(rows) != {"A0A1L7CWZ9", "A0ABT1GWL0", "Q47RJ6"}:
        raise RuntimeError("fixed natural references are missing from the frozen dataset")
    return rows


def run_alignment(
    executable: Path,
    structure_1: Path,
    structure_2: Path,
    raw_output_path: Path,
) -> dict[str, Any]:
    common = [str(executable), str(structure_1), str(structure_2), "-mol", "prot", "-ter", "2"]
    raw = subprocess.run(common + ["-outfmt", "-1"], check=True, text=True, capture_output=True).stdout
    raw_output_path.write_text(raw, encoding="utf-8")
    compact = subprocess.run(common + ["-outfmt", "2"], check=True, text=True, capture_output=True).stdout
    lines = [line for line in compact.splitlines() if line.strip()]
    if len(lines) != 2:
        raise RuntimeError(f"unexpected US-align output for {structure_1} vs {structure_2}")
    header = lines[0].lstrip("#").split("\t")
    values = lines[1].split("\t")
    parsed = dict(zip(header, values, strict=True))
    return {
        "structure_1": str(structure_1),
        "structure_2": str(structure_2),
        "structure_1_sha256": sha256_file(structure_1),
        "structure_2_sha256": sha256_file(structure_2),
        "tm_score_normalized_by_structure_1": float(parsed["TM1"]),
        "tm_score_normalized_by_structure_2": float(parsed["TM2"]),
        "rmsd_angstrom": float(parsed["RMSD"]),
        "sequence_identity_over_structure_1": float(parsed["ID1"]),
        "sequence_identity_over_structure_2": float(parsed["ID2"]),
        "sequence_identity_over_aligned_residues": float(parsed["IDali"]),
        "structure_1_length": int(parsed["L1"]),
        "structure_2_length": int(parsed["L2"]),
        "aligned_length": int(parsed["Lali"]),
        "raw_output": str(raw_output_path),
        "raw_output_sha256": sha256_file(raw_output_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usalign", required=True)
    parser.add_argument("--usalign-commit", required=True)
    parser.add_argument("--pdb-root", required=True)
    parser.add_argument("--reference-root", required=True)
    parser.add_argument("--natural-references", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    executable = Path(args.usalign)
    pdb_root = Path(args.pdb_root)
    reference_root = Path(args.reference_root)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    natural_path = Path(args.natural_references)
    natural = load_references(natural_path)

    reference_validation: dict[str, Any] = {}
    for accession, filename in REFERENCE_FILES.items():
        pdb_path = reference_root / filename
        sequence = pdb_sequence(pdb_path)
        expected = str(natural[accession]["sequence"])
        if sequence != expected:
            raise RuntimeError(f"public reference PDB sequence mismatch for {accession}")
        reference_validation[accession] = {
            "source": "AlphaFold Database",
            "entry_id": filename.removesuffix(".pdb"),
            "download_url": f"https://alphafold.ebi.ac.uk/files/{filename}",
            "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
            "sequence_length": len(sequence),
            "pdb_sha256": sha256_file(pdb_path),
            "exact_sequence_match_to_frozen_dataset": True,
        }

    comparisons = {
        "shuffled_lead_to_exact_closest_natural": run_alignment(
            executable,
            pdb_root / f"{LEAD_SHUFFLED}.pdb",
            reference_root / REFERENCE_FILES["A0A1L7CWZ9"],
            output_root / "shuffled_lead_to_A0A1L7CWZ9.txt",
        ),
        "shuffled_lead_to_fixed_Q47RJ6_anchor": run_alignment(
            executable,
            pdb_root / f"{LEAD_SHUFFLED}.pdb",
            reference_root / REFERENCE_FILES["Q47RJ6"],
            output_root / "shuffled_lead_to_Q47RJ6.txt",
        ),
        "true_lead_to_fixed_Q47RJ6_anchor": run_alignment(
            executable,
            pdb_root / f"{LEAD_TRUE}.pdb",
            reference_root / REFERENCE_FILES["Q47RJ6"],
            output_root / "true_lead_to_Q47RJ6.txt",
        ),
    }
    payload = {
        "contract": "pearl.frontier-replication-salvage-orthogonal-structure-alignment/1",
        "status": "complete_with_one_unavailable_exact_reference",
        "scope": "posthoc_exploratory_two_frozen_leads",
        "tool": {
            "name": "US-align",
            "version": "20260819",
            "source_repository": "https://github.com/pylelab/USalign",
            "source_commit": args.usalign_commit,
            "binary_sha256": sha256_file(executable),
            "options": ["-mol", "prot", "-ter", "2"],
        },
        "inputs": {
            "natural_references_sha256": sha256_file(natural_path),
            "lead_shuffled_sha256": LEAD_SHUFFLED,
            "lead_true_sha256": LEAD_TRUE,
            "exact_closest_natural_by_frozen_evaluator": {
                LEAD_SHUFFLED: "A0A1L7CWZ9",
                LEAD_TRUE: "A0ABT1GWL0",
            },
            "fixed_anchor": "Q47RJ6",
        },
        "retrieval_audit": {
            "RCSB_Search_API": {
                "lookup_date": "2026-08-23",
                "result": {
                    "A0A1L7CWZ9": "no mapped experimental polymer entity (HTTP 204)",
                    "A0ABT1GWL0": "no mapped experimental polymer entity (HTTP 204)",
                    "Q47RJ6": "no mapped experimental polymer entity (HTTP 204)",
                },
            },
            "AlphaFold_Database_API": {
                "lookup_date": "2026-08-23",
                "result": {
                    "A0A1L7CWZ9": "AF-A0A1L7CWZ9-F1 model version 6 retrieved",
                    "A0ABT1GWL0": "no prediction entry (HTTP 404)",
                    "Q47RJ6": "AF-Q47RJ6-F1 model version 6 retrieved",
                },
            },
            "candidate_data_uploaded": False,
        },
        "public_reference_validation": reference_validation,
        "comparisons": comparisons,
        "unavailable_comparison": {
            "name": "true_lead_to_exact_closest_natural",
            "accession": "A0ABT1GWL0",
            "reason": "No RCSB experimental entry or AlphaFold Database prediction was available.",
            "substitute_selected": False,
        },
        "interpretation_boundary": {
            "descriptive_not_confirmatory": True,
            "functional_activity_inferred": False,
            "new_candidates_promoted": 0,
            "paid_compute_used": False,
        },
    }
    payload["alignment_audit_sha256"] = sha256_value(payload)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
