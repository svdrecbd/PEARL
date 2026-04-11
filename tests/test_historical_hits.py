from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.historical_hits import classify_anchor_opportunity, discover_finalized_wave_dirs


class HistoricalHitsTests(unittest.TestCase):
    def test_discover_finalized_wave_dirs_honors_include_and_exclude_globs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir)
            keep = reports_root / "wave_keep"
            drop = reports_root / "wave_drop"
            keep.mkdir(parents=True)
            drop.mkdir(parents=True)
            (keep / "finalization_summary.json").write_text("{}", encoding="utf-8")
            (drop / "finalization_summary.json").write_text("{}", encoding="utf-8")

            discovered = discover_finalized_wave_dirs(
                reports_root,
                include_globs=["wave_*"],
                exclude_globs=["*drop*"],
            )
            self.assertEqual([path.resolve() for path in discovered], [keep.resolve()])

    def test_classify_anchor_opportunity_green_and_red(self) -> None:
        green_report = {
            "neighbors_by_identity": {
                "0.95": {
                    "neighbor_count": 4,
                    "strict_neighbor_count": 1,
                    "bridge_only_neighbor_count": 3,
                }
            }
        }
        red_report = {
            "neighbors_by_identity": {
                "0.95": {
                    "neighbor_count": 1,
                    "strict_neighbor_count": 0,
                    "bridge_only_neighbor_count": 1,
                },
                "0.85": {
                    "neighbor_count": 2,
                    "strict_neighbor_count": 0,
                    "bridge_only_neighbor_count": 2,
                },
            }
        }
        self.assertEqual(classify_anchor_opportunity(green_report), "green")
        self.assertEqual(classify_anchor_opportunity(red_report), "red")

    def test_classify_anchor_opportunity_yellow_for_dense_near_neighbors(self) -> None:
        yellow_report = {
            "neighbors_by_identity": {
                "0.95": {
                    "neighbor_count": 3,
                    "strict_neighbor_count": 0,
                    "bridge_only_neighbor_count": 0,
                }
            }
        }
        self.assertEqual(classify_anchor_opportunity(yellow_report), "yellow")


if __name__ == "__main__":
    unittest.main()
