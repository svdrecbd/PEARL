from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scripts import build_manifold_v12_repair_frontier


class BuildManifoldV12RepairFrontierTests(unittest.TestCase):
    def test_builds_strict_frontier_from_motif_and_geometry_repairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            records_path = root / "records.jsonl"
            lanes_dir = root / "lanes"
            output_dir = root / "out"
            lanes_dir.mkdir()
            write_jsonl(records_path, [make_record("ref-a", strict_sequence())])

            geometry_sequence = mutate(strict_sequence(), {59: "F"})
            relocation_sequence = mutate(strict_sequence(), {58: "A", 59: "A", 60: "A", 61: "A", 62: "A", 115: "A", 128: "A"})
            relocation_sequence = put_motif(relocation_sequence, start=8, motif="GYSQG")

            write_jsonl(
                lanes_dir / "geometry_valid_needs_esm.jsonl",
                [
                    lane_row(
                        lane="geometry_valid_needs_esm",
                        mode="geometry_only",
                        sequence=geometry_sequence,
                        requested_length=len(geometry_sequence),
                    )
                ],
            )
            write_jsonl(
                lanes_dir / "esm_valid_needs_geometry.jsonl",
                [
                    lane_row(
                        lane="esm_valid_needs_geometry",
                        mode="stability_only",
                        sequence=relocation_sequence,
                        requested_length=len(relocation_sequence),
                    )
                ],
            )

            summary = build_manifold_v12_repair_frontier.build_frontier(
                SimpleNamespace(
                    lanes_dir=str(lanes_dir),
                    records_path=str(records_path),
                    output_dir=str(output_dir),
                    allowed_motifs="GYSLG",
                    max_input_per_lane=8,
                    max_output_candidates=100,
                    max_prompt_length_delta=40,
                    relocation_step=4,
                    relocation_window=8,
                )
            )

            self.assertGreaterEqual(summary["output_counts"]["strict_repair_frontier"], 2)
            self.assertIn("canonicalize_existing_motif", summary["output_counts"]["strict_by_operation"])
            self.assertIn("relocate_motif_repair_dh", summary["output_counts"]["strict_by_operation"])
            frontier = read_jsonl(output_dir / "strict_repair_frontier_pre_esm.jsonl")
            self.assertTrue(all(row["strict_manifold_passes"] for row in frontier))
            self.assertTrue(all(row["needs_esm_score"] for row in frontier))


def strict_sequence() -> str:
    residues = list(("ACDEFGHIKLMNPQRSTVWY" * 7)[:140])
    put(residues, 58, "G")
    put(residues, 59, "Y")
    put(residues, 60, "S")
    put(residues, 61, "L")
    put(residues, 62, "G")
    put(residues, 115, "D")
    put(residues, 128, "H")
    return "".join(residues)


def make_record(accession: str, sequence: str) -> dict[str, object]:
    return {
        "accession": accession,
        "sequence": sequence,
        "length": len(sequence),
        "active_sites": [
            {"start": 60},
            {"start": 115},
            {"start": 128},
        ],
    }


def lane_row(*, lane: str, mode: str, sequence: str, requested_length: int) -> dict[str, object]:
    return {
        "lane": lane,
        "mode": mode,
        "sequence": sequence,
        "length": len(sequence),
        "requested_length": requested_length,
        "length_delta": len(sequence) - requested_length,
        "selected": True,
        "seed": 41,
        "step": 0,
        "prompt": f"Generate a sequence with length near {requested_length} aa.",
        "raw_esm_score": 99.0 if lane == "esm_valid_needs_geometry" else 40.0,
        "geometry_score": 0.9 if lane == "geometry_valid_needs_esm" else 0.1,
        "best_gap_error": 0 if lane == "geometry_valid_needs_esm" else None,
    }


def mutate(sequence: str, mutations: dict[int, str]) -> str:
    residues = list(sequence)
    for position, residue in mutations.items():
        put(residues, position, residue)
    return "".join(residues)


def put_motif(sequence: str, *, start: int, motif: str) -> str:
    residues = list(sequence)
    for offset, residue in enumerate(motif):
        put(residues, start + offset, residue)
    return "".join(residues)


def put(residues: list[str], position: int, residue: str) -> None:
    residues[position - 1] = residue


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
