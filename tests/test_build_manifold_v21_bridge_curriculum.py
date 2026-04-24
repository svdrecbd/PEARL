from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.build_manifold_v21_bridge_curriculum import build_curriculum


class BuildManifoldV21BridgeCurriculumTests(unittest.TestCase):
    def test_builds_bridge_weighted_curriculum(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            selected_path = root / "selected.jsonl"
            v12_audit_path = root / "v12_audit.json"
            v2_audit_path = root / "v2" / "candidate_audit.json"
            support_path = root / "support.jsonl"
            purebred_path = root / "purebred.jsonl"
            output_dir = root / "out"

            write_jsonl(
                selected_path,
                [
                    selected_row("v2-a", 250, 1),
                    selected_row("v2-b", 275, 2),
                    selected_row("v2-c", 300, 3),
                ],
            )
            v12_audit_path.write_text(
                json.dumps(
                    {
                        "hit_prompt_steps": [7],
                        "hit_prompt_lengths": [240],
                        "hit_seed_records": [
                            {
                                "step": 7,
                                "seed": 53,
                                "run_name": "v12-p24-s53",
                                "prompt": "Generate a sequence with length near 240 aa.",
                                "requested_length": 240,
                                "selected_candidate": hit_candidate(260, family=True),
                            },
                            {
                                "step": 8,
                                "seed": 67,
                                "run_name": "v12-p24-s67",
                                "prompt": "Generate a sequence with length near 242 aa.",
                                "requested_length": 242,
                                "selected_candidate": hit_candidate(265, family=False),
                            },
                        ],
                        "prompt_records": [
                            {
                                "step": 2,
                                "prompt_count": 24,
                                "prompt": "Generate a sequence with length near 245 aa.",
                                "requested_length": 245,
                                "selected_any_geometry": True,
                                "selected_any_esm": False,
                                "all_any_geometry": True,
                                "all_any_esm": False,
                                "selected_mode_counts": {"geometry_only": 1},
                                "mean_abs_selected_length_delta": 12.0,
                            },
                            {
                                "step": 7,
                                "prompt_count": 24,
                                "prompt": "Generate a sequence with length near 240 aa.",
                                "requested_length": 240,
                                "selected_any_geometry": True,
                                "selected_any_esm": True,
                                "all_any_geometry": True,
                                "all_any_esm": True,
                                "selected_mode_counts": {"family_faithful": 1},
                                "mean_abs_selected_length_delta": 0.0,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            v2_audit_path.parent.mkdir(parents=True)
            v2_audit_path.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "step": 21,
                                "prompt": "Design a protein sequence inspired by Cutinase, length about 219 aa.",
                                "candidates": [
                                    {
                                        **hit_candidate(293, family=False),
                                        "selected": True,
                                        "extracted_sequence": seq(293, motif="GYSLG"),
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            write_jsonl(
                support_path,
                [
                    {
                        "sequence": seq(246, motif="GYSLG"),
                        "length": 246,
                        "family_faithful_bridge_passes": True,
                        "functional_bridge_passes": True,
                        "passes_core_screen": True,
                        "esm_score": 98.0,
                        "best_gap_error": 4,
                        "prompt": "support prompt",
                    }
                ],
            )
            write_jsonl(
                purebred_path,
                [{"accession": "PURE", "sequence": seq(240, motif="GYSLG"), "length": 240, "esm_score": 99.0}],
            )

            summary = build_curriculum(
                SimpleNamespace(
                    selected_path=str(selected_path),
                    v12_audit_path=str(v12_audit_path),
                    v2_candidate_audit_paths=[str(v2_audit_path)],
                    support_positive_paths=[str(support_path)],
                    purebred_path=str(purebred_path),
                    output_dir=str(output_dir),
                    output_name="curriculum.jsonl",
                    summary_name="summary.json",
                    max_v2_selected=3,
                    max_support_prompts=1,
                    support_window=20,
                    max_historical_support=1,
                    purebred_top_k=1,
                    v12_family_hit_repeat=2,
                    v12_bridge_hit_repeat=1,
                    v2_bridge_hit_repeat=1,
                    support_prompt_repeat=1,
                    historical_support_repeat=1,
                    purebred_repeat=1,
                    min_v2_selected=3,
                    min_measured_bridge_replay_rows=4,
                    min_family_faithful_replay_rows=2,
                    min_support_prompts=1,
                    recipe_stage="manifold_stage_a_v21_test",
                )
            )

            rows = read_jsonl(output_dir / "curriculum.jsonl")
            role_counts = summary["role_counts"]
            self.assertEqual(3, role_counts["v2_strict_breadth_anchor"])
            self.assertEqual(2, role_counts["v12_family_hit_replay"])
            self.assertEqual(1, role_counts["v12_bridge_hit_replay"])
            self.assertEqual(1, role_counts["v2_bridge_hit_replay"])
            self.assertEqual(1, role_counts["v21_bridge_prompt_anchor"])
            self.assertEqual(1, role_counts["historical_family_faithful_anchor"])
            self.assertEqual(1, role_counts["purebred_anchor"])
            self.assertTrue(summary["readiness"]["ready_for_stage_a_diagnostic_train"])
            self.assertEqual([2], summary["support_prompt_steps"])
            self.assertTrue(any(row["prompt_source"] == "v12_p24_support_prompt_replay" for row in rows))


def selected_row(candidate_id: str, length: int, rank: int) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "sequence_id": candidate_id,
        "sequence": seq(length, motif="GYSLG"),
        "length": length,
        "selection_rank": rank,
        "esm_score": 99.0,
        "family_faithful_proxy_passes": True,
        "bridge_quality_passes": True,
        "family_faithful_bridge_passes": True,
        "functional_bridge_passes": True,
        "passes_core_screen": True,
        "blueprint": {"motif": "GYSLG"},
        "prompt": f"Generate a sequence around {length} amino acids long.",
    }


def hit_candidate(length: int, *, family: bool) -> dict[str, object]:
    return {
        "sequence": seq(length, motif="GYSLG"),
        "length": length,
        "functional_bridge_passes": True,
        "family_faithful_bridge_passes": family,
        "esm_gate_pass": True,
        "geometry_passes": True,
        "passes_core_screen": True,
        "raw_esm_score": 96.0,
        "best_gap_error": 5,
        "motif_count": 1,
        "has_family_serine_motif": True,
    }


def seq(length: int, *, motif: str) -> str:
    left = "A" * 20
    right_len = max(0, length - len(left) - len(motif))
    return left + motif + ("D" * right_len)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
