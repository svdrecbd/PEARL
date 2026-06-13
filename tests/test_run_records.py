from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.run_records import build_candidate_audit_record, build_reward_components, build_step_record


def make_reward_info() -> dict[str, object]:
    return {
        "reward_mode": "dense_family",
        "esm_gate_pass": True,
        "functional_bridge_passes": True,
        "family_faithful_bridge_passes": False,
        "rl_family_reward": 12.5,
        "dense_family_reward": 34.0,
        "dense_reward_components": {"motif_component": 1.0},
        "template_penalty": 0.0,
        "motif_spam_penalty": 0.0,
        "tandem_repeat_penalty": 0.0,
        "local_entropy_penalty": 0.0,
        "kmer_uniqueness_ratio": 0.95,
        "motif_count": 2,
        "max_tandem_repeat_similarity": 0.1,
        "min_local_window_entropy": 3.4,
    }


def make_family_reward_info() -> dict[str, object]:
    return {
        "family_reward": 88.0,
        "family_reward_components": {"novelty": 22.0},
    }


class RunRecordsTests(unittest.TestCase):
    def test_build_reward_components_keeps_expected_fields(self) -> None:
        components = build_reward_components(
            esm_pll=91.2,
            reward_info=make_reward_info(),
            family_reward_info=make_family_reward_info(),
        )
        self.assertEqual(components["esm_reward"], 91.2)
        self.assertTrue(components["functional_bridge_passes"])
        self.assertEqual(components["family_reward"], 88.0)

    def test_build_candidate_audit_record_shape(self) -> None:
        record = build_candidate_audit_record(
            step=3,
            prompt="prompt",
            sequence_prompt="seq prompt",
            selection_metadata={"stage1_rank": 1},
            candidate_audit=[{"selected": True}],
        )
        self.assertEqual(record["step"], 3)
        self.assertEqual(record["candidates"][0]["selected"], True)

    def test_build_step_record_optionally_includes_training_metrics(self) -> None:
        record = build_step_record(
            step=4,
            prompt="prompt",
            sampled_text="SEQ=AAAA",
            extracted_sequence="AAAA",
            reward=42.0,
            selection_metadata={"stage1_rank": 1},
            esm_pll=90.0,
            reward_info=make_reward_info(),
            family_reward_info=make_family_reward_info(),
            quality={"is_trainable": True},
            family_evaluation={"family": "petase"},
            sample_token_count=12,
            sample_attempts=2,
            training_skipped=False,
            update_performed=True,
            forward_backward_metrics={"loss": 0.1},
            optim_step_metrics={"lr": 1e-4},
        )
        self.assertEqual(record["reward_components"]["family_reward"], 88.0)
        self.assertEqual(record["forward_backward_metrics"]["loss"], 0.1)
        self.assertEqual(record["optim_step_metrics"]["lr"], 1e-4)


if __name__ == "__main__":
    unittest.main()
