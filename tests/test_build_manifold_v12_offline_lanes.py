from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scripts import build_manifold_v12_offline_lanes
from tests.test_audit_manifold_v11_gate import candidate, write_json


class BuildManifoldV12OfflineLanesTests(unittest.TestCase):
    def test_builds_repair_and_negative_lanes_from_failed_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            suite_dir = root / "reports" / "robustness" / "suite-v11"
            run_dir = root / "reports" / "ablations" / "suite-v11-p24-t0p8-s41"
            out_dir = root / "reports" / "analysis" / "lanes"
            suite_dir.mkdir(parents=True)
            run_dir.mkdir(parents=True)
            summary_path = suite_dir / "robustness_summary.json"
            audit_path = run_dir / "candidate_audit.json"

            write_json(
                summary_path,
                {
                    "suite_name": "suite-v11",
                    "completed_run_count": 1,
                    "missing_run_count": 0,
                    "durability_gate": {"passed": False},
                    "groups": [
                        {
                            "prompt_count": 24,
                            "temperature": 0.8,
                            "runs": [
                                {
                                    "run_name": "suite-v11-p24-t0p8-s41",
                                    "seed": 41,
                                    "summary_path": str(run_dir / "summary.json"),
                                }
                            ],
                        }
                    ],
                },
            )
            write_json(
                audit_path,
                {
                    "records": [
                        {
                            "step": 0,
                            "prompt": "Generate a sequence with length near 220 aa.",
                            "candidates": [
                                candidate(
                                    selected=True,
                                    motif_count=1,
                                    geometry_passes=True,
                                    esm_gate_pass=False,
                                    length=280,
                                ),
                                candidate(
                                    selected=False,
                                    motif_count=1,
                                    geometry_passes=False,
                                    esm_gate_pass=True,
                                    length=221,
                                ),
                                candidate(
                                    selected=False,
                                    motif_count=1,
                                    geometry_passes=False,
                                    esm_gate_pass=False,
                                    length=222,
                                ),
                                candidate(
                                    selected=False,
                                    motif_count=2,
                                    geometry_passes=False,
                                    esm_gate_pass=False,
                                    length=223,
                                ),
                            ],
                        }
                    ]
                },
            )

            summary = build_manifold_v12_offline_lanes.build_lanes(
                SimpleNamespace(
                    robustness_summary_path=str(summary_path),
                    ablation_root=str(root / "reports" / "ablations"),
                    output_dir=str(out_dir),
                    max_per_lane=10,
                    length_delta_threshold=40,
                )
            )

            self.assertEqual(summary["raw_lane_counts"]["geometry_valid_needs_esm"], 1)
            self.assertEqual(summary["raw_lane_counts"]["esm_valid_needs_geometry"], 1)
            self.assertEqual(summary["raw_lane_counts"]["single_motif_background_negatives"], 1)
            self.assertEqual(summary["raw_lane_counts"]["motif_failure_negatives"], 1)
            self.assertEqual(summary["raw_lane_counts"]["length_offtarget_selected"], 1)
            self.assertTrue((out_dir / "geometry_valid_needs_esm.jsonl").exists())
            self.assertTrue((out_dir / "v12_offline_lanes_summary.json").exists())
            geometry_rows = read_jsonl(out_dir / "geometry_valid_needs_esm.jsonl")
            self.assertEqual(geometry_rows[0]["lane"], "geometry_valid_needs_esm")
            self.assertEqual(geometry_rows[0]["length_delta"], 60)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
