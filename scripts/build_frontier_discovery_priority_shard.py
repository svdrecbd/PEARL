#!/usr/bin/env python3
"""Extract the frozen 168-sequence discovery panel into one priority fold shard."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "reports/frontier_adaptation_v2_replication_salvage/folding_shards_esm3_repeat_filtered"
DISCOVERY_PATH = ROOT / "reports/frontier_adaptation_v2_replication_salvage/discovery_funnel_esm3_repeat_filtered.json"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    discovery = read_json(DISCOVERY_PATH)
    expected_discovery_sha = sha256_value(
        {key: value for key, value in discovery.items() if key != "funnel_sha256"}
    )
    if discovery.get("funnel_sha256") != expected_discovery_sha:
        raise RuntimeError("corrected ESM3 discovery funnel self-hash mismatch")

    panel_fields = {
        "selected": "selected_sequences",
        "random_survivor": "random_survivor_sequences",
        "random_audit": "audit_pool_sequences",
    }
    expected_roles: dict[str, str] = {}
    for role, field in panel_fields.items():
        for row in discovery.get(field, []):
            sequence_sha = str(row["sequence_sha256"])
            if sequence_sha in expected_roles:
                raise RuntimeError(f"discovery panels overlap: {sequence_sha}")
            if hashlib.sha256(str(row["sequence"]).encode()).hexdigest() != sequence_sha:
                raise RuntimeError(f"discovery sequence hash mismatch: {sequence_sha}")
            expected_roles[sequence_sha] = role
    if {role: list(expected_roles.values()).count(role) for role in panel_fields} != {
        "selected": 96,
        "random_survivor": 24,
        "random_audit": 48,
    }:
        raise RuntimeError("frozen discovery role counts changed")

    source_rows: dict[str, dict[str, Any]] = {}
    anchors: dict[str, Any] | None = None
    for source_index in range(6):
        source_path = SOURCE_ROOT / f"shard-{source_index}.json"
        source = read_json(source_path)
        if source.get("shard_sha256") != sha256_value(
            {key: value for key, value in source.items() if key != "shard_sha256"}
        ):
            raise RuntimeError(f"source shard self-hash mismatch: {source_path}")
        observed_anchors = {
            key: source[key]
            for key in (
                "manifest_sha256",
                "audit_sha256",
                "discovery_funnel_sha256",
                "calibration_result_sha256",
                "structural_anchor_ref",
            )
        }
        if anchors is None:
            anchors = observed_anchors
        elif observed_anchors != anchors:
            raise RuntimeError("source shard authority anchors differ")
        for row in source.get("sequences", []):
            sequence_sha = str(row["sequence_sha256"])
            if sequence_sha not in expected_roles:
                continue
            if sequence_sha in source_rows:
                raise RuntimeError(f"selected sequence occurs in multiple source shards: {sequence_sha}")
            expected_role = expected_roles[sequence_sha]
            if row.get("discovery_panel_roles") != [expected_role]:
                raise RuntimeError(f"selected sequence role mismatch: {sequence_sha}")
            source_rows[sequence_sha] = row

    missing = sorted(set(expected_roles) - set(source_rows))
    extras = sorted(set(source_rows) - set(expected_roles))
    if missing or extras or len(source_rows) != 168:
        raise RuntimeError(f"priority shard membership mismatch: missing={missing}, extras={extras}")
    if anchors is None or anchors["discovery_funnel_sha256"] != expected_discovery_sha:
        raise RuntimeError("source shards are not bound to the corrected ESM3 funnel")

    rows = [source_rows[sequence_sha] for sequence_sha in sorted(source_rows)]
    shard = {
        "contract": "pearl.frontier-structural-folding-shard/2",
        "shard_index": 0,
        "shard_count": 1,
        "sequence_count": len(rows),
        "total_slot_mapping_count": sum(int(row["slot_count"]) for row in rows),
        "estimated_work_units": sum(len(str(row["sequence"])) ** 2 for row in rows),
        **anchors,
        "sequences": rows,
    }
    shard["shard_sha256"] = sha256_value(shard)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    shard_path = output_dir / "shard-0.json"
    shard_path.write_text(json.dumps(shard, indent=2) + "\n", encoding="utf-8")
    index = {
        "contract": "pearl.frontier-structural-folding-shard-index/2",
        "execution_scope": "frozen_discovery_priority_only",
        "shard_count": 1,
        "total_sequences": 168,
        "total_slot_mappings": shard["total_slot_mapping_count"],
        "discovery_role_counts": {
            role: sum(row["discovery_panel_roles"] == [role] for row in rows)
            for role in panel_fields
        },
        "audit_sha256": shard["audit_sha256"],
        "discovery_funnel_sha256": expected_discovery_sha,
        "shard_0": {
            "path": str(shard_path),
            "sha256": sha256_file(shard_path),
            "sequence_count": 168,
        },
    }
    index_path = output_dir / "shard-index.json"
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(index, indent=2))


if __name__ == "__main__":
    main()
