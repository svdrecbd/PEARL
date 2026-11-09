#!/usr/bin/env python3
"""Run fixed local orthogonal checks on the frozen 15-structure shortlist."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

import biotite.structure as struc
import numpy as np
from biotite.sequence import ProteinSequence
from biotite.structure.io.pdb import PDBFile
from scipy.spatial import cKDTree


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pearl.family import (  # noqa: E402
    compute_family_stats,
    evaluate_candidate,
    load_reference_records,
    precompute_novelty_cache,
)


PRIMARY_HASHES = {
    "02e7e4519c13b33e09bcd126e95be40b6a84a2fd3ea451e260a9b1b1160c2f5f",
    "0faeecc54e3ed5bf1009e7821eaf77ed7d73a91d1e7b3faa216b507ecfc40a6d",
}
SHORTLIST_HASH = "81f704b4b6a98f7b64e02e56abdd91f911d6e1a78ebfc5455efd8152ebd3ff6f"
PRIMARY_SET_HASH = "ba12288b5ad272f2e1afd5e6ca0531aab8de17cbbca0e7a238e02f341a718faf"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compact_list_hash(values: list[str]) -> str:
    raw = json.dumps(sorted(values), separators=(",", ":"), ensure_ascii=True) + "\n"
    return hashlib.sha256(raw.encode()).hexdigest()


def round_float(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def residue_b_factors(array: struc.AtomArray) -> tuple[list[float], str]:
    starts = struc.get_residue_starts(array, add_exclusive_stop=True)
    values = [float(np.mean(array.b_factor[starts[i] : starts[i + 1]])) for i in range(len(starts) - 1)]
    # The ESMFold2 export used here stores confidence in [0, 1], while some
    # PDB producers store the same pLDDT quantity in [0, 100]. Normalize once
    # so downstream thresholds and the fold report use the same unit.
    if values and max(values) <= 1.5:
        return [value * 100 for value in values], "0_to_1_scaled_to_0_to_100"
    return values, "0_to_100"


def coarse_canonical_basin(phi: float, psi: float) -> bool:
    if not np.isfinite(phi) or not np.isfinite(psi):
        return True
    phi_deg = math.degrees(float(phi))
    psi_deg = math.degrees(float(psi))
    right_alpha = -160 <= phi_deg <= -20 and -120 <= psi_deg <= 70
    beta = -180 <= phi_deg <= -35 and (70 <= psi_deg <= 180 or -180 <= psi_deg <= -145)
    left_alpha = 20 <= phi_deg <= 120 and -30 <= psi_deg <= 120
    return right_alpha or beta or left_alpha


def structure_metrics(
    pdb_path: Path,
    *,
    expected_sequence: str,
    triad: dict[str, Any],
) -> dict[str, Any]:
    array = PDBFile.read(pdb_path).get_structure(model=1, extra_fields=["b_factor", "occupancy"])
    chains = sorted(set(str(value) for value in array.chain_id))
    residue_ids, residue_names = struc.get_residues(array)
    sequence = "".join(ProteinSequence.convert_letter_3to1(str(name)) for name in residue_names)
    if sequence != expected_sequence:
        raise RuntimeError(f"PDB sequence differs from frozen input: {pdb_path}")
    if chains != ["A"] or len(residue_ids) != len(expected_sequence):
        raise RuntimeError(f"unexpected PDB chain or residue count: {pdb_path}")

    starts = struc.get_residue_starts(array, add_exclusive_stop=True)
    residue_index = np.repeat(np.arange(len(starts) - 1), np.diff(starts))
    backbone_complete = []
    for index in range(len(starts) - 1):
        names = set(str(name) for name in array.atom_name[starts[index] : starts[index + 1]])
        backbone_complete.append({"N", "CA", "C", "O"}.issubset(names))

    ca = array[array.atom_name == "CA"]
    ca_distances = np.linalg.norm(np.diff(ca.coord, axis=0), axis=1)
    n_coordinates = array.coord[array.atom_name == "N"]
    c_coordinates = array.coord[array.atom_name == "C"]
    peptide_distances = np.linalg.norm(c_coordinates[:-1] - n_coordinates[1:], axis=1)

    phi, psi, omega = struc.dihedral_backbone(array)
    finite_phi_psi = np.isfinite(phi) & np.isfinite(psi)
    coarse_basin = [
        coarse_canonical_basin(phi[index], psi[index])
        for index in range(len(residue_ids))
        if finite_phi_psi[index]
    ]
    finite_omega_indices = np.where(np.isfinite(omega))[0]
    finite_omega = omega[finite_omega_indices]
    omega_deviation = np.abs(180 - np.abs(np.degrees(finite_omega)))
    omega_outliers = []
    for index, angle, deviation in zip(finite_omega_indices, np.degrees(finite_omega), omega_deviation):
        if deviation <= 30:
            continue
        omega_outliers.append({
            "peptide_bond_from_residue_index_1based": int(index + 1),
            "peptide_bond_from_residue": ProteinSequence.convert_letter_3to1(
                str(residue_names[index])
            ),
            "peptide_bond_to_residue_index_1based": int(index + 2),
            "peptide_bond_to_residue": ProteinSequence.convert_letter_3to1(
                str(residue_names[index + 1])
            ),
            "to_residue_is_proline": str(residue_names[index + 1]) == "PRO",
            "omega_degrees": round_float(angle, 2),
            "deviation_from_trans_degrees": round_float(deviation, 2),
        })

    sse = struc.annotate_sse(array)
    sse_counts = {code: int(np.sum(sse == code)) for code in ("a", "b", "c")}

    elements = np.array([str(value).upper() for value in array.element])
    heavy_mask = elements != "H"
    heavy_coordinates = array.coord[heavy_mask]
    heavy_residue_index = residue_index[heavy_mask]
    heavy_atoms = array[heavy_mask]
    pairs = cKDTree(heavy_coordinates).query_pairs(r=2.0)
    severe_clashes = 0
    severe_clash_details = []
    for left, right in pairs:
        left_residue = int(heavy_residue_index[left])
        right_residue = int(heavy_residue_index[right])
        if abs(left_residue - right_residue) <= 1:
            continue
        if (
            str(heavy_atoms.atom_name[left]) == "SG"
            and str(heavy_atoms.atom_name[right]) == "SG"
            and str(heavy_atoms.res_name[left]) == "CYS"
            and str(heavy_atoms.res_name[right]) == "CYS"
        ):
            continue
        severe_clashes += 1
        severe_clash_details.append({
            "left": {
                "residue_index_1based": left_residue + 1,
                "residue_name": str(heavy_atoms.res_name[left]),
                "atom_name": str(heavy_atoms.atom_name[left]),
            },
            "right": {
                "residue_index_1based": right_residue + 1,
                "residue_name": str(heavy_atoms.res_name[right]),
                "atom_name": str(heavy_atoms.atom_name[right]),
            },
            "distance_angstrom": round_float(
                np.linalg.norm(heavy_coordinates[left] - heavy_coordinates[right]), 3
            ),
        })

    plddt, plddt_encoding = residue_b_factors(array)
    triad_confidence: dict[str, Any] = {}
    if triad.get("found"):
        for label, field in (("ser", "ser_resseq"), ("asp", "asp_resseq"), ("his", "his_resseq")):
            residue_number = int(triad[field])
            index = residue_number - 1
            local = plddt[max(0, index - 5) : min(len(plddt), index + 6)]
            triad_confidence[label] = {
                "resseq": residue_number,
                "expected_residue": {"ser": "S", "asp": "D", "his": "H"}[label],
                "observed_residue": expected_sequence[index],
                "residue_plddt": round_float(plddt[index], 2),
                "local_plus_minus_5_mean_plddt": round_float(statistics.fmean(local), 2),
                "local_plus_minus_5_min_plddt": round_float(min(local), 2),
            }
    if any(row["expected_residue"] != row["observed_residue"] for row in triad_confidence.values()):
        raise RuntimeError(f"catalytic residue identity mismatch: {pdb_path}")

    centroid = np.mean(ca.coord, axis=0)
    radius_of_gyration = math.sqrt(float(np.mean(np.sum((ca.coord - centroid) ** 2, axis=1))))
    return {
        "pdb_sha256": sha256_file(pdb_path),
        "chain_count": len(chains),
        "residue_count": len(residue_ids),
        "atom_count": int(array.array_length()),
        "finite_coordinates": bool(np.isfinite(array.coord).all()),
        "occupancy": {
            "finite": bool(np.isfinite(array.occupancy).all()),
            "minimum": round_float(np.min(array.occupancy), 3),
            "maximum": round_float(np.max(array.occupancy), 3),
            "atoms_not_full_occupancy": int(np.sum(array.occupancy != 1.0)),
        },
        "backbone_complete_residues": sum(backbone_complete),
        "ca_continuity": {
            "max_adjacent_ca_distance_angstrom": round_float(np.max(ca_distances), 3),
            "breaks_over_4p5_angstrom": int(np.sum(ca_distances > 4.5)),
        },
        "peptide_continuity": {
            "max_c_to_n_distance_angstrom": round_float(np.max(peptide_distances), 3),
            "breaks_over_1p8_angstrom": int(np.sum(peptide_distances > 1.8)),
        },
        "backbone_geometry": {
            "finite_phi_psi_residues": int(np.sum(finite_phi_psi)),
            "coarse_canonical_basin_fraction": round_float(statistics.fmean(coarse_basin), 4),
            "note": "Broad fixed alpha/beta/left-alpha envelope; descriptive, not a MolProbity score.",
            "peptide_omega_over_30deg_from_trans": int(np.sum(omega_deviation > 30)),
            "max_peptide_omega_deviation_from_trans_degrees": round_float(np.max(omega_deviation), 2),
            "peptide_omega_outliers": omega_outliers,
        },
        "severe_heavy_atom_clashes": {
            "distance_cutoff_angstrom": 2.0,
            "nonlocal_pair_count": severe_clashes,
            "per_1000_heavy_atoms": round_float(severe_clashes * 1000 / len(heavy_coordinates), 3),
            "pairs": severe_clash_details,
            "note": "Hydrogen-free severe-clash screen; not a MolProbity clashscore.",
        },
        "plddt": {
            "pdb_b_factor_encoding": plddt_encoding,
            "mean": round_float(statistics.fmean(plddt), 2),
            "median": round_float(statistics.median(plddt), 2),
            "fraction_below_50": round_float(sum(value < 50 for value in plddt) / len(plddt), 4),
            "fraction_at_least_70": round_float(sum(value >= 70 for value in plddt) / len(plddt), 4),
            "fraction_at_least_90": round_float(sum(value >= 90 for value in plddt) / len(plddt), 4),
            "n_terminal_20_mean": round_float(statistics.fmean(plddt[:20]), 2),
            "c_terminal_20_mean": round_float(statistics.fmean(plddt[-20:]), 2),
        },
        "triad_local_confidence": triad_confidence,
        "secondary_structure_fraction": {
            "helix": round_float(sse_counts["a"] / len(sse), 4),
            "sheet": round_float(sse_counts["b"] / len(sse), 4),
            "coil": round_float(sse_counts["c"] / len(sse), 4),
        },
        "ca_radius_of_gyration_angstrom": round_float(radius_of_gyration, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--shard", required=True)
    parser.add_argument("--pdb-root", required=True)
    parser.add_argument("--references", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report_path = Path(args.report)
    shard_path = Path(args.shard)
    report = read_json(report_path)
    shard = read_json(shard_path)
    shard_rows = {str(row["sequence_sha256"]): row for row in shard["sequences"]}
    shortlist = [row for row in report["results"] if row["plddt_pass"]]
    shortlist_hashes = [str(row["sequence_sha256"]) for row in shortlist]
    primary_hashes = [str(row["sequence_sha256"]) for row in shortlist if row["full_structural_gate_pass"]]
    if len(shortlist) != 15 or set(primary_hashes) != PRIMARY_HASHES:
        raise RuntimeError("frozen shortlist membership changed")
    if compact_list_hash(shortlist_hashes) != SHORTLIST_HASH or compact_list_hash(primary_hashes) != PRIMARY_SET_HASH:
        raise RuntimeError("frozen shortlist identity hash changed")

    references = load_reference_records(Path(args.references))
    precompute_novelty_cache(references)
    family_stats = compute_family_stats(references)
    pdb_root = Path(args.pdb_root)
    rows = []
    for result in shortlist:
        sequence_sha = str(result["sequence_sha256"])
        sequence = str(shard_rows[sequence_sha]["sequence"])
        pdb_path = pdb_root / f"{sequence_sha}.pdb"
        metrics = structure_metrics(pdb_path, expected_sequence=sequence, triad=result["triad"])
        if metrics["pdb_sha256"] != result["pdb_sha256"]:
            raise RuntimeError(f"PDB hash differs from fold report: {sequence_sha}")
        family = evaluate_candidate(
            sequence=sequence,
            family_stats=family_stats,
            reference_records=references,
        )
        rows.append({
            "sequence_sha256": sequence_sha,
            "frozen_role": "primary_full_gate" if sequence_sha in PRIMARY_HASHES else "secondary_plddt_only",
            "source_job_key": result["slot_mappings"][0]["job_key"],
            "panel_role": result["discovery_panel_roles"][0],
            "fold_report": {
                "mean_plddt": result["mean_plddt"],
                "triad": result["triad"],
                "grade": result["grade"],
                "full_structural_gate_pass": result["full_structural_gate_pass"],
            },
            "local_structure_validation": metrics,
            "family_sequence_validation": {
                key: family[key]
                for key in (
                    "length",
                    "unique_residues",
                    "entropy",
                    "dominant_residue_fraction",
                    "length_in_family_band",
                    "serine_motifs",
                    "has_family_serine_motif",
                    "catalytic_geometry",
                    "novelty",
                    "passes_core_screen",
                )
            },
        })

    primary_rows = [row for row in rows if row["frozen_role"] == "primary_full_gate"]
    secondary_rows = [row for row in rows if row["frozen_role"] == "secondary_plddt_only"]
    payload = {
        "contract": "pearl.frontier-replication-salvage-orthogonal-local-validation/1",
        "status": "complete",
        "scope": "posthoc_exploratory_frozen_15_shortlist",
        "inputs": {
            "structure_report_sha256": sha256_file(report_path),
            "priority_shard_sha256": sha256_file(shard_path),
            "natural_references_sha256": sha256_file(Path(args.references)),
            "shortlist_hash": SHORTLIST_HASH,
            "primary_set_hash": PRIMARY_SET_HASH,
        },
        "methods": {
            "pdb_parser": "biotite 1.6.0",
            "severe_clash_distance_angstrom": 2.0,
            "ca_break_distance_angstrom": 4.5,
            "peptide_break_distance_angstrom": 1.8,
            "family_evaluator": "src/pearl/family.py existing immutable evaluator",
            "third_party_upload": False,
        },
        "summary": {
            "primary_count": len(primary_rows),
            "secondary_count": len(secondary_rows),
            "primary_with_complete_backbone": sum(
                row["local_structure_validation"]["backbone_complete_residues"]
                == row["local_structure_validation"]["residue_count"]
                for row in primary_rows
            ),
            "primary_with_no_chain_breaks": sum(
                row["local_structure_validation"]["ca_continuity"]["breaks_over_4p5_angstrom"] == 0
                and row["local_structure_validation"]["peptide_continuity"]["breaks_over_1p8_angstrom"] == 0
                for row in primary_rows
            ),
            "primary_with_no_severe_nonlocal_clashes": sum(
                row["local_structure_validation"]["severe_heavy_atom_clashes"]["nonlocal_pair_count"] == 0
                for row in primary_rows
            ),
            "primary_passing_existing_sequence_core_screen": sum(
                row["family_sequence_validation"]["passes_core_screen"] for row in primary_rows
            ),
        },
        "results": rows,
        "interpretation_boundary": {
            "descriptive_not_confirmatory": True,
            "new_candidates_promoted": 0,
            "gate_changed": False,
            "paid_compute_used": False,
        },
    }
    payload["validation_sha256"] = sha256_value(payload)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
