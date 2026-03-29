from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.finalize_ablation_from_candidate_audit import finalize_ablation_dir
from scripts.finalize_raft_wave import build_summary, resolve_runs_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize one partition of a stage1-only RAFT wave")
    parser.add_argument("--wave-dir", required=True)
    parser.add_argument("--partition-index", type=int, required=True, help="Zero-based partition index.")
    parser.add_argument("--partition-count", type=int, required=True, help="Total number of partitions.")
    parser.add_argument("--esm2-device", default="cuda")
    parser.add_argument("--skip-finalized", action="store_true", default=True)
    parser.add_argument("--no-skip-finalized", action="store_false", dest="skip_finalized")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.partition_count <= 0:
        raise SystemExit("--partition-count must be positive")
    if args.partition_index < 0 or args.partition_index >= args.partition_count:
        raise SystemExit(
            f"--partition-index must be in [0, {args.partition_count - 1}], got {args.partition_index}"
        )

    wave_dir = Path(args.wave_dir).expanduser().resolve()
    wave_metadata_path = wave_dir / "wave_metadata.json"
    if not wave_metadata_path.exists():
        raise SystemExit(f"Missing wave_metadata.json in {wave_dir}")

    wave_metadata = json.loads(wave_metadata_path.read_text(encoding="utf-8"))
    runs_dir = resolve_runs_dir(wave_dir=wave_dir, wave_metadata=wave_metadata)
    if not runs_dir.exists():
        raise SystemExit(f"Missing runs directory: {runs_dir}")

    run_dirs = sorted(path for path in runs_dir.iterdir() if path.is_dir())
    selected_run_dirs = run_dirs[args.partition_index :: args.partition_count]
    if not selected_run_dirs:
        raise SystemExit(
            f"No run directories selected for partition {args.partition_index}/{args.partition_count} in {runs_dir}"
        )

    print(
        json.dumps(
            {
                "event": "finalize_partition_start",
                "wave_dir": str(wave_dir),
                "runs_dir": str(runs_dir),
                "partition_index": args.partition_index,
                "partition_count": args.partition_count,
                "selected_run_count": len(selected_run_dirs),
                "selected_runs": [run_dir.name for run_dir in selected_run_dirs],
                "esm2_device": args.esm2_device,
            }
        ),
        flush=True,
    )

    results: list[dict[str, Any]] = []
    for run_dir in selected_run_dirs:
        result = finalize_ablation_dir(
            ablation_dir=run_dir,
            esm2_device=args.esm2_device,
            skip_finalized=args.skip_finalized,
        )
        results.append(result)
        print(json.dumps({"event": "finalize_run", **result}), flush=True)

    summary = build_summary(
        wave_dir=wave_dir,
        wave_metadata=wave_metadata,
        runs_dir=runs_dir,
        results=results,
        esm2_device=args.esm2_device,
    )
    summary["partition_index"] = args.partition_index
    summary["partition_count"] = args.partition_count
    summary["selected_run_count"] = len(selected_run_dirs)
    summary["selected_runs"] = [run_dir.name for run_dir in selected_run_dirs]

    summary_path = wave_dir / (
        f"finalization_summary_part{args.partition_index + 1:02d}of{args.partition_count:02d}.json"
    )
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
