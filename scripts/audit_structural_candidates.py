#!/usr/bin/env python3
"""Post-generation audit: global dedup, novelty, and stratification checks.

Runs after Tinker generation completes and before GMN folding submission.
Produces a self-hashed audit report consumed by the folding manifest builder.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_generation_builder() -> Any:
    path = ROOT / "scripts" / "build_frontier_adaptation_gmn_manifest.py"
    spec = importlib.util.spec_from_file_location("frontier_generation_builder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load frontier generation contract builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_value(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def load_generation_reports(
    output_root: Path,
    manifest: dict[str, Any],
    *,
    campaigns: set[str] | None = None,
) -> list[dict[str, Any]]:
    builder = load_generation_builder()
    reports = []
    for job in manifest["jobs"]:
        if campaigns is not None and str(job.get("campaign")) not in campaigns:
            continue
        expected_contract = builder.expected_generation_contract(job)
        run_dir = output_root / str(expected_contract["run_key"])
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
        if report.get("contract") != expected_contract:
            raise RuntimeError(f"generation contract mismatch: {report_path}")
        reports.append({"job": job, "report": report, "path": str(report_path)})
    if not reports:
        raise RuntimeError("candidate audit selected no generation reports")
    return reports


def build_dedup_map(
    reports: list[dict[str, Any]], *, cohort: str = "confirmatory"
) -> dict[str, Any]:
    sequence_to_slots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in reports:
        job_key = entry["job"]["job_key"]
        for row in entry["report"].get("candidates", []):
            if str(row.get("cohort", "confirmatory")) != cohort:
                continue
            seq_hash = row.get("sequence_sha256")
            if seq_hash and row.get("valid_sequence"):
                sequence_to_slots[seq_hash].append({
                    "job_key": job_key,
                    "candidate_id": row["candidate_id"],
                    "prompt_id": row.get("prompt_id"),
                    "sample_seed": row.get("sample_seed"),
                    "sample_index": row.get("sample_index", 0),
                    "length_bin": row.get("length_bin"),
                    "sequence": row.get("sequence"),
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

    def load_partition(name: str) -> list[dict[str, str]]:
        partition = training_manifest["partitions"][name]
        path = ROOT / partition["path"]
        if sha256_file(path) != partition["sha256"]:
            raise RuntimeError(f"reference partition hash mismatch: {name}")
        rows: list[dict[str, str]] = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            for key in ("chosen", "rejected"):
                sequence = str(value.get(key) or "")
                if sequence:
                    rows.append({"source": f"{name}:{key}", "sequence": sequence})
        return rows

    references["training"] = load_partition("d10_train_true")
    references["heldout"] = load_partition("d10_holdout_true")

    prompt_path = ROOT / config["prompt_panel"]
    if prompt_path.is_file():
        prompt_values = []
        for line in prompt_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            prompt_values.append(str(row["prompt"]))
        prompt_set = set(prompt_values)
        prompt_seqs = []
        holdout_path = ROOT / training_manifest["partitions"]["d10_holdout_true"]["path"]
        for line in holdout_path.read_text().splitlines():
            row = json.loads(line)
            if str(row.get("prompt")) not in prompt_set:
                continue
            for key in ("chosen", "rejected"):
                sequence = str(row.get(key) or "")
                if sequence:
                    prompt_seqs.append({"source": f"prompt:{key}", "sequence": sequence})
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
    reference_profiles: dict[str, list[tuple[str, str, Counter, float]]] = {}
    inverted: dict[str, dict[str, list[int]]] = {}
    for ref_name, ref_seqs in references.items():
        unique: dict[str, tuple[str, str]] = {}
        for entry in ref_seqs:
            sequence = entry["sequence"]
            unique.setdefault(hashlib.sha256(sequence.encode()).hexdigest(), (entry["source"], sequence))
        profiles: list[tuple[str, str, Counter, float]] = []
        postings: dict[str, list[int]] = defaultdict(list)
        for ref_hash, (source, sequence) in unique.items():
            profile = kmer_profile(sequence, kmer_k)
            norm = math.sqrt(sum(value * value for value in profile.values()))
            index = len(profiles)
            profiles.append((source, ref_hash, profile, norm))
            for kmer in profile:
                postings[kmer].append(index)
        reference_profiles[ref_name] = profiles
        inverted[ref_name] = postings

    for seq_hash in dedup_map:
        sequence = str(dedup_map[seq_hash][0].get("sequence") or "")
        classification = "novel"
        best_similarity = 0.0
        best_source = None
        best_ref = None
        for ref_name, profiles in reference_profiles.items():
            exact = next((row for row in profiles if row[1] == seq_hash), None)
            if exact is not None:
                classification = "exact_match"
                best_similarity = 1.0
                best_source = ref_name
                best_ref = exact[0]
                break

        if classification == "novel":
            candidate_profile = kmer_profile(sequence, kmer_k)
            candidate_norm = math.sqrt(sum(value * value for value in candidate_profile.values()))
            for ref_name, profiles in reference_profiles.items():
                candidates: set[int] = set()
                for kmer in candidate_profile:
                    candidates.update(inverted[ref_name].get(kmer, []))
                for index in candidates:
                    source, ref_hash, profile, ref_norm = profiles[index]
                    if candidate_norm == 0.0 or ref_norm == 0.0:
                        continue
                    dot = sum(
                        count * profile.get(kmer, 0)
                        for kmer, count in candidate_profile.items()
                    )
                    sim = dot / (candidate_norm * ref_norm)
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
    parser.add_argument(
        "--campaign",
        action="append",
        dest="campaigns",
        help="Campaign to include; repeat for multiple campaigns. Default: all.",
    )
    parser.add_argument("--cohort", default="confirmatory")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text())
    config_path = Path(args.config)
    output_root = Path(args.output_root)

    campaigns = set(args.campaigns) if args.campaigns else None
    reports = load_generation_reports(output_root, manifest, campaigns=campaigns)
    dedup_map = build_dedup_map(reports, cohort=args.cohort)
    references = load_reference_sequences(config_path)
    novelty = novelty_audit(dedup_map, references)
    stratification = stratification_summary(reports)

    selected_rows = [
        row
        for entry in reports
        for row in entry["report"].get("candidates", [])
        if str(row.get("cohort", "confirmatory")) == args.cohort
    ]
    total_slots = len(selected_rows)
    total_valid = sum(len(slots) for slots in dedup_map.values())
    unique_sequences = len(dedup_map)
    classification_counts = Counter(row["classification"] for row in novelty.values())

    payload = {
        "contract": "pearl.frontier-structural-candidate-audit/1",
        "manifest_sha256": sha256_file(manifest_path),
        "config_sha256": sha256_file(config_path),
        "source_structural_manifest_sha": manifest.get("structural_manifest_sha"),
        "selected_campaigns": sorted(campaigns) if campaigns else sorted(
            {str(entry["job"].get("campaign")) for entry in reports}
        ),
        "selected_job_keys": [entry["job"]["job_key"] for entry in reports],
        "candidate_cohort": args.cohort,
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
        "sequence_catalog": {
            seq_hash: str(slots[0].get("sequence") or "") for seq_hash, slots in dedup_map.items()
        },
        "slot_mappings": {
            seq_hash: [
                {key: value for key, value in slot.items() if key != "sequence"}
                for slot in slots
            ]
            for seq_hash, slots in dedup_map.items()
        },
        "novelty_detail": novelty,
    }
    payload["audit_sha256"] = sha256_value(payload)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({k: v for k, v in payload.items() if k not in ("dedup_map", "novelty_detail")}, indent=2))


if __name__ == "__main__":
    main()
