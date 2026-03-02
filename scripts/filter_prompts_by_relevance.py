from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def main() -> None:
    args = parse_args()
    rows = load_jsonl(Path(args.input_path))
    kept = [row for row in rows if int(row.get("relevance_score", 0)) >= args.min_relevance]
    write_jsonl(Path(args.output_path), kept)

    removed = [row for row in rows if int(row.get("relevance_score", 0)) < args.min_relevance]
    removed_names = Counter(str(row.get("protein_name") or "unknown") for row in removed)
    summary = {
        "input_path": args.input_path,
        "output_path": args.output_path,
        "min_relevance": args.min_relevance,
        "input_count": len(rows),
        "kept_count": len(kept),
        "removed_count": len(removed),
        "kept_fraction": round(len(kept) / len(rows), 4) if rows else 0.0,
        "removed_top_protein_names": removed_names.most_common(10),
    }
    if args.summary_path:
        Path(args.summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Filter prompt JSONL rows by relevance_score")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--min-relevance", type=int, default=10)
    parser.add_argument("--summary-path")
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


if __name__ == "__main__":
    main()
