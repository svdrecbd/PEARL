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
    key_shapes: Counter[str] = Counter()
    synthetic_artifacts: Counter[str] = Counter()
    organic_rows = 0
    synthetic_rows = 0

    for index, row in enumerate(rows, start=1):
        line_number = row.get("_line_number", index)
        prompt = str(row.get("prompt") or "").strip()
        chosen = str(row.get("chosen") or "").strip().upper()
        rejected = str(row.get("rejected") or "").strip().upper()
        source_type = str(row.get("source_type") or "unknown")

        if not prompt:
            failures.append(f"line {line_number}: missing prompt")
        if not valid_aa_sequence(chosen):
            failures.append(f"line {line_number}: chosen is not a valid amino-acid sequence")
        if not valid_aa_sequence(rejected):
            failures.append(f"line {line_number}: rejected is not a valid amino-acid sequence")
        if chosen == rejected:
            failures.append(f"line {line_number}: chosen equals rejected")

        triple = (prompt, chosen, rejected)
        if triple in triples:
            duplicate_triples += 1
        triples.add(triple)

        delta = len(rejected) - len(chosen)
        length_deltas[delta] += 1
        chosen_lengths[len(chosen)] += 1
        rejected_lengths[len(rejected)] += 1
        source_types[source_type] += 1
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
        warnings.append("no raw length-matched organic rows were retained")

    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "dataset_path": str(dataset_path),
        "sha256": sha256_file(dataset_path),
        "config": {
            "min_rows": int(args.min_rows),
            "require_length_matched": bool(args.require_length_matched),
            "require_no_duplicate_triples": bool(args.require_no_duplicate_triples),
            "require_synthetic_audit": bool(args.require_synthetic_audit),
        },
        "counts": {
            "rows": len(rows),
            "unique_triples": len(triples),
            "duplicate_triples": duplicate_triples,
            "organic_rows": organic_rows,
            "synthetic_rows": synthetic_rows,
        },
        "length_delta_counts": {str(key): value for key, value in sorted(length_deltas.items())},
        "chosen_length_counts": {str(key): value for key, value in sorted(chosen_lengths.items())},
        "rejected_length_counts": {str(key): value for key, value in sorted(rejected_lengths.items())},
        "source_type_counts": dict(sorted(source_types.items())),
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
