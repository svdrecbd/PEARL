#!/usr/bin/env python3
"""Post-generation audit: global dedup, novelty, and stratification checks.

Runs after Tinker generation completes and before GMN folding submission.
Produces a self-hashed audit report consumed by the folding manifest builder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_value(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def load_generation_reports(output_root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    reports = []
    for job in manifest["jobs"]:
        run_dir = output_root / str(job["job_key"])
        report_path = run_dir / "generation_report.json"
        if not report_path.is_file():
            raise RuntimeError(f"generation report missing: {report_path}")
        report = json.loads(report_path.read_text())
        if report.get("status") != "complete":
            raise RuntimeError(f"generation report not complete: {report_path}")
        expected = int(report.get("expected_candidate_count", 0))
        completed = int(report.get("completed_candidate_count", 0))
        if completed != expected:
            raise RuntimeError(f"generation incomplete: {report_path} ({completed}/{expected})")
        reports.append({"job": job, "report": report, "path": str(report_path)})
    return reports


def build_dedup_map(reports: list[dict[str, Any]]) -> dict[str, Any]:
    sequence_to_slots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in reports:
        job_key = entry["job"]["job_key"]
        for row in entry["report"].get("candidates", []):
            seq_hash = row.get("sequence_sha256")
            if seq_hash and row.get("valid_sequence"):
                sequence_to_slots[seq_hash].append({
                    "job_key": job_key,
                    "candidate_id": row["candidate_id"],
                    "prompt_id": row.get("prompt_id"),
                    "sample_seed": row.get("sample_seed"),
                    "length_bin": row.get("length_bin"),
                })
    return dict(sequence_to_slots)


def kmer_profile(sequence: str, k: int = 3) -> Counter:
    return Counter(sequence[i : i + k] for i in range(len(sequence) - k + 1))


def cosine_similarity(a: Counter, b: Counter) -> float:
    common = set(a) & set(b)
    dot = sum(a[x] * b[x] for x in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def load_reference_sequences(config_path: Path) -> dict[str, list[dict[str, str]]]:
    config = json.loads(config_path.read_text())
    references: dict[str, list[dict[str, str]]] = {}

    training_manifest = json.loads((ROOT / config["dataset_manifest"]).read_text())
    training_path = ROOT / training_manifest.get("dataset_path", "")
    if training_path.is_file():
        training_seqs = []
        for line in training_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            for key in ("chosen_sequence", "rejected_sequence", "sequence"):
                seq = row.get(key, "")
                if seq:
                    training_seqs.append({"source": key, "sequence": seq})
        references["training"] = training_seqs

    prompt_path = ROOT / config["prompt_panel"]
    if prompt_path.is_file():
        prompt_seqs = []
        for line in prompt_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("reference_sequence"):
                prompt_seqs.append({"source": "prompt", "sequence": row["reference_sequence"]})
        references["prompt"] = prompt_seqs

    return references


def novelty_audit(
    dedup_map: dict[str, list[dict[str, Any]]],
    references: dict[str, list[dict[str, str]]],
    *,
    exact_threshold: float = 1.0,
    near_threshold: float = 0.90,
    kmer_k: int = 3,
) -> dict[str, Any]:
    ref_profiles: dict[str, list[tuple[str, str, Counter]]] = {}
    for ref_name, ref_seqs in references.items():
        profiles = []
        for entry in ref_seqs:
            seq = entry["sequence"]
            profiles.append((entry["source"], hashlib.sha256(seq.encode()).hexdigest(), kmer_profile(seq, kmer_k)))
        ref_profiles[ref_name] = profiles

    audit_results = {}
    for seq_hash in dedup_map:
        sequence = None
        for slot in dedup_map[seq_hash]:
            pass
        classification = "novel"
        best_similarity = 0.0
        best_source = None
        best_ref = None
        for ref_name, profiles in ref_profiles.items():
            candidate_profile = None
            for source, ref_hash, profile in profiles:
                if ref_hash == seq_hash:
                    classification = "exact_match"
                    best_similarity = 1.0
                    best_source = ref_name
                    best_ref = source
                    break
            if classification == "exact_match":
                break

        if classification == "novel":
            for ref_name, profiles in ref_profiles.items():
                for source, ref_hash, profile in profiles:
                    if candidate_profile is None:
                        candidate_profile = kmer_profile(sequence or "", kmer_k)
                    sim = cosine_similarity(candidate_profile, profile)
                    if sim >= near_threshold and sim > best_similarity:
                        best_similarity = sim
                        best_source = ref_name
                        best_ref = source
            if best_similarity >= near_threshold:
                classification = "near_match"

        audit_results[seq_hash] = {
            "classification": classification,
            "best_similarity": round(best_similarity, 4),
            "best_reference_set": best_source,
            "best_reference_source": best_ref,
        }

    return audit_results


def stratification_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    by_length_bin: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "valid": 0})
    by_prompt: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "valid": 0})
    for entry in reports:
        for row in entry["report"].get("candidates", []):
            length_bin = str(row.get("length_bin", "unknown"))
            prompt_id = str(row.get("prompt_id", "unknown"))
            by_length_bin[length_bin]["total"] += 1
            by_prompt[prompt_id]["total"] += 1
            if row.get("valid_sequence"):
                by_length_bin[length_bin]["valid"] += 1
                by_prompt[prompt_id]["valid"] += 1
    return {"by_length_bin": dict(by_length_bin), "by_prompt": dict(by_prompt)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Structural manifest JSON")
    parser.add_argument("--config", required=True, help="Structural config JSON")
    parser.add_argument("--output-root", required=True, help="Generation output root")
    parser.add_argument("--output", required=True, help="Audit report output path")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text())
    config_path = Path(args.config)
    output_root = Path(args.output_root)

    reports = load_generation_reports(output_root, manifest)
    dedup_map = build_dedup_map(reports)
    references = load_reference_sequences(config_path)
    novelty = novelty_audit(dedup_map, references)
    stratification = stratification_summary(reports)

    total_slots = sum(len(entry["report"].get("candidates", [])) for entry in reports)
    total_valid = sum(len(slots) for slots in dedup_map.values())
    unique_sequences = len(dedup_map)
    classification_counts = Counter(row["classification"] for row in novelty.values())

    payload = {
        "contract": "pearl.frontier-structural-candidate-audit/1",
        "manifest_sha256": sha256_file(manifest_path),
        "config_sha256": sha256_file(config_path),
        "total_slots": total_slots,
        "total_valid_slots": total_valid,
        "total_invalid_slots": total_slots - total_valid,
        "unique_valid_sequences": unique_sequences,
        "dedup_savings_ratio": round(1.0 - unique_sequences / max(total_valid, 1), 4),
        "novelty": {
            "exact_match": classification_counts.get("exact_match", 0),
            "near_match": classification_counts.get("near_match", 0),
            "novel": classification_counts.get("novel", 0),
        },
        "novelty_qualified_yield": round(
            classification_counts.get("novel", 0) / max(unique_sequences, 1), 4
        ),
        "stratification": stratification,
        "dedup_map": {seq_hash: len(slots) for seq_hash, slots in dedup_map.items()},
        "novelty_detail": novelty,
    }
    payload["audit_sha256"] = sha256_value(payload)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({k: v for k, v in payload.items() if k not in ("dedup_map", "novelty_detail")}, indent=2))


if __name__ == "__main__":
    main()
