from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.opd_lite import build_sparse_poe_target_row


def logp(value: float) -> float:
    return math.log(value)


class SparseOPDLiteTests(unittest.TestCase):
    def test_sparse_poe_prefers_multi_teacher_consensus_token(self) -> None:
        row = {
            "sample_id": "rollout-1",
            "prompt": "Design a PETase/cutinase-like hydrolase.",
            "sequence": "AC",
            "teachers": {
                "foldability": {
                    "weight": 0.6,
                    "positions": [
                        {"token_ids": [10, 20], "logprobs": [logp(0.8), logp(0.2)]},
                        {"token_ids": [30, 40], "logprobs": [logp(0.7), logp(0.3)]},
                    ],
                },
                "solubility": {
                    "weight": 0.4,
                    "positions": [
                        {"token_ids": [10, 50], "logprobs": [logp(0.7), logp(0.3)]},
                        {"token_ids": [30, 60], "logprobs": [logp(0.6), logp(0.4)]},
                    ],
                },
            },
        }

        target = build_sparse_poe_target_row(row, top_k=3, missing_logprob=-20.0)

        self.assertEqual(target["target_token_ids"][0][0], 10)
        self.assertEqual(target["target_token_ids"][1][0], 30)
        self.assertAlmostEqual(sum(target["target_weights"][0]), 1.0)
        self.assertGreater(target["position_diagnostics"][0]["sparse_disagreement"], 0.0)
        self.assertEqual(target["consensus"]["method"], "sparse_weighted_product_of_experts")

    def test_cli_writes_sparse_targets_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            trace_path = tmp / "teacher_traces.jsonl"
            trace_row = {
                "sample_id": "rollout-1",
                "prompt": "Design a PETase/cutinase-like hydrolase.",
                "sequence": "AC",
                "teacher_topk": [
                    {
                        "teacher": "foldability",
                        "weight": 0.5,
                        "positions": [
                            [[10, logp(0.9)], [20, logp(0.1)]],
                            [[30, logp(0.9)], [40, logp(0.1)]],
                        ],
                    },
                    {
                        "teacher": "family",
                        "weight": 0.5,
                        "positions": [
                            [[10, logp(0.8)], [50, logp(0.2)]],
                            [[30, logp(0.7)], [60, logp(0.3)]],
                        ],
                    },
                ],
            }
            trace_path.write_text(json.dumps(trace_row) + "\n", encoding="utf-8")
            output_dir = tmp / "out"

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_sparse_opd_targets.py"),
                    "--name",
                    "fixture",
                    "--teacher-trace-path",
                    str(trace_path),
                    "--output-dir",
                    str(output_dir),
                    "--top-k",
                    "2",
                ],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            run_dir = output_dir / "fixture"
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            targets = [
                json.loads(line)
                for line in (run_dir / "sparse_opd_targets.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(manifest["target_count"], 1)
            self.assertTrue(manifest["ready_for_sparse_opd_smoke"])
            self.assertEqual(targets[0]["target_token_ids"][0][0], 10)


if __name__ == "__main__":
    unittest.main()
