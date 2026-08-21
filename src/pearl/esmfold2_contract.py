"""Shared, fail-closed identity and calibration checks for frontier ESMFold2."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_value(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def folding_identity(gate: dict[str, Any]) -> dict[str, Any]:
    """Return every model/runtime/inference field that may affect a fold."""
    keys = (
        "backend",
        "model_name",
        "model_revision",
        "esmc_model_name",
        "esmc_model_revision",
        "esm_package_version",
        "esm_source_revision",
        "transformers_version",
        "transformers_source_revision",
        "torch_version",
        "python_version",
    )
    identity = {key: gate[key] for key in keys}
    identity["inference"] = gate["inference"]
    return identity


def validate_folding_gate(gate: dict[str, Any], runtime_lock: dict[str, Any]) -> None:
    if gate.get("backend") != "esmfold2":
        raise RuntimeError("frontier ESMFold2 validation received another backend")
    lock_keys = (
        "model_name",
        "model_revision",
        "esmc_model_name",
        "esmc_model_revision",
        "esm_package_version",
        "esm_source_revision",
        "transformers_version",
        "transformers_source_revision",
        "torch_version",
        "python_version",
    )
    mismatches = {
        key: {"gate": gate.get(key), "runtime_lock": runtime_lock.get(key)}
        for key in lock_keys
        if str(gate.get(key)) != str(runtime_lock.get(key))
    }
    if runtime_lock.get("contract") != "pearl.esmfold2-runtime-lock/1" or mismatches:
        raise RuntimeError(f"ESMFold2 gate/runtime lock mismatch: {mismatches}")
    inference = gate.get("inference", {})
    required = {
        "mode": "single_sequence_no_msa",
        "num_diffusion_samples": 1,
        "model_dtype": "bfloat16",
        "esmc_precision": "bf16",
        "kernel_backend": "fused",
        "chunk_size": None,
    }
    observed = {key: inference.get(key) for key in required}
    if observed != required:
        raise RuntimeError(f"unsupported ESMFold2 inference contract: {observed}")
    if int(inference.get("num_loops", 0)) <= 0 or int(inference.get("num_sampling_steps", 0)) <= 0:
        raise RuntimeError("ESMFold2 loops and sampling steps must be positive")


def folding_contract_sha(gate: dict[str, Any]) -> str:
    return sha256_value(folding_identity(gate))


def validate_complete_calibration(
    calibration: dict[str, Any], gate: dict[str, Any]
) -> None:
    if calibration.get("contract") != "pearl.esmfold2-natural-reference-calibration/1":
        raise RuntimeError("ESMFold2 calibration has the wrong contract")
    if calibration.get("status") != "complete":
        raise RuntimeError("ESMFold2 production folding is blocked until calibration is complete")
    if calibration.get("backend") != "esmfold2":
        raise RuntimeError("ESMFold2 calibration has the wrong backend")
    if calibration.get("folding_contract_sha") != folding_contract_sha(gate):
        raise RuntimeError("ESMFold2 calibration belongs to a different folding contract")
    expected = int(calibration.get("expected_count", -1))
    completed = int(calibration.get("count", -1))
    if expected <= 0 or completed != expected:
        raise RuntimeError("ESMFold2 calibration is incomplete")
    results = calibration.get("results", [])
    plddt = [float(value) for value in calibration.get("plddt", [])]
    ser_his = [float(value) for value in calibration.get("ser_his", [])]
    his_asp = [float(value) for value in calibration.get("his_asp", [])]
    if len(results) != expected or len(plddt) != expected:
        raise RuntimeError("ESMFold2 calibration arrays are incomplete")
    observed_hashes = {row.get("sequence_sha256") for row in results}
    if len(observed_hashes) != expected:
        raise RuntimeError("ESMFold2 calibration sequences are absent or non-unique")
    calibration_contract = calibration.get("calibration_contract", {})
    supplied_contract_sha = calibration_contract.get("calibration_contract_sha")
    unsigned_contract = {
        key: value
        for key, value in calibration_contract.items()
        if key != "calibration_contract_sha"
    }
    if supplied_contract_sha != sha256_value(unsigned_contract):
        raise RuntimeError("ESMFold2 calibration contract hash is invalid")
    expected_hashes = {
        row.get("sequence_sha256") for row in calibration_contract.get("selected", [])
    }
    if observed_hashes != expected_hashes:
        raise RuntimeError("ESMFold2 calibration results differ from the selected references")
    acceptance = calibration.get("acceptance", {})
    plddt_fraction = sum(value >= float(gate["plddt_gate"]) for value in plddt) / expected
    triad_fraction = min(len(ser_his), len(his_asp)) / expected
    if plddt_fraction < float(acceptance["minimum_plddt_pass_fraction_at_frozen_gate"]):
        raise RuntimeError("ESMFold2 natural-reference pLDDT calibration failed")
    if triad_fraction < float(acceptance["minimum_sidechain_triad_observed_fraction"]):
        raise RuntimeError("ESMFold2 natural-reference side-chain calibration failed")
