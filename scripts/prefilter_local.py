from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, TextIO


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES_PATH = ROOT / "configs" / "prefilter" / "local_prefilter_v1.yaml"
DEFAULT_OUTPUT_ROOT = ROOT / "reports" / "prefilter"
DEFAULT_SCHEMA_VERSION = "local_prefilter_v1"
DEFAULT_ALPHABET = "ACDEFGHIKLMNPQRSTVWY"
JSON_INDENT = 2


def main() -> None:
    args = parse_args()
    rules = load_rules(Path(args.rules).expanduser().resolve())
    ruleset_version = args.ruleset_version or str(rules.get("ruleset_version") or "rules_unset")
    schema_version = args.schema_version or str(rules.get("schema_version") or DEFAULT_SCHEMA_VERSION)

    if args.command == "ingest":
        run_ingest(
            inputs=args.inputs,
            out_dir=Path(args.out_dir),
            schema_version=schema_version,
            ruleset_version=ruleset_version,
            line_limit=args.limit,
        )
        return
    if args.command == "canonicalize":
        run_canonicalize(
            input_jsonl=Path(args.input_jsonl),
            out_dir=Path(args.out_dir),
            schema_version=schema_version,
            rules=rules,
        )
        return
    if args.command == "hard-filter":
        run_hard_filter(
            input_jsonl=Path(args.input_jsonl),
            out_dir=Path(args.out_dir),
            rules=rules,
        )
        return
    if args.command == "exact-dedup":
        run_exact_dedup(
            input_jsonl=Path(args.input_jsonl),
            out_dir=Path(args.out_dir),
        )
        return
    if args.command == "near-dedup":
        run_near_dedup(
            input_jsonl=Path(args.input_jsonl),
            out_dir=Path(args.out_dir),
            rules=rules,
        )
        return
    if args.command == "priority":
        run_priority(
            input_jsonl=Path(args.input_jsonl),
            out_dir=Path(args.out_dir),
            rules=rules,
            reference_jsonl=args.reference_jsonl,
        )
        return
    if args.command == "handoff":
        run_handoff(
            tiers_a=Path(args.tier_a),
            tiers_b=Path(args.tier_b),
            tiers_c=Path(args.tier_c),
            out_dir=Path(args.out_dir),
            rules=rules,
            exploration_fraction_override=args.exploration_fraction,
            random_seed_override=args.random_seed,
        )
        return
    if args.command == "all":
        run_all(args=args, rules=rules, schema_version=schema_version, ruleset_version=ruleset_version)
        return
    raise SystemExit(f"Unknown command: {args.command}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local pre-HPC prefilter pipeline for raw candidate JSONL shards."
    )
    parser.add_argument("--rules", default=str(DEFAULT_RULES_PATH))
    parser.add_argument("--schema-version", default=DEFAULT_SCHEMA_VERSION)
    parser.add_argument("--ruleset-version", default=None)

    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Stage 0: parse raw shards and salvage malformed lines.")
    ingest.add_argument("--inputs", nargs="+", required=True, help="Raw shard files/directories.")
    ingest.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_ROOT / "ingest"))
    ingest.add_argument("--limit", type=int, default=None, help="Optional cap on total processed lines.")

    canonicalize = subparsers.add_parser("canonicalize", help="Stage 1: sequence canonicalization.")
    canonicalize.add_argument("--input-jsonl", required=True)
    canonicalize.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_ROOT / "canonical"))

    hard_filter = subparsers.add_parser("hard-filter", help="Stage 2: cheap hard filters.")
    hard_filter.add_argument("--input-jsonl", required=True)
    hard_filter.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_ROOT / "hard_filter"))

    exact_dedup = subparsers.add_parser("exact-dedup", help="Stage 3: hash-based exact dedup.")
    exact_dedup.add_argument("--input-jsonl", required=True)
    exact_dedup.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_ROOT / "exact_dedup"))

    near_dedup = subparsers.add_parser("near-dedup", help="Stage 4: cheap near-duplicate bucketing.")
    near_dedup.add_argument("--input-jsonl", required=True)
    near_dedup.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_ROOT / "near_dedup"))

    priority = subparsers.add_parser("priority", help="Stage 5: novelty + priority tiering.")
    priority.add_argument("--input-jsonl", required=True)
    priority.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_ROOT / "priority"))
    priority.add_argument(
        "--reference-jsonl",
        nargs="*",
        default=[],
        help="Optional baseline files/dirs used for novelty scoring.",
    )

    handoff = subparsers.add_parser("handoff", help="Stage 6: write scheduler-ready HPC handoff files.")
    handoff.add_argument("--tier-a", required=True)
    handoff.add_argument("--tier-b", required=True)
    handoff.add_argument("--tier-c", required=True)
    handoff.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_ROOT / "handoff"))
    handoff.add_argument("--exploration-fraction", type=float, default=None)
    handoff.add_argument("--random-seed", type=int, default=None)

    all_cmd = subparsers.add_parser("all", help="Run all stages in order.")
    all_cmd.add_argument("--inputs", nargs="+", required=True)
    all_cmd.add_argument("--out-root", default=str(DEFAULT_OUTPUT_ROOT / f"run_{utc_stamp_basic()}"))
    all_cmd.add_argument("--limit", type=int, default=None, help="Optional cap on total processed lines.")
    all_cmd.add_argument(
        "--reference-jsonl",
        nargs="*",
        default=[],
        help="Optional baseline files/dirs used for novelty scoring.",
    )
    return parser.parse_args()


def run_all(
    *,
    args: argparse.Namespace,
    rules: dict[str, Any],
    schema_version: str,
    ruleset_version: str,
) -> None:
    out_root = Path(args.out_root).expanduser().resolve()
    ingest_dir = out_root / "ingest"
    canonical_dir = out_root / "canonical"
    hard_filter_dir = out_root / "hard_filter"
    exact_dedup_dir = out_root / "exact_dedup"
    near_dedup_dir = out_root / "near_dedup"
    priority_dir = out_root / "priority"
    handoff_dir = out_root / "handoff"

    ingest_result = run_ingest(
        inputs=args.inputs,
        out_dir=ingest_dir,
        schema_version=schema_version,
        ruleset_version=ruleset_version,
        line_limit=args.limit,
    )
    canonical_result = run_canonicalize(
        input_jsonl=Path(ingest_result["records_path"]),
        out_dir=canonical_dir,
        schema_version=schema_version,
        rules=rules,
    )
    hard_filter_result = run_hard_filter(
        input_jsonl=Path(canonical_result["records_path"]),
        out_dir=hard_filter_dir,
        rules=rules,
    )
    exact_dedup_result = run_exact_dedup(
        input_jsonl=Path(hard_filter_result["pass_path"]),
        out_dir=exact_dedup_dir,
    )
    near_dedup_result = run_near_dedup(
        input_jsonl=Path(exact_dedup_result["unique_path"]),
        out_dir=near_dedup_dir,
        rules=rules,
    )
    priority_result = run_priority(
        input_jsonl=Path(near_dedup_result["selected_path"]),
        out_dir=priority_dir,
        rules=rules,
        reference_jsonl=args.reference_jsonl,
    )
    handoff_result = run_handoff(
        tiers_a=Path(priority_result["tier_a_path"]),
        tiers_b=Path(priority_result["tier_b_path"]),
        tiers_c=Path(priority_result["tier_c_path"]),
        out_dir=handoff_dir,
        rules=rules,
        exploration_fraction_override=None,
        random_seed_override=None,
    )

    summary = {
        "command": "all",
        "out_root": str(out_root),
        "stages": {
            "ingest": ingest_result["stats"],
            "canonicalize": canonical_result["stats"],
            "hard_filter": hard_filter_result["stats"],
            "exact_dedup": exact_dedup_result["stats"],
            "near_dedup": near_dedup_result["stats"],
            "priority": priority_result["stats"],
            "handoff": handoff_result["manifest"],
        },
        "generated_at_utc": utc_iso(),
    }
    summary_path = out_root / "summary.json"
    atomic_write_json(summary_path, summary)
    print(json.dumps(summary, indent=JSON_INDENT))


def run_ingest(
    *,
    inputs: list[str],
    out_dir: Path,
    schema_version: str,
    ruleset_version: str,
    line_limit: int | None,
) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    records_path = out_dir / "records.jsonl"
    rejects_path = out_dir / "rejects.jsonl"
    stats_path = out_dir / "stats.json"

    raw_files = resolve_input_files(inputs)
    stats: dict[str, Any] = {
        "stage": "ingest",
        "raw_file_count": len(raw_files),
        "lines_seen": 0,
        "records_written": 0,
        "rejects_written": 0,
        "json_parse_success": 0,
        "json_parse_fail": 0,
        "salvaged": 0,
        "salvage_failed": 0,
        "source_files": [str(path) for path in raw_files],
        "generated_at_utc": utc_iso(),
    }

    with jsonl_writer(records_path) as records_writer, jsonl_writer(rejects_path) as rejects_writer:
        for file_path in raw_files:
            source_file_label = source_file_label_for_path(file_path)
            for line_number, raw_line in enumerate(iter_lines(file_path), start=1):
                if line_limit is not None and int(stats["lines_seen"]) >= line_limit:
                    break
                stats["lines_seen"] = int(stats["lines_seen"]) + 1
                parsed, parse_ok, salvaged, error_label = parse_or_salvage(raw_line)
                if parsed is None:
                    stats["json_parse_fail"] = int(stats["json_parse_fail"]) + 1
                    stats["salvage_failed"] = int(stats["salvage_failed"]) + 1
                    reject_record = {
                        "schema_version": schema_version,
                        "run_name": guess_run_name(file_path, {}),
                        "source_file": source_file_label,
                        "source_line": line_number,
                        "reject_reasons": ["json_parse_error", "salvage_failed"],
                        "parse_ok": False,
                        "salvaged": False,
                        "ingested_at_utc": utc_iso(),
                        "error": error_label,
                        "raw_line": raw_line.rstrip("\n"),
                    }
                    rejects_writer(reject_record)
                    stats["rejects_written"] = int(stats["rejects_written"]) + 1
                    continue

                if parse_ok:
                    stats["json_parse_success"] = int(stats["json_parse_success"]) + 1
                else:
                    stats["json_parse_fail"] = int(stats["json_parse_fail"]) + 1
                if salvaged:
                    stats["salvaged"] = int(stats["salvaged"]) + 1

                record = build_ingest_record(
                    parsed=parsed,
                    file_path=file_path,
                    source_file_label=source_file_label,
                    source_line=line_number,
                    parse_ok=parse_ok,
                    salvaged=salvaged,
                    schema_version=schema_version,
                    ruleset_version=ruleset_version,
                )
                records_writer(record)
                stats["records_written"] = int(stats["records_written"]) + 1
            if line_limit is not None and int(stats["lines_seen"]) >= line_limit:
                break

    atomic_write_json(stats_path, stats)
    print(json.dumps({"stage": "ingest", "out_dir": str(out_dir), "stats": stats}, indent=JSON_INDENT))
    return {
        "records_path": str(records_path),
        "rejects_path": str(rejects_path),
        "stats_path": str(stats_path),
        "stats": stats,
    }


def run_canonicalize(
    *,
    input_jsonl: Path,
    out_dir: Path,
    schema_version: str,
    rules: dict[str, Any],
) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    records_path = out_dir / "records.jsonl"
    stats_path = out_dir / "stats.json"

    alphabet = str(rules.get("alphabet") or DEFAULT_ALPHABET)
    min_extract_len = int(rules_section(rules, "canonicalize").get("sequence_extract_min_len", 20))

    stats: dict[str, Any] = {
        "stage": "canonicalize",
        "input_jsonl": str(input_jsonl),
        "records_seen": 0,
        "records_written": 0,
        "sequence_missing_after_canonicalize": 0,
        "candidate_id_missing": 0,
        "generated_at_utc": utc_iso(),
    }

    with jsonl_writer(records_path) as writer:
        for record in iter_jsonl(input_jsonl):
            stats["records_seen"] = int(stats["records_seen"]) + 1
            sequence = normalize_sequence(str(record.get("sequence") or ""))
            if not sequence:
                sequence = extract_sequence_from_raw_text(
                    raw_text=str(record.get("raw_text") or ""),
                    alphabet=alphabet,
                    min_extract_len=min_extract_len,
                )

            record["schema_version"] = schema_version
            record["sequence"] = sequence
            record["sequence_length"] = len(sequence)
            record["candidate_id"] = compute_candidate_id(sequence) if sequence else None
            if not sequence:
                stats["sequence_missing_after_canonicalize"] = int(stats["sequence_missing_after_canonicalize"]) + 1
            if not record["candidate_id"]:
                stats["candidate_id_missing"] = int(stats["candidate_id_missing"]) + 1

            if "reject_reasons" not in record or not isinstance(record["reject_reasons"], list):
                record["reject_reasons"] = []
            writer(record)
            stats["records_written"] = int(stats["records_written"]) + 1

    atomic_write_json(stats_path, stats)
    print(json.dumps({"stage": "canonicalize", "out_dir": str(out_dir), "stats": stats}, indent=JSON_INDENT))
    return {
        "records_path": str(records_path),
        "stats_path": str(stats_path),
        "stats": stats,
    }


def run_hard_filter(
    *,
    input_jsonl: Path,
    out_dir: Path,
    rules: dict[str, Any],
) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pass_path = out_dir / "pass.jsonl"
    rejects_path = out_dir / "rejects.jsonl"
    stats_path = out_dir / "stats.json"

    hard_rules = rules_section(rules, "hard_filter")
    alphabet = str(rules.get("alphabet") or DEFAULT_ALPHABET)
    min_len = int(hard_rules.get("sequence_length_min", 40))
    max_len = int(hard_rules.get("sequence_length_max", 2048))
    max_low_complexity = float(hard_rules.get("low_complexity_frac_max", 0.65))
    max_run_fraction = float(hard_rules.get("repeat_spam_max_run_fraction", 0.35))
    min_run_length = int(hard_rules.get("repeat_spam_min_run_length", 12))

    reject_hist: dict[str, int] = {}
    stats: dict[str, Any] = {
        "stage": "hard_filter",
        "input_jsonl": str(input_jsonl),
        "records_seen": 0,
        "pass_count": 0,
        "reject_count": 0,
        "reject_reason_hist": reject_hist,
        "generated_at_utc": utc_iso(),
    }

    with jsonl_writer(pass_path) as pass_writer, jsonl_writer(rejects_path) as reject_writer:
        for record in iter_jsonl(input_jsonl):
            stats["records_seen"] = int(stats["records_seen"]) + 1
            sequence = str(record.get("sequence") or "")
            reject_reasons = unique_reasons(record.get("reject_reasons"))

            low_complexity_frac = compute_low_complexity_fraction(sequence)
            record["low_complexity_frac"] = low_complexity_frac

            if not sequence:
                reject_reasons.append("empty_sequence")
            if sequence and not is_valid_charset(sequence, alphabet):
                reject_reasons.append("invalid_charset")
            if sequence and len(sequence) < min_len:
                reject_reasons.append("length_too_short")
            if sequence and len(sequence) > max_len:
                reject_reasons.append("length_too_long")
            if sequence and low_complexity_frac > max_low_complexity:
                reject_reasons.append("low_complexity")
            if sequence and is_repeat_spam(
                sequence=sequence,
                max_run_fraction=max_run_fraction,
                min_run_length=min_run_length,
            ):
                reject_reasons.append("repeat_spam")

            reject_reasons = unique_reasons(reject_reasons)
            record["reject_reasons"] = reject_reasons
            if reject_reasons:
                record["priority_tier"] = "REJECT"
                for reason in reject_reasons:
                    reject_hist[reason] = int(reject_hist.get(reason, 0)) + 1
                reject_writer(record)
                stats["reject_count"] = int(stats["reject_count"]) + 1
            else:
                pass_writer(record)
                stats["pass_count"] = int(stats["pass_count"]) + 1

    atomic_write_json(stats_path, stats)
    print(json.dumps({"stage": "hard_filter", "out_dir": str(out_dir), "stats": stats}, indent=JSON_INDENT))
    return {
        "pass_path": str(pass_path),
        "rejects_path": str(rejects_path),
        "stats_path": str(stats_path),
        "stats": stats,
    }


def run_exact_dedup(
    *,
    input_jsonl: Path,
    out_dir: Path,
) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    unique_path = out_dir / "unique.jsonl"
    dups_path = out_dir / "dups.jsonl"
    stats_path = out_dir / "stats.json"

    seen_ids: set[str] = set()
    stats: dict[str, Any] = {
        "stage": "exact_dedup",
        "input_jsonl": str(input_jsonl),
        "records_seen": 0,
        "unique_count": 0,
        "dup_count": 0,
        "generated_at_utc": utc_iso(),
    }

    with jsonl_writer(unique_path) as unique_writer, jsonl_writer(dups_path) as dups_writer:
        for record in iter_jsonl(input_jsonl):
            stats["records_seen"] = int(stats["records_seen"]) + 1
            sequence = str(record.get("sequence") or "")
            candidate_id = str(record.get("candidate_id") or compute_candidate_id(sequence) or "")
            if not candidate_id:
                candidate_id = f"missing:{int(stats['records_seen'])}"
            record["candidate_id"] = candidate_id
            record["exact_dup_group"] = candidate_id

            if candidate_id in seen_ids:
                reject_reasons = unique_reasons(record.get("reject_reasons"))
                reject_reasons.append("exact_duplicate")
                record["reject_reasons"] = unique_reasons(reject_reasons)
                record["priority_tier"] = "REJECT"
                dups_writer(record)
                stats["dup_count"] = int(stats["dup_count"]) + 1
            else:
                seen_ids.add(candidate_id)
                unique_writer(record)
                stats["unique_count"] = int(stats["unique_count"]) + 1

    atomic_write_json(stats_path, stats)
    print(json.dumps({"stage": "exact_dedup", "out_dir": str(out_dir), "stats": stats}, indent=JSON_INDENT))
    return {
        "unique_path": str(unique_path),
        "dups_path": str(dups_path),
        "stats_path": str(stats_path),
        "stats": stats,
    }


def run_near_dedup(
    *,
    input_jsonl: Path,
    out_dir: Path,
    rules: dict[str, Any],
) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    selected_path = out_dir / "selected.jsonl"
    cluster_members_path = out_dir / "cluster_members.jsonl"
    stats_path = out_dir / "stats.json"

    near_rules = rules_section(rules, "near_dedup")
    enabled = bool(near_rules.get("enabled", True))
    length_bucket = int(near_rules.get("length_bucket_size", 16))
    prefix_length = int(near_rules.get("prefix_length", 24))
    suffix_length = int(near_rules.get("suffix_length", 24))
    composition_top_k = int(near_rules.get("composition_top_k", 3))

    key_to_cluster: dict[str, str] = {}
    cluster_sizes: dict[str, int] = {}
    stats: dict[str, Any] = {
        "stage": "near_dedup",
        "input_jsonl": str(input_jsonl),
        "enabled": enabled,
        "records_seen": 0,
        "selected_count": 0,
        "cluster_members_count": 0,
        "cluster_count": 0,
        "generated_at_utc": utc_iso(),
    }

    with jsonl_writer(selected_path) as selected_writer, jsonl_writer(cluster_members_path) as cluster_writer:
        for record in iter_jsonl(input_jsonl):
            stats["records_seen"] = int(stats["records_seen"]) + 1
            sequence = str(record.get("sequence") or "")

            if not enabled:
                cluster_id = f"cluster_{int(stats['records_seen']):08d}"
                record["near_dup_cluster"] = cluster_id
                record["priority_tier"] = record.get("priority_tier") or None
                selected_writer(record)
                stats["selected_count"] = int(stats["selected_count"]) + 1
                continue

            signature = near_dedup_signature(
                sequence=sequence,
                length_bucket=length_bucket,
                prefix_length=prefix_length,
                suffix_length=suffix_length,
                composition_top_k=composition_top_k,
            )
            cluster_id = key_to_cluster.get(signature)
            if cluster_id is None:
                cluster_id = f"cluster_{len(key_to_cluster) + 1:08d}"
                key_to_cluster[signature] = cluster_id
                stats["cluster_count"] = len(key_to_cluster)
                cluster_sizes[cluster_id] = 0

            cluster_sizes[cluster_id] = int(cluster_sizes.get(cluster_id, 0)) + 1
            record["near_dup_cluster"] = cluster_id

            if cluster_sizes[cluster_id] == 1:
                selected_writer(record)
                stats["selected_count"] = int(stats["selected_count"]) + 1
            else:
                reject_reasons = unique_reasons(record.get("reject_reasons"))
                reject_reasons.append("near_duplicate")
                record["reject_reasons"] = unique_reasons(reject_reasons)
                record["priority_tier"] = "REJECT"
                cluster_writer(record)
                stats["cluster_members_count"] = int(stats["cluster_members_count"]) + 1

    stats["cluster_count"] = len(key_to_cluster) if enabled else int(stats["records_seen"])
    atomic_write_json(stats_path, stats)
    print(json.dumps({"stage": "near_dedup", "out_dir": str(out_dir), "stats": stats}, indent=JSON_INDENT))
    return {
        "selected_path": str(selected_path),
        "cluster_members_path": str(cluster_members_path),
        "stats_path": str(stats_path),
        "stats": stats,
    }


def run_priority(
    *,
    input_jsonl: Path,
    out_dir: Path,
    rules: dict[str, Any],
    reference_jsonl: list[str],
) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    tier_a_path = out_dir / "tiers_A.jsonl"
    tier_b_path = out_dir / "tiers_B.jsonl"
    tier_c_path = out_dir / "tiers_C.jsonl"
    rejects_path = out_dir / "rejects.jsonl"
    stats_path = out_dir / "stats.json"

    priority_rules = rules_section(rules, "priority")
    tier_a_min = float(priority_rules.get("tier_a_min", 0.80))
    tier_b_min = float(priority_rules.get("tier_b_min", 0.55))
    novelty_weight = float(priority_rules.get("novelty_weight", 0.65))
    length_weight = float(priority_rules.get("length_weight", 0.20))
    complexity_weight = float(priority_rules.get("complexity_weight", 0.15))
    length_target = float(priority_rules.get("length_target", 512))
    length_band = float(priority_rules.get("length_band", 512))

    reference_ids = load_reference_candidate_ids(reference_jsonl)
    stats: dict[str, Any] = {
        "stage": "priority",
        "input_jsonl": str(input_jsonl),
        "reference_inputs": reference_jsonl,
        "reference_candidate_count": len(reference_ids),
        "records_seen": 0,
        "tier_a_count": 0,
        "tier_b_count": 0,
        "tier_c_count": 0,
        "reject_count": 0,
        "generated_at_utc": utc_iso(),
    }

    with (
        jsonl_writer(tier_a_path) as tier_a_writer,
        jsonl_writer(tier_b_path) as tier_b_writer,
        jsonl_writer(tier_c_path) as tier_c_writer,
        jsonl_writer(rejects_path) as reject_writer,
    ):
        for record in iter_jsonl(input_jsonl):
            stats["records_seen"] = int(stats["records_seen"]) + 1
            reject_reasons = unique_reasons(record.get("reject_reasons"))
            sequence = str(record.get("sequence") or "")
            candidate_id = str(record.get("candidate_id") or compute_candidate_id(sequence) or "")
            record["candidate_id"] = candidate_id or None

            if reject_reasons:
                record["priority_tier"] = "REJECT"
                record["priority_score"] = 0.0
                record["novelty_score"] = 0.0
                reject_writer(record)
                stats["reject_count"] = int(stats["reject_count"]) + 1
                continue

            novelty_score = 0.0 if candidate_id and candidate_id in reference_ids else 1.0
            low_complexity = float(record.get("low_complexity_frac") or 0.0)
            complexity_score = max(0.0, 1.0 - low_complexity)
            length_score = bounded_length_score(
                sequence_length=len(sequence),
                target=length_target,
                band=max(1.0, length_band),
            )

            priority_score = (
                novelty_weight * novelty_score
                + length_weight * length_score
                + complexity_weight * complexity_score
            )
            priority_score = round(float(priority_score), 6)

            record["novelty_score"] = novelty_score
            record["priority_score"] = priority_score
            if priority_score >= tier_a_min:
                record["priority_tier"] = "A"
                tier_a_writer(record)
                stats["tier_a_count"] = int(stats["tier_a_count"]) + 1
            elif priority_score >= tier_b_min:
                record["priority_tier"] = "B"
                tier_b_writer(record)
                stats["tier_b_count"] = int(stats["tier_b_count"]) + 1
            else:
                record["priority_tier"] = "C"
                tier_c_writer(record)
                stats["tier_c_count"] = int(stats["tier_c_count"]) + 1

    atomic_write_json(stats_path, stats)
    print(json.dumps({"stage": "priority", "out_dir": str(out_dir), "stats": stats}, indent=JSON_INDENT))
    return {
        "tier_a_path": str(tier_a_path),
        "tier_b_path": str(tier_b_path),
        "tier_c_path": str(tier_c_path),
        "rejects_path": str(rejects_path),
        "stats_path": str(stats_path),
        "stats": stats,
    }


def run_handoff(
    *,
    tiers_a: Path,
    tiers_b: Path,
    tiers_c: Path,
    out_dir: Path,
    rules: dict[str, Any],
    exploration_fraction_override: float | None,
    random_seed_override: int | None,
) -> dict[str, Any]:
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ready_a_path = out_dir / "hpc_ready_A.jsonl"
    ready_b_path = out_dir / "hpc_ready_B.jsonl"
    explore_c_path = out_dir / "hpc_explore_C_sample.jsonl"
    manifest_path = out_dir / "manifest.json"

    handoff_rules = rules_section(rules, "handoff")
    exploration_fraction = (
        float(exploration_fraction_override)
        if exploration_fraction_override is not None
        else float(handoff_rules.get("exploration_fraction_c_tier", 0.08))
    )
    random_seed = (
        int(random_seed_override)
        if random_seed_override is not None
        else int(handoff_rules.get("random_seed", 7))
    )
    rng = random.Random(random_seed)

    a_count = copy_jsonl_records(tiers_a, ready_a_path)
    b_count = copy_jsonl_records(tiers_b, ready_b_path)

    c_seen = 0
    c_selected = 0
    with jsonl_writer(explore_c_path) as writer:
        for record in iter_jsonl(tiers_c):
            c_seen += 1
            if rng.random() <= exploration_fraction:
                writer(record)
                c_selected += 1

    manifest: dict[str, Any] = {
        "generated_at_utc": utc_iso(),
        "inputs": {
            "tiers_A": str(tiers_a),
            "tiers_B": str(tiers_b),
            "tiers_C": str(tiers_c),
        },
        "outputs": {
            "hpc_ready_A": str(ready_a_path),
            "hpc_ready_B": str(ready_b_path),
            "hpc_explore_C_sample": str(explore_c_path),
        },
        "counts": {
            "tier_a_ready": a_count,
            "tier_b_ready": b_count,
            "tier_c_seen": c_seen,
            "tier_c_sampled": c_selected,
        },
        "exploration_fraction_c_tier": exploration_fraction,
        "random_seed": random_seed,
    }

    atomic_write_json(manifest_path, manifest)
    print(json.dumps({"stage": "handoff", "out_dir": str(out_dir), "manifest": manifest}, indent=JSON_INDENT))
    return {
        "manifest_path": str(manifest_path),
        "manifest": manifest,
    }


def build_ingest_record(
    *,
    parsed: dict[str, Any],
    file_path: Path,
    source_file_label: str,
    source_line: int,
    parse_ok: bool,
    salvaged: bool,
    schema_version: str,
    ruleset_version: str,
) -> dict[str, Any]:
    run_name = guess_run_name(file_path, parsed)
    sequence = normalize_sequence(str(parsed.get("sequence") or ""))
    raw_text = str(parsed.get("raw_text") or "")
    if not sequence and raw_text:
        sequence = extract_sequence_from_raw_text(raw_text=raw_text, alphabet=DEFAULT_ALPHABET, min_extract_len=20)

    return {
        "schema_version": schema_version,
        "candidate_id": compute_candidate_id(sequence) if sequence else None,
        "run_name": run_name,
        "source_file": source_file_label,
        "source_line": source_line,
        "prompt_index": safe_int(parsed.get("prompt_index")),
        "request_index": safe_int(parsed.get("request_index")),
        "sample_index": safe_int(parsed.get("sample_index")),
        "ingested_at_utc": utc_iso(),
        "raw_text": raw_text,
        "sequence": sequence,
        "sequence_length": len(sequence),
        "parse_ok": bool(parse_ok),
        "salvaged": bool(salvaged),
        "reject_reasons": [],
        "low_complexity_frac": None,
        "exact_dup_group": None,
        "near_dup_cluster": None,
        "novelty_score": None,
        "priority_tier": None,
        "priority_score": None,
        "prefilter_ruleset_version": ruleset_version,
        "embedding_model_version": "none",
        "notes": None,
    }


def resolve_input_files(inputs: Iterable[str]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for item in inputs:
        path = Path(item).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"Input does not exist: {path}")
        candidates: list[Path]
        if path.is_file():
            candidates = [path]
        else:
            candidates = sorted(path.rglob("raw_samples_*.jsonl")) + sorted(path.rglob("raw_samples_*.jsonl.gz"))
            if not candidates:
                candidates = sorted(path.rglob("*.jsonl")) + sorted(path.rglob("*.jsonl.gz"))
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            resolved.append(candidate)
    if not resolved:
        raise SystemExit("No input files found")
    return resolved


def parse_or_salvage(raw_line: str) -> tuple[dict[str, Any] | None, bool, bool, str]:
    try:
        payload = json.loads(raw_line)
        if isinstance(payload, dict):
            return payload, True, False, ""
        return None, False, False, "json_not_object"
    except Exception as exc:
        payload = salvage_json_line(raw_line)
        if payload is not None:
            return payload, False, True, f"{type(exc).__name__}"
        return None, False, False, f"{type(exc).__name__}: {exc}"


def salvage_json_line(raw_line: str) -> dict[str, Any] | None:
    text = raw_line.strip()
    if not text:
        return None

    if "}" in text:
        candidate = text[: text.rfind("}") + 1]
        try:
            payload = json.loads(candidate)
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass

    fields: dict[str, Any] = {}
    for key in ("run_name", "prompt", "sequence_prompt", "raw_text", "sequence", "prompt_id"):
        value = extract_json_string_field(text, key)
        if value is not None:
            fields[key] = value
    for key in ("prompt_index", "request_index", "sample_index"):
        value = extract_json_int_field(text, key)
        if value is not None:
            fields[key] = value
    return fields or None


def extract_json_string_field(text: str, key: str) -> str | None:
    pattern = re.compile(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"')
    match = pattern.search(text)
    if not match:
        return None
    try:
        return json.loads(f'"{match.group(1)}"')
    except Exception:
        return match.group(1)


def extract_json_int_field(text: str, key: str) -> int | None:
    pattern = re.compile(rf'"{re.escape(key)}"\s*:\s*(-?\d+)')
    match = pattern.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def source_file_label_for_path(path: Path) -> str:
    if path.parent.name == "samples":
        return f"samples/{path.name}"
    return path.name


def guess_run_name(path: Path, payload: dict[str, Any]) -> str:
    run_name = str(payload.get("run_name") or "").strip()
    if run_name:
        return run_name
    if path.parent.name == "samples":
        return path.parent.parent.name
    return path.parent.name or "unknown_run"


def normalize_sequence(sequence: str) -> str:
    text = (sequence or "").strip().upper()
    text = re.sub(r"\s+", "", text)
    if text.startswith("SEQUENCE="):
        text = text.split("=", 1)[1].strip()
    if text.startswith("SEQUENCE:"):
        text = text.split(":", 1)[1].strip()
    return text


def extract_sequence_from_raw_text(*, raw_text: str, alphabet: str, min_extract_len: int) -> str:
    text = (raw_text or "").upper()
    text = re.sub(r"</?[^>]+>", " ", text)
    text = text.replace("SEQUENCE=", " ").replace("SEQUENCE:", " ")
    pattern = re.compile(rf"[{re.escape(alphabet)}]{{{min_extract_len},}}")
    matches = pattern.findall(text)
    if not matches:
        return ""
    return max(matches, key=len)


def compute_candidate_id(sequence: str) -> str | None:
    if not sequence:
        return None
    digest = hashlib.sha1(sequence.encode("utf-8")).hexdigest()
    return f"sha1:{digest}"


def is_valid_charset(sequence: str, alphabet: str) -> bool:
    allowed = set(alphabet)
    return all(char in allowed for char in sequence)


def compute_low_complexity_fraction(sequence: str) -> float:
    if not sequence:
        return 0.0
    counts = Counter(sequence)
    dominant = max(counts.values())
    return dominant / len(sequence)


def is_repeat_spam(*, sequence: str, max_run_fraction: float, min_run_length: int) -> bool:
    if not sequence:
        return False
    longest_run = 1
    current_run = 1
    for index in range(1, len(sequence)):
        if sequence[index] == sequence[index - 1]:
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 1
    run_fraction = longest_run / len(sequence)
    return longest_run >= min_run_length or run_fraction >= max_run_fraction


def near_dedup_signature(
    *,
    sequence: str,
    length_bucket: int,
    prefix_length: int,
    suffix_length: int,
    composition_top_k: int,
) -> str:
    if not sequence:
        return "empty"
    length_bin = len(sequence) // max(1, length_bucket)
    prefix = sequence[: max(1, prefix_length)]
    suffix = sequence[-max(1, suffix_length) :]
    composition = Counter(sequence)
    top = sorted(composition.items(), key=lambda item: (-item[1], item[0]))[: max(1, composition_top_k)]
    comp_signature = "".join(f"{aa}{count}" for aa, count in top)
    return f"{length_bin}|{prefix}|{suffix}|{comp_signature}"


def bounded_length_score(*, sequence_length: int, target: float, band: float) -> float:
    delta = abs(float(sequence_length) - float(target))
    score = max(0.0, 1.0 - (delta / band))
    return min(1.0, score)


def load_reference_candidate_ids(inputs: list[str]) -> set[str]:
    if not inputs:
        return set()
    ids: set[str] = set()
    files = resolve_input_files(inputs)
    for file_path in files:
        for record in iter_jsonl(file_path):
            sequence = str(record.get("sequence") or "")
            candidate_id = str(record.get("candidate_id") or compute_candidate_id(sequence) or "")
            if candidate_id:
                ids.add(candidate_id)
    return ids


def copy_jsonl_records(source: Path, target: Path) -> int:
    count = 0
    with jsonl_writer(target) as writer:
        for record in iter_jsonl(source):
            writer(record)
            count += 1
    return count


def rules_section(rules: dict[str, Any], section: str) -> dict[str, Any]:
    value = rules.get(section)
    if isinstance(value, dict):
        return value
    return {}


def load_rules(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Rules file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except Exception as exc:
            raise SystemExit(
                f"Rules file is not JSON and PyYAML is unavailable: {path} ({type(exc).__name__}: {exc})"
            ) from exc
        payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise SystemExit(f"Rules payload must be a JSON/YAML object: {path}")
    return payload


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def unique_reasons(values: Any) -> list[str]:
    if not isinstance(values, list):
        values = []
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def iter_lines(path: Path) -> Iterator[str]:
    with open_text(path, "r") as handle:
        for line in handle:
            yield line


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    for line_number, line in enumerate(iter_lines(path), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception as exc:
            raise SystemExit(f"Invalid JSONL at {path}:{line_number}: {type(exc).__name__}: {exc}") from exc
        if not isinstance(payload, dict):
            raise SystemExit(f"Expected JSON object at {path}:{line_number}")
        yield payload


def jsonl_writer(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open_text(path, "w")

    def write_one(payload: dict[str, Any]) -> None:
        handle.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))
        handle.write("\n")

    class _Context:
        def __enter__(self):  # noqa: ANN204
            return write_one

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001, ANN204
            handle.close()

    return _Context()


def open_text(path: Path, mode: str) -> TextIO:
    if "b" in mode:
        raise ValueError("open_text expects text mode")
    if path.suffix == ".gz":
        return gzip.open(path, f"{mode}t", encoding="utf-8")
    return path.open(mode, encoding="utf-8")


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=JSON_INDENT) + "\n"
    path.write_text(text, encoding="utf-8")


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_stamp_basic() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


if __name__ == "__main__":
    main()
