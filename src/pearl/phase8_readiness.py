from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelTokenPrices:
    prefill_per_million: float
    sample_per_million: float
    train_per_million: float


TINKER_MODEL_PRICES: dict[str, ModelTokenPrices] = {
    "moonshotai/Kimi-K2.6": ModelTokenPrices(prefill_per_million=1.47, sample_per_million=3.66, train_per_million=4.40),
    "moonshotai/Kimi-K2.6:peft:131072": ModelTokenPrices(prefill_per_million=5.15, sample_per_million=12.81, train_per_million=15.40),
    "moonshotai/Kimi-K2.5": ModelTokenPrices(prefill_per_million=1.47, sample_per_million=3.66, train_per_million=4.40),
    "moonshotai/Kimi-K2.5:peft:131072": ModelTokenPrices(prefill_per_million=5.15, sample_per_million=12.81, train_per_million=15.40),
}


def estimate_pair_datum_tokens(row: dict[str, Any]) -> int:
    prompt_tokens = estimate_prompt_tokens(str(row.get("prompt") or ""))
    chosen_tokens = estimate_sequence_tokens(str(row.get("chosen") or ""))
    rejected_tokens = estimate_sequence_tokens(str(row.get("rejected") or ""))
    return max(1, prompt_tokens + chosen_tokens - 1) + max(1, prompt_tokens + rejected_tokens - 1)


def estimate_sparse_target_tokens(row: dict[str, Any]) -> int:
    prompt_tokens = estimate_prompt_tokens(str(row.get("prompt") or ""))
    target_rows = row.get("target_token_ids")
    if isinstance(target_rows, list):
        sequence_tokens = len(target_rows)
    else:
        sequence_tokens = estimate_sequence_tokens(str(row.get("sequence") or ""))
    return max(1, prompt_tokens + sequence_tokens - 1)


def estimate_rollout_trace_tokens(row: dict[str, Any]) -> int:
    prompt_tokens = estimate_prompt_tokens(str(row.get("prompt") or ""))
    sequence = str(row.get("sequence") or row.get("completion") or "")
    sequence_tokens = estimate_sequence_tokens(sequence)
    return prompt_tokens + sequence_tokens


def estimate_prompt_tokens(prompt: str) -> int:
    return max(1, math.ceil(len(prompt) / 4))


def estimate_sequence_tokens(sequence: str) -> int:
    letters = [char for char in sequence.strip() if char.isalpha()]
    return max(1, len(letters))


def cost_from_million_tokens(tokens: float, price_per_million: float) -> float:
    return (tokens / 1_000_000.0) * price_per_million


def estimate_dpo_cost(
    *,
    pair_rows: list[dict[str, Any]],
    prices: ModelTokenPrices,
    pair_count: int,
    epochs: int = 1,
) -> dict[str, float]:
    selected = pair_rows[:pair_count]
    token_count = sum(estimate_pair_datum_tokens(row) for row in selected)
    prefill_passes = 1 + max(0, epochs)
    train_passes = max(0, epochs)
    return {
        "pair_count": float(len(selected)),
        "estimated_training_tokens": float(token_count),
        "estimated_prefill_tokens": float(token_count * prefill_passes),
        "estimated_train_tokens": float(token_count * train_passes),
        "estimated_cost_usd": round(
            cost_from_million_tokens(token_count * prefill_passes, prices.prefill_per_million)
            + cost_from_million_tokens(token_count * train_passes, prices.train_per_million),
            4,
        ),
    }


def estimate_sparse_opd_cost(
    *,
    target_rows: list[dict[str, Any]],
    prices: ModelTokenPrices,
    row_count: int,
    epochs: int = 1,
) -> dict[str, float]:
    selected = target_rows[:row_count]
    token_count = sum(estimate_sparse_target_tokens(row) for row in selected)
    train_passes = max(0, epochs)
    return {
        "row_count": float(len(selected)),
        "estimated_train_tokens": float(token_count * train_passes),
        "estimated_cost_usd": round(cost_from_million_tokens(token_count * train_passes, prices.train_per_million), 4),
    }


def estimate_teacher_trace_cost(
    *,
    rollout_rows: list[dict[str, Any]],
    prices: ModelTokenPrices,
    rollout_count: int,
    teacher_count: int,
    generated_tokens_per_trace_request: int = 1,
) -> dict[str, float]:
    selected = rollout_rows[:rollout_count]
    prefill_tokens = sum(estimate_rollout_trace_tokens(row) for row in selected) * max(0, teacher_count)
    sample_tokens = len(selected) * max(0, teacher_count) * max(0, generated_tokens_per_trace_request)
    return {
        "rollout_count": float(len(selected)),
        "teacher_count": float(teacher_count),
        "estimated_prefill_tokens": float(prefill_tokens),
        "estimated_sample_tokens": float(sample_tokens),
        "estimated_cost_usd": round(
            cost_from_million_tokens(prefill_tokens, prices.prefill_per_million)
            + cost_from_million_tokens(sample_tokens, prices.sample_per_million),
            4,
        ),
    }


def estimate_policy_sampling_cost(
    *,
    prices: ModelTokenPrices,
    policies: int,
    samples_per_policy: int,
    prompt_tokens: int,
    generated_tokens: int,
) -> dict[str, float]:
    total_samples = max(0, policies) * max(0, samples_per_policy)
    prefill_tokens = total_samples * max(0, prompt_tokens)
    sample_tokens = total_samples * max(0, generated_tokens)
    return {
        "policy_count": float(max(0, policies)),
        "samples_per_policy": float(max(0, samples_per_policy)),
        "estimated_prefill_tokens": float(prefill_tokens),
        "estimated_sample_tokens": float(sample_tokens),
        "estimated_cost_usd": round(
            cost_from_million_tokens(prefill_tokens, prices.prefill_per_million)
            + cost_from_million_tokens(sample_tokens, prices.sample_per_million),
            4,
        ),
    }
