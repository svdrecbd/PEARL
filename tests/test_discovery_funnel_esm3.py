from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "discovery_funnel_esm3", ROOT / "scripts" / "discovery_funnel_esm3.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_partition_offsets_cover_each_residue_exactly_once() -> None:
    for length in (1, 7, 8, 9, 40, 500):
        partitions = MODULE.partition_residue_offsets(length)
        flattened = [offset for partition in partitions for offset in partition]
        assert sorted(flattened) == list(range(length))
        assert len(flattened) == len(set(flattened))


def test_esm3_artifact_identities_are_exact() -> None:
    assert MODULE.ESM3_MODEL == "biohub/esm3-sm-open-v1"
    assert MODULE.ESM3_MODEL_REVISION == "47f0545b2b6daf26a93439a3cd610f4f7f3d5478"
    assert MODULE.ESM3_CODE_REVISION == "d0207ea3c8cbf072679ece3bb332787d25e06852"


def test_selection_panels_are_disjoint() -> None:
    rows = [
        {"sequence_sha256": f"h{index:04d}", "esm3_score": float(index)}
        for index in range(300)
    ]
    selected, random_survivors, audit_pool = MODULE.select_panels(rows)
    selected_hashes = {row["sequence_sha256"] for row in selected}
    survivor_hashes = {row["sequence_sha256"] for row in random_survivors}
    audit_hashes = {row["sequence_sha256"] for row in audit_pool}
    assert (len(selected), len(random_survivors), len(audit_pool)) == (96, 24, 48)
    assert selected_hashes.isdisjoint(survivor_hashes)
    assert selected_hashes.isdisjoint(audit_hashes)
    assert survivor_hashes.isdisjoint(audit_hashes)
