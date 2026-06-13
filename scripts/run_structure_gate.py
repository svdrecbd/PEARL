#!/usr/bin/env python3
"""Automated structural gate: fold candidate sequences and score the real catalytic-triad
geometry, so manual ColabFold is only spent on survivors (or retired for screening).

Runs between the cheap sequence screens and ColabFold. For each sequence it folds (ESMFold
locally or via the ESMAtlas API), reads mean pLDDT, measures the side-chain Ser-His-Asp
H-bond distances, and emits a pass/fail.

Examples:
    # single sequence, ESMAtlas API (no local weights)
    python scripts/run_structure_gate.py --backend esmatlas --sequence MAVM...CPF

    # a candidate set, local ESMFold
    python scripts/run_structure_gate.py --backend esmfold \
        --input reports/ablations/<run>/report.json \
        --output reports/structure_gate/<run>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pearl.structure_gate import (  # noqa: E402
    STRUCTURE_PLDDT_GATE,
    TRIAD_HBOND_MAX_ANGSTROM,
    fold_and_gate,
    get_backend,
)

SEQUENCE_KEYS = ("extracted_sequence", "sequence", "sampled_sequence")


def _seq_from(record: dict) -> str | None:
    for key in SEQUENCE_KEYS:
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def extract_sequences(payload: object, *, selected_only: bool = False) -> list[tuple[str, str]]:
    """Return (label, sequence) pairs from a report.json, candidate_audit, or sequences jsonl rows.

    With ``selected_only`` (candidate_audit only), fold just the shortlist: candidates marked
    ``selected`` or ``is_trainable`` — i.e. the survivors that would otherwise reach ColabFold.
    """
    pairs: list[tuple[str, str]] = []

    # report.json: records[] are the per-step selected outputs (already the shortlist).
    if isinstance(payload, dict) and "records" in payload:
        for record in payload["records"]:
            sequence = _seq_from(record)
            if sequence:
                pairs.append((f"step{record.get('step', len(pairs))}", sequence))
        return pairs

    if isinstance(payload, list):
        # candidate_audit.json: list of {step, candidates: [...]} step records.
        if payload and isinstance(payload[0], dict) and "candidates" in payload[0]:
            for record in payload:
                step = record.get("step", "?")
                for index, candidate in enumerate(record.get("candidates", [])):
                    if selected_only and not (candidate.get("selected") or candidate.get("is_trainable")):
                        continue
                    sequence = _seq_from(candidate)
                    if sequence:
                        tag = "sel" if candidate.get("selected") else "cand"
                        pairs.append((f"step{step}-{tag}{index}", sequence))
            return pairs
        # plain list of records / sequences
        for index, record in enumerate(payload):
            if isinstance(record, dict):
                sequence = _seq_from(record)
                if sequence:
                    pairs.append((str(record.get("name", index)), sequence))
    return pairs


def load_input(path: Path, *, selected_only: bool = False) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8").strip()
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        return extract_sequences(rows, selected_only=selected_only)
    return extract_sequences(json.loads(text), selected_only=selected_only)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sequence", help="Gate a single inline sequence.")
    parser.add_argument("--input", help="report.json / candidate_audit.json / *.jsonl of candidates.")
    parser.add_argument("--output", help="Write the structural gate report JSON here.")
    parser.add_argument("--backend", default=None, help="esmfold (local) or esmatlas (API).")
    parser.add_argument("--plddt-gate", type=float, default=STRUCTURE_PLDDT_GATE)
    parser.add_argument("--hbond-max", type=float, default=TRIAD_HBOND_MAX_ANGSTROM)
    parser.add_argument("--max-records", type=int, default=0, help="Cap candidates folded (0 = all).")
    parser.add_argument(
        "--selected-only",
        action="store_true",
        help="From a candidate_audit, fold only selected/trainable survivors (the shortlist).",
    )
    args = parser.parse_args()

    backend = get_backend(args.backend)

    if args.sequence:
        targets = [("inline", args.sequence)]
    elif args.input:
        targets = load_input(Path(args.input), selected_only=args.selected_only)
    else:
        parser.error("provide --sequence or --input")

    if args.max_records and len(targets) > args.max_records:
        targets = targets[: args.max_records]

    print(f"Folding {len(targets)} candidate(s) with backend={backend.name} ...", flush=True)
    results = []
    for label, sequence in targets:
        try:
            gate = fold_and_gate(
                sequence,
                backend=backend,
                plddt_gate=args.plddt_gate,
                hbond_max=args.hbond_max,
            )
            gate["label"] = label
        except Exception as error:  # folding/network failures should not abort the batch
            gate = {"label": label, "error": f"{type(error).__name__}: {error}", "structural_gate_pass": False}
        results.append(gate)
        triad = gate.get("triad", {})
        print(
            f"  {label:<16} plddt={gate.get('mean_plddt')!s:<7} "
            f"S-H={triad.get('ser_his_distance')!s:<6} H-D={triad.get('his_asp_distance')!s:<6} "
            f"triad={triad.get('passes')} gate={gate.get('structural_gate_pass')}"
            + (f"  ERROR {gate['error']}" if "error" in gate else ""),
            flush=True,
        )

    passed = sum(1 for r in results if r.get("structural_gate_pass"))
    summary = {
        "backend": backend.name,
        "plddt_gate": args.plddt_gate,
        "triad_hbond_max": args.hbond_max,
        "candidate_count": len(results),
        "structural_gate_passes": passed,
        "results": results,
    }
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Wrote {output_path}")
    print(f"Structural gate: {passed}/{len(results)} passed.")


if __name__ == "__main__":
    main()
