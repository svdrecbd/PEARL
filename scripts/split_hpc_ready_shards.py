from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    shard_paths = sorted(input_dir.glob(args.glob))
    if not shard_paths:
        raise SystemExit(f"No files matched {args.glob!r} in {input_dir}")

    manifest: dict[str, Any] = {
        "created_at_utc": utc_iso(),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "glob": args.glob,
        "records_per_chunk": args.records_per_chunk,
        "source_file_count": len(shard_paths),
        "sources": [],
        "totals": {
            "records_seen": 0,
            "chunks_written": 0,
        },
    }

    for shard_path in shard_paths:
        source_summary = split_one_shard(
            shard_path=shard_path,
            output_dir=output_dir,
            records_per_chunk=args.records_per_chunk,
        )
        manifest["sources"].append(source_summary)
        manifest["totals"]["records_seen"] += int(source_summary["records_seen"])
        manifest["totals"]["chunks_written"] += int(source_summary["chunks_written"])

    manifest_path = output_dir / "split_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def split_one_shard(
    *,
    shard_path: Path,
    output_dir: Path,
    records_per_chunk: int,
) -> dict[str, Any]:
    records_seen = 0
    chunks_written = 0
    current_chunk_count = 0
    current_handle = None
    current_path: Path | None = None
    chunk_summaries: list[dict[str, Any]] = []

    def start_chunk(chunk_index: int) -> tuple[Any, Path]:
        chunk_name = f"{shard_path.stem}__chunk_{chunk_index:04d}.jsonl"
        path = output_dir / chunk_name
        handle = path.open("w", encoding="utf-8")
        return handle, path

    with shard_path.open("r", encoding="utf-8") as in_handle:
        for raw_line in in_handle:
            if not raw_line.strip():
                continue
            if current_handle is None or current_chunk_count >= records_per_chunk:
                if current_handle is not None:
                    current_handle.close()
                    assert current_path is not None
                    chunk_summaries.append(
                        {
                            "path": str(current_path),
                            "records": current_chunk_count,
                        }
                    )
                chunks_written += 1
                current_chunk_count = 0
                current_handle, current_path = start_chunk(chunks_written)

            current_handle.write(raw_line)
            current_chunk_count += 1
            records_seen += 1

    if current_handle is not None:
        current_handle.close()
        assert current_path is not None
        chunk_summaries.append(
            {
                "path": str(current_path),
                "records": current_chunk_count,
            }
        )

    return {
        "source_path": str(shard_path),
        "records_seen": records_seen,
        "chunks_written": chunks_written,
        "chunks": chunk_summaries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split scheduler-ready hpc_ready shard JSONL files into smaller subshards."
    )
    parser.add_argument("--input-dir", required=True, help="Directory containing hpc_ready shard JSONL files.")
    parser.add_argument("--output-dir", required=True, help="Directory for split chunk JSONL files.")
    parser.add_argument(
        "--glob",
        default="hpc_ready_A_shard_*.jsonl",
        help="Glob for source shard files inside input-dir.",
    )
    parser.add_argument(
        "--records-per-chunk",
        type=int,
        default=2000,
        help="Maximum non-empty JSONL records per output chunk.",
    )
    return parser.parse_args()


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
