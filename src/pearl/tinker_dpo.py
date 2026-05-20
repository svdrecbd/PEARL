from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np


@dataclass(frozen=True)
class DpoDatumMetadata:
    pair_index: int
    role: str
    prompt: str
    sequence: str


def dpo_loss_value(
    *,
    policy_chosen_logps: list[float],
    policy_rejected_logps: list[float],
    reference_margins: list[float],
    beta: float,
) -> float:
    losses: list[float] = []
    for chosen_logp, rejected_logp, ref_margin in zip(
        policy_chosen_logps,
        policy_rejected_logps,
        reference_margins,
        strict=True,
    ):
        logit = beta * ((chosen_logp - rejected_logp) - ref_margin)
        losses.append(-log_sigmoid(logit))
    return sum(losses) / max(1, len(losses))


def log_sigmoid(value: float) -> float:
    if value >= 0:
        return -math.log1p(math.exp(-value))
    return value - math.log1p(math.exp(value))


def build_sequence_cross_entropy_datum(prompt: str, sequence: str, tokenizer: Any) -> Any:
    from tinker import types

    prompt_tokens = tokenizer.encode(prompt, add_special_tokens=False)
    sequence_tokens = tokenizer.encode(sequence, add_special_tokens=False)
    if not prompt_tokens:
        raise RuntimeError("DPO prompt tokenized to zero input tokens")
    if not sequence_tokens:
        raise RuntimeError("DPO sequence tokenized to zero target tokens")

    prompt_input = types.ModelInput.from_ints(prompt_tokens)
    model_input = (
        prompt_input
        if len(sequence_tokens) == 1
        else prompt_input.append(types.EncodedTextChunk(tokens=sequence_tokens[:-1]))
    )
    observed_prompt_length = prompt_input.length - 1
    target_tokens = np.asarray([0] * observed_prompt_length + sequence_tokens, dtype=np.int64)
    weights = np.asarray(
        [0.0] * observed_prompt_length + [1.0] * (model_input.length - observed_prompt_length),
        dtype=np.float32,
    )
    if model_input.length != len(target_tokens) or model_input.length != len(weights):
        raise RuntimeError("DPO cross-entropy tensors are not aligned")
    return types.Datum(
        model_input=model_input,
        loss_fn_inputs={
            "target_tokens": target_tokens,
            "weights": weights,
        },
    )


def build_dpo_datums(pair_rows: list[dict[str, Any]], tokenizer: Any) -> tuple[list[Any], list[DpoDatumMetadata]]:
    datums: list[Any] = []
    metadata: list[DpoDatumMetadata] = []
    for pair_index, row in enumerate(pair_rows):
        prompt = str(row["prompt"])
        chosen = str(row["chosen"])
        rejected = str(row["rejected"])
        datums.append(build_sequence_cross_entropy_datum(prompt, chosen, tokenizer))
        metadata.append(DpoDatumMetadata(pair_index=pair_index, role="chosen", prompt=prompt, sequence=chosen))
        datums.append(build_sequence_cross_entropy_datum(prompt, rejected, tokenizer))
        metadata.append(DpoDatumMetadata(pair_index=pair_index, role="rejected", prompt=prompt, sequence=rejected))
    return datums, metadata


def weighted_logprob_sum(logprobs: Any, weights: Any) -> Any:
    return (logprobs * weights).sum()


def tensor_weights_from_datum(datum: Any, *, torch_module: Any) -> Any:
    weights = datum.loss_fn_inputs["weights"]
    if hasattr(weights, "to_torch"):
        return weights.to_torch()
    return torch_module.tensor(weights, dtype=torch_module.float32)


def reference_margins_from_forward_result(forward_result: Any, datums: list[Any]) -> list[float]:
    margins: list[float] = []
    outputs = list(forward_result.loss_fn_outputs)
    if len(outputs) != len(datums):
        raise RuntimeError(f"Expected {len(datums)} reference outputs, observed {len(outputs)}")
    sums: list[float] = []
    for output, datum in zip(outputs, datums, strict=True):
        logprob_data = output["logprobs"]
        weights_data = datum.loss_fn_inputs["weights"]
        logprobs = np.asarray(logprob_data.data, dtype=np.float32)
        weights = np.asarray(weights_data.data, dtype=np.float32)
        if logprob_data.shape is not None:
            logprobs = logprobs.reshape(logprob_data.shape)
        if weights_data.shape is not None:
            weights = weights.reshape(weights_data.shape)
        sums.append(float((logprobs * weights).sum()))
    for index in range(0, len(sums), 2):
        margins.append(sums[index] - sums[index + 1])
    return margins


def build_tinker_dpo_loss_fn(*, reference_margins: list[float], beta: float) -> Callable[[list[Any], list[Any]], tuple[Any, dict[str, float]]]:
    def dpo_loss(data: list[Any], logprobs_list: list[Any]) -> tuple[Any, dict[str, float]]:
        import torch

        if len(logprobs_list) != len(data):
            raise RuntimeError(f"Expected {len(data)} logprob tensors, observed {len(logprobs_list)}")
        if len(logprobs_list) % 2 != 0:
            raise RuntimeError("DPO custom loss expects chosen/rejected datum pairs")
        if len(reference_margins) != len(logprobs_list) // 2:
            raise RuntimeError("Reference margin count does not match DPO pair count")

        sequence_logps = []
        for datum, logprobs in zip(data, logprobs_list, strict=True):
            weights = tensor_weights_from_datum(datum, torch_module=torch).to(logprobs.device)
            sequence_logps.append(weighted_logprob_sum(logprobs, weights))

        losses = []
        rewards = []
        for pair_index, ref_margin in enumerate(reference_margins):
            chosen_logp = sequence_logps[2 * pair_index]
            rejected_logp = sequence_logps[(2 * pair_index) + 1]
            policy_margin = chosen_logp - rejected_logp
            reward = beta * (policy_margin - float(ref_margin))
            rewards.append(reward.detach())
            losses.append(-torch.nn.functional.logsigmoid(reward))
        loss = torch.stack(losses).mean()
        reward_tensor = torch.stack(rewards)
        metrics = {
            "dpo_loss": float(loss.detach().cpu()),
            "dpo_reward_margin_mean": float(reward_tensor.mean().cpu()),
            "dpo_reward_margin_min": float(reward_tensor.min().cpu()),
            "dpo_reward_margin_max": float(reward_tensor.max().cpu()),
            "dpo_pair_count": float(len(reference_margins)),
            "dpo_beta": float(beta),
        }
        return loss, metrics

    return dpo_loss
