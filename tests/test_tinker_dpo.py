from __future__ import annotations

import math
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.tinker_dpo import dpo_loss_value, log_sigmoid


class TinkerDpoTests(unittest.TestCase):
    def test_dpo_loss_value_prefers_larger_policy_margin_than_reference(self) -> None:
        lower_loss = dpo_loss_value(
            policy_chosen_logps=[-10.0],
            policy_rejected_logps=[-15.0],
            reference_margins=[1.0],
            beta=0.1,
        )
        higher_loss = dpo_loss_value(
            policy_chosen_logps=[-14.0],
            policy_rejected_logps=[-15.0],
            reference_margins=[1.0],
            beta=0.1,
        )
        self.assertLess(lower_loss, higher_loss)

    def test_log_sigmoid_is_stable_for_large_values(self) -> None:
        self.assertTrue(math.isfinite(log_sigmoid(1000.0)))
        self.assertTrue(math.isfinite(log_sigmoid(-1000.0)))
        self.assertAlmostEqual(log_sigmoid(0.0), -math.log(2.0))

    def test_shape_only_cli_validates_pairs_without_tinker_client(self) -> None:
        rows = [
            {
                "prompt": "Design a PETase-like hydrolase.",
                "chosen": "ACDEFGHIKLMNPQRSTVWY",
                "rejected": "ACDEFGHIKLMNPQRSTVWA",
                "chosen_id": "good",
                "rejected_id": "bad",
                "preference_rule": "hard_gate_pass",
            },
            {
                "prompt": "Design a PETase-like hydrolase.",
                "chosen": "ACDEFGHIKLMNPQRSTVWC",
                "rejected": "ACDEFGHIKLMNPQRSTVWD",
                "chosen_id": "good-2",
                "rejected_id": "bad-2",
                "preference_rule": "pareto_dominance",
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pairs_path = tmp / "pairs.jsonl"
            output_dir = tmp / "out"
            pairs_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_tinker_dpo_smoke.py"),
                    "--name",
                    "shape-fixture",
                    "--pairs-path",
                    str(pairs_path),
                    "--output-dir",
                    str(output_dir),
                    "--shape-only",
                ],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            report = json.loads((output_dir / "shape-fixture" / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "shape_validated")
            self.assertFalse(report["tinker_client_created"])
            self.assertEqual(report["pair_count"], 2)
            self.assertEqual(report["datum_count"], 4)
            self.assertEqual(report["shape_summary"]["unique_prompt_count"], 1)
            self.assertEqual(report["shape_summary"]["preference_rules"]["hard_gate_pass"], 1)


if __name__ == "__main__":
    unittest.main()
