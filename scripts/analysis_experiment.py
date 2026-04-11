#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
    parser = argparse.ArgumentParser(description="Config-driven historical-analysis launcher")
    parser.add_argument("--config", required=True, help="Analysis config JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    describe = subparsers.add_parser("describe", help="Print resolved analysis config")
    describe.add_argument("--pretty", action="store_true")

    build_universe = subparsers.add_parser("build-universe", help="Build the historical hit universe")
    build_universe.add_argument("--dry-run", action="store_true")

    build_neighborhoods = subparsers.add_parser("build-neighborhoods", help="Build anchor-neighborhood reports")
    build_neighborhoods.add_argument("--dry-run", action="store_true")

    build_shortlist = subparsers.add_parser("build-shortlist", help="Build the local-exploit shortlist")
    build_shortlist.add_argument("--dry-run", action="store_true")

    launch_pad = subparsers.add_parser("launch-pad", help="Print or run the full analysis sequence")
    launch_pad.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_config(path: str) -> dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["_config_path"] = str(config_path)
    return payload


def resolve_value(value: str | None) -> str | None:
    return resolve_repo_path(value)


def command_for_universe(config: dict[str, Any]) -> list[str]:
    universe = dict(config["universe"])
    command = [sys.executable, resolve_value(str(universe["script"]))]
    command.extend(["--reports-root", resolve_value(str(config["reports_root"]))])
    for pattern in config.get("include_globs") or []:
        command.extend(["--include-glob", str(pattern)])
    for pattern in config.get("exclude_globs") or []:
        command.extend(["--exclude-glob", str(pattern)])
    for raw in config.get("wave_dirs") or []:
        command.extend(["--wave-dir", resolve_value(str(raw))])
    command.extend(["--output-dir", resolve_value(str(universe["output_dir"]))])
    for key, value in universe.items():
        if key in {"script", "output_dir"}:
            continue
        flag = f"--{key.replace('_', '-')}"
        command.extend([flag, str(value)])
    return command


def command_for_neighborhoods(config: dict[str, Any]) -> list[str]:
    neighborhoods = dict(config["neighborhoods"])
    return [
        sys.executable,
        resolve_value(str(neighborhoods["script"])),
        "--candidate-hit-path",
        resolve_value(str(neighborhoods["candidate_hit_path"])),
        "--anchor-source-path",
        resolve_value(str(neighborhoods["anchor_source_path"])),
        "--output-dir",
        resolve_value(str(neighborhoods["output_dir"])),
        "--identity-thresholds",
        str(neighborhoods.get("identity_thresholds", "0.98,0.95,0.90,0.85")),
        "--strict-anchor-count",
        str(neighborhoods.get("strict_anchor_count", 24)),
        "--bridge-anchor-count",
        str(neighborhoods.get("bridge_anchor_count", 24)),
        "--max-examples-per-threshold",
        str(neighborhoods.get("max_examples_per_threshold", 12)),
    ]


def command_for_shortlist(config: dict[str, Any]) -> list[str]:
    shortlist = dict(config["shortlist"])
    return [
        sys.executable,
        resolve_value(str(shortlist["script"])),
        "--anchor-neighborhood-path",
        resolve_value(str(shortlist["anchor_neighborhood_path"])),
        "--output-dir",
        resolve_value(str(shortlist["output_dir"])),
        "--green-limit",
        str(shortlist.get("green_limit", 12)),
        "--yellow-limit",
        str(shortlist.get("yellow_limit", 12)),
    ]


def run_command(command: list[str], *, dry_run: bool) -> None:
    if dry_run:
        print(json.dumps({"command": command}, indent=2))
        return
    subprocess.run(command, check=True, cwd=ROOT)


def command_bundle(config: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "build_universe": command_for_universe(config),
        "build_neighborhoods": command_for_neighborhoods(config),
        "build_shortlist": command_for_shortlist(config),
    }


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    commands = command_bundle(config)

    if args.command == "describe":
        payload = {
            "name": config["name"],
            "reports_root": resolve_value(str(config["reports_root"])),
            "include_globs": config.get("include_globs") or [],
            "exclude_globs": config.get("exclude_globs") or [],
            "commands": commands,
        }
        if args.pretty:
            print(json.dumps(payload, indent=2))
        else:
            print(json.dumps(payload))
        return

    if args.command == "build-universe":
        run_command(commands["build_universe"], dry_run=args.dry_run)
        return

    if args.command == "build-neighborhoods":
        run_command(commands["build_neighborhoods"], dry_run=args.dry_run)
        return

    if args.command == "build-shortlist":
        run_command(commands["build_shortlist"], dry_run=args.dry_run)
        return

    if args.command == "launch-pad":
        if args.dry_run:
            print(json.dumps(commands, indent=2))
            return
        run_command(commands["build_universe"], dry_run=False)
        run_command(commands["build_neighborhoods"], dry_run=False)
        run_command(commands["build_shortlist"], dry_run=False)
        return

    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
