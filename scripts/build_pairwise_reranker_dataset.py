#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_finalized_hit_lineage_bundle import extract_hit_row, to_float, to_optional_int
from build_strict_first_union_curricula import normalize_prompt_bucket


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build prompt-matched pairwise preference data from finalized mining waves. "
            "Pairs are split with prompt, prompt-bucket, exact-sequence, and cluster leakage guards."
        )
    )
    parser.add_argument("--wave-dir", action="append", required=True, help="Finalized wave directory")
    parser.add_argument("--strict-hits-path", required=True, help="all_family_faithful_hits_exact.jsonl")
    parser.add_argument("--functional-hits-path", required=True, help="all_functional_hits_exact.jsonl")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-pairs-per-prompt", type=int, default=2)
    parser.add_argument("--max-chosen-per-cluster", type=int, default=1)
    parser.add_argument("--prompt-holdout-frac", type=float, default=0.1)
    parser.add_argument("--bucket-holdout-frac", type=float, default=0.1)
    parser.add_argument("--cluster-holdout-frac", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=37)
    return parser.parse_args()


def reward_component(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    raw_record = row.get("raw_record") or {}
    reward_components = raw_record.get("reward_components") or {}
    return to_float(reward_components.get(key), default=default)


def cluster_identity(row: dict[str, Any]) -> str:
    cluster_id = row.get("cluster_id")
    if cluster_id is not None:
        return f"cluster::{cluster_id}"
    sequence = str(row.get("sequence") or "").strip()
    return f"sequence::{sequence}"


def gap_quality(row: dict[str, Any]) -> float:
    best_gap_error = row.get("best_gap_error")
    if not isinstance(best_gap_error, int):
        return 0.0
    return 1.0 / (1.0 + max(best_gap_error, 0))


def candidate_payload(row: dict[str, Any], *, category: str) -> dict[str, Any]:
    prompt = str(row.get("prompt") or "").strip()
    prompt_bucket = normalize_prompt_bucket(prompt)
    closest_edit_identity = to_float(row.get("closest_edit_identity"))
    return {
        "category": category,
        "prompt": prompt,
        "prompt_bucket": prompt_bucket,
        "sequence": str(row.get("sequence") or "").strip(),
        "wave_name": str(row.get("wave_name") or ""),
        "source_run": str(row.get("source_run") or ""),
        "source_step": int(row.get("source_step") or -1),
        "cluster_id": row.get("cluster_id"),
        "cluster_key": cluster_identity(row),
        "cluster_size": to_optional_int(row.get("cluster_size")),
        "reward": to_float(row.get("reward")),
        "esm_reward": to_float(row.get("esm_reward")),
        "stage2_score": to_float(row.get("stage2_score")),
        "stage1_rank": to_optional_int(row.get("stage1_rank")),
        "stage2_rank": to_optional_int(row.get("stage2_rank")),
        "best_gap_error": to_optional_int(row.get("best_gap_error")),
        "gap_quality": gap_quality(row),
        "functional_bridge_passes": bool(row.get("functional_bridge_passes")),
        "family_faithful_bridge_passes": bool(row.get("family_faithful_bridge_passes")),
        "passes_core_screen": bool(row.get("passes_core_screen")),
        "catalytic_geometry_passes": bool(row.get("catalytic_geometry_passes")),
        "has_family_serine_motif": bool(row.get("has_family_serine_motif")),
        "motif_count": int(row.get("motif_count") or 0),
        "closest_edit_identity": closest_edit_identity,
        "novelty_bonus": 1.0 - closest_edit_identity,
        "length": int(row.get("length") or len(str(row.get("sequence") or ""))),
        "family_reward": reward_component(row, "family_reward"),
        "dense_family_reward": reward_component(row, "dense_family_reward"),
        "rl_family_reward": reward_component(row, "rl_family_reward"),
        "template_penalty": reward_component(row, "template_penalty"),
        "motif_spam_penalty": reward_component(row, "motif_spam_penalty", default=1.0),
        "tandem_repeat_penalty": reward_component(row, "tandem_repeat_penalty", default=1.0),
        "local_entropy_penalty": reward_component(row, "local_entropy_penalty", default=1.0),
        "kmer_uniqueness_ratio": reward_component(row, "kmer_uniqueness_ratio"),
        "min_local_window_entropy": reward_component(row, "min_local_window_entropy"),
    }


def strict_rank_key(row: dict[str, Any]) -> tuple[float, ...]:
    return (
        float(bool(row.get("family_faithful_bridge_passes"))),
        float(bool(row.get("passes_core_screen"))),
        float(bool(row.get("catalytic_geometry_passes"))),
        reward_component(row, "family_reward"),
        reward_component(row, "dense_family_reward"),
        to_float(row.get("reward")),
        to_float(row.get("esm_reward")),
        to_float(row.get("stage2_score")),
        gap_quality(row),
        1.0 - to_float(row.get("closest_edit_identity")),
        -float(int(row.get("length") or 0)),
    )


def functional_rank_key(row: dict[str, Any]) -> tuple[float, ...]:
    return (
        float(bool(row.get("functional_bridge_passes"))),
        float(bool(row.get("passes_core_screen"))),
        float(bool(row.get("catalytic_geometry_passes"))),
        reward_component(row, "family_reward"),
        reward_component(row, "dense_family_reward"),
        to_float(row.get("reward")),
        to_float(row.get("esm_reward")),
        to_float(row.get("stage2_score")),
        gap_quality(row),
        1.0 - to_float(row.get("closest_edit_identity")),
        -float(int(row.get("length") or 0)),
    )


def nonfunctional_rank_key(row: dict[str, Any]) -> tuple[float, ...]:
    return (
        reward_component(row, "family_reward"),
        reward_component(row, "dense_family_reward"),
        to_float(row.get("reward")),
        to_float(row.get("esm_reward")),
        to_float(row.get("stage2_score")),
        float(bool(row.get("passes_core_screen"))),
        float(bool(row.get("catalytic_geometry_passes"))),
        gap_quality(row),
        1.0 - to_float(row.get("closest_edit_identity")),
        -float(int(row.get("length") or 0)),
    )


def dedupe_exact_keep_best(
    rows: list[dict[str, Any]],
    *,
    rank_key: Callable[[dict[str, Any]], tuple[float, ...]],
) -> list[dict[str, Any]]:
    best_by_sequence: dict[str, dict[str, Any]] = {}
    for row in rows:
        sequence = str(row.get("sequence") or "").strip()
        if not sequence:
            continue
        existing = best_by_sequence.get(sequence)
        if existing is None or rank_key(row) > rank_key(existing):
            best_by_sequence[sequence] = row
    deduped = list(best_by_sequence.values())
    deduped.sort(key=rank_key, reverse=True)
    return deduped


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.open() if line.strip()]


def load_exact_hits(path: Path, *, category: str) -> list[dict[str, Any]]:
    rows = load_jsonl(path)
    for row in rows:
        row["category"] = category
    return rows


def collect_nonfunctional_rows(wave_dirs: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for wave_dir in wave_dirs:
        summary_path = wave_dir / "finalization_summary.json"
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        wave_name = str(payload.get("name") or wave_dir.name)
        for result in payload.get("results", []):
            report_basename = Path(str(result["report_path"])).parent.name
            report_path = wave_dir / "runs" / report_basename / "report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            for record in report.get("records", []):
                row = extract_hit_row(
                    wave_name=wave_name,
                    report_run_name=report_basename,
                    record=record,
                )
                if bool(row["functional_bridge_passes"]) or bool(row["family_faithful_bridge_passes"]):
                    continue
                rows.append(row)
    return dedupe_exact_keep_best(rows, rank_key=nonfunctional_rank_key)


def group_by_prompt(rows: list[dict[str, Any]], *, rank_key: Callable[[dict[str, Any]], tuple[float, ...]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        prompt = str(row.get("prompt") or "").strip()
        if not prompt:
            continue
        grouped[prompt].append(row)
    for prompt_rows in grouped.values():
        prompt_rows.sort(key=rank_key, reverse=True)
    return grouped


def build_pairs(
    *,
    strict_rows: list[dict[str, Any]],
    functional_rows: list[dict[str, Any]],
    nonfunctional_rows: list[dict[str, Any]],
    max_pairs_per_prompt: int,
    max_chosen_per_cluster: int,
) -> list[dict[str, Any]]:
    strict_by_prompt = group_by_prompt(strict_rows, rank_key=strict_rank_key)
    functional_by_prompt = group_by_prompt(functional_rows, rank_key=functional_rank_key)
    nonfunctional_by_prompt = group_by_prompt(nonfunctional_rows, rank_key=nonfunctional_rank_key)

    prompts = sorted(set(strict_by_prompt) | set(functional_by_prompt) | set(nonfunctional_by_prompt))
    chosen_cluster_counts: Counter[str] = Counter()
    pair_rows: list[dict[str, Any]] = []
    next_pair_index = 1

    for prompt in prompts:
        prompt_pairs: list[dict[str, Any]] = []
        chosen_source = None

        for candidate in strict_by_prompt.get(prompt, []):
            cluster_key = cluster_identity(candidate)
            if chosen_cluster_counts[cluster_key] >= max_chosen_per_cluster:
                continue
            chosen_source = ("family_faithful", candidate)
            break

        if chosen_source is None:
            for candidate in functional_by_prompt.get(prompt, []):
                cluster_key = cluster_identity(candidate)
                if chosen_cluster_counts[cluster_key] >= max_chosen_per_cluster:
                    continue
                chosen_source = ("functional_nonfaithful", candidate)
                break

        if chosen_source is None:
            continue

        chosen_category, chosen_row = chosen_source
        chosen_payload = candidate_payload(chosen_row, category=chosen_category)

        if chosen_category == "family_faithful":
            functional_rejected = functional_by_prompt.get(prompt, [])
            if functional_rejected:
                rejected_payload = candidate_payload(functional_rejected[0], category="functional_nonfaithful")
                prompt_pairs.append(
                    make_pair(
                        pair_index=next_pair_index,
                        pair_type="family_over_functional",
                        prompt=prompt,
                        chosen=chosen_payload,
                        rejected=rejected_payload,
                    )
                )
                next_pair_index += 1
            nonfunctional_rejected = nonfunctional_by_prompt.get(prompt, [])
            if nonfunctional_rejected and len(prompt_pairs) < max_pairs_per_prompt:
                rejected_payload = candidate_payload(nonfunctional_rejected[0], category="nonfunctional")
                prompt_pairs.append(
                    make_pair(
                        pair_index=next_pair_index,
                        pair_type="family_over_nonfunctional",
                        prompt=prompt,
                        chosen=chosen_payload,
                        rejected=rejected_payload,
                    )
                )
                next_pair_index += 1
        else:
            nonfunctional_rejected = nonfunctional_by_prompt.get(prompt, [])
            if nonfunctional_rejected:
                rejected_payload = candidate_payload(nonfunctional_rejected[0], category="nonfunctional")
                prompt_pairs.append(
                    make_pair(
                        pair_index=next_pair_index,
                        pair_type="functional_over_nonfunctional",
                        prompt=prompt,
                        chosen=chosen_payload,
                        rejected=rejected_payload,
                    )
                )
                next_pair_index += 1

        if prompt_pairs:
            chosen_cluster_counts[chosen_payload["cluster_key"]] += 1
            pair_rows.extend(prompt_pairs[:max_pairs_per_prompt])

    return pair_rows


def make_pair(
    *,
    pair_index: int,
    pair_type: str,
    prompt: str,
    chosen: dict[str, Any],
    rejected: dict[str, Any],
) -> dict[str, Any]:
    return {
        "pair_id": f"pair-{pair_index:06d}",
        "pair_type": pair_type,
        "prompt": prompt,
        "prompt_bucket": normalize_prompt_bucket(prompt),
        "chosen": chosen,
        "rejected": rejected,
    }


def deterministic_holdout(value: str, *, salt: str, seed: int, fraction: float) -> bool:
    digest = hashlib.sha256(f"{salt}:{seed}:{value}".encode("utf-8")).digest()
    raw = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return (raw / float(2**64)) < fraction


def assign_split(
    pair: dict[str, Any],
    *,
    seed: int,
    prompt_holdout_frac: float,
    bucket_holdout_frac: float,
    cluster_holdout_frac: float,
) -> str:
    prompt = pair["prompt"]
    prompt_bucket = pair["prompt_bucket"]
    chosen_cluster = pair["chosen"]["cluster_key"]
    rejected_cluster = pair["rejected"]["cluster_key"]

    prompt_holdout = deterministic_holdout(prompt, salt="prompt", seed=seed, fraction=prompt_holdout_frac)
    bucket_holdout = deterministic_holdout(prompt_bucket, salt="bucket", seed=seed, fraction=bucket_holdout_frac)
    chosen_cluster_holdout = deterministic_holdout(
        chosen_cluster,
        salt="cluster",
        seed=seed,
        fraction=cluster_holdout_frac,
    )
    rejected_cluster_holdout = deterministic_holdout(
        rejected_cluster,
        salt="cluster",
        seed=seed,
        fraction=cluster_holdout_frac,
    )

    if bucket_holdout and (chosen_cluster_holdout or rejected_cluster_holdout):
        return "hard_holdout"
    if prompt_holdout:
        return "prompt_holdout"
    if bucket_holdout:
        return "bucket_holdout"
    if chosen_cluster_holdout or rejected_cluster_holdout:
        return "cluster_holdout"
    return "train"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def summarize_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    prompts = {row["prompt"] for row in rows}
    buckets = {row["prompt_bucket"] for row in rows}
    chosen_sequences = {row["chosen"]["sequence"] for row in rows}
    rejected_sequences = {row["rejected"]["sequence"] for row in rows}
    chosen_clusters = {row["chosen"]["cluster_key"] for row in rows}
    rejected_clusters = {row["rejected"]["cluster_key"] for row in rows}
    pair_type_counts = Counter(row["pair_type"] for row in rows)
    chosen_category_counts = Counter(row["chosen"]["category"] for row in rows)
    rejected_category_counts = Counter(row["rejected"]["category"] for row in rows)
    return {
        "pair_count": len(rows),
        "prompt_count": len(prompts),
        "prompt_bucket_count": len(buckets),
        "chosen_sequence_count": len(chosen_sequences),
        "rejected_sequence_count": len(rejected_sequences),
        "chosen_cluster_count": len(chosen_clusters),
        "rejected_cluster_count": len(rejected_clusters),
        "pair_type_counts": dict(pair_type_counts),
        "chosen_category_counts": dict(chosen_category_counts),
        "rejected_category_counts": dict(rejected_category_counts),
    }


def leakage_summary(split_rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    train = split_rows["train"]
    train_prompts = {row["prompt"] for row in train}
    train_buckets = {row["prompt_bucket"] for row in train}
    train_sequences = {row["chosen"]["sequence"] for row in train} | {row["rejected"]["sequence"] for row in train}
    train_clusters = {row["chosen"]["cluster_key"] for row in train} | {row["rejected"]["cluster_key"] for row in train}

    summary: dict[str, Any] = {}
    for split_name, rows in split_rows.items():
        if split_name == "train":
            continue
        split_prompts = {row["prompt"] for row in rows}
        split_buckets = {row["prompt_bucket"] for row in rows}
        split_sequences = {row["chosen"]["sequence"] for row in rows} | {row["rejected"]["sequence"] for row in rows}
        split_clusters = {row["chosen"]["cluster_key"] for row in rows} | {row["rejected"]["cluster_key"] for row in rows}
        summary[split_name] = {
            "prompt_overlap_with_train": len(train_prompts & split_prompts),
            "prompt_bucket_overlap_with_train": len(train_buckets & split_buckets),
            "sequence_overlap_with_train": len(train_sequences & split_sequences),
            "cluster_overlap_with_train": len(train_clusters & split_clusters),
        }
    return summary


def main() -> None:
    args = parse_args()
    wave_dirs = [Path(raw).expanduser().resolve() for raw in args.wave_dir]
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    strict_rows = load_exact_hits(Path(args.strict_hits_path).expanduser().resolve(), category="family_faithful")
    functional_rows_all = load_exact_hits(Path(args.functional_hits_path).expanduser().resolve(), category="functional")
    strict_sequences = {str(row.get("sequence") or "").strip() for row in strict_rows}
    functional_rows = [
        row
        for row in functional_rows_all
        if str(row.get("sequence") or "").strip() not in strict_sequences
        and not bool(row.get("family_faithful_bridge_passes"))
    ]
    nonfunctional_rows = collect_nonfunctional_rows(wave_dirs)

    pair_rows = build_pairs(
        strict_rows=strict_rows,
        functional_rows=functional_rows,
        nonfunctional_rows=nonfunctional_rows,
        max_pairs_per_prompt=args.max_pairs_per_prompt,
        max_chosen_per_cluster=args.max_chosen_per_cluster,
    )

    split_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pair_rows:
        split_name = assign_split(
            row,
            seed=args.seed,
            prompt_holdout_frac=args.prompt_holdout_frac,
            bucket_holdout_frac=args.bucket_holdout_frac,
            cluster_holdout_frac=args.cluster_holdout_frac,
        )
        split_rows[split_name].append(dict(row, split=split_name))

    for split_name in ("train", "prompt_holdout", "bucket_holdout", "cluster_holdout", "hard_holdout"):
        split_rows.setdefault(split_name, [])

    summary = {
        "wave_dirs": [str(path) for path in wave_dirs],
        "strict_hits_path": str(Path(args.strict_hits_path).expanduser().resolve()),
        "functional_hits_path": str(Path(args.functional_hits_path).expanduser().resolve()),
        "max_pairs_per_prompt": args.max_pairs_per_prompt,
        "max_chosen_per_cluster": args.max_chosen_per_cluster,
        "seed": args.seed,
        "prompt_holdout_frac": args.prompt_holdout_frac,
        "bucket_holdout_frac": args.bucket_holdout_frac,
        "cluster_holdout_frac": args.cluster_holdout_frac,
        "strict_input_count": len(strict_rows),
        "functional_nonfaithful_input_count": len(functional_rows),
        "nonfunctional_input_count": len(nonfunctional_rows),
        "pair_count_total": sum(len(rows) for rows in split_rows.values()),
        "requires_split_specific_train_filtering": True,
        "split_summaries": {name: summarize_split(rows) for name, rows in split_rows.items()},
        "train_leakage_check": leakage_summary(split_rows),
        "output_dir": str(output_dir),
    }

    all_rows: list[dict[str, Any]] = []
    for split_name in ("train", "prompt_holdout", "bucket_holdout", "cluster_holdout", "hard_holdout"):
        rows = split_rows[split_name]
        write_jsonl(output_dir / f"pairs_{split_name}.jsonl", rows)
        all_rows.extend(rows)
    write_jsonl(output_dir / "pairs_all.jsonl", all_rows)

    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
