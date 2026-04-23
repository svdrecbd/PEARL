from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BuildManifoldV11CurriculumTests(unittest.TestCase):
    def test_builds_balanced_rows_and_p24_replay_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            selected_path = root / "selected.jsonl"
            scaffold_path = root / "scaffolds.jsonl"
            audit_path = root / "audit.json"
            prompts_path = root / "prompts.jsonl"
            purebred_path = root / "purebreds.jsonl"
            output_path = root / "stage_a.jsonl"
            summary_path = root / "summary.json"

            write_jsonl(
                selected_path,
                [
                    selected_row("sel-1", 214, "parent-a", 1),
                    selected_row("sel-2", 214, "parent-b", 2),
                    selected_row("sel-3", 228, "parent-c", 3),
                ],
            )
            write_jsonl(
                scaffold_path,
                [
                    scaffold_row("scaf-214", 214),
                    scaffold_row("scaf-215", 215),
                ],
            )
            audit_path.write_text(
                json.dumps(
                    {
                        "prompt_records": [
                            {
                                "prompt_count": 24,
                                "step": 0,
                                "prompt": "Generate a novel polyester hydrolase sequence with length near 214 aa.",
                                "requested_length": 214,
                                "replay_role": "p24_hole",
                                "seed_records": [],
                            },
                            {
                                "prompt_count": 24,
                                "step": 1,
                                "prompt": "Generate a novel polyester hydrolase sequence with length near 215 aa.",
                                "requested_length": 215,
                                "replay_role": "p24_weak_hit",
                                "seed_records": [],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            prompts_path.write_text("", encoding="utf-8")
            write_jsonl(purebred_path, [purebred_row("pure-1", 214)])

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_manifold_v11_curriculum.py"),
                    "--selected-path",
                    str(selected_path),
                    "--scaffold-bank-path",
                    str(scaffold_path),
                    "--audit-path",
                    str(audit_path),
                    "--prompts-path",
                    str(prompts_path),
                    "--purebred-path",
                    str(purebred_path),
                    "--output-path",
                    str(output_path),
                    "--summary-path",
                    str(summary_path),
                    "--base-selected-count",
                    "2",
                    "--base-max-per-length",
                    "1",
                    "--p24-replay-repeat",
                    "1",
                    "--purebred-top-k",
                    "1",
                    "--purebred-repeat",
                    "1",
                ],
                check=True,
                cwd=ROOT,
            )

            rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

            self.assertEqual(summary["dataset_count"], 5)
            self.assertEqual(summary["role_counts"]["balanced_phase2_anchor"], 2)
            self.assertEqual(summary["role_counts"]["p24_hole_anchor"], 1)
            self.assertEqual(summary["role_counts"]["p24_weak_hit_anchor"], 1)
            self.assertEqual(summary["role_counts"]["purebred_anchor"], 1)
            self.assertTrue(any(row["prompt_source"] == "v1_p24_prompt_replay" for row in rows))
            self.assertEqual(summary["anchor_length_delta"]["mean_abs"], 0.0)


def selected_row(sequence_id: str, length: int, parent: str, rank: int) -> dict[str, object]:
    return {
        "sequence_id": sequence_id,
        "sequence": sequence(length),
        "length": length,
        "parent_sequence_id": parent,
        "selection_rank": rank,
        "mutation_count": 1,
        "esm_score": 99.0,
        "bridge_quality_passes": True,
        "blueprint": {"motif": "GYSLG"},
        "strict_manifold_passes": True,
        "family_manifold_passes": True,
    }


def scaffold_row(sequence_id: str, length: int) -> dict[str, object]:
    return {
        "sequence_id": sequence_id,
        "sequence": sequence(length),
        "length": length,
        "source_roles": ["reference_scaffold"],
        "strict_manifold_passes": True,
        "family_manifold_passes": True,
        "negative_example": False,
        "blueprint": {"motif": "GYSLG", "gap_error": 1},
    }


def purebred_row(accession: str, length: int) -> dict[str, object]:
    return {
        "accession": accession,
        "sequence": sequence(length),
        "length": length,
        "esm_score": 98.0,
        "blueprint": {"motif": "GYSLG"},
    }


def sequence(length: int) -> str:
    motif = "GYSLG"
    if length <= len(motif):
        return motif[:length]
    left = "A" * 10
    right_len = max(0, length - len(left) - len(motif))
    return left + motif + ("D" * right_len)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
