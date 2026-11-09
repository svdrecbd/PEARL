#!/usr/bin/env python3
"""Build immutable, disjoint folding shard manifests from the candidate audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def sha256_value(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


SHARD_COUNT = 6


def build_shards(
    audit: dict[str, Any],
    manifest: dict[str, Any],
    calibration_result_path: Path,
    *,
    manifest_path: Path | None = None,
    discovery: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    dedup_map = dict(audit["dedup_map"])
    sequence_catalog = dict(audit.get("sequence_catalog", {}))
    all_slot_mappings = {
        key: list(value) for key, value in audit.get("slot_mappings", {}).items()
    }
    novelty_detail = audit.get("novelty_detail", {})
    discovery_roles: dict[str, list[str]] = {}
    discovery_funnel_sha256 = None
    if discovery is not None:
        if discovery.get("status") != "complete":
            raise RuntimeError("discovery selection is incomplete")
        expected_funnel_sha = sha256_value(
            {key: value for key, value in discovery.items() if key != "funnel_sha256"}
        )
        if discovery.get("funnel_sha256") != expected_funnel_sha:
            raise RuntimeError("discovery selection self-hash mismatch")
        ranker = discovery.get("ranker", {})
        if not ranker.get("all_survivors_rescored_from_scratch") or ranker.get(
            "esm2_scores_consumed"
        ):
            raise RuntimeError("discovery selection is not the clean ESM3 replacement")
        panel_fields = (
            ("selected", "selected_sequences"),
            ("random_survivor", "random_survivor_sequences"),
            ("random_audit", "audit_pool_sequences"),
        )
        seen_discovery_hashes: set[str] = set()
        for role, field in panel_fields:
            for row in discovery.get(field, []):
                sequence = str(row["sequence"])
                sequence_hash = str(row["sequence_sha256"])
                if hashlib.sha256(sequence.encode()).hexdigest() != sequence_hash:
                    raise RuntimeError(f"discovery sequence hash mismatch: {sequence_hash}")
                if sequence_hash in seen_discovery_hashes:
                    raise RuntimeError(f"discovery panels overlap: {sequence_hash}")
                seen_discovery_hashes.add(sequence_hash)
                existing = sequence_catalog.get(sequence_hash)
                if existing is not None and existing != sequence:
                    raise RuntimeError(f"sequence catalog collision: {sequence_hash}")
                sequence_catalog[sequence_hash] = sequence
                dedup_map[sequence_hash] = int(dedup_map.get(sequence_hash, 0)) + 1
                all_slot_mappings.setdefault(sequence_hash, []).append(
                    {
                        "job_key": row.get("source_job_key"),
                        "candidate_id": row.get("candidate_id"),
                        "prompt_id": row.get("prompt_id"),
                        "sample_seed": row.get("sample_seed"),
                        "sample_index": row.get("sample_index"),
                        "length_bin": row.get("length_bin"),
                        "cohort": "discovery",
                        "discovery_panel_role": role,
                        "esm3_score": row.get("esm3_score"),
                    }
                )
                discovery_roles[sequence_hash] = [role]
        if len(seen_discovery_hashes) != 168:
            raise RuntimeError("ESM3 discovery selection must contain 168 disjoint sequences")
        discovery_funnel_sha256 = discovery["funnel_sha256"]

    # Stable longest-processing-time partitioning keeps long sequences from
    # collecting in one tail shard. Length squared is a result-blind proxy for
    # the attention-dominated folding cost.
    shard_hashes: list[list[str]] = [[] for _ in range(SHARD_COUNT)]
    shard_work = [0] * SHARD_COUNT
    ranked_hashes = sorted(
        dedup_map,
        key=lambda seq_hash: (
            -(max(1, len(sequence_catalog.get(seq_hash) or "")) ** 2),
            seq_hash,
        ),
    )
    for sequence_hash in ranked_hashes:
        shard_index = min(range(SHARD_COUNT), key=lambda index: (shard_work[index], index))
        work = max(1, len(sequence_catalog.get(sequence_hash) or "")) ** 2
        shard_hashes[shard_index].append(sequence_hash)
        shard_work[shard_index] += work

    shards = []
    for shard_index in range(SHARD_COUNT):
        hashes = sorted(shard_hashes[shard_index])
        if not hashes:
            continue

        slot_mappings = []
        for seq_hash in hashes:
            slot_count = dedup_map[seq_hash]
            novelty = novelty_detail.get(seq_hash, {})
            slot_mappings.append({
                "sequence_sha256": seq_hash,
                "sequence": sequence_catalog.get(seq_hash),
                "slot_count": slot_count,
                "slot_mappings": all_slot_mappings.get(seq_hash, []),
                "novelty_classification": novelty.get("classification", "unknown"),
                "discovery_panel_roles": discovery_roles.get(seq_hash, []),
            })

        shard = {
            "contract": "pearl.frontier-structural-folding-shard/2",
            "shard_index": shard_index,
            "shard_count": SHARD_COUNT,
            "sequence_count": len(hashes),
            "total_slot_mapping_count": sum(m["slot_count"] for m in slot_mappings),
            "estimated_work_units": shard_work[shard_index],
            "manifest_sha256": sha256_file(manifest_path) if manifest_path else "test",
            "audit_sha256": audit["audit_sha256"],
            "discovery_funnel_sha256": discovery_funnel_sha256,
            "calibration_result_sha256": sha256_file(calibration_result_path) if calibration_result_path.is_file() else None,
            "structural_anchor_ref": manifest.get("structural_manifest_sha"),
            "sequences": slot_mappings,
        }
        shard["shard_sha256"] = sha256_value(shard)
        shards.append(shard)

    return shards


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", required=True, help="Candidate audit JSON")
    parser.add_argument("--manifest", required=True, help="Structural manifest JSON")
    parser.add_argument("--calibration-result", required=True)
    parser.add_argument("--discovery-selection")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    audit = json.loads(Path(args.audit).read_text())
    manifest = json.loads(Path(args.manifest).read_text())
    calibration_result_path = Path(args.calibration_result)
    discovery = (
        json.loads(Path(args.discovery_selection).read_text())
        if args.discovery_selection
        else None
    )

    shards = build_shards(
        audit,
        manifest,
        calibration_result_path,
        manifest_path=Path(args.manifest),
        discovery=discovery,
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    index = {
        "contract": "pearl.frontier-structural-folding-shard-index/2",
        "shard_count": len(shards),
        "total_sequences": sum(s["sequence_count"] for s in shards),
        "total_slot_mappings": sum(s["total_slot_mapping_count"] for s in shards),
        "audit_sha256": audit["audit_sha256"],
        "discovery_funnel_sha256": discovery.get("funnel_sha256") if discovery else None,
    }

    for shard in shards:
        path = output_dir / f"shard-{shard['shard_index']}.json"
        path.write_text(json.dumps(shard, indent=2) + "\n")
        index[f"shard_{shard['shard_index']}"] = {
            "path": str(path),
            "sha256": sha256_file(path),
            "sequence_count": shard["sequence_count"],
        }

    index_path = output_dir / "shard-index.json"
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    print(json.dumps(index, indent=2))


if __name__ == "__main__":
    main()
