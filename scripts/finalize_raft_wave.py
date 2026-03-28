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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize a stage1-only RAFT wave by rescoring each shard run")
    parser.add_argument("--wave-dir", required=True)
    parser.add_argument("--esm2-device", default="cuda")
    parser.add_argument("--skip-finalized", action="store_true", default=True)
    parser.add_argument("--no-skip-finalized", action="store_false", dest="skip_finalized")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    wave_dir = Path(args.wave_dir).expanduser().resolve()
    wave_metadata_path = wave_dir / "wave_metadata.json"
    if not wave_metadata_path.exists():
        raise SystemExit(f"Missing wave_metadata.json in {wave_dir}")

    wave_metadata = json.loads(wave_metadata_path.read_text(encoding="utf-8"))
    runs_dir = resolve_runs_dir(wave_dir=wave_dir, wave_metadata=wave_metadata)
    if not runs_dir.exists():
        raise SystemExit(f"Missing runs directory: {runs_dir}")

    run_dirs = sorted(path for path in runs_dir.iterdir() if path.is_dir())
    results: list[dict[str, Any]] = []
    for run_dir in run_dirs:
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
    summary_path = wave_dir / "finalization_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def resolve_runs_dir(*, wave_dir: Path, wave_metadata: dict[str, Any]) -> Path:
    metadata_runs_dir = wave_metadata.get("runs_dir")
    if metadata_runs_dir:
        candidate = Path(str(metadata_runs_dir)).expanduser()
        if candidate.exists():
            return candidate.resolve()
        # Cross-machine syncs preserve the original absolute path in wave_metadata.
        # Fall back to the colocated wave directory when the recorded path is stale.
    return (wave_dir / "runs").resolve()


def build_summary(
    *,
    wave_dir: Path,
    wave_metadata: dict[str, Any],
    runs_dir: Path,
    results: list[dict[str, Any]],
    esm2_device: str,
) -> dict[str, Any]:
    finalized = [result for result in results if result.get("status") == "finalized"]
    skipped = [result for result in results if result.get("status") == "skipped"]
    average_rewards = [float(result.get("average_reward") or 0.0) for result in finalized]
    functional_bridge_step_count = sum(len(result.get("functional_bridge_steps") or []) for result in finalized)
    family_faithful_bridge_step_count = sum(
        len(result.get("family_faithful_bridge_steps") or []) for result in finalized
    )
    return {
        "wave_dir": str(wave_dir),
        "runs_dir": str(runs_dir),
        "name": wave_metadata.get("name"),
        "init_state_path": wave_metadata.get("init_state_path"),
        "model": wave_metadata.get("model"),
        "variant": wave_metadata.get("variant", "baseline"),
        "stage1_only": bool(wave_metadata.get("stage1_only")),
        "esm2_device": esm2_device,
        "run_count": len(results),
        "finalized_run_count": len(finalized),
        "skipped_run_count": len(skipped),
        "mean_average_reward": sum(average_rewards) / len(average_rewards) if average_rewards else 0.0,
        "functional_bridge_step_count": functional_bridge_step_count,
        "family_faithful_bridge_step_count": family_faithful_bridge_step_count,
        "results": results,
    }


if __name__ == "__main__":
    main()
