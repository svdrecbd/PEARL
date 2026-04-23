from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scripts import score_manifold_v12_repair_frontier


class ScoreManifoldV12RepairFrontierTests(unittest.TestCase):
    def test_score_rows_marks_ready_candidates(self) -> None:
        rows = [
            {
                "candidate_id": "a",
                "sequence": "A" * 50,
                "source_lane": "geometry_valid_needs_esm",
                "operation": "canonicalize_existing_motif",
                "strict_trainable_candidate": True,
                "passes_core_screen": True,
            },
            {
                "candidate_id": "b",
                "sequence": "C" * 50,
                "source_lane": "esm_valid_needs_geometry",
                "operation": "relocate_motif_repair_dh",
                "strict_trainable_candidate": True,
                "passes_core_screen": True,
            },
        ]

        scored = score_manifold_v12_repair_frontier.score_rows(
            rows,
            score_fn=lambda sequences: [92.0, 74.0],
            esm_threshold=85.0,
            batch_size=2,
        )
        summary = score_manifold_v12_repair_frontier.summarize(scored, esm_threshold=85.0)

        self.assertTrue(scored[0]["v12_ready_candidate"])
        self.assertFalse(scored[1]["v12_ready_candidate"])
        self.assertEqual(summary["v12_ready_candidates"], 1)
        self.assertEqual(summary["ready_by_lane"]["geometry_valid_needs_esm"], 1)


if __name__ == "__main__":
    unittest.main()
