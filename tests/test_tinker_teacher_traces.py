from __future__ import annotations

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

from pearl.tinker_teacher_traces import extract_sequence_topk_positions, parse_teacher_spec


class TinkerTeacherTraceTests(unittest.TestCase):
    def test_parse_teacher_spec_accepts_tinker_path_with_colons(self) -> None:
        spec = parse_teacher_spec(
            "name=foldability,path=tinker://abc:train:0/weights/fold,weight=0.35,temperature=0.7"
        )

        self.assertEqual(spec.name, "foldability")
        self.assertEqual(spec.model_path, "tinker://abc:train:0/weights/fold")
        self.assertAlmostEqual(spec.weight, 0.35)
        self.assertAlmostEqual(spec.temperature, 0.7)

    def test_extract_sequence_topk_positions_slices_after_prompt_tokens(self) -> None:
        positions = extract_sequence_topk_positions(
            full_topk_prompt_logprobs=[
                None,
                [(1, -0.1)],
                [(10, -0.2), (11, -1.0)],
                [(20, -0.3), (21, -1.2)],
            ],
            prompt_token_count=2,
            sequence_token_count=2,
            teacher_name="fixture",
        )

        self.assertEqual(positions[0]["token_ids"], [10, 11])
        self.assertEqual(positions[1]["logprobs"], [-0.3, -1.2])

    def test_rollout_seed_cli_writes_static_panel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pairs_path = tmp / "pairs.jsonl"
            output_path = tmp / "rollouts.jsonl"
            rows = [
                {
                    "prompt": "Design a PETase-like hydrolase.",
                    "chosen": "ACDE",
                    "rejected": "AAAA",
                    "chosen_id": "good",
                    "rejected_id": "bad",
                    "preference_rule": "hard_gate_pass",
                }
            ]
            pairs_path.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_sparse_opd_rollout_seed.py"),
                    "--pairs-path",
                    str(pairs_path),
                    "--output-path",
                    str(output_path),
                    "--max-rows",
                    "1",
                ],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            rollout = json.loads(output_path.read_text(encoding="utf-8").strip())
            self.assertEqual(rollout["sequence"], "ACDE")
            self.assertEqual(rollout["source"], "phase8_dpo_static_seed")


if __name__ == "__main__":
    unittest.main()
