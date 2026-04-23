from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BuildManifoldCurriculumTests(unittest.TestCase):
    def test_builds_prompted_stage_a_rows_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            selected_path = root / "selected.jsonl"
            prompts_path = root / "prompts.jsonl"
            purebred_path = root / "purebreds.jsonl"
            output_path = root / "stage_a.jsonl"
            summary_path = root / "summary.json"

            write_jsonl(
                selected_path,
                [
                    {
                        "sequence_id": "sel-1",
                        "selection_rank": 1,
                        "sequence": "A" * 20 + "GYSLG" + "D" * 55 + "H" + "A" * 20,
                        "length": 101,
                        "mutation_count": 1,
                        "esm_score": 99.1,
                        "bridge_quality_passes": True,
                        "blueprint": {"motif": "GYSLG"},
                    },
                    {
                        "sequence_id": "sel-2",
                        "selection_rank": 2,
                        "sequence": "C" * 20 + "GYSQG" + "D" * 55 + "H" + "C" * 20,
                        "length": 101,
                        "mutation_count": 2,
                        "esm_score": 99.0,
                        "bridge_quality_passes": False,
                        "blueprint": {"motif": "GYSQG"},
                    },
                ],
            )
            write_jsonl(
                prompts_path,
                [
                    {
                        "prompt_id": "p1",
                        "prompt": "Generate a polyester-hydrolase-family cutinase sequence around 100 amino acids long.",
                        "length": 100,
                        "relevance_score": 10,
                    },
                    {
                        "prompt_id": "p2",
                        "prompt": "Generate a novel polyester hydrolase sequence with length near 102 aa.",
                        "length": 102,
                        "relevance_score": 11,
                    },
                ],
            )
            write_jsonl(
                purebred_path,
                [
                    {
                        "accession": "pure-1",
                        "sequence": "M" * 20 + "GYSLG" + "D" * 55 + "H" + "M" * 20,
                        "length": 101,
                        "esm_score": 98.0,
                    }
                ],
            )

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_manifold_curriculum.py"),
                    "--selected-path",
                    str(selected_path),
                    "--prompts-path",
                    str(prompts_path),
                    "--purebred-path",
                    str(purebred_path),
                    "--output-path",
                    str(output_path),
                    "--summary-path",
                    str(summary_path),
                    "--purebred-repeat",
                    "2",
                ],
                check=True,
                cwd=ROOT,
            )

            rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

            self.assertEqual(len(rows), 4)
            self.assertEqual(summary["dataset_count"], 4)
            self.assertEqual(summary["selected_dataset_rows"], 2)
            self.assertEqual(summary["purebred_dataset_rows"], 2)
            self.assertTrue(all(row["prompt"] for row in rows))
            self.assertTrue(all(row["sequence_prompt"] for row in rows))
            self.assertEqual(rows[0]["curriculum_source"], "manifold_phase2_selected")
            self.assertEqual(rows[-1]["curriculum_source"], "canonical_purebred")


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
