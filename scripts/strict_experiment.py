#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT_PATH = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT_PATH / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.paths import (
    LOGS_DIR,
    REPO_ROOT,
    detached_log_path,
    detached_metadata_path,
    resolve_repo_path,
    robustness_summary_path,
    warmstart_summary_path,
)
from pearl.watchers import wait_for_path, wait_for_path_or_abort


ROOT = REPO_ROOT
LOG_DIR = LOGS_DIR
DEFAULT_CPU_PYTHON = Path.home() / "venvs" / "pearl-stage1-cpu" / "bin" / "python"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Config-driven strict experiment launcher and watcher")
    parser.add_argument("--config", required=True, help="Experiment config JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    describe = subparsers.add_parser("describe", help="Print resolved experiment metadata")
    describe.add_argument("--pretty", action="store_true")

    launch_stage = subparsers.add_parser("launch-stage", help="Launch a train stage")
    launch_stage.add_argument("--stage", choices=["stage-a", "stage-b-lite"], required=True)
    launch_stage.add_argument("--init-state-path")
    launch_stage.add_argument("--dry-run", action="store_true")

    build_datasets = subparsers.add_parser("build-datasets", help="Build stage-A and stage-B datasets")
    build_datasets.add_argument("--old-repeat", type=int)
    build_datasets.add_argument("--new-repeat", type=int)
    build_datasets.add_argument("--pure-repeat", type=int)
    build_datasets.add_argument("--anchor-count", type=int)
    build_datasets.add_argument("--new-top-k", type=int)
    build_datasets.add_argument("--repair-top-k", type=int)
    build_datasets.add_argument("--repair-repeat", type=int)
    build_datasets.add_argument("--strict-selection-mode", choices=["rank", "prompt_cluster", "bucket_cap"])
    build_datasets.add_argument("--repair-selection-mode", choices=["rank", "prompt_cluster", "source_cluster", "bucket_cap"])
    build_datasets.add_argument("--anchor-selection-mode", choices=["rank", "prompt_cluster"])
    build_datasets.add_argument("--strict-max-per-prompt-bucket", type=int)
    build_datasets.add_argument("--strict-max-per-cluster", type=int)
    build_datasets.add_argument("--repair-max-per-prompt-bucket", type=int)
    build_datasets.add_argument("--repair-max-per-source-run", type=int)
    build_datasets.add_argument("--repair-max-per-cluster", type=int)
    build_datasets.add_argument("--dry-run", action="store_true")

    launch_smoke = subparsers.add_parser("launch-smoke", help="Launch the smoke robustness run")
    launch_smoke.add_argument("--esm2-device")
    launch_smoke.add_argument("--dry-run", action="store_true")

    launch_robustness = subparsers.add_parser("launch-robustness", help="Launch the full robustness run")
    launch_robustness.add_argument("--init-state-path")
    launch_robustness.add_argument("--checkpoint-summary-path")
    launch_robustness.add_argument("--run-name")
    launch_robustness.add_argument("--esm2-device")
    launch_robustness.add_argument("--dry-run", action="store_true")

    watch_smoke = subparsers.add_parser("watch-smoke-after-stage", help="Wait for stage-A summary then launch smoke")
    watch_smoke.add_argument("--dry-run", action="store_true")

    watch_stageb = subparsers.add_parser("watch-stageb-after-smoke", help="Wait for smoke gate then launch stage-B-lite")
    watch_stageb.add_argument("--dry-run", action="store_true")

    watch_robustness = subparsers.add_parser(
        "watch-robustness-after-stageb",
        help="Wait for stage-B summary then launch full robustness",
    )
    watch_robustness.add_argument("--dry-run", action="store_true")

    launch_chain = subparsers.add_parser("launch-chain", help="Launch stage-A plus detached smoke/stageB/robustness watchers")
    launch_chain.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_config(path: str) -> dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["_config_path"] = str(config_path)
    return payload


def resolve_path(value: str | None) -> Path | None:
    if value is None:
        return None
    resolved = resolve_repo_path(value)
    if resolved is None or resolved.startswith("tinker://"):
        return None
    return Path(resolved)


def resolve_value(value: str | None) -> str | None:
    return resolve_repo_path(value)


def python_bin() -> str:
    env = os.environ.get("TINKER_PYTHON_BIN")
    if env:
        return env
    if DEFAULT_CPU_PYTHON.exists():
        return str(DEFAULT_CPU_PYTHON)
    return sys.executable


def require_api_key() -> str:
    api_key = os.environ.get("TINKER_API_KEY")
    if not api_key:
        raise SystemExit("TINKER_API_KEY is not set")
    return api_key


def stage_config(config: dict[str, Any], stage: str) -> dict[str, Any]:
    stages = config.get("stages") or {}
    if stage not in stages:
        raise SystemExit(f"Config {config['_config_path']} is missing stage '{stage}'")
    return dict(stages[stage])


def build_config(config: dict[str, Any]) -> dict[str, Any]:
    payload = config.get("build")
    if not payload:
        raise SystemExit(f"Config {config['_config_path']} is missing a build section")
    return dict(payload)


def smoke_decision_path(config: dict[str, Any]) -> Path:
    smoke_run_name = str((config.get("smoke") or {})["run_name"])
    return robustness_summary_path(smoke_run_name).parent / "smoke_gate_decision.json"


def checkpoint_from_summary(summary_path: Path) -> str:
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    checkpoint_path = payload.get("checkpoint_path")
    if not checkpoint_path:
        raise SystemExit(f"checkpoint_path missing from {summary_path}")
    return str(checkpoint_path)


def stage_init_state(config: dict[str, Any], stage: str) -> str:
    stage_payload = stage_config(config, stage)
    explicit = stage_payload.get("init_state_path")
    if explicit:
        return str(explicit)

    explicit_summary = stage_payload.get("init_state_summary_path")
    if explicit_summary:
        return checkpoint_from_summary(Path(resolve_value(str(explicit_summary))))

    init_from_stage = stage_payload.get("init_from_stage")
    if init_from_stage:
        summary = warmstart_summary_path(stage_config(config, init_from_stage)["run_name"])
        if not summary.exists():
            raise SystemExit(f"Checkpoint summary is missing: {summary}")
        return checkpoint_from_summary(summary)

    base = config.get("base_init_state_path")
    if base:
        return str(base)

    raise SystemExit(f"No init state configured for stage '{stage}' in {config['_config_path']}")


def env_override(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value


def smoke_init_state(config: dict[str, Any]) -> str:
    smoke = config.get("smoke") or {}
    init_from_stage = str(smoke.get("init_from_stage") or "stage-a")
    summary = warmstart_summary_path(stage_config(config, init_from_stage)["run_name"])
    if not summary.exists():
        raise SystemExit(f"Checkpoint summary is missing: {summary}")
    return checkpoint_from_summary(summary)


def robustness_init_state(
    config: dict[str, Any],
    *,
    explicit_init_state: str | None = None,
    explicit_checkpoint_summary_path: str | None = None,
) -> str:
    if explicit_init_state:
        return explicit_init_state
    if explicit_checkpoint_summary_path:
        return checkpoint_from_summary(Path(resolve_value(explicit_checkpoint_summary_path)))
    robustness = config.get("robustness") or {}
    init_from_stage = str(robustness.get("init_from_stage") or "stage-b-lite")
    summary = warmstart_summary_path(stage_config(config, init_from_stage)["run_name"])
    if not summary.exists():
        raise SystemExit(f"Checkpoint summary is missing: {summary}")
    return checkpoint_from_summary(summary)


def run_launch_detached(*, job_name: str, env_overrides: dict[str, str], command: list[str], dry_run: bool) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    launch_command = [
        sys.executable,
        str(ROOT / "scripts" / "launch_detached_job.py"),
        "--job-name",
        job_name,
        "--cwd",
        str(ROOT),
        "--metadata-path",
        str(detached_metadata_path(job_name)),
        "--log-path",
        str(detached_log_path(job_name)),
    ]
    for key, value in env_overrides.items():
        launch_command.extend(["--env", f"{key}={value}"])
    launch_command.append("--")
    launch_command.extend(command)

    if dry_run:
        print(json.dumps({"job_name": job_name, "launch_command": launch_command}, indent=2))
        return

    subprocess.run(launch_command, check=True)


def env_for_detached(*, allow_missing_api_key: bool = False) -> dict[str, str]:
    api_key = os.environ.get("TINKER_API_KEY")
    if not api_key and not allow_missing_api_key:
        api_key = require_api_key()
    env = {"TINKER_PYTHON_BIN": python_bin()}
    if api_key:
        env["TINKER_API_KEY"] = api_key
    return env


def launch_stage(config: dict[str, Any], stage: str, *, dry_run: bool, init_state_override: str | None = None) -> None:
    stage_payload = stage_config(config, stage)
    records_path = resolve_value(str(config["records_path"]))
    model = str(config["model"])
    dataset_path = resolve_value(str(stage_payload["dataset_path"]))
    init_state = init_state_override or env_override("STRICT_EXPERIMENT_INIT_STATE_OVERRIDE") or stage_init_state(config, stage)
    job_name = str(stage_payload["run_name"])

    command = [
        python_bin(),
        str(ROOT / "scripts" / "run_sft_warmstart.py"),
        "--name",
        job_name,
        "--dataset-path",
        dataset_path,
        "--records-path",
        str(records_path),
        "--model",
        model,
        "--init-state-path",
        init_state,
        "--epochs",
        str(stage_payload["epochs"]),
        "--batch-size",
        str(stage_payload["batch_size"]),
        "--learning-rate",
        str(stage_payload["learning_rate"]),
        "--seed",
        str(stage_payload["seed"]),
    ]
    run_launch_detached(
        job_name=job_name,
        env_overrides=env_for_detached(allow_missing_api_key=dry_run),
        command=command,
        dry_run=dry_run,
    )


def build_datasets(config: dict[str, Any], *, dry_run: bool, overrides: dict[str, Any] | None = None) -> None:
    build = build_config(config)
    for key, value in (overrides or {}).items():
        if value is not None:
            build[key] = value
    command = [
        sys.executable,
        str(ROOT / "scripts" / "build_strict_first_union_curricula.py"),
        "--old-strict-path",
        resolve_value(str(build["old_strict_path"])),
        "--new-strict-path",
        resolve_value(str(build["new_strict_path"])),
        "--purebred-path",
        resolve_value(str(build["purebred_path"])),
        "--anchor-path",
        resolve_value(str(build["anchor_path"])),
        "--stage-a-output-path",
        resolve_value(str(build["stage_a_output_path"])),
        "--stage-a-summary-path",
        resolve_value(str(build["stage_a_summary_path"])),
        "--stage-b-output-path",
        resolve_value(str(build["stage_b_output_path"])),
        "--stage-b-summary-path",
        resolve_value(str(build["stage_b_summary_path"])),
        "--old-repeat",
        str(build["old_repeat"]),
        "--new-repeat",
        str(build["new_repeat"]),
        "--pure-repeat",
        str(build["pure_repeat"]),
        "--anchor-count",
        str(build["anchor_count"]),
    ]
    optional_args = [
        ("repair_strict_path", "--repair-strict-path"),
        ("new_top_k", "--new-top-k"),
        ("repair_top_k", "--repair-top-k"),
        ("strict_max_per_prompt_bucket", "--strict-max-per-prompt-bucket"),
        ("strict_max_per_cluster", "--strict-max-per-cluster"),
        ("strict_selection_mode", "--strict-selection-mode"),
        ("repair_selection_mode", "--repair-selection-mode"),
        ("anchor_selection_mode", "--anchor-selection-mode"),
        ("repair_repeat", "--repair-repeat"),
        ("repair_identity_threshold", "--repair-identity-threshold"),
        ("repair_max_per_prompt_bucket", "--repair-max-per-prompt-bucket"),
        ("repair_max_per_source_run", "--repair-max-per-source-run"),
        ("repair_max_per_cluster", "--repair-max-per-cluster"),
        ("selected_new_output_path", "--selected-new-output-path"),
        ("selected_repair_output_path", "--selected-repair-output-path"),
        ("selected_anchor_output_path", "--selected-anchor-output-path"),
    ]
    for key, flag in optional_args:
        value = build.get(key)
        if value is None:
            continue
        if key.endswith("_path"):
            value = resolve_value(str(value))
        command.extend([flag, str(value)])

    if dry_run:
        print(json.dumps({"build_command": command}, indent=2))
        return

    output_paths = [
        Path(resolve_value(str(build["stage_a_output_path"]))),
        Path(resolve_value(str(build["stage_b_output_path"]))),
    ]
    for path in output_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, check=True)


def launch_smoke(config: dict[str, Any], *, dry_run: bool, esm2_device_override: str | None = None) -> None:
    smoke = dict(config.get("smoke") or {})
    model = str(config["model"])
    job_name = str(smoke["run_name"])
    esm2_device = esm2_device_override or env_override("STRICT_EXPERIMENT_ESM2_DEVICE") or str(smoke.get("esm2_device", "cuda"))
    command = [
        python_bin(),
        str(ROOT / "scripts" / "run_robustness_two_phase.py"),
        "--name",
        job_name,
        "--init-state-path",
        smoke_init_state(config),
        "--model",
        model,
        "--variant",
        str(smoke["variant"]),
        "--suite-sizes",
        ",".join(str(value) for value in smoke["suite_sizes"]),
        "--temperatures",
        ",".join(str(value) for value in smoke["temperatures"]),
        "--seeds",
        ",".join(str(value) for value in smoke["seeds"]),
        "--candidate-sample-count",
        str(smoke["candidate_sample_count"]),
        "--second-stage-top-k",
        str(smoke["second_stage_top_k"]),
        "--esm2-device",
        esm2_device,
        "--stockpile-jobs",
        str(smoke["stockpile_jobs"]),
        "--stockpile-retries",
        str(smoke["stockpile_retries"]),
    ]
    run_launch_detached(
        job_name=job_name,
        env_overrides=env_for_detached(allow_missing_api_key=dry_run),
        command=command,
        dry_run=dry_run,
    )


def launch_robustness(
    config: dict[str, Any],
    *,
    dry_run: bool,
    esm2_device_override: str | None = None,
    init_state_override: str | None = None,
    checkpoint_summary_path_override: str | None = None,
    run_name_override: str | None = None,
) -> None:
    robustness = dict(config.get("robustness") or {})
    model = str(config["model"])
    job_name = str(run_name_override or robustness["run_name"])
    esm2_device = esm2_device_override or env_override("STRICT_EXPERIMENT_ESM2_DEVICE") or str(robustness.get("esm2_device", "cuda"))
    command = [
        python_bin(),
        str(ROOT / "scripts" / "run_robustness_two_phase.py"),
        "--name",
        job_name,
        "--init-state-path",
        robustness_init_state(
            config,
            explicit_init_state=init_state_override,
            explicit_checkpoint_summary_path=checkpoint_summary_path_override,
        ),
        "--model",
        model,
        "--variant",
        str(robustness["variant"]),
        "--suite-sizes",
        ",".join(str(value) for value in robustness["suite_sizes"]),
        "--temperatures",
        ",".join(str(value) for value in robustness["temperatures"]),
        "--seeds",
        ",".join(str(value) for value in robustness["seeds"]),
        "--candidate-sample-count",
        str(robustness["candidate_sample_count"]),
        "--second-stage-top-k",
        str(robustness["second_stage_top_k"]),
        "--esm2-device",
        esm2_device,
        "--stockpile-jobs",
        str(robustness["stockpile_jobs"]),
        "--stockpile-retries",
        str(robustness["stockpile_retries"]),
    ]
    run_launch_detached(
        job_name=job_name,
        env_overrides=env_for_detached(allow_missing_api_key=dry_run),
        command=command,
        dry_run=dry_run,
    )


def evaluate_smoke_gate(config: dict[str, Any]) -> bool:
    smoke = dict(config.get("smoke") or {})
    summary_path = robustness_summary_path(str(smoke["run_name"]))
    decision_path = smoke_decision_path(config)
    gate = smoke.get("gate") or {}
    command = [
        python_bin(),
        str(ROOT / "scripts" / "evaluate_strict_core_smoke_gate.py"),
        "--summary-path",
        str(summary_path),
        "--prompt-count",
        str(smoke["suite_sizes"][0]),
        "--temperature",
        str(smoke["temperatures"][0]),
        "--min-seeds-with-hit",
        str(gate["min_seeds_with_hit"]),
        "--min-prompts-with-hit",
        str(gate["min_prompts_with_hit"]),
        "--output-path",
        str(decision_path),
    ]
    completed = subprocess.run(command, check=False)
    return completed.returncode == 0


def watch_smoke_after_stage(config: dict[str, Any], *, dry_run: bool) -> None:
    stage_a_summary = warmstart_summary_path(stage_config(config, "stage-a")["run_name"])
    if dry_run:
        print(json.dumps({"wait_for": str(stage_a_summary), "action": "launch-smoke"}, indent=2))
        return
    wait_for_path(stage_a_summary)
    launch_smoke(config, dry_run=False)


def watch_stageb_after_smoke(config: dict[str, Any], *, dry_run: bool) -> None:
    smoke = dict(config.get("smoke") or {})
    smoke_summary = robustness_summary_path(str(smoke["run_name"]))
    if dry_run:
        print(json.dumps({"wait_for": str(smoke_summary), "action": "evaluate-smoke-and-launch-stage-b-lite"}, indent=2))
        return
    wait_for_path(smoke_summary)
    if evaluate_smoke_gate(config):
        launch_stage(config, "stage-b-lite", dry_run=False)
    else:
        print("Smoke gate failed; stage-b-lite will not launch", file=sys.stderr)


def smoke_failed(config: dict[str, Any]) -> bool:
    decision_path = smoke_decision_path(config)
    if not decision_path.exists():
        return False
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    return not bool(payload.get("passed"))


def watch_robustness_after_stageb(config: dict[str, Any], *, dry_run: bool) -> None:
    stage_b_summary = warmstart_summary_path(stage_config(config, "stage-b-lite")["run_name"])
    if dry_run:
        print(json.dumps({"wait_for": str(stage_b_summary), "action": "launch-robustness"}, indent=2))
        return
    if not wait_for_path_or_abort(stage_b_summary, should_abort=lambda: smoke_failed(config)):
        print("Smoke gate failed; robustness watcher exiting without launch", file=sys.stderr)
        return
    launch_robustness(config, dry_run=False)


def launch_chain(config: dict[str, Any], *, dry_run: bool) -> None:
    launch_stage(config, "stage-a", dry_run=dry_run)

    name = str(config["name"])
    env = env_for_detached(allow_missing_api_key=dry_run)
    watcher_specs = [
        (
            f"{name}-smoke-watcher",
            [sys.executable, str(Path(__file__).resolve()), "--config", str(config["_config_path"]), "watch-smoke-after-stage"],
        ),
        (
            f"{name}-stageb-gate",
            [sys.executable, str(Path(__file__).resolve()), "--config", str(config["_config_path"]), "watch-stageb-after-smoke"],
        ),
        (
            f"{name}-robustness-gate",
            [sys.executable, str(Path(__file__).resolve()), "--config", str(config["_config_path"]), "watch-robustness-after-stageb"],
        ),
    ]
    for job_name, command in watcher_specs:
        run_launch_detached(job_name=job_name, env_overrides=env, command=command, dry_run=dry_run)


def describe(config: dict[str, Any], *, pretty: bool) -> None:
    stages = config.get("stages") or {}
    payload = {
        "config_path": config["_config_path"],
        "name": config["name"],
        "records_path": resolve_value(str(config["records_path"])),
        "model": config["model"],
        "stages": {
            stage: {
                "run_name": stages[stage]["run_name"],
                "dataset_path": resolve_value(str(stages[stage]["dataset_path"])),
                "summary_path": str(warmstart_summary_path(stage_config(config, stage)["run_name"])),
            }
            for stage in stages
        },
    }
    if config.get("smoke"):
        payload["smoke"] = {
            "run_name": config["smoke"]["run_name"],
            "summary_path": str(robustness_summary_path(config["smoke"]["run_name"])),
            "decision_path": str(smoke_decision_path(config)),
        }
    if config.get("robustness"):
        payload["robustness"] = {
            "run_name": config["robustness"]["run_name"],
            "summary_path": str(robustness_summary_path(config["robustness"]["run_name"])),
        }
    print(json.dumps(payload, indent=2 if pretty else None))


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.command == "describe":
        describe(config, pretty=args.pretty)
    elif args.command == "build-datasets":
        build_datasets(
            config,
            dry_run=args.dry_run,
            overrides={
                "old_repeat": args.old_repeat,
                "new_repeat": args.new_repeat,
                "pure_repeat": args.pure_repeat,
                "anchor_count": args.anchor_count,
                "new_top_k": args.new_top_k,
                "repair_top_k": args.repair_top_k,
                "repair_repeat": args.repair_repeat,
                "strict_selection_mode": args.strict_selection_mode,
                "repair_selection_mode": args.repair_selection_mode,
                "anchor_selection_mode": args.anchor_selection_mode,
                "strict_max_per_prompt_bucket": args.strict_max_per_prompt_bucket,
                "strict_max_per_cluster": args.strict_max_per_cluster,
                "repair_max_per_prompt_bucket": args.repair_max_per_prompt_bucket,
                "repair_max_per_source_run": args.repair_max_per_source_run,
                "repair_max_per_cluster": args.repair_max_per_cluster,
            },
        )
    elif args.command == "launch-stage":
        launch_stage(config, args.stage, dry_run=args.dry_run, init_state_override=args.init_state_path)
    elif args.command == "launch-smoke":
        launch_smoke(config, dry_run=args.dry_run, esm2_device_override=args.esm2_device)
    elif args.command == "launch-robustness":
        launch_robustness(
            config,
            dry_run=args.dry_run,
            esm2_device_override=args.esm2_device,
            init_state_override=args.init_state_path,
            checkpoint_summary_path_override=args.checkpoint_summary_path,
            run_name_override=args.run_name,
        )
    elif args.command == "watch-smoke-after-stage":
        watch_smoke_after_stage(config, dry_run=args.dry_run)
    elif args.command == "watch-stageb-after-smoke":
        watch_stageb_after_smoke(config, dry_run=args.dry_run)
    elif args.command == "watch-robustness-after-stageb":
        watch_robustness_after_stageb(config, dry_run=args.dry_run)
    elif args.command == "launch-chain":
        launch_chain(config, dry_run=args.dry_run)
    else:
        raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
