#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


FEATURE_NAMES = [
    "reward",
    "esm_reward",
    "stage2_score",
    "family_reward",
    "dense_family_reward",
    "rl_family_reward",
    "gap_quality",
    "passes_core_screen",
    "catalytic_geometry_passes",
    "has_family_serine_motif",
    "motif_count",
    "novelty_bonus",
    "kmer_uniqueness_ratio",
    "min_local_window_entropy",
    "template_penalty",
    "motif_spam_penalty",
    "tandem_repeat_penalty",
    "local_entropy_penalty",
    "length",
    "stage1_rank_score",
    "stage2_rank_score",
]

BASELINE_FIELDS = [
    "reward",
    "esm_reward",
    "stage2_score",
    "family_reward",
    "dense_family_reward",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Train a lightweight pairwise reranker over mined candidate pairs and evaluate "
            "it against scalar proxy baselines on held-out splits."
        )
    )
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--epochs", type=int, default=800)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--l2", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument("--log-every", type=int, default=50)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open() if line.strip()]


def rank_score(raw_rank: Any) -> float:
    if raw_rank is None:
        return 0.0
    try:
        rank = int(raw_rank)
    except (TypeError, ValueError):
        return 0.0
    if rank < 0:
        return 0.0
    return 1.0 / (1.0 + rank)


def candidate_vector(candidate: dict[str, Any]) -> np.ndarray:
    values = {
        "reward": float(candidate.get("reward") or 0.0),
        "esm_reward": float(candidate.get("esm_reward") or 0.0),
        "stage2_score": float(candidate.get("stage2_score") or 0.0),
        "family_reward": float(candidate.get("family_reward") or 0.0),
        "dense_family_reward": float(candidate.get("dense_family_reward") or 0.0),
        "rl_family_reward": float(candidate.get("rl_family_reward") or 0.0),
        "gap_quality": float(candidate.get("gap_quality") or 0.0),
        "passes_core_screen": 1.0 if bool(candidate.get("passes_core_screen")) else 0.0,
        "catalytic_geometry_passes": 1.0 if bool(candidate.get("catalytic_geometry_passes")) else 0.0,
        "has_family_serine_motif": 1.0 if bool(candidate.get("has_family_serine_motif")) else 0.0,
        "motif_count": float(candidate.get("motif_count") or 0.0),
        "novelty_bonus": float(candidate.get("novelty_bonus") or 0.0),
        "kmer_uniqueness_ratio": float(candidate.get("kmer_uniqueness_ratio") or 0.0),
        "min_local_window_entropy": float(candidate.get("min_local_window_entropy") or 0.0),
        "template_penalty": float(candidate.get("template_penalty") or 0.0),
        "motif_spam_penalty": float(candidate.get("motif_spam_penalty") or 0.0),
        "tandem_repeat_penalty": float(candidate.get("tandem_repeat_penalty") or 0.0),
        "local_entropy_penalty": float(candidate.get("local_entropy_penalty") or 0.0),
        "length": float(candidate.get("length") or 0.0),
        "stage1_rank_score": rank_score(candidate.get("stage1_rank")),
        "stage2_rank_score": rank_score(candidate.get("stage2_rank")),
    }
    return np.array([values[name] for name in FEATURE_NAMES], dtype=np.float64)


def dataset_matrices(pairs: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    chosen = np.stack([candidate_vector(row["chosen"]) for row in pairs], axis=0)
    rejected = np.stack([candidate_vector(row["rejected"]) for row in pairs], axis=0)
    return chosen, rejected


def standardize_from_train(train_pairs: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    chosen, rejected = dataset_matrices(train_pairs)
    stacked = np.concatenate([chosen, rejected], axis=0)
    mean = stacked.mean(axis=0)
    std = stacked.std(axis=0)
    std[std < 1e-8] = 1.0
    return mean, std


def transform_pair_matrix(pairs: list[dict[str, Any]], mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    chosen, rejected = dataset_matrices(pairs)
    chosen_norm = (chosen - mean) / std
    rejected_norm = (rejected - mean) / std
    return chosen_norm - rejected_norm


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def train_pairwise_model(
    train_pairs: list[dict[str, Any]],
    *,
    epochs: int,
    learning_rate: float,
    l2: float,
    seed: int,
    log_every: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict[str, float]]]:
    if not train_pairs:
        raise SystemExit("pairwise reranker training requires at least one train pair")

    mean, std = standardize_from_train(train_pairs)
    x = transform_pair_matrix(train_pairs, mean, std)
    rng = np.random.default_rng(seed)
    weights = rng.normal(scale=0.01, size=x.shape[1])
    m = np.zeros_like(weights)
    v = np.zeros_like(weights)
    beta1 = 0.9
    beta2 = 0.999
    eps = 1e-8
    history: list[dict[str, float]] = []

    for epoch in range(1, epochs + 1):
        margins = x @ weights
        loss_terms = np.logaddexp(0.0, -margins)
        loss = float(loss_terms.mean() + 0.5 * l2 * np.dot(weights, weights))

        grad_factors = -sigmoid(-margins)
        grad = (x.T @ grad_factors) / x.shape[0]
        grad += l2 * weights

        m = beta1 * m + (1.0 - beta1) * grad
        v = beta2 * v + (1.0 - beta2) * (grad * grad)
        m_hat = m / (1.0 - beta1**epoch)
        v_hat = v / (1.0 - beta2**epoch)
        weights -= learning_rate * m_hat / (np.sqrt(v_hat) + eps)

        if epoch == 1 or epoch % log_every == 0 or epoch == epochs:
            accuracy = pair_accuracy_from_margins(margins)
            history.append(
                {
                    "epoch": float(epoch),
                    "loss": loss,
                    "train_accuracy": accuracy,
                }
            )

    return weights, mean, std, history


def pair_accuracy_from_margins(margins: np.ndarray) -> float:
    if margins.size == 0:
        return 0.0
    wins = np.sum(margins > 0.0)
    ties = np.sum(margins == 0.0)
    return float((wins + 0.5 * ties) / margins.size)


def baseline_accuracy(pairs: list[dict[str, Any]], *, field: str) -> float:
    if not pairs:
        return 0.0
    chosen = np.array([float(row["chosen"].get(field) or 0.0) for row in pairs], dtype=np.float64)
    rejected = np.array([float(row["rejected"].get(field) or 0.0) for row in pairs], dtype=np.float64)
    return pair_accuracy_from_margins(chosen - rejected)


def evaluate_split(
    pairs: list[dict[str, Any]],
    *,
    weights: np.ndarray,
    mean: np.ndarray,
    std: np.ndarray,
) -> dict[str, Any]:
    if not pairs:
        return {
            "pair_count": 0,
            "accuracy": None,
            "pair_type_accuracy": {},
            "baseline_accuracy": {name: None for name in BASELINE_FIELDS},
        }

    x = transform_pair_matrix(pairs, mean, std)
    margins = x @ weights
    pair_type_accuracy: dict[str, float] = {}
    pair_type_groups: dict[str, list[int]] = {}
    for index, row in enumerate(pairs):
        pair_type_groups.setdefault(row["pair_type"], []).append(index)
    for pair_type, indices in pair_type_groups.items():
        pair_type_accuracy[pair_type] = pair_accuracy_from_margins(margins[np.array(indices, dtype=np.int64)])

    return {
        "pair_count": len(pairs),
        "accuracy": pair_accuracy_from_margins(margins),
        "pair_type_accuracy": pair_type_accuracy,
        "baseline_accuracy": {name: baseline_accuracy(pairs, field=name) for name in BASELINE_FIELDS},
    }


def filter_train_against_eval(train_pairs: list[dict[str, Any]], eval_pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eval_prompts = {row["prompt"] for row in eval_pairs}
    eval_prompt_buckets = {row["prompt_bucket"] for row in eval_pairs}
    eval_sequences = {row["chosen"]["sequence"] for row in eval_pairs} | {row["rejected"]["sequence"] for row in eval_pairs}
    eval_clusters = {row["chosen"]["cluster_key"] for row in eval_pairs} | {row["rejected"]["cluster_key"] for row in eval_pairs}
    return [
        row
        for row in train_pairs
        if row["prompt"] not in eval_prompts
        and row["prompt_bucket"] not in eval_prompt_buckets
        and row["chosen"]["sequence"] not in eval_sequences
        and row["rejected"]["sequence"] not in eval_sequences
        and row["chosen"]["cluster_key"] not in eval_clusters
        and row["rejected"]["cluster_key"] not in eval_clusters
    ]


def main() -> None:
    args = parse_args()
    dataset_dir = Path(args.dataset_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else dataset_dir / "reranker_model"
    output_dir.mkdir(parents=True, exist_ok=True)

    train_pool = load_jsonl(dataset_dir / "pairs_train.jsonl")
    eval_split_names = ["prompt_holdout", "bucket_holdout", "cluster_holdout", "hard_holdout"]
    eval_rows = {name: load_jsonl(dataset_dir / f"pairs_{name}.jsonl") for name in eval_split_names}

    weights, mean, std, history = train_pairwise_model(
        train_pool,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        l2=args.l2,
        seed=args.seed,
        log_every=args.log_every,
    )

    model_dir = output_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)

    train_pool_model = {
        "feature_names": FEATURE_NAMES,
        "weights": weights.tolist(),
        "mean": mean.tolist(),
        "std": std.tolist(),
    }
    (model_dir / "train_pool_model.json").write_text(json.dumps(train_pool_model, indent=2) + "\n", encoding="utf-8")

    split_metrics: dict[str, Any] = {
        "train_pool": {
            "train_pair_count": len(train_pool),
            "history": history,
            "metrics": evaluate_split(train_pool, weights=weights, mean=mean, std=std),
        }
    }

    for split_name in eval_split_names:
        heldout_pairs = eval_rows[split_name]
        filtered_train = filter_train_against_eval(train_pool, heldout_pairs)
        if not filtered_train:
            split_metrics[split_name] = {
                "train_pair_count": 0,
                "history": [],
                "metrics": evaluate_split(heldout_pairs, weights=weights, mean=mean, std=std),
                "note": "no leakage-safe training pairs available for this held-out split",
            }
            continue

        split_weights, split_mean, split_std, split_history = train_pairwise_model(
            filtered_train,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            l2=args.l2,
            seed=args.seed,
            log_every=args.log_every,
        )
        split_model = {
            "feature_names": FEATURE_NAMES,
            "weights": split_weights.tolist(),
            "mean": split_mean.tolist(),
            "std": split_std.tolist(),
        }
        (model_dir / f"{split_name}_model.json").write_text(json.dumps(split_model, indent=2) + "\n", encoding="utf-8")
        split_metrics[split_name] = {
            "train_pair_count": len(filtered_train),
            "history": split_history,
            "metrics": evaluate_split(heldout_pairs, weights=split_weights, mean=split_mean, std=split_std),
        }

    metrics = {
        "dataset_dir": str(dataset_dir),
        "output_dir": str(output_dir),
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "l2": args.l2,
        "seed": args.seed,
        "feature_names": FEATURE_NAMES,
        "splits": split_metrics,
        "feature_weights": [
            {"feature": name, "weight": float(weight)}
            for name, weight in sorted(zip(FEATURE_NAMES, weights), key=lambda item: abs(item[1]), reverse=True)
        ],
        "normalization": {
            "mean": mean.tolist(),
            "std": std.tolist(),
        },
    }
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
