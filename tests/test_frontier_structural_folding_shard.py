from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_frontier_structural_folding_shard",
    ROOT / "scripts" / "run_frontier_structural_folding_shard.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_real_esm3_discovery_and_shard_validate() -> None:
    discovery = MODULE.read_json(
        ROOT
        / "reports"
        / "frontier_adaptation_v2_replication_salvage"
        / "discovery_funnel_esm3_repeat_filtered.json"
    )
    shard = MODULE.read_json(
        ROOT
        / "reports"
        / "frontier_adaptation_v2_replication_salvage"
        / "folding_shards_esm3_repeat_filtered"
        / "shard-0.json"
    )
    funnel_sha = MODULE.validate_discovery(discovery)
    MODULE.validate_shard(shard, discovery_sha=funnel_sha)


def test_esm2_scores_are_refused_even_with_a_recomputed_self_hash() -> None:
    discovery = MODULE.read_json(
        ROOT
        / "reports"
        / "frontier_adaptation_v2_replication_salvage"
        / "discovery_funnel_esm3_repeat_filtered.json"
    )
    tampered = copy.deepcopy(discovery)
    tampered["ranker"]["esm2_scores_consumed"] = True
    tampered["funnel_sha256"] = MODULE.sha256_value(
        {key: value for key, value in tampered.items() if key != "funnel_sha256"}
    )
    with pytest.raises(RuntimeError, match="consumed ESM2"):
        MODULE.validate_discovery(tampered)
