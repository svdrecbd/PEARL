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
    "thinkingmachines/Inkling": ModelTokenPrices(prefill_per_million=1.87, sample_per_million=4.68, train_per_million=5.61),
    "deepseek-ai/DeepSeek-V3.1": ModelTokenPrices(prefill_per_million=1.695, sample_per_million=4.215, train_per_million=3.718),
    "moonshotai/Kimi-K2.6": ModelTokenPrices(prefill_per_million=2.205, sample_per_million=5.49, train_per_million=4.84),
    "moonshotai/Kimi-K2.6:peft:131072": ModelTokenPrices(prefill_per_million=5.15, sample_per_million=12.81, train_per_million=15.40),
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16": ModelTokenPrices(prefill_per_million=0.195, sample_per_million=0.495, train_per_million=0.44),
    "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16": ModelTokenPrices(prefill_per_million=0.57, sample_per_million=1.44, train_per_million=1.276),
    "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16": ModelTokenPrices(prefill_per_million=2.49, sample_per_million=6.225, train_per_million=5.478),
    "Qwen/Qwen3.6-35B-A3B": ModelTokenPrices(prefill_per_million=0.54, sample_per_million=1.335, train_per_million=1.177),
    "Qwen/Qwen3.6-27B": ModelTokenPrices(prefill_per_million=1.86, sample_per_million=5.595, train_per_million=4.103),
    "Qwen/Qwen3.5-397B-A17B": ModelTokenPrices(prefill_per_million=3.00, sample_per_million=7.50, train_per_million=6.60),
    "Qwen/Qwen3.5-9B": ModelTokenPrices(prefill_per_million=0.66, sample_per_million=1.995, train_per_million=1.463),
    "Qwen/Qwen3.5-4B": ModelTokenPrices(prefill_per_million=0.33, sample_per_million=1.005, train_per_million=0.737),
    "Qwen/Qwen3-8B": ModelTokenPrices(prefill_per_million=0.195, sample_per_million=0.60, train_per_million=0.44),
    "openai/gpt-oss-120b": ModelTokenPrices(prefill_per_million=0.33, sample_per_million=0.84, train_per_million=0.737),
    "openai/gpt-oss-20b": ModelTokenPrices(prefill_per_million=0.18, sample_per_million=0.45, train_per_million=0.396),
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


def estimate_preference_evaluation_cost(
    *,
    pair_rows: list[dict[str, Any]],
    prices: ModelTokenPrices,
    pair_count: int,
    policy_count: int = 2,
) -> dict[str, float]:
    selected = pair_rows[:pair_count]
    token_count = sum(estimate_pair_datum_tokens(row) for row in selected)
    prefill_tokens = token_count * max(0, policy_count)
    return {
        "pair_count": float(len(selected)),
        "policy_count": float(max(0, policy_count)),
        "estimated_prefill_tokens": float(prefill_tokens),
        "estimated_cost_usd": round(
            cost_from_million_tokens(prefill_tokens, prices.prefill_per_million),
            4,
        ),
    }
