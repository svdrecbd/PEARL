from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scripts import manifold_construction_experiment


class ManifoldConstructionExperimentTests(unittest.TestCase):
    def test_phase1_roundtrip_accepts_strict_positive_and_rejects_negative(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = write_test_fixture(root)
            config = manifold_construction_experiment.load_config(config_path)

            summary = manifold_construction_experiment.build_bank(config)
            report = manifold_construction_experiment.validate_roundtrip(config)

            self.assertEqual(summary["counts"]["strict_candidate_positives"], 1)
            self.assertEqual(summary["counts"]["negative_examples"], 1)
            self.assertEqual(summary["counts"]["negative_family_manifold_passes"], 0)
            self.assertTrue(report["ready"])
            self.assertEqual(report["failures"], [])

            bank_path = Path(summary["outputs"]["scaffold_bank"])
            rows = [json.loads(line) for line in bank_path.read_text(encoding="utf-8").splitlines()]
            strict_rows = [row for row in rows if "strict_positive" in row["source_roles"]]
            self.assertEqual(len(strict_rows), 1)
            self.assertTrue(strict_rows[0]["blueprint"]["passes"])
            self.assertEqual(strict_rows[0]["edit_mask"]["locked_count"], 7)

    def test_phase2_frontier_stops_before_esm_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = write_test_fixture(root)
            config = manifold_construction_experiment.load_config(config_path)

            manifold_construction_experiment.build_bank(config)
            report = manifold_construction_experiment.build_phase2_frontier(config)

            self.assertTrue(report["stopped_before_esm_scoring"])
            self.assertGreater(report["counts"]["frontier_candidates"], 0)

            frontier_path = Path(report["outputs"]["phase2_frontier"])
            rows = [json.loads(line) for line in frontier_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(all(row["needs_esm_score"] for row in rows))
            self.assertTrue(all(row["esm_score"] is None for row in rows))
            self.assertTrue(all(row["strict_manifold_passes"] for row in rows))
            self.assertTrue(all(len(row["sequence"]) == len(strict_sequence_fixture()) for row in rows))

    def test_phase2_selection_uses_scored_frontier_and_reports_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = write_test_fixture(root)
            config = manifold_construction_experiment.load_config(config_path)

            manifold_construction_experiment.build_bank(config)
            frontier_report = manifold_construction_experiment.build_phase2_frontier(config)
            paths = manifold_construction_experiment.output_paths(config)
            frontier_rows = [
                json.loads(line)
                for line in Path(frontier_report["outputs"]["phase2_frontier"])
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            scored_rows = []
            for row in frontier_rows:
                payload = dict(row)
                payload["esm_score"] = 97.0
                payload["needs_esm_score"] = False
                payload["phase"] = "phase2_esm_scored"
                scored_rows.append(payload)
            write_jsonl(paths["phase2_scored"], scored_rows)

            report = manifold_construction_experiment.select_phase2(config)

            self.assertTrue(report["ready_for_curriculum_build"])
            self.assertGreater(report["selected_counts"]["selected"], 0)
            self.assertEqual(report["selected_counts"]["parent_scaffolds"], 1)
            self.assertEqual(report["input_counts"]["scored_candidates"], len(scored_rows))

            selected_path = Path(report["outputs"]["phase2_selected"])
            selected_rows = [json.loads(line) for line in selected_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(all(row["esm_score"] >= 95.0 for row in selected_rows))
            self.assertTrue(all("selection_rank" in row for row in selected_rows))
            self.assertTrue(all("bridge_quality_passes" in row for row in selected_rows))

    def test_describe_reports_optional_missing_negative_source_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = write_test_fixture(root, include_negative=False)
            config = manifold_construction_experiment.load_config(config_path)
            description = manifold_construction_experiment.describe(config)

            self.assertFalse(description["sources"]["negative_rejects"]["exists"])
            report = manifold_construction_experiment.validate_roundtrip(config)
            self.assertTrue(report["ready"])


def write_test_fixture(root: Path, *, include_negative: bool = True) -> Path:
    records_path = root / "records.jsonl"
    positives_path = root / "strict_positive.jsonl"
    negative_path = root / "negative.jsonl"
    output_dir = root / "reports"

    records = [
        make_record("ref-a", mutate(make_sequence(), {10: "Y"})),
        make_record("ref-b", mutate(make_sequence(), {20: "F"})),
        make_record("ref-c", mutate(make_sequence(), {30: "W"})),
    ]
    write_jsonl(records_path, records)

    strict_sequence = mutate(make_sequence(), {12: "M", 34: "L"})
    write_jsonl(
        positives_path,
        [
            {
                "sequence": strict_sequence,
                "esm_score": 97.5,
                "strict_family": True,
            }
        ],
    )

    if include_negative:
        write_jsonl(
            negative_path,
            [
                {
                    "sequence": "ACDEFGHIKLMNPQRSTVWY" * 4,
                    "esm_score": 96.0,
                    "strict_family": False,
                }
            ],
        )

    config = {
        "name": "test-manifold",
        "records_path": str(records_path),
        "output_dir": str(output_dir),
        "sources": [
            {
                "name": "references",
                "path": str(records_path),
                "role": "reference_scaffold",
                "required": True,
            },
            {
                "name": "known_positive",
                "path": str(positives_path),
                "role": "strict_positive",
                "required": True,
            },
            {
                "name": "negative_rejects",
                "path": str(negative_path),
                "role": "negative",
                "required": False,
            },
        ],
        "validation": {
            "min_family_manifold_scaffolds": 1,
            "min_strict_manifold_scaffolds": 1,
            "min_strict_candidate_positives": 1,
            "max_strict_positive_rejects": 0,
            "max_negative_family_manifold_passes": 0,
            "require_negative_rows_if_source_exists": True,
        },
        "phase2": {
            "parent_source": "strict_candidate_passes",
            "max_parent_scaffolds": 1,
            "mutation_depths": [1, 2],
            "max_mutable_positions_per_scaffold": 8,
            "residues_per_position": 2,
            "min_position_support": 1,
            "relative_profile_bins": 20,
            "max_proposals_per_scaffold": 64,
            "max_candidates_per_parent": 16,
            "max_frontier_candidates": 16,
            "require_strict_manifold": True,
        },
        "phase2_selection": {
            "max_selected": 4,
            "min_esm_score": 95.0,
            "bridge_gap_error_max": 20,
            "max_per_parent": 4,
            "max_length_share": 1.0,
            "max_per_mutation_depth": {
                "1": 4,
                "2": 4,
            },
            "max_per_parent_mutation_depth": {
                "1": 4,
                "2": 4,
            },
            "readiness": {
                "min_selected": 1,
                "min_parent_scaffolds": 1,
                "min_unique_lengths": 1,
                "min_bridge_quality_rows": 1,
                "min_bridge_quality_parents": 1,
                "min_two_mutants": 0,
                "max_parent_share": 1.0,
                "max_length_share": 1.0,
            },
        },
    }
    config_path = root / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def strict_sequence_fixture() -> str:
    return mutate(make_sequence(), {12: "M", 34: "L"})


def make_sequence() -> str:
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


def mutate(sequence: str, mutations: dict[int, str]) -> str:
    residues = list(sequence)
    for position, residue in mutations.items():
        put(residues, position, residue)
    return "".join(residues)


def put(residues: list[str], position: int, residue: str) -> None:
    residues[position - 1] = residue


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
