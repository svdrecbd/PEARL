from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_robustness_suite


class RunRobustnessSuiteTests(unittest.TestCase):
    def test_no_baseline_marks_basin_pressure_not_applicable(self) -> None:
        result = run_robustness_suite.evaluate_durability_group(
            prompt_count=24,
            temperature=0.8,
            group=group_payload(),
            baseline_group=None,
            baseline_locked=False,
            durability_config=durability_config(),
        )

        self.assertTrue(result["passed"])
        baseline_condition = result["conditions"][-1]
        self.assertEqual(baseline_condition["id"], "basin_pressure_vs_baseline")
        self.assertFalse(baseline_condition["applicable"])
        self.assertTrue(baseline_condition["passed"])
        self.assertEqual(baseline_condition["reason"], "no_baseline_summary_supplied")

    def test_missing_baseline_group_is_a_real_failure_when_baseline_locked(self) -> None:
        result = run_robustness_suite.evaluate_durability_group(
            prompt_count=24,
            temperature=0.8,
            group=group_payload(),
            baseline_group=None,
            baseline_locked=True,
            durability_config=durability_config(),
        )

        self.assertFalse(result["passed"])
        baseline_condition = result["conditions"][-1]
        self.assertTrue(baseline_condition["applicable"])
        self.assertFalse(baseline_condition["passed"])
        self.assertEqual(baseline_condition["reason"], "baseline_group_missing")


def durability_config() -> dict[str, float | int]:
    return {
        "required_seed_count": 3,
        "min_seeds_with_hit": 2,
        "prompt_coverage_threshold": 0.15,
        "small_prompt_count": 12,
        "seed_spread_limit_small": 2,
        "seed_spread_limit_large": 4,
    }


def group_payload() -> dict[str, object]:
    return {
        "run_count": 3,
        "tier2_hits_by_seed": [1, 1, 1],
        "prompt_coverage_by_seed": [1, 1, 1],
        "prompt_coverage_rate_by_seed": [0.041667, 0.041667, 0.041667],
        "prompts_with_any_tier2_across_seeds": 4,
        "bridge_hits_per_prompt": {"mean": 0.166667},
        "stability_dominant_rate": {"mean": 0.2},
        "geometry_dominant_rate": {"mean": 0.1},
    }


if __name__ == "__main__":
    unittest.main()
