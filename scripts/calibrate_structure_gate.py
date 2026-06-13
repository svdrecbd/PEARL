#!/usr/bin/env python3
"""Calibrate the structural gate against natural PETase/cutinase folds.

Folds a sample of natural references, measures mean pLDDT and the side-chain catalytic-triad
H-bond distances, and writes ``configs/structure_gate_calibration.<folder>.json`` (the sorted
distributions). The gate then reports a graded ``structural_score`` in [0,1] — how a candidate
fold compares to real enzymes — alongside the boolean pass/fail.

Folding is expensive, so default sample size is small; expand on a GPU/M4 Pro with the local
``esmfold`` backend for a tighter distribution.

Usage:
    python scripts/calibrate_structure_gate.py --backend esmatlas --max-records 20
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pearl.structure_gate import _calibration_key, fold_and_gate, get_backend  # noqa: E402

MIN_LENGTH = 60


def load_natural_sequences(records_path: Path) -> list[str]:
    sequences: list[str] = []
    with records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            sequence = json.loads(line).get("sequence")
            if isinstance(sequence, str) and len(sequence) >= MIN_LENGTH:
                sequences.append(sequence.upper())
    return sequences


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    return sorted_values[int(round((len(sorted_values) - 1) * q))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--records", default=str(ROOT / "data" / "petase_family_expanded" / "petase_records.jsonl"))
    parser.add_argument("--backend", default="esmatlas", help="esmfold (local) or esmatlas (API).")
    parser.add_argument("--max-records", type=int, default=20, help="Natural sequences to fold (folding is costly).")
    parser.add_argument("--retries", type=int, default=2, help="Retries per sequence on transient fold failures.")
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    backend = get_backend(args.backend)
    sequences = sorted(set(load_natural_sequences(Path(args.records))))
    if not sequences:
        raise SystemExit(f"No sequences in {args.records}")
    rng = random.Random(args.seed)
    if len(sequences) > args.max_records:
        sequences = rng.sample(sequences, args.max_records)

    print(f"Folding {len(sequences)} natural sequences with backend={backend.name} ...", flush=True)
    plddt: list[float] = []
    ser_his: list[float] = []
    his_asp: list[float] = []
    folded = 0
    import time

    for index, sequence in enumerate(sequences):
        gate = None
        for attempt in range(args.retries + 1):
            try:
                gate = fold_and_gate(sequence, backend=backend)
                break
            except Exception as error:
                last = attempt == args.retries
                print(
                    f"  [{index}] fold attempt {attempt + 1} failed: {type(error).__name__}: {error}"
                    + ("" if last else " (retrying)"),
                    flush=True,
                )
                if not last:
                    time.sleep(3.0)
        if gate is None:
            continue
        folded += 1
        plddt.append(float(gate["mean_plddt"]))
        triad = gate.get("triad", {})
        if triad.get("method") == "sidechain":
            if triad.get("ser_his_distance") is not None:
                ser_his.append(float(triad["ser_his_distance"]))
            if triad.get("his_asp_distance") is not None:
                his_asp.append(float(triad["his_asp_distance"]))
        print(
            f"  [{index}] plddt={gate['mean_plddt']} ser_his={triad.get('ser_his_distance')} "
            f"his_asp={triad.get('his_asp_distance')}",
            flush=True,
        )

    if not plddt:
        raise SystemExit("No sequences folded successfully; nothing to calibrate.")

    plddt.sort(); ser_his.sort(); his_asp.sort()
    payload = {
        "backend": _calibration_key(backend.name),
        "records_path": args.records,
        "count": folded,
        "plddt_mean": round(statistics.fmean(plddt), 3),
        "plddt_p05": percentile(plddt, 0.05),
        "plddt_median": percentile(plddt, 0.5),
        "ser_his_median": percentile(ser_his, 0.5) if ser_his else None,
        "his_asp_median": percentile(his_asp, 0.5) if his_asp else None,
        "plddt": plddt,
        "ser_his": ser_his,
        "his_asp": his_asp,
    }
    output = Path(args.output) if args.output else (ROOT / "configs" / f"structure_gate_calibration.{_calibration_key(backend.name)}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {output}")
    for key in ("count", "plddt_mean", "plddt_p05", "plddt_median", "ser_his_median", "his_asp_median"):
        print(f"  {key:>14}: {payload[key]}")


if __name__ == "__main__":
    main()
