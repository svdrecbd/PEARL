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


if __name__ == "__main__":
    unittest.main()
