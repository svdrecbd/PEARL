from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from petase_family import compute_family_stats, evaluate_candidate, load_reference_records


def main() -> None:
    args = parse_args()
    reference_records = load_reference_records(Path(args.reference_records))
    family_stats = compute_family_stats(reference_records)
    candidates = load_candidate_sequences(Path(args.candidates))
    evaluations = [
        evaluate_candidate(sequence=sequence, family_stats=family_stats, reference_records=reference_records)
        for sequence in candidates
    ]
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(evaluations, indent=2), encoding="utf-8")
    print(json.dumps({"candidate_count": len(evaluations), "output": str(output_path)}, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate PETase-family candidate sequences")
    parser.add_argument("--candidates", required=True, help="FASTA or JSONL file of candidate sequences")
    parser.add_argument(
        "--reference-records",
        default="data/petase_family/petase_records.jsonl",
        help="Normalized PETase-family records JSONL",
    )
    parser.add_argument("--output", default="reports/candidate_evaluations.json")
    return parser.parse_args()


def load_candidate_sequences(path: Path) -> list[str]:
    if path.suffix.lower() in {".fa", ".fasta", ".faa"}:
        return load_fasta(path)
    return load_jsonl_sequences(path)


def load_fasta(path: Path) -> list[str]:
    sequences: list[str] = []
    current: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current:
                    sequences.append("".join(current))
                    current = []
                continue
            current.append(line.upper())
    if current:
        sequences.append("".join(current))
    return sequences


def load_jsonl_sequences(path: Path) -> list[str]:
    sequences: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            for key in ("sequence", "extracted_sequence", "sample_text"):
                value = record.get(key)
                if isinstance(value, str):
                    candidate = "".join(char for char in value.upper() if char.isalpha())
                    if candidate:
                        sequences.append(candidate)
                        break
    return sequences


if __name__ == "__main__":
    main()
