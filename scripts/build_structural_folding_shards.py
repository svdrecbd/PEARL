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
    *, manifest_path: Path | None = None,
) -> list[dict[str, Any]]:
    dedup_map = audit["dedup_map"]
    novelty_detail = audit.get("novelty_detail", {})
    sequence_hashes = sorted(dedup_map.keys())
    shard_size = (len(sequence_hashes) + SHARD_COUNT - 1) // SHARD_COUNT

    shards = []
    for shard_index in range(SHARD_COUNT):
        start = shard_index * shard_size
        end = min(start + shard_size, len(sequence_hashes))
        shard_hashes = sequence_hashes[start:end]
        if not shard_hashes:
            continue

        slot_mappings = []
        for seq_hash in shard_hashes:
            slot_count = dedup_map[seq_hash]
            novelty = novelty_detail.get(seq_hash, {})
            slot_mappings.append({
                "sequence_sha256": seq_hash,
                "slot_count": slot_count,
                "novelty_classification": novelty.get("classification", "unknown"),
            })

        shard = {
            "contract": "pearl.frontier-structural-folding-shard/1",
            "shard_index": shard_index,
            "shard_count": SHARD_COUNT,
            "sequence_count": len(shard_hashes),
            "total_slot_mapping_count": sum(m["slot_count"] for m in slot_mappings),
            "manifest_sha256": sha256_file(manifest_path) if manifest_path else "test",
            "audit_sha256": audit["audit_sha256"],
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
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    audit = json.loads(Path(args.audit).read_text())
    manifest = json.loads(Path(args.manifest).read_text())
    calibration_result_path = Path(args.calibration_result)

    shards = build_shards(audit, manifest, calibration_result_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    index = {
        "contract": "pearl.frontier-structural-folding-shard-index/1",
        "shard_count": len(shards),
        "total_sequences": sum(s["sequence_count"] for s in shards),
        "total_slot_mappings": sum(s["total_slot_mapping_count"] for s in shards),
        "audit_sha256": audit["audit_sha256"],
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
