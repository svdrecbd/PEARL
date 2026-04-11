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

from pearl.paths import REPO_ROOT, resolve_repo_path


ROOT = REPO_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Config-driven mining launcher")
    parser.add_argument("--config", required=True, help="Mining config JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    describe = subparsers.add_parser("describe", help="Print resolved mining config")
    describe.add_argument("--pretty", action="store_true")

    build_pack = subparsers.add_parser("build-prompt-pack", help="Build a configured prompt pack")
    build_pack.add_argument("--dry-run", action="store_true")

    launch_stage1 = subparsers.add_parser("launch-stage1", help="Launch a stage1 mining wave")
    launch_stage1.add_argument("--variant-key")
    launch_stage1.add_argument("--prompts-path")
    launch_stage1.add_argument("--total-prompts", type=int)
    launch_stage1.add_argument("--prompt-offset", type=int)
    launch_stage1.add_argument("--shard-count", type=int)
    launch_stage1.add_argument("--candidate-sample-count", type=int)
    launch_stage1.add_argument("--second-stage-top-k", type=int)
    launch_stage1.add_argument("--temperature", type=float)
    launch_stage1.add_argument("--esm2-device")
    launch_stage1.add_argument("--prompt-variant")
    launch_stage1.add_argument("--date-tag")
    launch_stage1.add_argument("--sampler-backend")
    launch_stage1.add_argument("--sampler-base-url")
    launch_stage1.add_argument("--sampler-api-key")
    launch_stage1.add_argument("--sampler-tokenizer")
    launch_stage1.add_argument("--sampler-timeout-seconds", type=float)
    launch_stage1.add_argument("--sampler-max-retries", type=int)
    launch_stage1.add_argument("--sampler-trust-remote-code", action=argparse.BooleanOptionalAction)
    launch_stage1.add_argument("--dry-run", action="store_true")

    launch = subparsers.add_parser("launch", help="Build prompt pack if configured, then launch stage1")
    launch.add_argument("--variant-key")
    launch.add_argument("--prompts-path")
    launch.add_argument("--total-prompts", type=int)
    launch.add_argument("--prompt-offset", type=int)
    launch.add_argument("--shard-count", type=int)
    launch.add_argument("--candidate-sample-count", type=int)
    launch.add_argument("--second-stage-top-k", type=int)
    launch.add_argument("--temperature", type=float)
    launch.add_argument("--esm2-device")
    launch.add_argument("--prompt-variant")
    launch.add_argument("--date-tag")
    launch.add_argument("--sampler-backend")
    launch.add_argument("--sampler-base-url")
    launch.add_argument("--sampler-api-key")
    launch.add_argument("--sampler-tokenizer")
    launch.add_argument("--sampler-timeout-seconds", type=float)
    launch.add_argument("--sampler-max-retries", type=int)
    launch.add_argument("--sampler-trust-remote-code", action=argparse.BooleanOptionalAction)
    launch.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_config(path: str) -> dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["_config_path"] = str(config_path)
    return payload


def resolve_value(value: str | None) -> str | None:
    return resolve_repo_path(value)


def config_path_value(config: dict[str, Any], key: str, default: str | None = None) -> str | None:
    raw = config.get(key, default)
    if raw is None:
        return None
    return resolve_value(str(raw))


def require_api_key(*, dry_run: bool, sampler_backend: str) -> None:
    if dry_run:
        return
    if sampler_backend != "tinker":
        return
    if not os.environ.get("TINKER_API_KEY"):
        raise SystemExit("TINKER_API_KEY is not set")


def stage1_config(config: dict[str, Any]) -> dict[str, Any]:
    payload = config.get("stage1")
    if not payload:
        raise SystemExit(f"Config {config['_config_path']} is missing stage1")
    return dict(payload)


def variant_key(config: dict[str, Any], explicit: str | None) -> str:
    if explicit:
        return explicit
    stage1 = stage1_config(config)
    value = stage1.get("variant_key") or config.get("default_variant_key")
    if not value:
        raise SystemExit(f"Config {config['_config_path']} has no default variant key")
    return str(value)


def variant_config(config: dict[str, Any], key: str) -> dict[str, Any]:
    variants = config.get("variants") or {}
    if key not in variants:
        raise SystemExit(f"Config {config['_config_path']} is missing mining variant '{key}'")
    return dict(variants[key])


def prompt_pack_config(config: dict[str, Any]) -> dict[str, Any] | None:
    payload = config.get("prompt_pack")
    if not payload:
        return None
    return dict(payload)


def config_scalar(config: dict[str, Any], stage1: dict[str, Any], key: str, default: Any) -> Any:
    if key in stage1:
        return stage1[key]
    return config.get(key, default)


def build_prompt_pack(config: dict[str, Any], *, dry_run: bool) -> None:
    pack = prompt_pack_config(config)
    if not pack:
        raise SystemExit(f"Config {config['_config_path']} has no prompt_pack section")
    command = [
        sys.executable,
        resolve_value(str(pack["builder_script"])),
    ]
    builder_args = pack.get("builder_args") or {}
    for key, value in builder_args.items():
        flag = f"--{key.replace('_', '-')}"
        command.extend([flag, resolve_value(str(value)) if str(key).endswith("_path") or str(key).endswith("_dir") else str(value)])
    command.extend(["--output-path", resolve_value(str(pack["output_path"]))])
    command.extend(["--summary-path", resolve_value(str(pack["summary_path"]))])

    if dry_run:
        print(json.dumps({"build_prompt_pack_command": command}, indent=2))
        return

    output_path = Path(resolve_value(str(pack["output_path"])))
    summary_path = Path(resolve_value(str(pack["summary_path"])))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, check=True, cwd=ROOT)


def prompt_pack_paths(config: dict[str, Any]) -> tuple[Path, Path] | None:
    pack = prompt_pack_config(config)
    if not pack:
        return None
    return (
        Path(resolve_value(str(pack["output_path"]))),
        Path(resolve_value(str(pack["summary_path"]))),
    )


def effective_prompts_path(config: dict[str, Any], override: str | None) -> str:
    if override:
        return resolve_value(override)
    pack_paths = prompt_pack_paths(config)
    if pack_paths and pack_paths[0].exists():
        return str(pack_paths[0])
    return config_path_value(config, "prompts_path", str(ROOT / "data" / "petase_family_expanded" / "train_prompts_relevance_ge10.jsonl"))


def effective_total_prompts(config: dict[str, Any], override: int | None) -> int:
    if override is not None:
        return int(override)
    pack_paths = prompt_pack_paths(config)
    if pack_paths and pack_paths[1].exists():
        summary = json.loads(pack_paths[1].read_text(encoding="utf-8"))
        return int(summary["total_prompt_count"])
    return int(stage1_config(config)["total_prompt_count"])


def launch_stage1(config: dict[str, Any], args: argparse.Namespace) -> None:
    stage1 = stage1_config(config)
    sampler_backend = str(args.sampler_backend or config_scalar(config, stage1, "sampler_backend", "tinker"))
    require_api_key(dry_run=args.dry_run, sampler_backend=sampler_backend)
    selected_variant_key = variant_key(config, args.variant_key)
    variant = variant_config(config, selected_variant_key)
    total_prompts = effective_total_prompts(config, args.total_prompts)
    candidate_sample_count = int(args.candidate_sample_count if args.candidate_sample_count is not None else stage1["candidate_sample_count"])
    date_tag = str(args.date_tag or stage1["date_tag"])
    wave_name = str(variant["wave_name_template"]).format(
        total_prompts=total_prompts,
        candidate_sample_count=candidate_sample_count,
        date_tag=date_tag,
    )
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_raft_wave.py"),
        "--name",
        wave_name,
        "--prompts-path",
        effective_prompts_path(config, args.prompts_path),
        "--reference-records-path",
        config_path_value(
            config,
            "reference_records_path",
            str(ROOT / "data" / "petase_family_expanded" / "petase_records.jsonl"),
        ),
        "--output-dir",
        config_path_value(config, "output_dir", str(ROOT / "reports" / "raft")),
        "--model",
        str(config.get("model", "moonshotai/Kimi-K2.5")),
        "--variant",
        str(args.prompt_variant or stage1["prompt_variant"]),
        "--total-prompt-count",
        str(total_prompts),
        "--prompt-offset",
        str(args.prompt_offset if args.prompt_offset is not None else stage1["prompt_offset"]),
        "--shard-count",
        str(args.shard_count if args.shard_count is not None else stage1["shard_count"]),
        "--candidate-sample-count",
        str(candidate_sample_count),
        "--second-stage-top-k",
        str(args.second_stage_top_k if args.second_stage_top_k is not None else stage1["second_stage_top_k"]),
        "--temperature",
        str(args.temperature if args.temperature is not None else stage1["temperature"]),
        "--esm2-device",
        str(args.esm2_device or stage1.get("esm2_device", "mps")),
        "--sampler-backend",
        sampler_backend,
        "--seed",
        str(stage1.get("seed", 37)),
        "--stage1-only",
    ]
    init_state_path = variant.get("init_state_path")
    if init_state_path:
        command.extend(["--init-state-path", str(init_state_path)])
    sampler_base_url = args.sampler_base_url or config_scalar(config, stage1, "sampler_base_url", None)
    sampler_api_key = args.sampler_api_key or config_scalar(config, stage1, "sampler_api_key", None)
    sampler_tokenizer = args.sampler_tokenizer or config_scalar(config, stage1, "sampler_tokenizer", None)
    sampler_timeout_seconds = args.sampler_timeout_seconds
    if sampler_timeout_seconds is None:
        sampler_timeout_seconds = float(config_scalar(config, stage1, "sampler_timeout_seconds", 120.0))
    sampler_max_retries = args.sampler_max_retries
    if sampler_max_retries is None:
        sampler_max_retries = int(config_scalar(config, stage1, "sampler_max_retries", 3))
    sampler_trust_remote_code = args.sampler_trust_remote_code
    if sampler_trust_remote_code is None:
        sampler_trust_remote_code = bool(config_scalar(config, stage1, "sampler_trust_remote_code", True))
    if sampler_base_url:
        command.extend(["--sampler-base-url", str(sampler_base_url)])
    if sampler_api_key:
        command.extend(["--sampler-api-key", str(sampler_api_key)])
    if sampler_tokenizer:
        command.extend(["--sampler-tokenizer", str(sampler_tokenizer)])
    command.extend(
        [
            "--sampler-timeout-seconds",
            str(sampler_timeout_seconds),
            "--sampler-max-retries",
            str(sampler_max_retries),
            "--sampler-trust-remote-code" if sampler_trust_remote_code else "--no-sampler-trust-remote-code",
        ]
    )

    if args.dry_run:
        print(json.dumps({"launch_stage1_command": command}, indent=2))
        return

    subprocess.run(command, check=True, cwd=ROOT)


def describe(config: dict[str, Any], *, pretty: bool) -> None:
    stage1 = stage1_config(config)
    payload: dict[str, Any] = {
        "config_path": config["_config_path"],
        "name": config["name"],
        "model": config.get("model", "moonshotai/Kimi-K2.5"),
        "reference_records_path": config_path_value(
            config,
            "reference_records_path",
            str(ROOT / "data" / "petase_family_expanded" / "petase_records.jsonl"),
        ),
        "stage1": stage1,
        "variants": config.get("variants") or {},
        "sampler_backend": config_scalar(config, stage1, "sampler_backend", "tinker"),
        "sampler_base_url": config_scalar(config, stage1, "sampler_base_url", None),
        "sampler_tokenizer": config_scalar(config, stage1, "sampler_tokenizer", None),
        "sampler_timeout_seconds": config_scalar(config, stage1, "sampler_timeout_seconds", 120.0),
        "sampler_max_retries": config_scalar(config, stage1, "sampler_max_retries", 3),
        "sampler_trust_remote_code": config_scalar(config, stage1, "sampler_trust_remote_code", True),
    }
    pack = prompt_pack_config(config)
    if pack:
        payload["prompt_pack"] = {
            "output_path": resolve_value(str(pack["output_path"])),
            "summary_path": resolve_value(str(pack["summary_path"])),
            "builder_script": resolve_value(str(pack["builder_script"])),
        }
    print(json.dumps(payload, indent=2 if pretty else None))


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    if args.command == "describe":
        describe(config, pretty=args.pretty)
    elif args.command == "build-prompt-pack":
        build_prompt_pack(config, dry_run=args.dry_run)
    elif args.command == "launch-stage1":
        launch_stage1(config, args)
    elif args.command == "launch":
        if prompt_pack_config(config):
            build_prompt_pack(config, dry_run=args.dry_run)
        launch_stage1(config, args)
    else:
        raise SystemExit(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    main()
