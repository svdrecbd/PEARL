#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_strict_first_union_curricula import normalize_prompt_bucket
from scripts.rebalance_stage1_wave import collect_run_states, resolve_runs_dir


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.open("r", encoding="utf-8") if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def prompt_row_id(row: dict[str, Any]) -> str:
    for key in ("prompt_id", "sequence_sha256", "prompt"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    raise SystemExit(f"Prompt row is missing a stable id: {row}")


def prompt_bucket(row: dict[str, Any]) -> str:
    return normalize_prompt_bucket(str(row["prompt"]))


def load_remaining_tail_rows(wave_dir: Path) -> list[dict[str, Any]]:
    wave_metadata = json.loads((wave_dir / "wave_metadata.json").read_text(encoding="utf-8"))
    runs_dir = resolve_runs_dir(wave_dir=wave_dir, wave_metadata=wave_metadata)
    run_states = collect_run_states(runs_dir=runs_dir)
    tail_rows: list[dict[str, Any]] = []
    for state in run_states:
        tail_rows.extend(state["remaining_rows"])
    if not tail_rows:
        raise SystemExit(f"No remaining tail rows found in {wave_dir}")
    return tail_rows


def load_hit_prompt_sets(functional_hits_path: Path, family_hits_path: Path) -> tuple[set[str], set[str]]:
    functional_prompts = {str(row["prompt"]) for row in load_jsonl(functional_hits_path)}
    family_prompts = {str(row["prompt"]) for row in load_jsonl(family_hits_path)}
    return functional_prompts, family_prompts


def compute_bucket_stats(
    attempted_rows: list[dict[str, Any]],
    *,
    functional_prompts: set[str],
    family_prompts: set[str],
) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"attempted": 0, "functional_hit_prompts": 0, "family_hit_prompts": 0})
    for row in attempted_rows:
        bucket = prompt_bucket(row)
        stats[bucket]["attempted"] += 1
        stats[bucket]["functional_hit_prompts"] += int(str(row["prompt"]) in functional_prompts)
        stats[bucket]["family_hit_prompts"] += int(str(row["prompt"]) in family_prompts)
    for bucket, item in stats.items():
        attempted = int(item["attempted"])
        item["functional_hit_rate"] = item["functional_hit_prompts"] / attempted
        item["family_hit_rate"] = item["family_hit_prompts"] / attempted
        item["bucket"] = bucket
    return stats


def select_adversarial_rows(
    future_pool: list[dict[str, Any]],
    *,
    bucket_stats: dict[str, dict[str, Any]],
    adversarial_count: int,
    min_attempted_bucket_count: int,
    max_family_hit_rate: float,
    max_functional_hit_rate: float,
    max_per_bucket: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    weak_buckets = [
        stats
        for stats in bucket_stats.values()
        if int(stats["attempted"]) >= min_attempted_bucket_count
        and float(stats["family_hit_rate"]) <= max_family_hit_rate
        and float(stats["functional_hit_rate"]) <= max_functional_hit_rate
    ]
    weak_buckets.sort(
        key=lambda stats: (
            float(stats["family_hit_rate"]),
            float(stats["functional_hit_rate"]),
            -int(stats["attempted"]),
            str(stats["bucket"]),
        )
    )
    candidate_rows_by_bucket: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for row in future_pool:
        bucket = prompt_bucket(row)
        if bucket in bucket_stats and int(bucket_stats[bucket]["attempted"]) >= min_attempted_bucket_count:
            candidate_rows_by_bucket[bucket].append(row)

    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    selected_per_bucket: Counter[str] = Counter()
    live_bucket_stats = [stats for stats in weak_buckets if candidate_rows_by_bucket.get(str(stats["bucket"]))]
    while len(selected) < adversarial_count and live_bucket_stats:
        advanced = False
        next_live: list[dict[str, Any]] = []
        for stats in live_bucket_stats:
            bucket = str(stats["bucket"])
            rows = candidate_rows_by_bucket[bucket]
            while rows and prompt_row_id(rows[0]) in seen_ids:
                rows.popleft()
            under_cap = max_per_bucket <= 0 or selected_per_bucket[bucket] < max_per_bucket
            if rows and len(selected) < adversarial_count and under_cap:
                row = rows.popleft()
                seen_ids.add(prompt_row_id(row))
                selected.append(row)
                selected_per_bucket[bucket] += 1
                advanced = True
            keep_live = max_per_bucket <= 0 or selected_per_bucket[bucket] < max_per_bucket
            if rows and keep_live:
                next_live.append(stats)
        live_bucket_stats = next_live
        if not advanced:
            break

    if len(selected) < adversarial_count:
        raise SystemExit(
            f"Adversarial prompt shortfall: needed {adversarial_count}, selected {len(selected)} "
            f"from weak buckets with min_attempted_bucket_count={min_attempted_bucket_count}, "
            f"max_family_hit_rate={max_family_hit_rate}, max_functional_hit_rate={max_functional_hit_rate}"
        )

    selected_bucket_stats = [bucket_stats[prompt_bucket(row)] for row in selected]
    return selected, selected_bucket_stats


def select_standard_rows(
    future_pool: list[dict[str, Any]],
    *,
    excluded_ids: set[str],
    standard_count: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in future_pool:
        row_id = prompt_row_id(row)
        if row_id in excluded_ids:
            continue
        selected.append(row)
        excluded_ids.add(row_id)
        if len(selected) == standard_count:
            return selected
    raise SystemExit(f"Standard prompt shortfall: needed {standard_count}, selected {len(selected)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an explicit prompt pack for the next stageb-lite million tranche")
    parser.add_argument("--source-prompts-path", default=str(ROOT / "data" / "petase_family_expanded" / "train_prompts_relevance_ge10.jsonl"))
    parser.add_argument("--tail-wave-dir", required=True)
    parser.add_argument("--functional-hits-path", required=True)
    parser.add_argument("--family-hits-path", required=True)
    parser.add_argument("--prior-consumed-prompt-count", type=int, default=7813)
    parser.add_argument("--tail-count")
    parser.add_argument("--standard-count", type=int, required=True)
    parser.add_argument("--adversarial-count", type=int, required=True)
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument("--min-attempted-bucket-count", type=int, default=5)
    parser.add_argument("--max-family-hit-rate", type=float, default=0.0)
    parser.add_argument("--max-functional-hit-rate", type=float, default=0.0)
    parser.add_argument("--max-adversarial-per-bucket", type=int, default=0)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path", required=True)
    args = parser.parse_args()

    source_prompts = load_jsonl(Path(args.source_prompts_path))
    shuffled = list(source_prompts)
    random.Random(args.seed).shuffle(shuffled)
    if args.prior_consumed_prompt_count >= len(shuffled):
        raise SystemExit("prior-consumed-prompt-count is past the end of the source prompt list")

    tail_rows = load_remaining_tail_rows(Path(args.tail_wave_dir))
    if args.tail_count is not None and int(args.tail_count) != len(tail_rows):
        raise SystemExit(f"Tail count mismatch: expected {args.tail_count}, found {len(tail_rows)}")

    functional_prompts, family_prompts = load_hit_prompt_sets(
        Path(args.functional_hits_path),
        Path(args.family_hits_path),
    )
    attempted_rows = shuffled[: args.prior_consumed_prompt_count]
    bucket_stats = compute_bucket_stats(
        attempted_rows,
        functional_prompts=functional_prompts,
        family_prompts=family_prompts,
    )

    future_pool = shuffled[args.prior_consumed_prompt_count :]
    tail_ids = {prompt_row_id(row) for row in tail_rows}
    future_pool = [row for row in future_pool if prompt_row_id(row) not in tail_ids]

    adversarial_rows, selected_bucket_stats = select_adversarial_rows(
        future_pool,
        bucket_stats=bucket_stats,
        adversarial_count=args.adversarial_count,
        min_attempted_bucket_count=args.min_attempted_bucket_count,
        max_family_hit_rate=args.max_family_hit_rate,
        max_functional_hit_rate=args.max_functional_hit_rate,
        max_per_bucket=args.max_adversarial_per_bucket,
    )
    selected_ids = set(tail_ids)
    selected_ids.update(prompt_row_id(row) for row in adversarial_rows)
    standard_rows = select_standard_rows(
        future_pool,
        excluded_ids=selected_ids,
        standard_count=args.standard_count,
    )

    combined_rows = tail_rows + standard_rows + adversarial_rows
    write_jsonl(Path(args.output_path), combined_rows)

    selected_adversarial_buckets = Counter(prompt_bucket(row) for row in adversarial_rows)
    selected_standard_buckets = Counter(prompt_bucket(row) for row in standard_rows)
    summary = {
        "source_prompts_path": str(Path(args.source_prompts_path).resolve()),
        "tail_wave_dir": str(Path(args.tail_wave_dir).resolve()),
        "prior_consumed_prompt_count": args.prior_consumed_prompt_count,
        "tail_count": len(tail_rows),
        "standard_count": len(standard_rows),
        "adversarial_count": len(adversarial_rows),
        "total_prompt_count": len(combined_rows),
        "seed": args.seed,
        "min_attempted_bucket_count": args.min_attempted_bucket_count,
        "max_family_hit_rate": args.max_family_hit_rate,
        "max_functional_hit_rate": args.max_functional_hit_rate,
        "max_adversarial_per_bucket": args.max_adversarial_per_bucket,
        "attempted_bucket_count": len(bucket_stats),
        "weak_bucket_candidate_count": sum(
            1
            for stats in bucket_stats.values()
            if int(stats["attempted"]) >= args.min_attempted_bucket_count
            and float(stats["family_hit_rate"]) <= args.max_family_hit_rate
            and float(stats["functional_hit_rate"]) <= args.max_functional_hit_rate
        ),
        "selected_adversarial_bucket_count": len(selected_adversarial_buckets),
        "selected_standard_bucket_count": len(selected_standard_buckets),
        "selected_adversarial_buckets": [
            {
                **stats,
                "selected_prompt_count": int(selected_adversarial_buckets[str(stats["bucket"])]),
            }
            for stats in sorted(
                {
                    str(stats["bucket"]): stats
                    for stats in selected_bucket_stats
                }.values(),
                key=lambda stats: (
                    float(stats["family_hit_rate"]),
                    float(stats["functional_hit_rate"]),
                    -int(stats["attempted"]),
                    str(stats["bucket"]),
                ),
            )
        ],
        "output_path": str(Path(args.output_path).resolve()),
    }
    Path(args.summary_path).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
