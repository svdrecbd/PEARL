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
DEFAULT_POSITIVE_RECORDS = ROOT / "data/petase_family_expanded/petase_records.jsonl"
DEFAULT_GENERATED_NEGATIVE_PATHS = (
    ROOT / "reports/analysis/phase7_local_library_v1/full_library.jsonl",
    ROOT / "reports/analysis/phase7_local_library_v1/validation_panel.jsonl",
)
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
    "class_d_phase7_duplicate_24aa": "FAPQSFVMNLLEHDSVVKQGDVVK",
}

POSITIVE_TERMS = (
    "cutinase",
    "petase",
    "polyester",
    "poly(ethylene terephthalate)",
    "terephthalate",
    "hydrolase",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a Phase 8 DPO dataset with length-preserving hard negatives. "
            "Chosen sequences are restricted to audited natural PETase/cutinase records. "
            "Fold-failed Phase 7 generated sequences are used only as rejected hard negatives."
        )
    )
    parser.add_argument("--positive-records", default=str(DEFAULT_POSITIVE_RECORDS))
    parser.add_argument(
        "--generated-negative-path",
        action="append",
        default=[str(path) for path in DEFAULT_GENERATED_NEGATIVE_PATHS],
    )
    parser.add_argument("--organic-path", action="append", default=[str(path) for path in DEFAULT_ORGANIC_PATHS])
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--target-total", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260428)
    parser.add_argument("--site-margin", type=int, default=50)
    parser.add_argument("--min-positive-length", type=int, default=180)
    parser.add_argument("--max-positive-length", type=int, default=360)
    parser.add_argument("--max-positive-exact-repeat", type=int, default=15)
    parser.add_argument("--generated-hard-negative-fraction", type=float, default=0.25)
    parser.add_argument("--include-generated-hard-negatives", action=argparse.BooleanOptionalAction, default=True)
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


def longest_exact_repeat(sequence: str, *, min_len: int = 8) -> dict[str, Any] | None:
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


def positive_record_text(row: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("protein_name", "organism_name", "accession", "uniprot_id"):
        if row.get(key):
            values.append(str(row[key]))
    for key in ("alternative_names", "ec_numbers", "matched_relevance_terms", "function_texts"):
        values.extend(str(value) for value in row.get(key) or [])
    return " ".join(values).lower()


def load_positive_records(path: Path, args: argparse.Namespace) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in read_jsonl(path):
        sequence = str(row.get("sequence") or "").strip().upper()
        if not valid_aa_sequence(sequence) or sequence in seen:
            continue
        if not (int(args.min_positive_length) <= len(sequence) <= int(args.max_positive_length)):
            continue
        if not any(term in positive_record_text(row) for term in POSITIVE_TERMS):
            continue
        if not row.get("reviewed"):
            continue
        if len(row.get("active_sites") or []) < 3:
            continue
        repeat = longest_exact_repeat(sequence, min_len=int(args.max_positive_exact_repeat) + 1)
        if repeat:
            continue
        seen.add(sequence)
        records.append(
            {
                "sequence": sequence,
                "record_id": str(row.get("uniprot_id") or row.get("accession") or row.get("sequence_sha256")),
                "accession": str(row.get("accession") or ""),
                "protein_name": str(row.get("protein_name") or ""),
                "organism_name": str(row.get("organism_name") or ""),
                "length": len(sequence),
                "reviewed": bool(row.get("reviewed")),
                "annotation_score": row.get("annotation_score"),
                "active_site_count": len(row.get("active_sites") or []),
                "confidence_basis": "reviewed_natural_record_with_active_site_annotation",
            }
        )
    if not records:
        raise ValueError(f"no audited natural chosen sequences found in {path}")
    return records


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


def load_generated_negative_sequences(paths: list[Path], *, max_exact_repeat: int) -> list[dict[str, Any]]:
    negatives: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        for row in read_jsonl(path):
            sequence = str(row.get("sequence") or "").strip().upper()
            if not valid_aa_sequence(sequence) or sequence in seen:
                continue
            repeat = longest_exact_repeat(sequence, min_len=max_exact_repeat + 1)
            if not repeat:
                continue
            seen.add(sequence)
            negatives.append(
                {
                    "sequence": sequence,
                    "source_path": str(path),
                    "repeat_length": repeat["length"],
                    "repeat_first_start": repeat["first_start"],
                    "repeat_second_start": repeat["second_start"],
                    "repeat_fragment": repeat["fragment"],
                    "rejection_basis": "phase7_generated_fold_failed_or_long_repeat_positive_audit_failure",
                }
            )
    return negatives


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


def positive_prompt(record: dict[str, Any], prompts: list[str], rng: random.Random) -> str:
    if prompts and rng.random() < 0.5:
        return rng.choice(prompts)
    name = record["protein_name"] or "PETase/cutinase-family hydrolase"
    organism = record["organism_name"] or "a reviewed natural source"
    return (
        f"Design a protein sequence inspired by {name} from {organism}, length about {record['length']} aa. "
        "Favor a PETase/cutinase-like GxSxG nucleophile motif and compatible catalytic residues. "
        "Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."
    )


def positive_audit_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "chosen_source_type": "natural_reference_record",
        "chosen_record_id": record["record_id"],
        "chosen_accession": record["accession"],
        "chosen_protein_name": record["protein_name"],
        "chosen_organism_name": record["organism_name"],
        "chosen_reviewed": record["reviewed"],
        "chosen_annotation_score": record["annotation_score"],
        "chosen_active_site_count": record["active_site_count"],
        "chosen_confidence_basis": record["confidence_basis"],
    }


def group_records_by_length(records: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(int(record["length"]), []).append(record)
    return grouped


def build_dataset(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(int(args.seed))
    positive_records = load_positive_records(repo_path(args.positive_records), args)
    positive_records_by_length = group_records_by_length(positive_records)
    generated_negative_paths = [repo_path(path) for path in args.generated_negative_path]
    generated_negatives = load_generated_negative_sequences(
        generated_negative_paths,
        max_exact_repeat=int(args.max_positive_exact_repeat),
    )
    organic_paths = [repo_path(path) for path in args.organic_path]
    organic_rows = load_organic_pairs(organic_paths)
    prompts = organic_prompts(organic_rows)

    rows: list[dict[str, Any]] = []
    seen_triples: set[tuple[str, str, str]] = set()

    if args.include_generated_hard_negatives:
        target_generated = min(
            len(generated_negatives),
            int(round(int(args.target_total) * float(args.generated_hard_negative_fraction))),
        )
        rng.shuffle(generated_negatives)
        for negative in generated_negatives[:target_generated]:
            candidates = positive_records_by_length.get(len(negative["sequence"]))
            if not candidates:
                continue
            chosen_record = rng.choice(candidates)
            row = {
                "prompt": positive_prompt(chosen_record, prompts, rng),
                "chosen": chosen_record["sequence"],
                "rejected": negative["sequence"],
                "source_type": "natural_vs_generated_fold_failed_hard_negative",
                "rejected_source_type": "phase7_generated_local_library_fold_failed",
                "rejected_source_path": negative["source_path"],
                "rejected_repeat_length": negative["repeat_length"],
                "rejected_repeat_first_start": negative["repeat_first_start"],
                "rejected_repeat_second_start": negative["repeat_second_start"],
                "rejected_repeat_fragment": negative["repeat_fragment"],
                "rejected_basis": negative["rejection_basis"],
                **positive_audit_fields(chosen_record),
            }
            triple = (row["prompt"], row["chosen"], row["rejected"])
            if triple in seen_triples:
                continue
            seen_triples.add(triple)
            rows.append(row)

    duplicate_attempts = 0
    while len(rows) < int(args.target_total):
        chosen_record = rng.choice(positive_records)
        chosen = chosen_record["sequence"]
        corruption = artifact_replacement(chosen, rng=rng, margin=int(args.site_margin))
        row = {
            "prompt": positive_prompt(chosen_record, prompts, rng),
            "chosen": chosen,
            "rejected": corruption["rejected"],
            "source_type": "synthetic_length_preserving_artifact_replacement",
            "rejected_source_type": "synthetic_length_preserving_artifact_replacement",
            "rejected_basis": "equal_length_internal_window_replaced_with_known_artifact",
            "corruption_method": "replace_equal_length_internal_window",
            "synthetic_artifact_class": corruption["synthetic_artifact_class"],
            "synthetic_artifact": corruption["synthetic_artifact"],
            "artifact_site": corruption["artifact_site"],
            "artifact_window_length": corruption["artifact_window_length"],
            "replaced_window": corruption["replaced_window"],
            **positive_audit_fields(chosen_record),
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
    artifact_counts = Counter(
        str(row.get("synthetic_artifact_class") or row.get("rejected_source_type") or "none")
        for row in rows
    )
    length_deltas = Counter(len(row["rejected"]) - len(row["chosen"]) for row in rows)
    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "builder": str(Path(__file__).relative_to(ROOT)),
        "config": {
            "target_total": int(args.target_total),
            "seed": int(args.seed),
            "site_margin": int(args.site_margin),
            "min_positive_length": int(args.min_positive_length),
            "max_positive_length": int(args.max_positive_length),
            "max_positive_exact_repeat": int(args.max_positive_exact_repeat),
            "include_generated_hard_negatives": bool(args.include_generated_hard_negatives),
            "generated_hard_negative_fraction": float(args.generated_hard_negative_fraction),
        },
        "inputs": {
            "positive_records": str(repo_path(args.positive_records)),
            "positive_record_count": len(positive_records),
            "positive_length_counts": dict(sorted(Counter(record["length"] for record in positive_records).items())),
            "generated_negative_paths": [str(path) for path in generated_negative_paths],
            "generated_negative_count": len(generated_negatives),
            "organic_paths": [str(path) for path in organic_paths],
            "organic_raw_count": len(organic_rows),
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
