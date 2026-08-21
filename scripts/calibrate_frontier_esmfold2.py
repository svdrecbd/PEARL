#!/usr/bin/env python3
"""Run the prospective natural-reference calibration for pinned full ESMFold2."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pearl.esmfold2_contract import (  # noqa: E402
    folding_contract_sha,
    folding_identity,
    sha256_value,
    validate_complete_calibration,
    validate_folding_gate,
)
from pearl.io_utils import atomic_write_json  # noqa: E402
from pearl.structure_gate import (  # noqa: E402
    EsmFold2LocalBackend,
    find_catalytic_triad,
    parse_pdb,
)


DEFAULT_CONFIG = ROOT / "configs/experiments/frontier_adaptation_structural_v2_original.json"
MIN_LENGTH = 60


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def natural_records(path: Path) -> list[dict[str, str]]:
    unique: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        sequence = str(row.get("sequence") or "").upper()
        if len(sequence) >= MIN_LENGTH:
            unique.setdefault(sequence, str(row.get("accession") or "unknown"))
    return [
        {"accession": unique[sequence], "sequence": sequence}
        for sequence in sorted(unique)
    ]


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config_path = repo_path(args.config)
    config = read_json(config_path)
    gate = config["structure_gate"]
    validate_folding_gate(gate, read_json(repo_path(gate["runtime_lock"])))
    pending = read_json(repo_path(gate["calibration"]))
    if gate.get("backend") != "esmfold2" or pending.get("status") != "pending":
        raise RuntimeError("calibration requires the prospective pending ESMFold2 contract")
    records_path = repo_path(pending["records_path"])
    records = natural_records(records_path)
    expected_count = int(pending["expected_count"])
    rng = random.Random(int(pending["selection_seed"]))
    selected = rng.sample(records, expected_count)
    selected_identity = [
        {
            "accession": row["accession"],
            "sequence_sha256": hashlib.sha256(row["sequence"].encode()).hexdigest(),
        }
        for row in selected
    ]
    calibration_contract = {
        "contract": pending["contract"],
        "backend": "esmfold2",
        "structural_config_sha256": sha256_file(config_path),
        "records_path": pending["records_path"],
        "records_sha256": sha256_file(records_path),
        "selection_seed": int(pending["selection_seed"]),
        "expected_count": expected_count,
        "selected": selected_identity,
        "folding_identity": folding_identity(gate),
        "folding_contract_sha": folding_contract_sha(gate),
        "plddt_gate": float(gate["plddt_gate"]),
        "triad_hbond_max_angstrom": float(gate["triad_hbond_max_angstrom"]),
        "acceptance": pending["acceptance"],
    }
    calibration_contract["calibration_contract_sha"] = sha256_value(calibration_contract)
    output = Path(args.output)
    results: list[dict[str, Any]] = []
    if output.exists():
        prior = read_json(output)
        if prior.get("calibration_contract") != calibration_contract:
            raise RuntimeError("existing calibration output belongs to another contract")
        results = list(prior.get("results", []))
    completed = {str(row["sequence_sha256"]) for row in results}
    inference = gate["inference"]
    backend = EsmFold2LocalBackend(
        model_name=gate["model_name"],
        model_revision=gate["model_revision"],
        esmc_model_name=gate["esmc_model_name"],
        esmc_model_revision=gate["esmc_model_revision"],
        num_loops=inference["num_loops"],
        num_sampling_steps=inference["num_sampling_steps"],
        num_diffusion_samples=inference["num_diffusion_samples"],
        inference_seed=inference["inference_seed"],
        esmc_precision=inference["esmc_precision"],
        kernel_backend=inference["kernel_backend"],
        chunk_size=inference["chunk_size"],
    )
    load_started = time.perf_counter()
    backend._load()
    model_load_seconds = time.perf_counter() - load_started
    for row, identity in zip(selected, selected_identity, strict=True):
        if identity["sequence_sha256"] in completed:
            continue
        started = time.perf_counter()
        try:
            pdb = backend.fold(row["sequence"])
            duration = time.perf_counter() - started
            residues, mean_plddt = parse_pdb(pdb)
            triad = find_catalytic_triad(
                row["sequence"], residues, hbond_max=float(gate["triad_hbond_max_angstrom"])
            )
            result = {
                **identity,
                "sequence_length": len(row["sequence"]),
                "mean_plddt": mean_plddt,
                "triad": triad.as_dict(),
                "fold_seconds": duration,
            }
        except Exception as error:
            atomic_write_json(
                output,
                {
                    "status": "infrastructure_interrupted",
                    "calibration_contract": calibration_contract,
                    "results": results,
                    "error": {
                        "sequence_sha256": identity["sequence_sha256"],
                        "type": type(error).__name__,
                        "message": str(error),
                    },
                },
            )
            raise
        results.append(result)
        completed.add(identity["sequence_sha256"])
        atomic_write_json(
            output,
            {
                "status": "running",
                "calibration_contract": calibration_contract,
                "results": results,
            },
        )
    plddt = sorted(float(row["mean_plddt"]) for row in results)
    sidechain = [row["triad"] for row in results if row["triad"]["method"] == "sidechain"]
    ser_his = sorted(float(row["ser_his_distance"]) for row in sidechain)
    his_asp = sorted(float(row["his_asp_distance"]) for row in sidechain)
    latencies = [float(row["fold_seconds"]) for row in results]
    payload = {
        "contract": pending["contract"],
        "status": "complete",
        "backend": "esmfold2",
        "records_path": pending["records_path"],
        "records_sha256": sha256_file(records_path),
        "selection_seed": int(pending["selection_seed"]),
        "expected_count": expected_count,
        "count": len(results),
        "folding_identity": folding_identity(gate),
        "folding_contract_sha": folding_contract_sha(gate),
        "calibration_contract": calibration_contract,
        "acceptance": pending["acceptance"],
        "plddt": plddt,
        "ser_his": ser_his,
        "his_asp": his_asp,
        "plddt_mean": statistics.fmean(plddt),
        "plddt_p05": percentile(plddt, 0.05),
        "plddt_median": statistics.median(plddt),
        "model_load_seconds": model_load_seconds,
        "fold_seconds_mean": statistics.fmean(latencies),
        "fold_seconds_p95": percentile(latencies, 0.95),
        "results": results,
    }
    validate_complete_calibration(payload, gate)
    atomic_write_json(output, payload)
    print(json.dumps({key: value for key, value in payload.items() if key not in {"results", "plddt", "ser_his", "his_asp"}}, indent=2))


if __name__ == "__main__":
    main()
