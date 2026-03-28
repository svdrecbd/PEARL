from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.run_raft_wave import build_env_overrides, resolve_python_executable, sanitize_name, split_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stop a long-running stage1-only RAFT wave and relaunch the unfinished prompts as more shards"
    )
    parser.add_argument("--wave-dir", required=True)
    parser.add_argument("--target-shard-count", type=int, required=True)
    parser.add_argument("--name-suffix", default="rebal")
    parser.add_argument("--api-key")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-stop-running", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    wave_dir = Path(args.wave_dir).expanduser().resolve()
    wave_metadata_path = wave_dir / "wave_metadata.json"
    if not wave_metadata_path.exists():
        raise SystemExit(f"Missing wave_metadata.json in {wave_dir}")

    wave_metadata = json.loads(wave_metadata_path.read_text(encoding="utf-8"))
    if not bool(wave_metadata.get("stage1_only")):
        raise SystemExit(f"{wave_dir} is not a stage1-only wave")
    if args.target_shard_count <= 0:
        raise SystemExit("--target-shard-count must be positive")

    runs_dir = resolve_runs_dir(wave_dir=wave_dir, wave_metadata=wave_metadata)
    prompts_dir = (wave_dir / "prompts").resolve()
    if not runs_dir.exists():
        raise SystemExit(f"Missing runs dir: {runs_dir}")

    if not args.no_stop_running and not args.dry_run:
        stopped_jobs = stop_active_jobs(wave_metadata=wave_metadata)
    else:
        stopped_jobs = []

    run_states = collect_run_states(runs_dir=runs_dir)
    completed_prompt_count = sum(state["completed_prompt_count"] for state in run_states)
    remaining_rows: list[dict[str, Any]] = []
    for state in run_states:
        remaining_rows.extend(state["remaining_rows"])

    if not remaining_rows:
        payload = {
            "wave_dir": str(wave_dir),
            "status": "nothing_to_rebalance",
            "completed_prompt_count": completed_prompt_count,
            "remaining_prompt_count": 0,
            "stopped_jobs": stopped_jobs,
        }
        print(json.dumps(payload, indent=2))
        return

    prior_rebalances = [record for record in (wave_metadata.get("rebalances") or []) if not record.get("dry_run")]
    round_index = len(prior_rebalances) + 1
    shard_rows = split_rows(remaining_rows, min(args.target_shard_count, len(remaining_rows)))
    python_executable = resolve_python_executable()
    launch_payloads: list[dict[str, Any]] = []
    launch_plan = []
    for shard_index, rows in enumerate(shard_rows, start=1):
        shard_name = f"{sanitize_name(wave_metadata['name'])}-{args.name_suffix}{round_index:02d}-shard{shard_index:02d}"
        prompt_path = prompts_dir / f"{shard_name}.jsonl"
        metadata_path = ROOT / "reports" / "logs" / f"{shard_name}.json"
        log_path = ROOT / "reports" / "logs" / f"{shard_name}.log"
        seed = int(wave_metadata.get("seed") or 0) + 1000 * round_index + shard_index
        launch_plan.append(
            {
                "job_name": shard_name,
                "prompt_path": str(prompt_path),
                "metadata_path": str(metadata_path),
                "log_path": str(log_path),
                "prompt_count": len(rows),
                "seed": seed,
                "rows": rows,
            }
        )

    if not args.dry_run:
        for plan in launch_plan:
            prompt_path = Path(plan["prompt_path"])
            prompt_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in plan["rows"]),
                encoding="utf-8",
            )
            launch_payloads.append(
                launch_job(
                    wave_metadata=wave_metadata,
                    python_executable=python_executable,
                    runs_dir=runs_dir,
                    prompt_path=prompt_path,
                    metadata_path=Path(plan["metadata_path"]),
                    log_path=Path(plan["log_path"]),
                    job_name=str(plan["job_name"]),
                    prompt_count=int(plan["prompt_count"]),
                    seed=int(plan["seed"]),
                    api_key=args.api_key,
                )
            )

    if not args.dry_run:
        rebalance_record = {
            "round": round_index,
            "created_at_epoch": int(time.time()),
            "target_shard_count": int(args.target_shard_count),
            "launched_shard_count": len(shard_rows),
            "completed_prompt_count_before": completed_prompt_count,
            "remaining_prompt_count_before": len(remaining_rows),
            "stopped_jobs": stopped_jobs,
            "source_runs": [
                {
                    "run_dir": state["run_dir"],
                    "prompt_count": state["prompt_count"],
                    "completed_prompt_count": state["completed_prompt_count"],
                    "remaining_prompt_count": len(state["remaining_rows"]),
                }
                for state in run_states
            ],
            "jobs": launch_payloads,
            "dry_run": False,
        }
        wave_metadata.setdefault("rebalances", []).append(rebalance_record)
        wave_metadata["jobs"] = launch_payloads
        wave_metadata["shard_count"] = len(launch_payloads)
        wave_metadata["completed_prompt_count"] = completed_prompt_count
        wave_metadata["remaining_prompt_count"] = len(remaining_rows)
        wave_metadata["runs_dir"] = str(runs_dir)
        wave_metadata_path.write_text(json.dumps(wave_metadata, indent=2), encoding="utf-8")

    payload = {
        "wave_dir": str(wave_dir),
        "status": "rebalanced" if not args.dry_run else "dry_run",
        "completed_prompt_count": completed_prompt_count,
        "remaining_prompt_count": len(remaining_rows),
        "launched_shard_count": len(shard_rows),
        "target_shard_count": args.target_shard_count,
        "stopped_jobs": stopped_jobs,
        "jobs": launch_payloads if not args.dry_run else strip_rows_from_launch_plan(launch_plan),
    }
    print(json.dumps(payload, indent=2))


def resolve_runs_dir(*, wave_dir: Path, wave_metadata: dict[str, Any]) -> Path:
    metadata_runs_dir = wave_metadata.get("runs_dir")
    if metadata_runs_dir:
        candidate = Path(str(metadata_runs_dir)).expanduser()
        if candidate.exists():
            return candidate.resolve()
    return (wave_dir / "runs").resolve()


def collect_run_states(*, runs_dir: Path) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        metadata_path = run_dir / "metadata.json"
        report_path = run_dir / "report.json"
        prompt_subset_path = run_dir / "prompt_subset.jsonl"
        if not (metadata_path.exists() and report_path.exists() and prompt_subset_path.exists()):
            continue

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        prompt_rows = load_jsonl(prompt_subset_path)
        prompt_count = int(metadata.get("prompt_count") or len(prompt_rows))
        if prompt_count != len(prompt_rows):
            raise RuntimeError(
                f"Prompt subset length mismatch in {run_dir}: metadata prompt_count={prompt_count}, rows={len(prompt_rows)}"
            )
        completed_prompt_count = extract_contiguous_step_count(report.get("records"), prompt_count=prompt_count)
        states.append(
            {
                "run_dir": str(run_dir),
                "name": str(metadata.get("name") or run_dir.name),
                "metadata": metadata,
                "prompt_count": prompt_count,
                "completed_prompt_count": completed_prompt_count,
                "remaining_rows": prompt_rows[completed_prompt_count:],
            }
        )
    return states


def extract_contiguous_step_count(raw_records: Any, *, prompt_count: int) -> int:
    if not isinstance(raw_records, list):
        return 0
    by_step: dict[int, dict[str, Any]] = {}
    for record in raw_records:
        if not isinstance(record, dict):
            continue
        try:
            step = int(record.get("step"))
        except (TypeError, ValueError):
            continue
        if 0 <= step < prompt_count:
            by_step[step] = record

    count = 0
    for step in range(prompt_count):
        if step not in by_step:
            break
        count += 1
    return count


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def stop_active_jobs(*, wave_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    stop_script = ROOT / "scripts" / "stop_detached_job.py"
    stopped_jobs: list[dict[str, Any]] = []
    for job in wave_metadata.get("jobs") or []:
        metadata_path = ROOT / "reports" / "logs" / f"{job['job_name']}.json"
        if not metadata_path.exists():
            continue
        completed = subprocess.run(
            [sys.executable, str(stop_script), "--metadata-path", str(metadata_path)],
            check=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        stopped_jobs.append(json.loads(completed.stdout))
    return stopped_jobs


def launch_job(
    *,
    wave_metadata: dict[str, Any],
    python_executable: str,
    runs_dir: Path,
    prompt_path: Path,
    metadata_path: Path,
    log_path: Path,
    job_name: str,
    prompt_count: int,
    seed: int,
    api_key: str | None,
) -> dict[str, Any]:
    launcher = ROOT / "scripts" / "launch_detached_job.py"
    run_ablation = ROOT / "scripts" / "run_ablation.py"

    command = [
        python_executable,
        str(run_ablation),
        "--name",
        job_name,
        "--variant",
        str(wave_metadata["variant"]),
        "--model",
        str(wave_metadata["model"]),
        "--prompts-path",
        str(prompt_path),
        "--reference-records-path",
        str(wave_metadata["reference_records_path"]),
        "--output-dir",
        str(runs_dir),
        "--prompt-count",
        str(prompt_count),
        "--candidate-sample-count",
        str(int(wave_metadata["candidate_sample_count"])),
        "--second-stage-top-k",
        str(int(wave_metadata["second_stage_top_k"])),
        "--plddt-gate-threshold",
        str(float(wave_metadata["plddt_gate_threshold"])),
        "--init-state-path",
        str(wave_metadata["init_state_path"]),
        "--eval-only",
        "--capture-candidate-audit",
        "--seed",
        str(seed),
        "--preserve-order",
        "--stage1-only",
    ]

    launch_command = [
        sys.executable,
        str(launcher),
        "--job-name",
        job_name,
        "--cwd",
        str(ROOT),
        "--metadata-path",
        str(metadata_path),
        "--log-path",
        str(log_path),
    ]
    cli_args = argparse.Namespace(
        api_key=api_key,
        temperature=float(wave_metadata["temperature"]),
        esm2_device="mps",
    )
    for env_item in build_env_overrides(cli_args):
        launch_command.extend(["--env", env_item])
    launch_command.extend(["--", *command])

    completed = subprocess.run(
        launch_command,
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)

def strip_rows_from_launch_plan(launch_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped: list[dict[str, Any]] = []
    for item in launch_plan:
        stripped.append({key: value for key, value in item.items() if key != "rows"})
    return stripped


if __name__ == "__main__":
    main()
