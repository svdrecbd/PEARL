#!/usr/bin/env python3
"""Fold one immutable salvage shard under the exact FP32 ESMFold2 contract."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.esmfold2_contract import (  # noqa: E402
    folding_identity,
    validate_complete_calibration,
    validate_folding_gate,
    validate_fp32_folding_config,
)
from pearl.io_utils import atomic_write_json  # noqa: E402
from pearl.structure_gate import (  # noqa: E402
    EsmFold2LocalBackend,
    StructurePrediction,
    gate_prediction,
    parse_pdb,
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "missing"


def validate_discovery(discovery: dict[str, Any]) -> str:
    if discovery.get("contract") != "pearl.frontier-discovery-funnel-esm3-repeat-filtered/1":
        raise RuntimeError("folding requires the post-hoc repeat-filtered ESM3 result")
    if discovery.get("status") != "complete":
        raise RuntimeError("ESM3 discovery result is incomplete")
    expected = sha256_value({key: value for key, value in discovery.items() if key != "funnel_sha256"})
    if discovery.get("funnel_sha256") != expected:
        raise RuntimeError("ESM3 discovery result self-hash mismatch")
    ranker = discovery.get("ranker", {})
    if not ranker.get("all_survivors_rescored_from_scratch"):
        raise RuntimeError("discovery result did not rescore every survivor from scratch")
    if ranker.get("esm2_scores_consumed") is not False:
        raise RuntimeError("discovery result consumed ESM2 scores")
    if not ranker.get("posthoc_repeat_filter_applied"):
        raise RuntimeError("discovery result omitted the authorized repeat filter")
    expected_filter = {
        "status": "posthoc_exploratory",
        "max_tested_period": 100,
        "max_global_periodicity_exclusive": 0.8,
        "max_exact_tandem_coverage_exclusive": 0.4,
        "kmer_size": 5,
        "min_distinct_kmer_fraction_inclusive": 0.75,
        "max_single_residue_fraction_inclusive": 0.2,
        "selection_seed": 20260822,
    }
    if discovery.get("repeat_filter") != expected_filter:
        raise RuntimeError("discovery result has a different repeat-filter contract")
    panel_rows = [
        *discovery.get("selected_sequences", []),
        *discovery.get("random_survivor_sequences", []),
        *discovery.get("audit_pool_sequences", []),
    ]
    if len(panel_rows) != 168:
        raise RuntimeError("repeat-filtered discovery panel must contain 168 sequences")
    panel_hashes = [str(row.get("sequence_sha256")) for row in panel_rows]
    if len(set(panel_hashes)) != len(panel_hashes):
        raise RuntimeError("repeat-filtered discovery panels overlap")
    if any(not row.get("repeat_screen", {}).get("passes") for row in panel_rows):
        raise RuntimeError("repeat-filtered discovery panel contains a rejected sequence")
    return expected


def validate_shard(shard: dict[str, Any], *, discovery_sha: str) -> None:
    if shard.get("contract") != "pearl.frontier-structural-folding-shard/2":
        raise RuntimeError("unexpected folding shard contract")
    expected = sha256_value({key: value for key, value in shard.items() if key != "shard_sha256"})
    if shard.get("shard_sha256") != expected:
        raise RuntimeError("folding shard self-hash mismatch")
    if shard.get("discovery_funnel_sha256") != discovery_sha:
        raise RuntimeError("folding shard is not bound to the clean ESM3 result")
    sequences = shard.get("sequences", [])
    if len(sequences) != int(shard.get("sequence_count", -1)):
        raise RuntimeError("folding shard sequence count mismatch")
    seen: set[str] = set()
    for row in sequences:
        sequence = str(row.get("sequence") or "")
        sequence_sha = str(row.get("sequence_sha256") or "")
        if not sequence or hashlib.sha256(sequence.encode()).hexdigest() != sequence_sha:
            raise RuntimeError(f"folding shard sequence hash mismatch: {sequence_sha}")
        if sequence_sha in seen:
            raise RuntimeError(f"duplicate sequence in folding shard: {sequence_sha}")
        seen.add(sequence_sha)


def validate_config(config_path: Path, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    gate = config["structure_gate"]
    if gate.get("backend") != "esmfold2":
        raise RuntimeError("salvage folding requires ESMFold2")
    generation_path = repo_path(config["generation_config"])
    generation = read_json(generation_path)
    runtime_lock = read_json(repo_path(gate["runtime_lock"]))
    calibration = read_json(repo_path(gate["calibration"]))
    validate_fp32_folding_config(
        config,
        generation,
        generation_config_sha256=sha256_file(generation_path),
        runtime_lock=runtime_lock,
        calibration=calibration,
    )
    validate_folding_gate(gate, runtime_lock)
    validate_complete_calibration(calibration, gate)
    if config.get("generation_config_sha256") != sha256_file(generation_path):
        raise RuntimeError("folding successor has the wrong immutable generation predecessor")
    return gate, calibration


def validate_environment(gate: dict[str, Any]) -> None:
    observed = {
        "esm": package_version("esm"),
        "torch": package_version("torch"),
        "transformers": package_version("transformers"),
        "python": ".".join(platform.python_version_tuple()[:2]),
    }
    expected = {
        "esm": str(gate["esm_package_version"]),
        "torch": str(gate["torch_version"]),
        "transformers": str(gate["transformers_version"]),
        "python": str(gate["python_version"]),
    }
    if observed != expected:
        raise RuntimeError(f"structural environment mismatch: observed={observed}, expected={expected}")


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def report_payload(contract: dict[str, Any], results: list[dict[str, Any]], status: str) -> dict[str, Any]:
    return {
        "contract": contract,
        "status": status,
        "expected_sequence_count": contract["sequence_count"],
        "completed_sequence_count": len(results),
        "complete": len(results) == contract["sequence_count"],
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--shard", required=True)
    parser.add_argument("--discovery-selection", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--shape-only", action="store_true")
    args = parser.parse_args()

    config_path = repo_path(args.config)
    shard_path = repo_path(args.shard)
    discovery_path = repo_path(args.discovery_selection)
    config = read_json(config_path)
    shard = read_json(shard_path)
    discovery_sha = validate_discovery(read_json(discovery_path))
    validate_shard(shard, discovery_sha=discovery_sha)
    gate, _calibration = validate_config(config_path, config)
    calibration_path = repo_path(gate["calibration"])
    if shard.get("calibration_result_sha256") != sha256_file(calibration_path):
        raise RuntimeError("folding shard is not bound to the exact FP32 calibration")

    contract = {
        "contract": "pearl.frontier-structural-salvage-fold/1",
        "campaign_id": config["campaign_id"],
        "folding_config_sha256": sha256_file(config_path),
        "shard_file_sha256": sha256_file(shard_path),
        "shard_sha256": shard["shard_sha256"],
        "shard_index": shard["shard_index"],
        "sequence_count": shard["sequence_count"],
        "discovery_file_sha256": sha256_file(discovery_path),
        "discovery_funnel_sha256": discovery_sha,
        "calibration_sha256": sha256_file(calibration_path),
        "folding_identity": folding_identity(gate),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "structure_gate_library_sha256": sha256_file(ROOT / "src" / "pearl" / "structure_gate.py"),
    }
    contract["fold_contract_sha256"] = sha256_value(contract)

    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "structure_report.json"
    contract_path = output_dir / "fold_contract.json"
    results: list[dict[str, Any]] = []
    if report_path.exists():
        existing = read_json(report_path)
        if existing.get("contract") != contract:
            raise RuntimeError("existing result belongs to a different immutable fold contract")
        results = list(existing.get("results", []))
    atomic_write_json(contract_path, contract)
    if args.shape_only:
        atomic_write_json(report_path, report_payload(contract, results, "shape_validated"))
        print(json.dumps({"status": "shape_validated", "contract": contract}, indent=2))
        return

    validate_environment(gate)
    os.environ["STRUCTURE_GATE_CALIBRATION_PATH"] = str(calibration_path)
    inference = gate["inference"]
    backend = EsmFold2LocalBackend(
        model_name=str(gate["model_name"]),
        model_revision=str(gate["model_revision"]),
        esmc_model_name=str(gate["esmc_model_name"]),
        esmc_model_revision=str(gate["esmc_model_revision"]),
        num_loops=int(inference["num_loops"]),
        num_sampling_steps=int(inference["num_sampling_steps"]),
        num_diffusion_samples=int(inference["num_diffusion_samples"]),
        inference_seed=int(inference["inference_seed"]),
        model_dtype=str(inference["model_dtype"]),
        esmc_precision=str(inference["esmc_precision"]),
        kernel_backend=inference["kernel_backend"],
        chunk_size=inference["chunk_size"],
        device=os.environ.get("ESMFOLD_DEVICE") or None,
    )
    completed = {str(row["sequence_sha256"]) for row in results}
    pdb_dir = output_dir / "pdb"
    for candidate in shard["sequences"]:
        sequence_sha = str(candidate["sequence_sha256"])
        if sequence_sha in completed:
            continue
        try:
            pdb_text = backend.fold(str(candidate["sequence"]))
            residues, mean_plddt = parse_pdb(pdb_text)
            structural = gate_prediction(
                StructurePrediction(
                    sequence=str(candidate["sequence"]),
                    residues=residues,
                    mean_plddt=mean_plddt,
                    backend=backend.name,
                    pdb_text=pdb_text,
                ),
                plddt_gate=float(gate["plddt_gate"]),
                hbond_max=float(gate["triad_hbond_max_angstrom"]),
            )
            full_pass = bool(
                structural["structural_gate_pass"]
                and structural.get("triad", {}).get("method") == gate["required_triad_method"]
            )
            pdb_path = pdb_dir / f"{sequence_sha}.pdb"
            atomic_write_text(pdb_path, pdb_text)
            row = {
                "sequence_sha256": sequence_sha,
                "slot_count": candidate["slot_count"],
                "slot_mappings": candidate["slot_mappings"],
                "discovery_panel_roles": candidate.get("discovery_panel_roles", []),
                **structural,
                "pdb_path": str(pdb_path),
                "pdb_sha256": sha256_file(pdb_path),
                "required_triad_method": gate["required_triad_method"],
                "full_structural_gate_pass": full_pass,
            }
        except Exception as error:
            payload = report_payload(contract, results, "infrastructure_interrupted")
            payload["infrastructure_error"] = {
                "sequence_sha256": sequence_sha,
                "error_type": type(error).__name__,
                "message": str(error),
                "counted_as_scientific_failure": False,
            }
            atomic_write_json(report_path, payload)
            raise
        results.append(row)
        completed.add(sequence_sha)
        atomic_write_json(report_path, report_payload(contract, results, "running"))
        print(json.dumps({"sequence_sha256": sequence_sha, "completed": len(results)}), flush=True)

    atomic_write_json(report_path, report_payload(contract, results, "complete"))
    print(json.dumps({"status": "complete", "completed": len(results)}, indent=2))


if __name__ == "__main__":
    main()
