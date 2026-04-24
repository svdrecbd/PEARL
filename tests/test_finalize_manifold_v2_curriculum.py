from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.finalize_manifold_v2_curriculum import build_curriculum


class FinalizeManifoldV2CurriculumTests(unittest.TestCase):
    def test_preserves_selected_metadata_and_writes_paid_gate_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            selected_path = root / "selected.jsonl"
            purebred_path = root / "purebred.jsonl"
            output_dir = root / "curriculum"
            selected_rows = [
                selected_row(index, parent_source=f"parent-{index}", length=240 + index)
                for index in range(3)
            ]
            write_jsonl(selected_path, selected_rows)
            write_jsonl(
                purebred_path,
                [
                    {
                        "accession": "PURE1",
                        "sequence": "ACDEFGHIKLMNPQRSTVWY" * 13,
                        "length": 260,
                    }
                ],
            )

            summary = build_curriculum(
                SimpleNamespace(
                    selected_path=str(selected_path),
                    purebred_path=str(purebred_path),
                    output_dir=str(output_dir),
                    output_name="curriculum.jsonl",
                    summary_name="summary.json",
                    purebred_top_k=1,
                    esm_threshold=85.0,
                    min_selected_for_paid_gate=3,
                    min_unique_parent_sources=3,
                    min_unique_lengths=3,
                    recipe_stage="manifold_stage_a_v2_test",
                )
            )

            rows = read_jsonl(output_dir / "curriculum.jsonl")
            selected = [row for row in rows if row["curriculum_role"] == "v2_selected_candidate"]
            self.assertEqual(3, len(selected))
            self.assertEqual("manifold_stage_a_v2_test", selected[0]["recipe_stage"])
            self.assertEqual("v2_scored_constructor_selected", selected[0]["strict_bucket"])
            self.assertEqual("parent-0", selected[0]["parent_source_key"])
            self.assertEqual("panel-0", selected[0]["parent_panel_id"])
            self.assertEqual({"strict_manifold_passes": True}, selected[0]["family_assessment"])
            self.assertEqual({"passes_core_screen": True}, selected[0]["core_evaluation"])
            self.assertTrue(selected[0]["strict_manifold_passes"])
            self.assertTrue(selected[0]["passes_core_screen"])
            self.assertTrue(selected[0]["esm_gate_pass"])
            self.assertEqual(selected[0]["prompt"], selected[0]["sequence_prompt"])
            self.assertTrue(summary["ready_for_paid_gate"])
            self.assertEqual(3, summary["selected_counts"]["strict_manifold_passes"])
            self.assertEqual(3, summary["selected_counts"]["passes_core_screen"])
            self.assertEqual(3, summary["selected_counts"]["unique_parent_sources"])


def selected_row(index: int, *, parent_source: str, length: int) -> dict[str, object]:
    sequence = ("ACDEFGHIKLMNPQRSTVWY" * 20)[:length]
    return {
        "candidate_id": f"v2-{index}",
        "sequence_id": f"v2-{index}",
        "sequence": sequence,
        "length": length,
        "prompt": f"Generate a sequence around {length} aa.",
        "source_prompt": f"Generate a sequence around {length} aa.",
        "sequence_prompt": f"Generate a sequence around {length} aa.",
        "parent_panel_id": f"panel-{index}",
        "parent_source_key": parent_source,
        "parent_panel_source": "support_repair_validated_strict",
        "selection_rank": index + 1,
        "mutation_count": 1,
        "esm_score": 95.0 + index,
        "family_assessment": {"strict_manifold_passes": True},
        "core_evaluation": {"passes_core_screen": True},
        "family_faithful_proxy_passes": True,
        "bridge_quality_passes": True,
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
