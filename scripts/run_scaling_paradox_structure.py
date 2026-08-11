#!/usr/bin/env python3
"""Fold one complete scaling-paradox generation panel under a frozen ESMFold contract."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.io_utils import atomic_write_json  # noqa: E402
from pearl.structure_gate import (  # noqa: E402
    EsmFoldLocalBackend,
    StructurePrediction,
    gate_prediction,
    parse_pdb,
)


DEFAULT_CONFIG = ROOT / "configs" / "experiments" / "scaling_paradox_structural_v1.json"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


def build_contract(config_path: Path, config: dict[str, Any], generation: dict[str, Any]) -> dict[str, Any]:
    gate = config["structure_gate"]
    calibration_path = repo_path(gate["calibration"])
    identity = {
        "campaign_id": config["campaign_id"],
        "structural_contract": config["contract"],
        "structural_config_sha256": sha256_file(config_path),
        "generation_contract_sha": generation["contract"]["generation_contract_sha"],
        "generation_run_key": generation["contract"]["run_key"],
        "expected_candidate_count": generation["expected_candidate_count"],
        "backend": gate["backend"],
        "model_name": gate["model_name"],
        "model_revision": gate["model_revision"],
        "transformers_version": gate["transformers_version"],
        "torch_version": gate["torch_version"],
        "plddt_gate": gate["plddt_gate"],
        "triad_hbond_max_angstrom": gate["triad_hbond_max_angstrom"],
        "required_triad_method": gate["required_triad_method"],
        "calibration_sha256": sha256_file(calibration_path),
        "evaluator_sha256": sha256_file(Path(__file__).resolve()),
        "structure_gate_library_sha256": sha256_file(ROOT / "src" / "pearl" / "structure_gate.py"),
    }
    identity["fold_contract_sha"] = sha256_value(identity)
    return identity


def validate_environment(contract: dict[str, Any]) -> None:
    observed = {
        "transformers": package_version("transformers"),
        "torch": package_version("torch"),
    }
    expected = {
        "transformers": str(contract["transformers_version"]),
        "torch": str(contract["torch_version"]),
    }
    if observed != expected:
        raise RuntimeError(f"structural environment mismatch: observed={observed}, expected={expected}")


def report_payload(contract: dict[str, Any], results: list[dict[str, Any]], *, status: str) -> dict[str, Any]:
    expected = int(contract["expected_candidate_count"])
    passes = sum(bool(row.get("full_structural_gate_pass")) for row in results)
    return {
        "contract": contract,
        "status": status,
        "expected_candidate_count": expected,
        "completed_candidate_count": len(results),
        "complete": len(results) == expected,
        "full_structural_gate_passes": passes,
        "full_structural_gate_yield": passes / expected if expected else 0.0,
        "results": results,
    }


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--generation-report", required=True)
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "scaling_paradox_v1" / "structural"))
    parser.add_argument("--shape-only", action="store_true")
    args = parser.parse_args()

    config_path = repo_path(args.config)
    config = read_json(config_path)
    generation_path = repo_path(args.generation_report)
    generation = read_json(generation_path)
    if generation.get("status") != "complete" or not generation.get("complete"):
        raise RuntimeError("structural folding requires a complete immutable generation panel")
    if len(generation.get("candidates", [])) != int(generation["expected_candidate_count"]):
        raise RuntimeError("generation candidate count does not match its declared contract")
    contract = build_contract(config_path, config, generation)
    run_dir = repo_path(args.output_dir) / str(generation["contract"]["run_key"])
    report_path = run_dir / "structure_report.json"
    contract_path = run_dir / "fold_contract.json"
    generation_contract_path = run_dir / "generation_contract.json"
    pdb_dir = run_dir / "pdb"
    results: list[dict[str, Any]] = []
    if report_path.exists():
        existing = read_json(report_path)
        if existing.get("contract") != contract:
            raise RuntimeError("existing structure report belongs to a different immutable contract")
        results = [dict(row) for row in existing.get("results", []) if row.get("candidate_id")]
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(contract_path, contract)
    atomic_write_json(generation_contract_path, generation["contract"])
    if args.shape_only:
        payload = report_payload(contract, results, status="shape_validated")
        atomic_write_json(report_path, payload)
        print(json.dumps({key: value for key, value in payload.items() if key != "results"}, indent=2))
        return

    validate_environment(contract)
    gate = config["structure_gate"]
    os.environ["STRUCTURE_GATE_CALIBRATION_PATH"] = str(repo_path(gate["calibration"]))
    backend = EsmFoldLocalBackend(
        model_name=str(gate["model_name"]),
        revision=str(gate["model_revision"]),
        device=os.environ.get("ESMFOLD_DEVICE") or None,
    )
    completed = {str(row["candidate_id"]) for row in results}
    for candidate in generation["candidates"]:
        cid = str(candidate["candidate_id"])
        if cid in completed:
            continue
        base = {
            "candidate_id": cid,
            "prompt_id": candidate["prompt_id"],
            "sample_seed": candidate["sample_seed"],
            "target_length": candidate["target_length"],
            "sequence_sha256": candidate.get("sequence_sha256"),
            "valid_generation": bool(candidate.get("valid_sequence")),
            "duplicate_sequence": bool(candidate.get("duplicate_sequence")),
        }
        sequence = str(candidate.get("sequence") or "")
        if not candidate.get("valid_sequence"):
            row = {
                **base,
                "failure_reason": candidate.get("generation_error") or "duplicate_generation",
                "full_structural_gate_pass": False,
            }
        else:
            try:
                pdb_text = backend.fold(sequence)
                residues, mean_plddt = parse_pdb(pdb_text)
                prediction = StructurePrediction(
                    sequence=sequence,
                    residues=residues,
                    mean_plddt=mean_plddt,
                    backend=backend.name,
                    pdb_text=pdb_text,
                )
                structural = gate_prediction(
                    prediction,
                    plddt_gate=float(gate["plddt_gate"]),
                    hbond_max=float(gate["triad_hbond_max_angstrom"]),
                )
                required_method = str(gate["required_triad_method"])
                full_pass = bool(
                    structural["structural_gate_pass"]
                    and structural.get("triad", {}).get("method") == required_method
                )
                pdb_path = pdb_dir / f"{cid}.pdb"
                atomic_write_text(pdb_path, pdb_text)
                row = {
                    **base,
                    **structural,
                    "pdb_sha256": sha256_file(pdb_path),
                    "pdb_path": str(pdb_path),
                    "required_triad_method": required_method,
                    "full_structural_gate_pass": full_pass,
                    "failure_reason": None if full_pass else "structural_gate_failed",
                }
            except Exception as error:
                interruption = report_payload(contract, results, status="infrastructure_interrupted")
                interruption["infrastructure_error"] = {
                    "candidate_id": cid,
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "counted_as_scientific_failure": False,
                }
                atomic_write_json(report_path, interruption)
                raise RuntimeError(
                    f"structural backend interrupted at {cid}; candidate remains unobserved for resume"
                ) from error
        results.append(row)
        completed.add(cid)
        atomic_write_json(report_path, report_payload(contract, results, status="running"))
        print(
            json.dumps(
                {
                    "candidate_id": cid,
                    "pass": row["full_structural_gate_pass"],
                    "completed": len(results),
                }
            ),
            flush=True,
        )

    payload = report_payload(contract, results, status="complete")
    atomic_write_json(report_path, payload)
    print(json.dumps({key: value for key, value in payload.items() if key != "results"}, indent=2))


if __name__ == "__main__":
    main()
