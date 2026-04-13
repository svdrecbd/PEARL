from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl import strict_curricula as MODULE


def strict_row(*, prompt: str, cluster_id: str, reward: float) -> dict[str, object]:
    return {
        "prompt": prompt,
        "sequence": f"SEQ_{cluster_id}_{int(reward * 10)}",
        "cluster_id": cluster_id,
        "reward": reward,
        "esm_reward": reward,
        "best_gap_error": 0.1,
        "stage1_rank": 1,
        "stage2_rank": 1,
        "cluster_size": 1,
        "family_faithful_bridge_passes": True,
        "passes_core_screen": True,
        "catalytic_geometry_passes": True,
    }


def repair_row(*, prompt: str, source_run: str, sequence: str, esm_score: float) -> dict[str, object]:
    return {
        "sequence": sequence,
        "source_prompt": prompt,
        "source_parent_run": source_run,
        "source_step": 1,
        "strict_family": True,
        "strict_bridge": True,
        "strict_consensus": True,
        "esm_score": esm_score,
        "source_mutation_count": 1,
        "validated_passes_core_screen": True,
        "validated_geometry_passes": True,
        "validated_family_motif": True,
        "validated_novelty_identity": 0.2,
        "family_evaluation": {
            "length": len(sequence),
            "serine_motifs": ["GYSLG"],
            "catalytic_geometry": {"best_gap_error": 3},
        },
    }


class StrictCurriculaTests(unittest.TestCase):
    def test_prompt_cluster_selector_enforces_diversity(self) -> None:
        rows = [
            strict_row(prompt="Generate PETase around 210 aa motif A", cluster_id="c1", reward=10.0),
            strict_row(prompt="Generate PETase around 240 aa motif B", cluster_id="c2", reward=9.0),
            strict_row(prompt="Generate PETase around 270 aa motif C", cluster_id="c3", reward=8.0),
        ]
        selected = MODULE.select_prompt_cluster_diverse_rows(rows, top_k=2, ranker="strict", label="strict")
        self.assertEqual(len(selected), 2)
        self.assertEqual(len({MODULE.prompt_key(row) for row in selected}), 2)
        self.assertEqual(len({MODULE.prompt_bucket_key(row) for row in selected}), 2)
        self.assertEqual(len({MODULE.cluster_key(row) for row in selected}), 2)

    def test_prompt_cluster_selector_fails_loudly_on_bucket_shortfall(self) -> None:
        rows = [
            strict_row(prompt="Generate PETase around 210 aa motif A", cluster_id="c1", reward=10.0),
            strict_row(prompt="Generate PETase around 240 aa motif A", cluster_id="c2", reward=9.0),
        ]
        with self.assertRaises(SystemExit) as exc:
            MODULE.select_prompt_cluster_diverse_rows(rows, top_k=2, ranker="strict", label="strict")
        self.assertIn("selection shortfall", str(exc.exception))

    def test_prepare_repair_rows_and_source_cluster_selection_spreads_sources(self) -> None:
        rows = [
            repair_row(
                prompt="Generate PETase around 210 aa motif A",
                source_run="run-a",
                sequence="M" + "A" * 30 + "GYSLG" + "C" * 30,
                esm_score=99.0,
            ),
            repair_row(
                prompt="Generate PETase around 220 aa motif A",
                source_run="run-a",
                sequence="M" + "A" * 31 + "GYSLG" + "C" * 29,
                esm_score=98.5,
            ),
            repair_row(
                prompt="Generate PETase around 230 aa motif B",
                source_run="run-b",
                sequence="M" + "D" * 30 + "GYSLG" + "E" * 30,
                esm_score=98.0,
            ),
        ]

        prepared = MODULE.prepare_repair_strict_rows(rows, identity_threshold=0.95)
        selected = MODULE.select_source_cluster_diverse_rows(
            prepared,
            top_k=2,
            ranker="strict",
            label="repair_strict",
            max_per_source=1,
            max_per_cluster=1,
        )

        self.assertEqual(len(selected), 2)
        self.assertEqual({row["source_run"] for row in selected}, {"run-a", "run-b"})

    def test_build_stage_a_dataset_includes_repair_bucket(self) -> None:
        dataset, summary = MODULE.build_stage_a_dataset(
            old_rows=[strict_row(prompt="old", cluster_id="o1", reward=10.0)],
            new_rows=[strict_row(prompt="new", cluster_id="n1", reward=9.0)],
            repair_rows=[strict_row(prompt="repair", cluster_id="r1", reward=8.0)],
            pure_rows=[{"sequence": "MGYSLGAAA", "prompt": "pure", "esm_score": 1.0}],
            old_repeat=2,
            new_repeat=3,
            repair_repeat=2,
            pure_repeat=1,
        )

        self.assertEqual(summary["source_counts"]["repair_family_faithful"], 2)
        self.assertEqual(summary["bucket_counts"]["repair_family_faithful"], 2)
        self.assertEqual(len(dataset), 8)


if __name__ == "__main__":
    unittest.main()
