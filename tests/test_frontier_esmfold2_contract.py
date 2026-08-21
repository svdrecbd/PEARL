import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pearl.esmfold2_contract import (  # noqa: E402
    folding_contract_sha,
    validate_complete_calibration,
    validate_folding_gate,
)


def config_and_lock():
    config = json.loads(
        (ROOT / "configs/experiments/frontier_adaptation_structural_v2_original.json").read_text()
    )
    lock = json.loads((ROOT / config["structure_gate"]["runtime_lock"]).read_text())
    return config, lock


def test_frontier_structural_amendment_has_384_fixed_slots_and_full_model() -> None:
    config, lock = config_and_lock()
    gate = config["structure_gate"]
    validate_folding_gate(gate, lock)
    assert config["contract"] == "pearl.frontier-adaptation-structural/3"
    assert config["prompt_count"] * len(config["sampling"]["sample_seeds"]) == 384
    assert gate["model_name"] == "biohub/ESMFold2"
    assert gate["inference"] == {
        "mode": "single_sequence_no_msa",
        "num_loops": 20,
        "num_sampling_steps": 100,
        "num_diffusion_samples": 1,
        "inference_seed": 20260821,
        "model_dtype": "bfloat16",
        "esmc_precision": "bf16",
        "kernel_backend": "fused",
        "chunk_size": None,
    }


def test_frontier_container_pins_sources_and_cannot_fall_back_to_v1_or_fast() -> None:
    _, lock = config_and_lock()
    dockerfile = (
        ROOT / "deploy/frontier_adaptation_v2/Dockerfile.esmfold2"
    ).read_text()
    for value in (
        lock["cuda_base_image"],
        lock["esm_source_revision"],
        lock["transformers_source_revision"],
        lock["model_revision"],
        lock["esmc_model_revision"],
    ):
        assert value in dockerfile
    assert "facebook/esmfold_v1" not in dockerfile
    assert "ESMFold2-Fast" not in dockerfile


def test_frontier_context_builders_publish_the_provider_default_dockerfile() -> None:
    for builder in (
        "build_esmfold2_context.sh",
        "build_esmfold2_calibration_context.sh",
    ):
        script = (ROOT / "deploy/frontier_adaptation_v2" / builder).read_text()
        assert '"$context_root/Dockerfile"' in script
        assert '"$context_root/Dockerfile.esmfold2"' not in script
        assert 'records_source="$repo_root/data/petase_family_expanded/petase_records.jsonl"' in script
        assert (
            'cp "$records_source" '
            '"$context_root/data/petase_family_expanded/petase_records.jsonl"'
        ) in script


def test_pending_calibration_hard_blocks_production() -> None:
    config, _ = config_and_lock()
    gate = config["structure_gate"]
    pending = json.loads((ROOT / gate["calibration"]).read_text())
    with pytest.raises(RuntimeError, match="blocked until calibration is complete"):
        validate_complete_calibration(pending, gate)


def test_complete_calibration_must_bind_runtime_and_pass_prospective_gates() -> None:
    config, _ = config_and_lock()
    gate = config["structure_gate"]
    count = 80
    selected = [{"sequence_sha256": f"{index:064x}"} for index in range(count)]
    calibration_contract = {"selected": selected}
    from pearl.esmfold2_contract import sha256_value
    calibration_contract["calibration_contract_sha"] = sha256_value(calibration_contract)
    calibration = {
        "contract": "pearl.esmfold2-natural-reference-calibration/1",
        "status": "complete",
        "backend": "esmfold2",
        "folding_contract_sha": folding_contract_sha(gate),
        "expected_count": count,
        "count": count,
        "acceptance": {
            "minimum_plddt_pass_fraction_at_frozen_gate": 0.85,
            "minimum_sidechain_triad_observed_fraction": 0.45,
        },
        "calibration_contract": calibration_contract,
        "plddt": [80.0] * count,
        "ser_his": [3.0] * 40,
        "his_asp": [3.0] * 40,
        "results": selected,
    }
    validate_complete_calibration(calibration, gate)
    calibration["plddt"] = [60.0] * count
    with pytest.raises(RuntimeError, match="pLDDT calibration failed"):
        validate_complete_calibration(calibration, gate)
