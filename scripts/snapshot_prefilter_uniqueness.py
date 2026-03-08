from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, TextIO


def main() -> None:
    args = parse_args()
    baseline_files = resolve_input_files(args.baseline)
    current_files = resolve_input_files(args.current)

    baseline = collect_snapshot(files=baseline_files, id_field=args.id_field, sequence_field=args.sequence_field)
    current = collect_snapshot(files=current_files, id_field=args.id_field, sequence_field=args.sequence_field)
    comparison = compare_snapshots(baseline=baseline, current=current)

    payload = {
        "baseline": baseline.to_dict(),
        "current": current.to_dict(),
        "comparison": comparison,
    }
    if args.output_json:
        out_path = Path(args.output_json).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(payload, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare prefilter snapshots by unique candidate IDs and overlap."
    )
    parser.add_argument("--baseline", nargs="+", required=True, help="Baseline files or directories.")
    parser.add_argument("--current", nargs="+", required=True, help="Current files or directories.")
    parser.add_argument("--id-field", default="candidate_id")
    parser.add_argument("--sequence-field", default="sequence")
    parser.add_argument("--output-json", default=None)
    return parser.parse_args()


@dataclass
class SnapshotStats:
    file_count: int
    line_count: int
    json_object_count: int
    id_count: int
    id_set: set[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_count": self.file_count,
            "line_count": self.line_count,
            "json_object_count": self.json_object_count,
            "id_count": self.id_count,
        }


def collect_snapshot(*, files: list[Path], id_field: str, sequence_field: str) -> SnapshotStats:
    ids: set[str] = set()
    line_count = 0
    json_object_count = 0
    for file_path in files:
        for line in iter_lines(file_path):
            line_count += 1
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            json_object_count += 1
            raw_id = str(payload.get(id_field) or "").strip()
            if raw_id:
                ids.add(raw_id)
                continue
            sequence = str(payload.get(sequence_field) or "")
            sequence = normalize_sequence(sequence)
            if sequence:
                ids.add(f"sha1:{hashlib.sha1(sequence.encode('utf-8')).hexdigest()}")
    return SnapshotStats(
        file_count=len(files),
        line_count=line_count,
        json_object_count=json_object_count,
        id_count=len(ids),
        id_set=ids,
    )


def compare_snapshots(*, baseline: SnapshotStats, current: SnapshotStats) -> dict[str, Any]:
    intersection = baseline.id_set.intersection(current.id_set)
    baseline_only = baseline.id_set - current.id_set
    current_only = current.id_set - baseline.id_set
    union = baseline.id_set.union(current.id_set)
    jaccard = (len(intersection) / len(union)) if union else 1.0
    novelty_rate = (len(current_only) / len(current.id_set)) if current.id_set else 0.0

    return {
        "intersection_count": len(intersection),
        "baseline_only_count": len(baseline_only),
        "current_only_count": len(current_only),
        "union_count": len(union),
        "jaccard_overlap": round(jaccard, 6),
        "current_novelty_rate": round(novelty_rate, 6),
    }


def resolve_input_files(inputs: Iterable[str]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for raw in inputs:
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"Input does not exist: {path}")
        candidates: list[Path]
        if path.is_file():
            candidates = [path]
        else:
            candidates = sorted(path.rglob("*.jsonl")) + sorted(path.rglob("*.jsonl.gz"))
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            resolved.append(candidate)
    if not resolved:
        raise SystemExit("No JSONL files found")
    return resolved


def iter_lines(path: Path) -> Iterator[str]:
    with open_text(path, "r") as handle:
        for line in handle:
            yield line


def open_text(path: Path, mode: str) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, f"{mode}t", encoding="utf-8")
    return path.open(mode, encoding="utf-8")


def normalize_sequence(sequence: str) -> str:
    return "".join(sequence.upper().split())


if __name__ == "__main__":
    main()
