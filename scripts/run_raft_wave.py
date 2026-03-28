from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_MAX_SAFE_PARALLEL_JOBS = 12


def resolve_max_safe_parallel_jobs() -> int:
    raw_value = os.environ.get("TINKER_MAX_SAFE_PARALLEL_JOBS", str(DEFAULT_MAX_SAFE_PARALLEL_JOBS))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise SystemExit(f"Invalid TINKER_MAX_SAFE_PARALLEL_JOBS={raw_value!r}; expected an integer") from exc
    if value <= 0:
        raise SystemExit("TINKER_MAX_SAFE_PARALLEL_JOBS must be positive")
    return value


MAX_SAFE_PARALLEL_JOBS = resolve_max_safe_parallel_jobs()
DEFAULT_SHARD_COUNT = min(4, MAX_SAFE_PARALLEL_JOBS)


def main() -> None:
    args = parse_args()
    validate_args(args)
    python_executable = resolve_python_executable()
    launcher = ROOT / "scripts" / "launch_detached_job.py"
    run_ablation = ROOT / "scripts" / "run_ablation.py"

    wave_dir = Path(args.output_dir) / sanitize_name(args.name)
    prompts_dir = wave_dir / "prompts"
    runs_dir = wave_dir / "runs"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    prompt_rows = load_jsonl(Path(args.prompts_path))
    if args.prompt_offset < 0:
        raise SystemExit("--prompt-offset must be non-negative")
    if args.prompt_offset >= len(prompt_rows):
        raise SystemExit(
            f"--prompt-offset={args.prompt_offset} is past the end of {args.prompts_path} "
            f"({len(prompt_rows)} prompts available)"
        )
    if args.prompt_offset + args.total_prompt_count > len(prompt_rows):
        raise SystemExit(
            f"Requested prompt slice [{args.prompt_offset}, {args.prompt_offset + args.total_prompt_count}) "
            f"but only found {len(prompt_rows)} prompts in {args.prompts_path}"
        )

    shuffled = list(prompt_rows)
    random.Random(args.seed).shuffle(shuffled)
    slice_start = args.prompt_offset
    slice_end = args.prompt_offset + args.total_prompt_count
    selected_rows = shuffled[slice_start:slice_end]
    shards = split_rows(selected_rows, args.shard_count)

    launched_jobs: list[dict[str, Any]] = []
    for shard_index, shard_rows in enumerate(shards, start=1):
        shard_name = f"{sanitize_name(args.name)}-shard{shard_index:02d}"
        shard_prompt_path = prompts_dir / f"{shard_name}.jsonl"
        shard_prompt_path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in shard_rows),
            encoding="utf-8",
        )

        metadata_path = ROOT / "reports" / "logs" / f"{shard_name}.json"
        log_path = ROOT / "reports" / "logs" / f"{shard_name}.log"
        command = [
            python_executable,
            str(run_ablation),
            "--name",
            shard_name,
            "--variant",
            args.variant,
            "--model",
            args.model,
            "--prompts-path",
            str(shard_prompt_path),
            "--reference-records-path",
            args.reference_records_path,
            "--output-dir",
            str(runs_dir),
            "--prompt-count",
            str(len(shard_rows)),
            "--candidate-sample-count",
            str(args.candidate_sample_count),
            "--second-stage-top-k",
            str(args.second_stage_top_k),
            "--plddt-gate-threshold",
            str(args.plddt_gate_threshold),
            "--init-state-path",
            args.init_state_path,
            "--eval-only",
            "--capture-candidate-audit",
            "--seed",
            str(args.seed + shard_index),
            "--preserve-order",
        ]
        if args.stage1_only:
            command.extend(["--stage1-only", "--resume"])

        launch_command = [
            sys.executable,
            str(launcher),
            "--job-name",
            shard_name,
            "--cwd",
            str(ROOT),
            "--metadata-path",
            str(metadata_path),
            "--log-path",
            str(log_path),
        ]
        for env_item in build_env_overrides(args):
            launch_command.extend(["--env", env_item])
        launch_command.extend(["--", *command])

        completed = subprocess.run(
            launch_command,
            check=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        launched_jobs.append(json.loads(completed.stdout))

    wave_metadata = {
        "name": args.name,
        "init_state_path": args.init_state_path,
        "model": args.model,
        "variant": args.variant,
        "prompts_path": args.prompts_path,
        "reference_records_path": args.reference_records_path,
        "total_prompt_count": args.total_prompt_count,
        "prompt_offset": args.prompt_offset,
        "shard_count": args.shard_count,
        "candidate_sample_count": args.candidate_sample_count,
        "second_stage_top_k": args.second_stage_top_k,
        "plddt_gate_threshold": args.plddt_gate_threshold,
        "temperature": args.temperature,
        "stage1_only": args.stage1_only,
        "seed": args.seed,
        "jobs": launched_jobs,
        "prompts_dir": str(prompts_dir),
        "runs_dir": str(runs_dir),
    }
    wave_metadata_path = wave_dir / "wave_metadata.json"
    wave_metadata_path.write_text(json.dumps(wave_metadata, indent=2), encoding="utf-8")
    print(json.dumps(wave_metadata, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch a detached RAFT / Expert Iteration mining wave")
    parser.add_argument("--name", required=True)
    parser.add_argument("--init-state-path", required=True)
    parser.add_argument(
        "--prompts-path",
        default=str(ROOT / "data" / "petase_family_expanded" / "train_prompts_relevance_ge10.jsonl"),
    )
    parser.add_argument(
        "--reference-records-path",
        default=str(ROOT / "data" / "petase_family_expanded" / "petase_records.jsonl"),
    )
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "raft"))
    parser.add_argument("--model", default="moonshotai/Kimi-K2.5")
    parser.add_argument(
        "--variant",
        choices=("baseline", "motif_prior_v1", "motif_prior_soft_v2"),
        default="baseline",
    )
    parser.add_argument("--total-prompt-count", type=int, default=200)
    parser.add_argument("--prompt-offset", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=DEFAULT_SHARD_COUNT)
    parser.add_argument("--candidate-sample-count", type=int, default=256)
    parser.add_argument("--second-stage-top-k", type=int, default=16)
    parser.add_argument("--plddt-gate-threshold", type=float, default=85.0)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--esm2-device", default="mps")
    parser.add_argument("--stage1-only", action="store_true")
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument("--api-key")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.shard_count <= 0:
        raise SystemExit("--shard-count must be positive")
    if args.shard_count > MAX_SAFE_PARALLEL_JOBS:
        raise SystemExit(
            f"--shard-count={args.shard_count} exceeds the safety cap of {MAX_SAFE_PARALLEL_JOBS}. "
            "Split into multiple waves instead."
        )


def build_env_overrides(args: argparse.Namespace) -> list[str]:
    api_key = args.api_key or os.environ.get("TINKER_API_KEY")
    if not api_key:
        raise SystemExit("TINKER_API_KEY is required via --api-key or environment")
    return [
        f"TINKER_API_KEY={api_key}",
        f"SAMPLING_TEMPERATURE={args.temperature}",
        f"ESM2_DEVICE={args.esm2_device}",
    ]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def split_rows(rows: list[dict[str, Any]], shard_count: int) -> list[list[dict[str, Any]]]:
    if shard_count <= 0:
        raise SystemExit("--shard-count must be positive")
    base = len(rows) // shard_count
    extra = len(rows) % shard_count
    shards: list[list[dict[str, Any]]] = []
    start = 0
    for index in range(shard_count):
        size = base + (1 if index < extra else 0)
        shards.append(rows[start : start + size])
        start += size
    return [shard for shard in shards if shard]


def resolve_python_executable() -> str:
    explicit = os.environ.get("TINKER_PYTHON_BIN")
    candidates = [
        explicit,
        sys.executable,
        str(ROOT / ".venv" / "bin" / "python"),
        shutil.which("python"),
        shutil.which("python3"),
        "/opt/anaconda3/bin/python",
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if not Path(candidate).exists():
            continue
        probe = subprocess.run(
            [candidate, "-c", "import tinker"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode == 0:
            return candidate
    raise RuntimeError(
        "Could not find a Python interpreter with the tinker package installed. "
        "Set TINKER_PYTHON_BIN to a working interpreter."
    )


def sanitize_name(value: str) -> str:
    chars = []
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("-")
    sanitized = "".join(chars).strip("-")
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized or "raft-wave"


if __name__ == "__main__":
    main()
