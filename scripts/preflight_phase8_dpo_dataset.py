#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_PATH = ROOT / "data/phase8_dpo/dpo_preferences_hybrid_10k.jsonl"
DEFAULT_MANIFEST_PATH = ROOT / "data/phase8_dpo/dpo_preferences_hybrid_10k_preflight.json"
AA_ALPHABET = set("ACDEFGHIKLMNPQRSTVWY")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preflight a Phase 8 prompt/chosen/rejected DPO dataset")
    parser.add_argument("--dataset-path", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--min-rows", type=int, default=10_000)
    parser.add_argument("--require-length-matched", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-no-duplicate-triples", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-synthetic-audit", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-positive-audit", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-chosen-exact-repeat", type=int, default=15)
    return parser.parse_args()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_aa_sequence(sequence: str) -> bool:
    return bool(sequence) and all(residue in AA_ALPHABET for residue in sequence)


def longest_exact_repeat(sequence: str, *, min_len: int) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    max_len = len(sequence) // 2
    for window in range(min_len, max_len + 1):
        seen: dict[str, int] = {}
        for index in range(0, len(sequence) - window + 1):
            fragment = sequence[index : index + window]
            previous = seen.get(fragment)
            if previous is not None and index - previous >= window:
                best = {
                    "length": window,
                    "first_start": previous,
                    "second_start": index,
                    "fragment": fragment,
                }
            else:
                seen.setdefault(fragment, index)
    return best


def read_dataset(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                failures.append(f"line {line_number}: invalid JSON: {exc}")
                continue
            if not isinstance(row, dict):
                failures.append(f"line {line_number}: row is not an object")
                continue
            row["_line_number"] = line_number
            rows.append(row)
    return rows, failures


def positive_audit_failure(row: dict[str, Any]) -> str | None:
    required = (
        "chosen_source_type",
        "chosen_record_id",
        "chosen_reviewed",
        "chosen_active_site_count",
        "chosen_confidence_basis",
    )
    missing = [key for key in required if row.get(key) in (None, "")]
    if missing:
        return f"missing chosen positive audit fields: {', '.join(missing)}"
    if row.get("chosen_source_type") != "natural_reference_record":
        return f"chosen_source_type is not natural_reference_record: {row.get('chosen_source_type')}"
    if row.get("chosen_reviewed") is not True:
        return "chosen positive is not a reviewed natural record"
    try:
        active_site_count = int(row.get("chosen_active_site_count"))
    except (TypeError, ValueError):
        return "chosen_active_site_count is not an integer"
    if active_site_count < 3:
        return "chosen positive has fewer than three annotated active-site residues"
    basis = str(row.get("chosen_confidence_basis") or "")
    if "natural" not in basis or "active_site" not in basis:
        return "chosen_confidence_basis does not document natural active-site support"
    return None


def synthetic_audit_failure(row: dict[str, Any]) -> str | None:
    if row.get("source_type") != "synthetic_length_preserving_artifact_replacement":
        return None
    required = (
        "corruption_method",
        "synthetic_artifact_class",
        "synthetic_artifact",
        "artifact_site",
        "artifact_window_length",
        "replaced_window",
    )
    missing = [key for key in required if row.get(key) in (None, "")]
    if missing:
        return f"missing synthetic audit fields: {', '.join(missing)}"
    if row.get("corruption_method") != "replace_equal_length_internal_window":
        return "unexpected synthetic corruption_method"
    chosen = str(row.get("chosen") or "")
    rejected = str(row.get("rejected") or "")
    artifact = str(row.get("synthetic_artifact") or "")
    try:
        site = int(row.get("artifact_site"))
        window = int(row.get("artifact_window_length"))
    except (TypeError, ValueError):
        return "artifact_site/window are not integers"
    if window != len(artifact):
        return "artifact_window_length does not match synthetic_artifact length"
    if len(str(row.get("replaced_window") or "")) != window:
        return "replaced_window length does not match artifact_window_length"
    if site < 0 or site + window > len(chosen) or site + window > len(rejected):
        return "artifact window is outside sequence bounds"
    if rejected[site : site + window] != artifact:
        return "rejected sequence does not contain synthetic_artifact at artifact_site"
    if chosen[:site] != rejected[:site] or chosen[site + window :] != rejected[site + window :]:
        return "synthetic pair differs outside the artifact replacement window"
    return None


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    dataset_path = repo_path(args.dataset_path)
    rows, failures = read_dataset(dataset_path)
    warnings: list[str] = []
    triples: set[tuple[str, str, str]] = set()
    duplicate_triples = 0
    length_deltas: Counter[int] = Counter()
    chosen_lengths: Counter[int] = Counter()
    rejected_lengths: Counter[int] = Counter()
    source_types: Counter[str] = Counter()
    chosen_source_types: Counter[str] = Counter()
    rejected_source_types: Counter[str] = Counter()
    key_shapes: Counter[str] = Counter()
    synthetic_artifacts: Counter[str] = Counter()
    organic_rows = 0
    synthetic_rows = 0
    chosen_repeat_violations = 0

    for index, row in enumerate(rows, start=1):
        line_number = row.get("_line_number", index)
        prompt = str(row.get("prompt") or "").strip()
        chosen = str(row.get("chosen") or "").strip().upper()
        rejected = str(row.get("rejected") or "").strip().upper()
        source_type = str(row.get("source_type") or "unknown")
        chosen_source_type = str(row.get("chosen_source_type") or "missing")
        rejected_source_type = str(row.get("rejected_source_type") or "not_provided")

        if not prompt:
            failures.append(f"line {line_number}: missing prompt")
        if not valid_aa_sequence(chosen):
            failures.append(f"line {line_number}: chosen is not a valid amino-acid sequence")
        if not valid_aa_sequence(rejected):
            failures.append(f"line {line_number}: rejected is not a valid amino-acid sequence")
        if chosen == rejected:
            failures.append(f"line {line_number}: chosen equals rejected")
        chosen_repeat = longest_exact_repeat(
            chosen,
            min_len=int(args.max_chosen_exact_repeat) + 1,
        )
        if chosen_repeat:
            chosen_repeat_violations += 1
            failures.append(
                "line "
                f"{line_number}: chosen contains exact repeat length {chosen_repeat['length']} "
                f"at positions {chosen_repeat['first_start']} and {chosen_repeat['second_start']}"
            )
        if args.require_positive_audit:
            audit_failure = positive_audit_failure(row)
            if audit_failure:
                failures.append(f"line {line_number}: {audit_failure}")

        triple = (prompt, chosen, rejected)
        if triple in triples:
            duplicate_triples += 1
        triples.add(triple)

        delta = len(rejected) - len(chosen)
        length_deltas[delta] += 1
        chosen_lengths[len(chosen)] += 1
        rejected_lengths[len(rejected)] += 1
        source_types[source_type] += 1
        chosen_source_types[chosen_source_type] += 1
        rejected_source_types[rejected_source_type] += 1
        key_shapes["|".join(sorted(key for key in row if key != "_line_number"))] += 1

        if source_type.startswith("organic"):
            organic_rows += 1
        if source_type == "synthetic_length_preserving_artifact_replacement":
            synthetic_rows += 1
            synthetic_artifacts[str(row.get("synthetic_artifact_class") or "missing")] += 1
            if args.require_synthetic_audit:
                audit_failure = synthetic_audit_failure(row)
                if audit_failure:
                    failures.append(f"line {line_number}: {audit_failure}")

    if len(rows) < int(args.min_rows):
        failures.append(f"row count {len(rows)} is below required minimum {args.min_rows}")
    if args.require_length_matched and any(delta != 0 for delta in length_deltas):
        failures.append(f"length-mismatched pairs found: {dict(sorted(length_deltas.items()))}")
    if args.require_no_duplicate_triples and duplicate_triples:
        failures.append(f"duplicate prompt/chosen/rejected triples found: {duplicate_triples}")
    if synthetic_rows == 0:
        failures.append("no synthetic length-preserving rows found")
    if organic_rows == 0:
        warnings.append("no raw organic rows were retained; this is expected for natural-positive Phase 8 builds")

    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "dataset_path": str(dataset_path),
        "sha256": sha256_file(dataset_path),
        "config": {
            "min_rows": int(args.min_rows),
            "require_length_matched": bool(args.require_length_matched),
            "require_no_duplicate_triples": bool(args.require_no_duplicate_triples),
            "require_synthetic_audit": bool(args.require_synthetic_audit),
            "require_positive_audit": bool(args.require_positive_audit),
            "max_chosen_exact_repeat": int(args.max_chosen_exact_repeat),
        },
        "counts": {
            "rows": len(rows),
            "unique_triples": len(triples),
            "duplicate_triples": duplicate_triples,
            "organic_rows": organic_rows,
            "synthetic_rows": synthetic_rows,
            "chosen_repeat_violations": chosen_repeat_violations,
        },
        "length_delta_counts": {str(key): value for key, value in sorted(length_deltas.items())},
        "chosen_length_counts": {str(key): value for key, value in sorted(chosen_lengths.items())},
        "rejected_length_counts": {str(key): value for key, value in sorted(rejected_lengths.items())},
        "source_type_counts": dict(sorted(source_types.items())),
        "chosen_source_type_counts": dict(sorted(chosen_source_types.items())),
        "rejected_source_type_counts": dict(sorted(rejected_source_types.items())),
        "synthetic_artifact_class_counts": dict(sorted(synthetic_artifacts.items())),
        "key_shape_counts": dict(sorted(key_shapes.items())),
        "failures": failures,
        "warnings": warnings,
        "ready_for_paid_dpo_smoke": not failures,
    }


def main() -> None:
    args = parse_args()
    manifest = preflight(args)
    manifest_path = repo_path(args.manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if manifest["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
