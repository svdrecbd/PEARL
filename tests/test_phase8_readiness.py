from __future__ import annotations

import unittest

from pearl.phase8_readiness import (
    ModelTokenPrices,
    estimate_dpo_cost,
    estimate_policy_sampling_cost,
    estimate_prompt_tokens,
    estimate_sequence_tokens,
)


class Phase8ReadinessTests(unittest.TestCase):
    def test_token_estimates_are_conservative_for_protein_sequences(self) -> None:
        self.assertEqual(estimate_sequence_tokens("ACDE"), 4)
        self.assertGreaterEqual(estimate_prompt_tokens("Design a PETase sequence."), 1)

    def test_dpo_cost_estimate_counts_reference_forward_and_train_epoch(self) -> None:
        prices = ModelTokenPrices(prefill_per_million=1.0, sample_per_million=2.0, train_per_million=3.0)
        cost = estimate_dpo_cost(
            pair_rows=[{"prompt": "abcd" * 1000, "chosen": "AC" * 1000, "rejected": "DE" * 1000}],
            prices=prices,
            pair_count=1,
            epochs=1,
        )

        self.assertEqual(cost["pair_count"], 1.0)
        self.assertGreater(cost["estimated_prefill_tokens"], cost["estimated_training_tokens"])
        self.assertGreater(cost["estimated_cost_usd"], 0.0)

    def test_sampling_cost_uses_prefill_and_sample_prices(self) -> None:
        prices = ModelTokenPrices(prefill_per_million=1.0, sample_per_million=2.0, train_per_million=3.0)
        cost = estimate_policy_sampling_cost(
            prices=prices,
            policies=2,
            samples_per_policy=10,
            prompt_tokens=5,
            generated_tokens=7,
        )

        self.assertEqual(cost["estimated_prefill_tokens"], 100.0)
        self.assertEqual(cost["estimated_sample_tokens"], 140.0)


if __name__ == "__main__":
    unittest.main()
