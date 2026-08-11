#!/usr/bin/env python3
"""Build nested, provenance-preserving datasets for the PEARL scaling study."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from argparse import Namespace
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_hybrid_10k_dpo import (  # noqa: E402
    DEFAULT_GENERATED_NEGATIVE_PATHS,
    DEFAULT_ORGANIC_PATHS,
    DEFAULT_POSITIVE_RECORDS,
    build_dataset,
)


DEFAULT_OUTPUT_DIR = ROOT / "data" / "phase8_dpo" / "scaling_paradox_v1"
DEFAULT_SEED = 20260811
REQUIRED_AUDIT_FIELDS = (
    "chosen_record_id",
    "chosen_source_type",
    "chosen_reviewed",
    "chosen_active_site_count",
    "chosen_confidence_basis",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--large-size", type=int, default=10_000)
    parser.add_argument("--small-size", type=int, default=2_500)
    parser.add_argument("--holdout-groups", type=int, default=250)
    parser.add_argument("--challenge-positive-groups", type=int, default=100)
    parser.add_argument("--max-chosen-uses", type=int, default=4)
    parser.add_argument("--exclude-positive-length", action="append", type=int, default=[303])
    parser.add_argument("--positive-records", default=str(DEFAULT_POSITIVE_RECORDS))
    parser.add_argument(
        "--generated-negative-path",
        action="append",
        default=[str(path) for path in DEFAULT_GENERATED_NEGATIVE_PATHS],
    )
    parser.add_argument(
        "--organic-path",
        action="append",
        default=[str(path) for path in DEFAULT_ORGANIC_PATHS],
    )
    return parser.parse_args()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portable_repo_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"frozen dataset outputs must live beneath the repository root: {resolved}") from exc


def stable_rank(value: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode("utf-8")).hexdigest()


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def group_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        record_id = str(row.get("chosen_record_id") or "")
        if not record_id:
            raise ValueError("every row must have chosen_record_id")
        groups[record_id].append(row)
    return dict(groups)


def select_holdout_group_ids(
    groups: dict[str, list[dict[str, Any]]],
    *,
    holdout_groups: int,
    max_chosen_uses: int,
    seed: int,
) -> set[str]:
    eligible = [record_id for record_id, rows in groups.items() if len(rows) == max_chosen_uses]
    eligible.sort(key=lambda record_id: stable_rank(record_id, seed))
    if len(eligible) < holdout_groups:
        raise ValueError(
            f"need {holdout_groups} groups with {max_chosen_uses} rows for an exact holdout; found {len(eligible)}"
        )
    return set(eligible[:holdout_groups])


def select_challenge_group_ids(
    groups: dict[str, list[dict[str, Any]]],
    *,
    challenge_groups: int,
    max_chosen_uses: int,
    target_length: int,
    tolerance: int,
    seed: int,
) -> set[str]:
    eligible = [
        record_id
        for record_id, rows in groups.items()
        if len(rows) == max_chosen_uses
        and abs(len(str(rows[0]["chosen"])) - target_length) <= tolerance
    ]
    eligible.sort(key=lambda record_id: stable_rank(record_id, seed))
    if len(eligible) < challenge_groups:
        raise ValueError(
            f"need {challenge_groups} held-out positives near length {target_length}; found {len(eligible)}"
        )
    return set(eligible[:challenge_groups])


def select_one_per_group(
    groups: dict[str, list[dict[str, Any]]],
    group_ids: list[str],
    *,
    target_size: int,
    seed: int,
) -> list[dict[str, Any]]:
    if len(group_ids) < target_size:
        raise ValueError(f"need {target_size} distinct chosen groups; found {len(group_ids)}")
    ordered_ids = sorted(group_ids, key=lambda record_id: stable_rank(record_id, seed))[:target_size]
    artifact_counts: Counter[str] = Counter()
    selected: list[dict[str, Any]] = []
    for record_id in ordered_ids:
        candidates = sorted(
            groups[record_id],
            key=lambda row: (
                artifact_counts[str(row.get("synthetic_artifact_class") or "unknown")],
                stable_rank(canonical_json(row), seed),
            ),
        )
        row = dict(candidates[0])
        artifact = str(row.get("synthetic_artifact_class") or "unknown")
        artifact_counts[artifact] += 1
        selected.append(row)
    selected.sort(key=lambda row: stable_rank(canonical_json(row), seed + 1))
    return selected


def shuffled_label_control(rows: list[dict[str, Any]], *, seed: int) -> list[dict[str, Any]]:
    ordered = sorted(range(len(rows)), key=lambda index: stable_rank(canonical_json(rows[index]), seed))
    swapped_indices = set(ordered[: len(rows) // 2])
    control: list[dict[str, Any]] = []
    for index, source in enumerate(rows):
        row = dict(source)
        original_chosen = str(source["chosen"])
        original_rejected = str(source["rejected"])
        swapped = index in swapped_indices
        if swapped:
            row["chosen"], row["rejected"] = original_rejected, original_chosen
        row.update(
            {
                "label_arm": "deterministic_shuffled",
                "label_swapped": swapped,
                "positive_sequence": original_chosen,
                "negative_sequence": original_rejected,
                "preference_rule": "deterministic_50pct_label_shuffle",
            }
        )
        control.append(row)
    return control


def validate_partition(
    rows: list[dict[str, Any]],
    *,
    max_chosen_uses: int,
    require_positive_labels: bool = True,
    require_length_matched: bool = True,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("partition is empty")
    chosen_counts: Counter[str] = Counter()
    record_ids: set[str] = set()
    triples: set[tuple[str, str, str]] = set()
    artifact_counts: Counter[str] = Counter()
    swap_count = 0
    length_deltas: Counter[int] = Counter()
    for index, row in enumerate(rows, start=1):
        missing = [field for field in REQUIRED_AUDIT_FIELDS if field not in row]
        if missing:
            raise ValueError(f"row {index} missing audit fields: {missing}")
        chosen = str(row.get("chosen") or "")
        rejected = str(row.get("rejected") or "")
        if not chosen or not rejected:
            raise ValueError(f"row {index} has an empty preference sequence")
        length_delta = len(rejected) - len(chosen)
        length_deltas[length_delta] += 1
        if require_length_matched and length_delta:
            raise ValueError(f"row {index} is not length matched")
        if require_positive_labels and str(row.get("chosen_source_type")) != "natural_reference_record":
            raise ValueError(f"row {index} does not identify an audited natural positive")
        triple = (str(row.get("prompt") or ""), chosen, rejected)
        if triple in triples:
            raise ValueError(f"duplicate prompt/chosen/rejected triple at row {index}")
        triples.add(triple)
        chosen_counts[str(row.get("positive_sequence") or chosen)] += 1
        record_ids.add(str(row["chosen_record_id"]))
        artifact_counts[str(row.get("synthetic_artifact_class") or "unknown")] += 1
        swap_count += int(bool(row.get("label_swapped")))
    observed_max = max(chosen_counts.values())
    if observed_max > max_chosen_uses:
        raise ValueError(f"chosen reuse {observed_max} exceeds maximum {max_chosen_uses}")
    return {
        "rows": len(rows),
        "unique_chosen_sequences": len(chosen_counts),
        "unique_chosen_record_ids": len(record_ids),
        "max_observed_chosen_uses": observed_max,
        "artifact_class_counts": dict(sorted(artifact_counts.items())),
        "label_swaps": swap_count,
        "length_matched_rows": length_deltas.get(0, 0),
        "length_delta_counts": {str(key): value for key, value in sorted(length_deltas.items())},
    }


def rebuild_disjoint_challenge(
    challenge_rows: list[dict[str, Any]],
    groups: dict[str, list[dict[str, Any]]],
    holdout_ids: set[str],
    *,
    max_chosen_uses: int,
    seed: int,
) -> list[dict[str, Any]]:
    positive_by_length: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record_id in holdout_ids:
        representative = groups[record_id][0]
        positive_by_length[len(str(representative["chosen"]))].append(representative)
    for candidates in positive_by_length.values():
        candidates.sort(key=lambda row: stable_rank(str(row["chosen_record_id"]), seed))

    uses: Counter[str] = Counter()
    rebuilt: list[dict[str, Any]] = []
    ordered_challenges = sorted(challenge_rows, key=lambda row: stable_rank(canonical_json(row), seed + 1))
    for source in ordered_challenges:
        rejected = str(source.get("rejected") or "")
        exact_candidates = [
            row
            for row in positive_by_length.get(len(rejected), [])
            if uses[str(row["chosen_record_id"])] < max_chosen_uses
        ]
        candidates = exact_candidates
        if not candidates:
            tolerance = max(5, round(len(rejected) * 0.05))
            candidates = [
                row
                for length, rows in positive_by_length.items()
                if abs(length - len(rejected)) <= tolerance
                for row in rows
                if uses[str(row["chosen_record_id"])] < max_chosen_uses
            ]
        if not candidates:
            continue
        positive = min(
            candidates,
            key=lambda row: (
                uses[str(row["chosen_record_id"])],
                stable_rank(f"{row['chosen_record_id']}:{rejected}", seed + 2),
            ),
        )
        row = dict(source)
        row["prompt"] = positive["prompt"]
        row["chosen"] = positive["chosen"]
        for key, value in positive.items():
            if key.startswith("chosen_"):
                row[key] = value
        row["challenge_partition"] = "heldout_positive_vs_real_generated_failure"
        row["challenge_length_delta"] = len(rejected) - len(str(positive["chosen"]))
        row["challenge_margin_normalization"] = "per_residue_required"
        uses[str(positive["chosen_record_id"])] += 1
        rebuilt.append(row)
    rebuilt.sort(key=lambda row: stable_rank(canonical_json(row), seed + 3))
    return rebuilt


def build_contract(args: argparse.Namespace) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    if args.small_size <= args.holdout_groups:
        raise ValueError("small_size must exceed holdout_groups")
    builder_args = Namespace(
        positive_records=args.positive_records,
        generated_negative_path=args.generated_negative_path,
        organic_path=args.organic_path,
        output_path="unused.jsonl",
        manifest_path="unused.json",
        target_total=args.large_size + (args.challenge_positive_groups * args.max_chosen_uses),
        seed=args.seed,
        site_margin=50,
        min_positive_length=180,
        max_positive_length=360,
        max_positive_exact_repeat=15,
        generated_hard_negative_fraction=0.25,
        include_generated_hard_negatives=False,
        max_chosen_uses=args.max_chosen_uses,
        exclude_positive_length=args.exclude_positive_length,
        generated_challenge_output_path="challenge.jsonl",
    )
    large_rows, challenge_rows, source_manifest = build_dataset(builder_args)
    groups = group_rows(large_rows)
    challenge_ids = select_challenge_group_ids(
        groups,
        challenge_groups=args.challenge_positive_groups,
        max_chosen_uses=args.max_chosen_uses,
        target_length=303,
        tolerance=15,
        seed=args.seed + 5,
    )
    holdout_ids = select_holdout_group_ids(
        {record_id: rows for record_id, rows in groups.items() if record_id not in challenge_ids},
        holdout_groups=args.holdout_groups,
        max_chosen_uses=args.max_chosen_uses,
        seed=args.seed + 10,
    )
    large_holdout = [row for row in large_rows if str(row["chosen_record_id"]) in holdout_ids]
    large_train = [
        row
        for row in large_rows
        if str(row["chosen_record_id"]) not in holdout_ids | challenge_ids
    ]
    small_holdout = select_one_per_group(
        groups,
        sorted(holdout_ids),
        target_size=args.holdout_groups,
        seed=args.seed + 20,
    )
    small_train = select_one_per_group(
        groups,
        sorted(set(groups) - holdout_ids - challenge_ids),
        target_size=args.small_size - args.holdout_groups,
        seed=args.seed + 30,
    )
    disjoint_challenge = rebuild_disjoint_challenge(
        challenge_rows,
        groups,
        challenge_ids,
        max_chosen_uses=args.max_chosen_uses,
        seed=args.seed + 40,
    )

    partitions = {
        "d10_train_true": large_train,
        "d10_holdout_true": large_holdout,
        "d10_train_shuffled": shuffled_label_control(large_train, seed=args.seed + 50),
        "d2p5_train_true": small_train,
        "d2p5_holdout_true": small_holdout,
        "d2p5_train_shuffled": shuffled_label_control(small_train, seed=args.seed + 60),
        "real_failure_challenge": disjoint_challenge,
    }

    train_ids = {str(row["chosen_record_id"]) for row in large_train}
    holdout_record_ids = {str(row["chosen_record_id"]) for row in large_holdout}
    if train_ids & holdout_record_ids:
        raise ValueError("large train and holdout chosen groups overlap")
    if (train_ids | holdout_record_ids) & challenge_ids:
        raise ValueError("real-failure challenge positives overlap train or holdout groups")
    if not {canonical_json(row) for row in small_train}.issubset({canonical_json(row) for row in large_train}):
        raise ValueError("small train is not nested within large train")
    if not {canonical_json(row) for row in small_holdout}.issubset({canonical_json(row) for row in large_holdout}):
        raise ValueError("small holdout is not nested within large holdout")

    manifest = {
        "contract": "pearl.scaling-paradox-datasets/1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "config": {
            "large_size": args.large_size,
            "small_size": args.small_size,
            "holdout_groups": args.holdout_groups,
            "challenge_positive_groups": args.challenge_positive_groups,
            "max_chosen_uses": args.max_chosen_uses,
            "excluded_positive_lengths": sorted(set(args.exclude_positive_length)),
            "label_control": "deterministic balanced 50% swap",
        },
        "source_builder_manifest": source_manifest,
        "invariants": {
            "chosen_group_disjoint_train_holdout": True,
            "challenge_positive_groups_disjoint": True,
            "small_is_nested_in_large": True,
            "all_training_pairs_length_matched": True,
            "positive_provenance_required": True,
        },
        "partitions": {},
    }
    return partitions, manifest


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    partitions, manifest = build_contract(args)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in partitions.items():
        path = output_dir / f"{name}.jsonl"
        write_jsonl(path, rows)
        max_uses = 1 if name.startswith("d2p5") else args.max_chosen_uses
        require_positive = "shuffled" not in name
        summary = validate_partition(
            rows,
            max_chosen_uses=max_uses,
            require_positive_labels=require_positive,
            require_length_matched=name != "real_failure_challenge",
        )
        manifest["partitions"][name] = {
            "path": portable_repo_path(path),
            "sha256": sha256_file(path),
            **summary,
        }
    contract_payload = {
        "contract": manifest["contract"],
        "seed": manifest["seed"],
        "config": manifest["config"],
        "invariants": manifest["invariants"],
        "partitions": {
            name: {
                key: value
                for key, value in summary.items()
                if key not in {"path"}
            }
            for name, summary in manifest["partitions"].items()
        },
    }
    manifest["manifest_sha256"] = hashlib.sha256(canonical_json(contract_payload).encode("utf-8")).hexdigest()
    manifest_path = output_dir / "dataset_manifest.json"
    write_json(manifest_path, manifest)
    print(json.dumps({"manifest_path": str(manifest_path), **manifest}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
