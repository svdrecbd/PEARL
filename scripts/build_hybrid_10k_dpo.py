#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FULL_LIBRARY = ROOT / "reports/analysis/phase7_local_library_v1/full_library.jsonl"
DEFAULT_ORGANIC_PATHS = (
    ROOT / "data/phase7_dpo/dpo_preferences.jsonl",
    ROOT / "data/phase8_dpo/dpo_preferences_1m_sweep.jsonl",
)
DEFAULT_OUTPUT_PATH = ROOT / "data/phase8_dpo/dpo_preferences_hybrid_10k.jsonl"
DEFAULT_MANIFEST_PATH = ROOT / "data/phase8_dpo/dpo_preferences_hybrid_10k_build_manifest.json"
AA_ALPHABET = set("ACDEFGHIKLMNPQRSTVWY")

ARTIFACT_CLASSES = {
    "class_a_repeat_loop_30aa": "YGDGDGDNGSPGDSEYFVAINAASNSQQTG",
    "class_b_boundary_surfer_21aa": "ANPGKVTQGGATTLQEAIEYL",
    "class_c_boundary_loop_16aa": "HGVAHEDYTPQPGVDG",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a Phase 8 DPO dataset with length-preserving synthetic hard negatives. "
            "The rejected side replaces an equal-length internal window instead of inserting "
            "extra residues, preventing the model from learning length as the preference signal."
        )
    )
    parser.add_argument("--full-library", default=str(DEFAULT_FULL_LIBRARY))
    parser.add_argument("--organic-path", action="append", default=[str(path) for path in DEFAULT_ORGANIC_PATHS])
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--target-total", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260428)
    parser.add_argument("--site-margin", type=int, default=50)
    parser.add_argument("--include-raw-length-matched-organic", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} is not valid JSON: {exc}") from exc
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_aa_sequence(sequence: str) -> bool:
    return bool(sequence) and all(residue in AA_ALPHABET for residue in sequence)


def load_clean_sequences(path: Path) -> list[str]:
    sequences: list[str] = []
    seen: set[str] = set()
    for row in read_jsonl(path):
        sequence = str(row.get("sequence") or "").strip().upper()
        if valid_aa_sequence(sequence) and sequence not in seen:
            sequences.append(sequence)
            seen.add(sequence)
    if not sequences:
        raise ValueError(f"no valid clean chosen sequences found in {path}")
    return sequences


def load_organic_pairs(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        for row in read_jsonl(path):
            prompt = str(row.get("prompt") or "").strip()
            chosen = str(row.get("chosen") or "").strip().upper()
            rejected = str(row.get("rejected") or "").strip().upper()
            if not prompt or not valid_aa_sequence(chosen) or not valid_aa_sequence(rejected):
                continue
            payload = dict(row)
            payload.update(
                {
                    "prompt": prompt,
                    "chosen": chosen,
                    "rejected": rejected,
                    "source_path": str(path),
                    "source_type": "organic_raw",
                }
            )
            rows.append(payload)
    return rows


def artifact_replacement(seq: str, *, rng: random.Random, margin: int) -> dict[str, Any]:
    artifact_class, artifact = rng.choice(list(ARTIFACT_CLASSES.items()))
    window = len(artifact)
    if len(seq) <= (2 * margin) + window:
        low = 0
        high = len(seq) - window
    else:
        low = margin
        high = len(seq) - margin - window
    if high < low:
        raise ValueError(f"sequence length {len(seq)} is too short for {window} aa artifact replacement")
    site = rng.randint(low, high)
    replaced_window = seq[site : site + window]
    rejected = seq[:site] + artifact + seq[site + window :]
    if rejected == seq:
        return artifact_replacement(seq, rng=rng, margin=margin)
    return {
        "rejected": rejected,
        "synthetic_artifact_class": artifact_class,
        "synthetic_artifact": artifact,
        "artifact_site": site,
        "artifact_window_length": window,
        "replaced_window": replaced_window,
    }


def organic_prompts(rows: list[dict[str, Any]]) -> list[str]:
    prompts = sorted({str(row.get("prompt") or "").strip() for row in rows if row.get("prompt")})
    return prompts or ["Design a functional PETase/cutinase bridge sequence."]


def raw_length_matched_organic(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        chosen = str(row["chosen"])
        rejected = str(row["rejected"])
        if len(chosen) != len(rejected):
            continue
        payload = {
            "prompt": row["prompt"],
            "chosen": chosen,
            "rejected": rejected,
            "source_type": "organic_raw_length_matched",
            "source_path": row.get("source_path"),
        }
        if "rejected_esm" in row:
            payload["rejected_esm"] = row["rejected_esm"]
        selected.append(payload)
    return selected


def build_dataset(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(int(args.seed))
    clean_sequences = load_clean_sequences(repo_path(args.full_library))
    organic_paths = [repo_path(path) for path in args.organic_path]
    organic_rows = load_organic_pairs(organic_paths)
    prompts = organic_prompts(organic_rows)

    rows: list[dict[str, Any]] = []
    if args.include_raw_length_matched_organic:
        rows.extend(raw_length_matched_organic(organic_rows))

    seen_triples = {(row["prompt"], row["chosen"], row["rejected"]) for row in rows}
    duplicate_attempts = 0
    while len(rows) < int(args.target_total):
        chosen = rng.choice(clean_sequences)
        prompt = rng.choice(prompts)
        corruption = artifact_replacement(chosen, rng=rng, margin=int(args.site_margin))
        row = {
            "prompt": prompt,
            "chosen": chosen,
            "rejected": corruption["rejected"],
            "source_type": "synthetic_length_preserving_artifact_replacement",
            "corruption_method": "replace_equal_length_internal_window",
            "synthetic_artifact_class": corruption["synthetic_artifact_class"],
            "synthetic_artifact": corruption["synthetic_artifact"],
            "artifact_site": corruption["artifact_site"],
            "artifact_window_length": corruption["artifact_window_length"],
            "replaced_window": corruption["replaced_window"],
        }
        triple = (row["prompt"], row["chosen"], row["rejected"])
        if triple in seen_triples:
            duplicate_attempts += 1
            continue
        seen_triples.add(triple)
        rows.append(row)

    rng.shuffle(rows)
    rows = rows[: int(args.target_total)]
    source_counts = Counter(str(row.get("source_type") or "") for row in rows)
    artifact_counts = Counter(str(row.get("synthetic_artifact_class") or "organic") for row in rows)
    length_deltas = Counter(len(row["rejected"]) - len(row["chosen"]) for row in rows)
    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "builder": str(Path(__file__).relative_to(ROOT)),
        "config": {
            "target_total": int(args.target_total),
            "seed": int(args.seed),
            "site_margin": int(args.site_margin),
            "include_raw_length_matched_organic": bool(args.include_raw_length_matched_organic),
        },
        "inputs": {
            "full_library": str(repo_path(args.full_library)),
            "organic_paths": [str(path) for path in organic_paths],
            "clean_sequence_count": len(clean_sequences),
            "organic_raw_count": len(organic_rows),
            "organic_raw_length_matched_count": len(raw_length_matched_organic(organic_rows)),
            "organic_prompt_count": len(prompts),
        },
        "outputs": {
            "row_count": len(rows),
            "source_type_counts": dict(sorted(source_counts.items())),
            "artifact_class_counts": dict(sorted(artifact_counts.items())),
            "length_delta_counts": {str(key): value for key, value in sorted(length_deltas.items())},
            "duplicate_attempts_skipped": duplicate_attempts,
        },
    }
    return rows, manifest


def main() -> None:
    args = parse_args()
    output_path = repo_path(args.output_path)
    manifest_path = repo_path(args.manifest_path)
    rows, manifest = build_dataset(args)
    write_jsonl(output_path, rows)
    manifest["outputs"]["output_path"] = str(output_path)
    manifest["outputs"]["sha256"] = sha256_file(output_path)
    write_json(manifest_path, manifest)
    print(f"Wrote {len(rows)} DPO pairs to {output_path}")
    print(f"Wrote build manifest to {manifest_path}")
    print(f"SHA256: {manifest['outputs']['sha256']}")


if __name__ == "__main__":
    main()
