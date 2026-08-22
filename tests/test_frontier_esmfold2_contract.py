import json
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pearl.esmfold2_contract import (  # noqa: E402
    folding_contract_sha,
    sha256_value,
    validate_complete_calibration,
    validate_folding_gate,
)


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    ):
        assert value in dockerfile
    assert "facebook/esmfold_v1" not in dockerfile
    assert "ESMFold2-Fast" not in dockerfile
    assert "build-essential" in dockerfile
    assert "python3-dev" in dockerfile
    model_import = (
        "from transformers.models.esmfold2.modeling_esmfold2 "
        "import ESMFold2Model"
    )
    assert model_import in dockerfile

    backend_source = (ROOT / "src/pearl/structure_gate.py").read_text()
    assert model_import in backend_source
    assert "from transformers import ESMFold2Model" not in backend_source
    assert "from transformers.models.esmfold2 import ESMFold2Model" not in backend_source


def test_frontier_container_keeps_weights_out_of_buildkit_and_uses_pinned_runtime_cache() -> None:
    config, lock = config_and_lock()
    dockerfile = (
        ROOT / "deploy/frontier_adaptation_v2/Dockerfile.esmfold2"
    ).read_text()
    backend_source = (ROOT / "src/pearl/structure_gate.py").read_text()

    assert "snapshot_download" not in dockerfile
    assert "--no-cache-dir" in dockerfile
    assert "rm -rf /opt/src /root/.cache/pip" in dockerfile
    assert "snapshot_download(repo_id=self.model_name, revision=self.model_revision)" in backend_source
    assert "repo_id=self.esmc_model_name, revision=self.esmc_model_revision" in backend_source
    assert config["structure_gate"]["model_revision"] == lock["model_revision"]
    assert config["structure_gate"]["esmc_model_revision"] == lock["esmc_model_revision"]


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


def test_frontier_calibration_mode_uses_provider_output_capture() -> None:
    entrypoint = (
        ROOT / "deploy/frontier_adaptation_v2/run_esmfold2_job.sh"
    ).read_text()
    assert '"${ESMFOLD2_CALIBRATION:-0}" == "1"' in entrypoint
    assert '${GMN_OUTPUT_DIR:?GMN_OUTPUT_DIR is required}' in entrypoint
    assert "esmfold2-natural-reference-calibration.json" in entrypoint


def test_frontier_stock_image_bootstrap_preserves_exact_runtime_contract() -> None:
    bootstrap = (
        ROOT / "deploy/frontier_adaptation_v2/bootstrap_esmfold2_stock_image.sh"
    ).read_text()
    _, lock = config_and_lock()
    for value in (
        lock["esm_source_revision"],
        lock["transformers_source_revision"],
        lock["torch_version"],
    ):
        assert value in bootstrap
    assert "PEARL_SOURCE_COMMIT" in bootstrap
    assert "git rev-parse HEAD" in bootstrap
    assert "--no-cache-dir" in bootstrap
    assert "ESMFOLD2_CALIBRATION=1" in bootstrap
    assert "run_esmfold2_job.sh" in bootstrap


def test_frontier_stock_calibration_command_enters_bash_before_pipefail() -> None:
    builder = load_script("build_frontier_esmfold2_stock_calibration_approval.py")
    command = builder.provider_command("a" * 40)
    assert command.startswith("exec /usr/bin/env bash -lc ")
    assert not command.startswith("set -euo pipefail")
    subprocess.run(["/bin/sh", "-n"], input=command, text=True, check=True)
    payload = builder.packet("a" * 40, replacement_job_id="job-failed")
    assert payload["provider_command_posix_syntax_valid"] is True
    assert payload["scientific_contract_changes"] == []
    assert payload["packet_sha256"] == sha256_value(
        {key: value for key, value in payload.items() if key != "packet_sha256"}
    )


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
