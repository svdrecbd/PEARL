#!/usr/bin/env python3
"""Calibrate the ESM-2 pseudo-log-likelihood (PLL) proxy against the natural reference set.

Scores natural PETase/cutinase records with the configured ESM model and writes
`configs/esm_pll_calibration.<model>.json` (mean, std, and the sorted PLL distribution).
The proxy uses this to map a candidate PLL onto the natural distribution (percentile /
z-score) instead of an uncalibrated sigmoid.

Usage:
    python scripts/calibrate_esm_pll.py \
        --records data/petase_family_expanded/petase_records.jsonl \
        --max-records 1000
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

from pearl.esm_proxy import ESM2_MODEL_NAME, MIN_SEQUENCE_LENGTH, get_esm2_plls  # noqa: E402


def load_sequences(records_path: Path) -> list[str]:
    sequences: list[str] = []
    with records_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            sequence = record.get("sequence")
            if isinstance(sequence, str) and len(sequence) >= MIN_SEQUENCE_LENGTH:
                sequences.append(sequence.upper())
    return sequences


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    index = int(round((len(sorted_values) - 1) * q))
    return sorted_values[index]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", default=str(ROOT / "data" / "petase_family_expanded" / "petase_records.jsonl"))
    parser.add_argument("--max-records", type=int, default=1000, help="Cap on sequences scored (0 = all).")
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--output", default="", help="Override output path (default: configs/esm_pll_calibration.<model>.json).")
    args = parser.parse_args()

    records_path = Path(args.records)
    sequences = load_sequences(records_path)
    if not sequences:
        raise SystemExit(f"No valid sequences found in {records_path}")

    unique = sorted(set(sequences))
    if args.max_records and len(unique) > args.max_records:
        rng = random.Random(args.seed)
        unique = rng.sample(unique, args.max_records)

    print(f"Scoring {len(unique)} natural sequences with {ESM2_MODEL_NAME} ...", flush=True)
    plls = get_esm2_plls(unique)
    plls = [round(float(value), 4) for value in plls if value > -50.0]  # drop UNSCORED sentinels
    if not plls:
        raise SystemExit("All sequences returned UNSCORED; nothing to calibrate.")

    sorted_plls = sorted(plls)
    mean = statistics.fmean(sorted_plls)
    std = statistics.pstdev(sorted_plls) if len(sorted_plls) > 1 else 0.0

    safe_model = ESM2_MODEL_NAME.replace("/", "__")
    output_path = Path(args.output) if args.output else (ROOT / "configs" / f"esm_pll_calibration.{safe_model}.json")
    payload = {
        "model_name": ESM2_MODEL_NAME,
        "records_path": str(records_path),
        "count": len(sorted_plls),
        "mean": round(mean, 6),
        "std": round(std, 6),
        "min": sorted_plls[0],
        "p05": percentile(sorted_plls, 0.05),
        "p25": percentile(sorted_plls, 0.25),
        "median": percentile(sorted_plls, 0.50),
        "p75": percentile(sorted_plls, 0.75),
        "p95": percentile(sorted_plls, 0.95),
        "max": sorted_plls[-1],
        "sorted_plls": sorted_plls,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    print(f"Wrote {output_path}")
    for key in ("count", "mean", "std", "min", "p05", "p25", "median", "p75", "p95", "max"):
        print(f"  {key:>7}: {payload[key]}")


if __name__ == "__main__":
    main()
