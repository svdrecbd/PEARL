from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from scripts.select_manifold_v12_repair_candidates import run_selection


class SelectManifoldV12RepairCandidatesTest(unittest.TestCase):
    def test_selects_esm_strict_rows_with_source_and_length_balance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            scored_path = root / "scored.jsonl"
            output_path = root / "selected.jsonl"
            summary_path = root / "summary.json"
            rows = [
                scored_row(
                    "aaa",
                    "ACDEFGHIKLMNPQRSTVWY" * 15,
                    score=96.0,
                    source_seed=1,
                    source_step=12,
                    requested_length=240,
                ),
                scored_row(
                    "bbb",
                    "CDEFGHIKLMNPQRSTVWYA" * 15,
                    score=94.0,
                    source_seed=2,
                    source_step=12,
                    requested_length=240,
                ),
                scored_row(
                    "ccc",
                    "DEFGHIKLMNPQRSTVWYAC" * 15,
                    score=70.0,
                    source_seed=3,
                    source_step=12,
                    requested_length=240,
                ),
                scored_row(
                    "ddd",
                    "EFGHIKLMNPQRSTVWYACD" * 15,
                    score=97.0,
                    source_seed=4,
                    source_step=12,
                    requested_length=180,
                    strict=False,
                ),
                scored_row(
                    "aaa-duplicate",
                    "ACDEFGHIKLMNPQRSTVWY" * 15,
                    score=91.0,
                    source_seed=9,
                    source_step=12,
                    requested_length=240,
                ),
            ]
            write_jsonl(scored_path, rows)

            summary = run_selection(
                argparse.Namespace(
                    scored_path=[str(scored_path)],
                    output_path=str(output_path),
                    summary_path=str(summary_path),
                    esm_threshold=85.0,
                    max_candidates=10,
                    max_per_source=1,
                    length_bin_size=10,
                    max_per_length_bin=10,
                    max_original_prompt_delta=100,
                    min_selected_for_paid_gate=2,
                    min_unique_sources_for_paid_gate=2,
                    min_unique_lengths_for_paid_gate=1,
                    recipe_stage="manifold_stage_a_v12_test",
                )
            )

            selected = read_jsonl(output_path)
            self.assertEqual(2, len(selected))
            self.assertEqual(2, summary["counts"]["selected_rows"])
            self.assertEqual(2, summary["counts"]["unique_sources"])
            self.assertTrue(summary["ready_for_paid_gate"])
            self.assertEqual("aaa", selected[0]["candidate_id"])
            self.assertEqual("synthetic_v12_retargeted_prompt", selected[0]["prompt_source"])
            self.assertIn("300 amino acids", selected[0]["prompt"])
            self.assertEqual(0, selected[0]["prompt_length_delta"])
            self.assertEqual(60, selected[0]["original_prompt_length_delta"])
            self.assertTrue(selected[0]["bridge_quality_passes"])

    def test_length_bin_cap_limits_near_duplicate_lengths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            scored_path = root / "scored.jsonl"
            output_path = root / "selected.jsonl"
            summary_path = root / "summary.json"
            rows = [
                scored_row(
                    f"cand-{index}",
                    ("ACDEFGHIKLMNPQRSTVWY" * 15) + ("A" * index),
                    score=99.0 - index,
                    source_seed=index,
                    source_step=12,
                    requested_length=300,
                )
                for index in range(4)
            ]
            write_jsonl(scored_path, rows)

            summary = run_selection(
                argparse.Namespace(
                    scored_path=[str(scored_path)],
                    output_path=str(output_path),
                    summary_path=str(summary_path),
                    esm_threshold=85.0,
                    max_candidates=10,
                    max_per_source=1,
                    length_bin_size=10,
                    max_per_length_bin=2,
                    max_original_prompt_delta=100,
                    min_selected_for_paid_gate=3,
                    min_unique_sources_for_paid_gate=3,
                    min_unique_lengths_for_paid_gate=3,
                    recipe_stage="manifold_stage_a_v12_test",
                )
            )

            selected = read_jsonl(output_path)
            self.assertEqual(2, len(selected))
            self.assertFalse(summary["ready_for_paid_gate"])


def scored_row(
    candidate_id: str,
    sequence: str,
    *,
    score: float,
    source_seed: int,
    source_step: int,
    requested_length: int,
    strict: bool = True,
) -> dict[str, object]:
    length = len(sequence)
    return {
        "candidate_id": candidate_id,
        "sequence": sequence,
        "length": length,
        "requested_length": requested_length,
        "prompt_length_delta": length - requested_length,
        "prompt_length_ok": abs(length - requested_length) <= 40,
        "prompt": f"Generate a sequence around {requested_length} aa.",
        "source_lane": "esm_valid_needs_geometry",
        "source_mode": "test",
        "source_seed": source_seed,
        "source_step": source_step,
        "source_selected": False,
        "source_raw_esm_score": 95.0,
        "operation": "relocate_motif_repair_dh",
        "mutation_count": 6,
        "strict_manifold_passes": strict,
        "passes_core_screen": True,
        "esm_score": score,
        "blueprint": {"motif": "GYSLG"},
    }


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
