from __future__ import annotations

import math
import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from pearl.model_rendering import RAW_RENDERER, RendererContract, build_cross_entropy_datum, create_model_renderer


@dataclass(frozen=True)
class DpoDatumMetadata:
    pair_index: int
    role: str
    prompt: str
    sequence: str


def pair_rows_fingerprint(pair_rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in pair_rows:
        payload = {
            "prompt": str(row.get("prompt") or ""),
            "chosen": str(row.get("chosen") or ""),
            "rejected": str(row.get("rejected") or ""),
        }
        digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def split_pair_rows_grouped(
    pair_rows: list[dict[str, Any]],
    *,
    holdout_fraction: float,
    seed: int,
    group_field: str = "chosen_record_id",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not 0.0 <= holdout_fraction < 1.0:
        raise ValueError("holdout_fraction must be in [0, 1)")
    rows = list(pair_rows)
    rng = random.Random(seed)
    if holdout_fraction == 0.0 or len(rows) < 2:
        rng.shuffle(rows)
        return rows, []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        group_value = row.get(group_field)
        if group_value in (None, ""):
            group_value = row.get("chosen")
        group_key = str(group_value)
        grouped.setdefault(group_key, []).append(row)

    target_rows = max(1, round(len(rows) * holdout_fraction))
    group_keys = sorted(
        grouped,
        key=lambda key: hashlib.sha256(f"{seed}\0{key}".encode("utf-8")).hexdigest(),
    )
    holdout_keys: set[str] = set()
    holdout_count = 0
    for key in group_keys:
        candidate_count = holdout_count + len(grouped[key])
        if abs(target_rows - candidate_count) <= abs(target_rows - holdout_count):
            holdout_keys.add(key)
            holdout_count = candidate_count

    train_rows = [row for key in group_keys if key not in holdout_keys for row in grouped[key]]
    holdout_rows = [row for key in group_keys if key in holdout_keys for row in grouped[key]]
    rng.shuffle(train_rows)
    rng.shuffle(holdout_rows)
    return train_rows, holdout_rows


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


def build_sequence_cross_entropy_datum(
    prompt: str,
    sequence: str,
    tokenizer: Any,
    *,
    renderer_contract: RendererContract | None = None,
    renderer: Any | None = None,
) -> Any:
    return build_cross_entropy_datum(
        prompt,
        sequence,
        tokenizer,
        renderer_contract or RendererContract(name=RAW_RENDERER),
        renderer=renderer,
    )


def build_dpo_datums(
    pair_rows: list[dict[str, Any]],
    tokenizer: Any,
    *,
    renderer_contract: RendererContract | None = None,
) -> tuple[list[Any], list[DpoDatumMetadata]]:
    contract = renderer_contract or RendererContract(name=RAW_RENDERER)
    renderer = create_model_renderer(contract)
    datums: list[Any] = []
    metadata: list[DpoDatumMetadata] = []
    for pair_index, row in enumerate(pair_rows):
        prompt = str(row["prompt"])
        chosen = str(row["chosen"])
        rejected = str(row["rejected"])
        datums.append(
            build_sequence_cross_entropy_datum(
                prompt,
                chosen,
                tokenizer,
                renderer_contract=contract,
                renderer=renderer,
            )
        )
        metadata.append(DpoDatumMetadata(pair_index=pair_index, role="chosen", prompt=prompt, sequence=chosen))
        datums.append(
            build_sequence_cross_entropy_datum(
                prompt,
                rejected,
                tokenizer,
                renderer_contract=contract,
                renderer=renderer,
            )
        )
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


def preference_margin_diagnostics(
    *,
    policy_margins: list[float],
    reference_margins: list[float],
) -> dict[str, float]:
    if len(policy_margins) != len(reference_margins):
        raise RuntimeError("Policy and reference margin counts do not match")
    if not policy_margins:
        return {
            "pair_count": 0.0,
            "raw_preference_accuracy": 0.0,
            "improved_over_reference_fraction": 0.0,
            "policy_margin_mean": 0.0,
            "reference_margin_mean": 0.0,
            "margin_delta_mean": 0.0,
        }
    deltas = [policy - reference for policy, reference in zip(policy_margins, reference_margins, strict=True)]
    return {
        "pair_count": float(len(policy_margins)),
        "raw_preference_accuracy": sum(margin > 0.0 for margin in policy_margins) / len(policy_margins),
        "improved_over_reference_fraction": sum(delta > 0.0 for delta in deltas) / len(deltas),
        "policy_margin_mean": sum(policy_margins) / len(policy_margins),
        "reference_margin_mean": sum(reference_margins) / len(reference_margins),
        "margin_delta_mean": sum(deltas) / len(deltas),
    }


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
