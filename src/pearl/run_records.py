from __future__ import annotations

from typing import Any


def build_reward_components(
    *,
    esm_pll: float,
    reward_info: dict[str, Any],
    family_reward_info: dict[str, Any],
) -> dict[str, Any]:
    return {
        "reward_mode": reward_info["reward_mode"],
        "esm_reward": esm_pll,
        "esm_gate_pass": reward_info["esm_gate_pass"],
        "functional_bridge_passes": reward_info["functional_bridge_passes"],
        "family_faithful_bridge_passes": reward_info["family_faithful_bridge_passes"],
        "family_reward": family_reward_info["family_reward"],
        "rl_family_reward": reward_info["rl_family_reward"],
        "dense_family_reward": reward_info["dense_family_reward"],
        "dense_reward_components": reward_info["dense_reward_components"],
        "template_penalty": reward_info["template_penalty"],
        "motif_spam_penalty": reward_info["motif_spam_penalty"],
        "tandem_repeat_penalty": reward_info["tandem_repeat_penalty"],
        "local_entropy_penalty": reward_info["local_entropy_penalty"],
        "kmer_uniqueness_ratio": reward_info["kmer_uniqueness_ratio"],
        "motif_count": reward_info["motif_count"],
        "max_tandem_repeat_similarity": reward_info["max_tandem_repeat_similarity"],
        "min_local_window_entropy": reward_info["min_local_window_entropy"],
        "family_reward_components": family_reward_info["family_reward_components"],
    }


def build_candidate_audit_record(
    *,
    step: int,
    prompt: str,
    sequence_prompt: str,
    selection_metadata: dict[str, Any],
    candidate_audit: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "step": step,
        "prompt": prompt,
        "sequence_prompt": sequence_prompt,
        "selection_metadata": selection_metadata,
        "candidates": candidate_audit,
    }


def build_step_record(
    *,
    step: int,
    prompt: str,
    sampled_text: str,
    extracted_sequence: str,
    reward: float,
    selection_metadata: dict[str, Any],
    esm_pll: float,
    reward_info: dict[str, Any],
    family_reward_info: dict[str, Any],
    quality: dict[str, Any],
    family_evaluation: dict[str, Any] | None,
    sample_token_count: int,
    sample_attempts: int,
    training_skipped: bool,
    update_performed: bool,
    forward_backward_metrics: dict[str, Any] | None = None,
    optim_step_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "step": step,
        "prompt": prompt,
        "sample_text": sampled_text,
        "extracted_sequence": extracted_sequence,
        "reward": reward,
        "selection_metadata": selection_metadata,
        "reward_components": build_reward_components(
            esm_pll=esm_pll,
            reward_info=reward_info,
            family_reward_info=family_reward_info,
        ),
        "sample_token_count": sample_token_count,
        "sample_attempts": sample_attempts,
        "sequence_quality": quality,
        "family_evaluation": family_evaluation,
        "training_skipped": training_skipped,
        "update_performed": update_performed,
    }
    if forward_backward_metrics is not None:
        record["forward_backward_metrics"] = forward_backward_metrics
    if optim_step_metrics is not None:
        record["optim_step_metrics"] = optim_step_metrics
    return record
