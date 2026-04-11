#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import shutil
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
    parser = argparse.ArgumentParser(description="Config-driven repair/local-exploit launcher")
    parser.add_argument("--config", required=True, help="Repair config JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    describe = subparsers.add_parser("describe", help="Print resolved repair config")
    describe.add_argument("--pretty", action="store_true")

    build_pool = subparsers.add_parser("build-pool", help="Build the merged repair pool")
    build_pool.add_argument("--max-total", type=int)
    build_pool.add_argument("--dry-run", action="store_true")

    native_repair = subparsers.add_parser("run-native-repair", help="Run same-length native repair on the repair pool")
    native_repair.add_argument("--max-hits", type=int)
    native_repair.add_argument("--proposal-device")
    native_repair.add_argument("--dry-run", action="store_true")

    validate = subparsers.add_parser("validate", help="Validate repair survivors under the full family screen")
    validate.add_argument("--dry-run", action="store_true")

    readiness = subparsers.add_parser(
        "check-readiness",
        help="Check retrain readiness after adding strict repair survivors back to the base audits",
    )
    readiness.add_argument("--dry-run", action="store_true")

    launch = subparsers.add_parser("launch-pad", help="Run the full repair pilot sequence")
    launch.add_argument("--max-total", type=int)
    launch.add_argument("--max-hits", type=int)
    launch.add_argument("--proposal-device")
    launch.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_config(path: str) -> dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["_config_path"] = str(config_path)
    return payload


def resolve_value(value: str | None) -> str | None:
    return resolve_repo_path(value)


def execution_prefix(config: dict[str, Any]) -> list[str]:
    execution = dict(config.get("execution") or {})
    mode = str(execution.get("mode") or "python")
    if mode == "python":
        python_bin = str(execution.get("python_bin") or sys.executable)
        return [python_bin]
    if mode == "uv_with_requirements":
        requirements_path = execution.get("requirements_path") or "requirements.txt"
        uv_bin = shutil.which("uv")
        if uv_bin is None:
            raise SystemExit("uv is not installed but execution.mode is uv_with_requirements")
        return [
            uv_bin,
            "run",
            "--isolated",
            "--no-project",
            "--with-requirements",
            resolve_value(str(requirements_path)),
            "python",
        ]
    raise SystemExit(f"Unsupported execution mode in {config['_config_path']}: {mode}")


def repair_root(config: dict[str, Any]) -> Path:
    base = Path(resolve_value(str(config.get("output_dir") or "reports/repair")))
    name = str(config["name"])
    return base / name


def repair_paths(config: dict[str, Any]) -> dict[str, Path]:
    root = repair_root(config)
    return {
        "root": root,
        "repair_pool_path": root / "repair_pool_selected.jsonl",
        "repair_pool_audit_path": root / "repair_pool_selected_audit.json",
        "repair_pool_summary_path": root / "repair_pool_selected_summary.json",
        "repair_survivors_path": root / "repair_survivors.jsonl",
        "repair_best_attempts_path": root / "repair_best_attempts.jsonl",
        "repair_summary_path": root / "repair_summary.json",
        "validated_path": root / "repair_validated.jsonl",
        "strict_path": root / "repair_validated_strict.jsonl",
        "review_path": root / "repair_validated_review.jsonl",
        "reject_path": root / "repair_validated_reject.jsonl",
        "validation_summary_path": root / "repair_validation_summary.json",
        "readiness_path": root / "repair_readiness.json",
    }


def resolve_audit_paths(config: dict[str, Any]) -> list[Path]:
    sources = dict(config.get("sources") or {})
    resolved: list[Path] = []
    for raw_pattern in sources.get("audit_globs") or []:
        pattern = resolve_value(str(raw_pattern))
        resolved.extend(Path(path).resolve() for path in sorted(glob.glob(pattern)))
    for raw_path in sources.get("audit_paths") or []:
        resolved.append(Path(resolve_value(str(raw_path))).resolve())

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in resolved:
        if path in seen:
            continue
        if not path.exists():
            raise SystemExit(f"Audit path does not exist: {path}")
        if path.name != "candidate_audit.json":
            raise SystemExit(f"Expected candidate_audit.json path, got: {path}")
        seen.add(path)
        unique.append(path)
    if not unique:
        raise SystemExit(f"No candidate_audit.json files resolved from {config['_config_path']}")
    return unique


def build_pool_command(config: dict[str, Any], *, max_total_override: int | None = None) -> list[str]:
    payload = dict(config["repair_pool"])
    paths = repair_paths(config)
    audit_paths = resolve_audit_paths(config)
    command = execution_prefix(config) + [
        str(ROOT / "scripts" / "build_repair_pool_dataset.py"),
        "--audit-paths",
        ",".join(str(path) for path in audit_paths),
        "--output-path",
        str(paths["repair_pool_path"]),
        "--output-audit-path",
        str(paths["repair_pool_audit_path"]),
        "--summary-path",
        str(paths["repair_pool_summary_path"]),
        "--max-geometry-per-step",
        str(payload.get("max_geometry_per_step", 1)),
    ]
    if not bool(payload.get("selected_only", True)):
        command.append("--include-unselected")
    max_total = max_total_override if max_total_override is not None else payload.get("max_total")
    if max_total is not None:
        command.extend(["--max-total", str(max_total)])
    return command


def native_repair_command(
    config: dict[str, Any],
    *,
    max_hits_override: int | None = None,
    proposal_device_override: str | None = None,
) -> list[str]:
    payload = dict(config["native_repair"])
    paths = repair_paths(config)
    command = execution_prefix(config) + [
        str(ROOT / "scripts" / "build_kimi_native_repair_dataset.py"),
        "--audit-path",
        str(paths["repair_pool_audit_path"]),
        "--records-path",
        resolve_value(str(config.get("records_path") or "data/petase_family_expanded/petase_records.jsonl")),
        "--output-path",
        str(paths["repair_survivors_path"]),
        "--summary-path",
        str(paths["repair_summary_path"]),
        "--best-attempts-output-path",
        str(paths["repair_best_attempts_path"]),
        "--esm-threshold",
        str(payload.get("esm_threshold", 85.0)),
        "--max-hits",
        str(max_hits_override if max_hits_override is not None else payload.get("max_hits", 48)),
        "--rounds",
        str(payload.get("rounds", 3)),
        "--mutable-radius",
        str(payload.get("mutable_radius", 3)),
        "--top-residues-per-position",
        str(payload.get("top_residues_per_position", 3)),
        "--beam-size",
        str(payload.get("beam_size", 6)),
        "--proposal-device",
        str(proposal_device_override or payload.get("proposal_device", "auto")),
    ]
    if not bool(payload.get("selected_only", True)):
        command.append("--include-unselected")
    return command


def validate_command(config: dict[str, Any]) -> list[str]:
    payload = dict(config["validation"])
    paths = repair_paths(config)
    return execution_prefix(config) + [
        str(ROOT / "scripts" / "validate_repair_survivors.py"),
        "--survivors-path",
        str(paths["repair_survivors_path"]),
        "--records-path",
        resolve_value(str(config.get("records_path") or "data/petase_family_expanded/petase_records.jsonl")),
        "--output-path",
        str(paths["validated_path"]),
        "--strict-output-path",
        str(paths["strict_path"]),
        "--review-output-path",
        str(paths["review_path"]),
        "--reject-output-path",
        str(paths["reject_path"]),
        "--summary-path",
        str(paths["validation_summary_path"]),
        "--min-esm",
        str(payload.get("min_esm", 95.0)),
        "--max-mutations",
        str(payload.get("max_mutations", 2)),
        "--max-gap-error",
        str(payload.get("max_gap_error", 14)),
    ]


def readiness_command(config: dict[str, Any]) -> list[str]:
    payload = dict(config.get("readiness") or {})
    paths = repair_paths(config)
    audit_paths = resolve_audit_paths(config)
    command = execution_prefix(config) + [
        str(ROOT / "scripts" / "check_repair_survivor_readiness.py"),
        *(str(path) for path in audit_paths),
        "--survivors-path",
        str(paths["strict_path"]),
        "--parent-pool-path",
        str(paths["repair_pool_path"]),
        "--output-path",
        str(paths["readiness_path"]),
    ]
    if bool(payload.get("selected_only", True)):
        command.append("--selected-only")
    return command


def command_bundle(
    config: dict[str, Any],
    *,
    max_total_override: int | None = None,
    max_hits_override: int | None = None,
    proposal_device_override: str | None = None,
) -> dict[str, list[str]]:
    return {
        "build_pool": build_pool_command(config, max_total_override=max_total_override),
        "run_native_repair": native_repair_command(
            config,
            max_hits_override=max_hits_override,
            proposal_device_override=proposal_device_override,
        ),
        "validate": validate_command(config),
        "check_readiness": readiness_command(config),
    }


def run_command(command: list[str], *, dry_run: bool) -> None:
    if dry_run:
        print(json.dumps({"command": command}, indent=2))
        return
    subprocess.run(command, check=True, cwd=ROOT)


def describe_payload(config: dict[str, Any]) -> dict[str, Any]:
    paths = repair_paths(config)
    audits = resolve_audit_paths(config)
    return {
        "name": config["name"],
        "execution": config.get("execution") or {"mode": "python"},
        "records_path": resolve_value(str(config.get("records_path") or "data/petase_family_expanded/petase_records.jsonl")),
        "repair_root": str(paths["root"]),
        "source_audit_count": len(audits),
        "source_audits_preview": [str(path) for path in audits[:8]],
        "source_audit_preview_truncated": len(audits) > 8,
        "repair_pool": dict(config["repair_pool"]),
        "native_repair": dict(config["native_repair"]),
        "validation": dict(config["validation"]),
        "readiness": dict(config.get("readiness") or {}),
        "artifacts": {key: str(value) for key, value in paths.items()},
    }


def main() -> None:
    args = parse_args()
    config = load_config(args.config)

    if args.command == "describe":
        payload = describe_payload(config)
        if args.pretty:
            print(json.dumps(payload, indent=2))
        else:
            print(json.dumps(payload))
        return

    commands = command_bundle(
        config,
        max_total_override=getattr(args, "max_total", None),
        max_hits_override=getattr(args, "max_hits", None),
        proposal_device_override=getattr(args, "proposal_device", None),
    )

    if args.command == "build-pool":
        run_command(commands["build_pool"], dry_run=args.dry_run)
        return
    if args.command == "run-native-repair":
        run_command(commands["run_native_repair"], dry_run=args.dry_run)
        return
    if args.command == "validate":
        run_command(commands["validate"], dry_run=args.dry_run)
        return
    if args.command == "check-readiness":
        run_command(commands["check_readiness"], dry_run=args.dry_run)
        return
    if args.command == "launch-pad":
        if args.dry_run:
            print(json.dumps(commands, indent=2))
            return
        run_command(commands["build_pool"], dry_run=False)
        run_command(commands["run_native_repair"], dry_run=False)
        run_command(commands["validate"], dry_run=False)
        run_command(commands["check_readiness"], dry_run=False)
        return
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
