from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BuildManifoldV13CurriculumTests(unittest.TestCase):
    def test_builds_base_support_and_hit_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_selected_path = root / "base_selected.jsonl"
            scaffold_path = root / "scaffolds.jsonl"
            audit_path = root / "audit.json"
            prompts_path = root / "prompts.jsonl"
            purebred_path = root / "purebreds.jsonl"
            output_path = root / "stage_a.jsonl"
            summary_path = root / "summary.json"

            write_jsonl(
                base_selected_path,
                [
                    base_row("base-1", 214, "parent-a", 1),
                    base_row("base-2", 236, "parent-b", 2),
                ],
            )
            write_jsonl(
                scaffold_path,
                [
                    scaffold_row("scaf-220", 220),
                    scaffold_row("scaf-224", 224),
                ],
            )
            audit_path.write_text(
                json.dumps(
                    {
                        "hit_prompt_steps": [7],
                        "hit_prompt_lengths": [215],
                        "hit_seed_records": [
                            {
                                "step": 7,
                                "seed": 53,
                                "prompt": "Generate a sequence with length near 215 aa.",
                                "requested_length": 215,
                                "selected_candidate": {
                                    "sequence": sequence(300),
                                    "functional_bridge_passes": True,
                                    "family_faithful_bridge_passes": True,
                                    "esm_gate_pass": True,
                                    "geometry_passes": True,
                                    "raw_esm_score": 96.0,
                                },
                            }
                        ],
                        "prompt_records": [
                            {
                                "step": 4,
                                "prompt_count": 24,
                                "prompt": "Generate a sequence with length near 224 aa.",
                                "requested_length": 224,
                                "selected_any_geometry": True,
                                "selected_any_esm": False,
                                "all_any_geometry": True,
                                "all_any_esm": False,
                                "selected_mode_counts": {"geometry_only": 1},
                                "all_candidate_mode_counts": {"geometry_only": 2},
                                "mean_abs_selected_length_delta": 12.0,
                                "seed_records": [],
                            },
                            {
                                "step": 7,
                                "prompt_count": 24,
                                "prompt": "Generate a sequence with length near 215 aa.",
                                "requested_length": 215,
                                "selected_any_geometry": True,
                                "selected_any_esm": True,
                                "all_any_geometry": True,
                                "all_any_esm": True,
                                "selected_mode_counts": {"family_faithful": 1},
                                "all_candidate_mode_counts": {"family_faithful": 1},
                                "mean_abs_selected_length_delta": 40.0,
                                "seed_records": [],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            prompts_path.write_text("", encoding="utf-8")
            write_jsonl(purebred_path, [purebred_row("pure-1", 214)])

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_manifold_v13_curriculum.py"),
                    "--base-selected-path",
                    str(base_selected_path),
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
                    "--support-prompt-limit",
                    "2",
                    "--support-replay-repeat",
                    "1",
                    "--hit-replay-repeat",
                    "2",
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

            self.assertEqual(summary["dataset_count"], 6)
            self.assertEqual(summary["role_counts"]["v12_breadth_anchor"], 2)
            self.assertEqual(summary["role_counts"]["support_prompt_anchor"], 1)
            self.assertEqual(summary["role_counts"]["family_hit_replay"], 2)
            self.assertEqual(summary["role_counts"]["purebred_anchor"], 1)
            self.assertEqual(summary["support_prompt_steps"], [4])
            self.assertEqual(summary["hit_prompt_steps"], [7])
            self.assertTrue(any(row["prompt_source"] == "v12_p24_support_prompt_replay" for row in rows))


def base_row(sequence_id: str, length: int, parent: str, rank: int) -> dict[str, object]:
    prompt = f"Generate a polyester-hydrolase-family cutinase sequence around {length} amino acids long."
    return {
        "sequence_id": sequence_id,
        "candidate_id": sequence_id,
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
        "prompt": prompt,
        "prompt_id": f"prompt:{sequence_id}",
        "prompt_source": "synthetic_v12_retargeted_prompt",
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
