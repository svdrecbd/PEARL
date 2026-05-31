#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.io_utils import atomic_write_json
from pearl.opd_lite import validate_sparse_target_rows
from pearl.phase8_readiness import (
    TINKER_MODEL_PRICES,
    estimate_dpo_cost,
    estimate_policy_sampling_cost,
    estimate_sparse_opd_cost,
    estimate_teacher_trace_cost,
)
from pearl.preference_distillation import load_jsonl


def main() -> None:
    args = parse_args()
    output_dir = repo_path(args.output_dir) / sanitize_name(args.name)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"

    prices = TINKER_MODEL_PRICES.get(args.model)
    if prices is None:
        supported = ", ".join(sorted(TINKER_MODEL_PRICES))
        raise RuntimeError(f"No local price table entry for {args.model!r}. Supported: {supported}")

    dpo = inspect_dpo(args=args, prices=prices)
    traces = inspect_teacher_traces(args=args, prices=prices)
    sparse = inspect_sparse_targets(args=args, prices=prices)
    sampling = estimate_policy_sampling_cost(
        prices=prices,
        policies=args.eval_policies,
        samples_per_policy=args.eval_samples_per_policy,
        prompt_tokens=args.avg_prompt_tokens,
        generated_tokens=args.avg_sequence_tokens,
    )

    teacher_specs_ready = bool(args.teacher)
    paid_smoke_cost = dpo["costs"]["smoke"]["estimated_cost_usd"]
    if sparse["exists"]:
        paid_smoke_cost += sparse["costs"]["smoke"]["estimated_cost_usd"]
    elif traces["rollouts_exist"]:
        paid_smoke_cost += traces["costs"]["trace_smoke"]["estimated_cost_usd"]

    pilot_cost = (
        dpo["costs"]["full_10k_one_epoch"]["estimated_cost_usd"]
        + sampling["estimated_cost_usd"]
    )
    if sparse["exists"]:
        pilot_cost += sparse["costs"]["pilot"]["estimated_cost_usd"]
    elif traces["rollouts_exist"]:
        pilot_cost += traces["costs"]["trace_pilot"]["estimated_cost_usd"]

    report = {
        "name": args.name,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "model": args.model,
        "price_table": {
            "prefill_per_million": prices.prefill_per_million,
            "sample_per_million": prices.sample_per_million,
            "train_per_million": prices.train_per_million,
            "source": "https://tinker-docs.thinkingmachines.ai/tinker/models/",
        },
        "auth": {
            "tinker_api_key_set": bool(os.environ.get("TINKER_API_KEY")),
        },
        "readiness": {
            "paid_dpo_smoke_ready": dpo["ready"],
            "teacher_specs_supplied": teacher_specs_ready,
            "rollout_seed_ready": traces["rollouts_exist"] and traces["rollout_count"] > 0,
            "ready_to_start_teacher_trace_paid_step": bool(
                os.environ.get("TINKER_API_KEY")
                and teacher_specs_ready
                and traces["rollouts_exist"]
                and traces["rollout_count"] > 0
            ),
            "teacher_trace_ready": traces["ready"],
            "sparse_opd_smoke_ready": sparse["ready"],
            "fully_ready_for_first_paid_smoke_sequence": bool(
                os.environ.get("TINKER_API_KEY")
                and dpo["ready"]
                and traces["rollouts_exist"]
                and traces["rollout_count"] > 0
                and teacher_specs_ready
            ),
            "fully_ready_for_sparse_opd_paid_training": bool(dpo["ready"] and sparse["ready"]),
        },
        "dpo": dpo,
        "teacher_traces": traces,
        "sparse_opd": sparse,
        "eval_sampling": sampling,
        "costs": {
            "paid_smoke_sequence_estimated_usd": round(paid_smoke_cost, 4),
            "pilot_with_10k_dpo_and_eval_sampling_estimated_usd": round(pilot_cost, 4),
            "local_folding_and_external_oracles_usd": "not_included",
        },
        "commands": build_commands(args),
    }
    atomic_write_json(report_path, report)
    print(json.dumps(report, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preflight Phase 8 paid DPO/sparse-OPD runs and estimate Tinker spend."
    )
    parser.add_argument("--name", default="phase8-paid-readiness")
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "phase8_paid_preflight"))
    parser.add_argument("--model", default="moonshotai/Kimi-K2.6")
    parser.add_argument("--pairs-path", default=str(ROOT / "data" / "phase8_dpo" / "dpo_preferences_hybrid_10k.jsonl"))
    parser.add_argument(
        "--preflight-path",
        default=str(ROOT / "data" / "phase8_dpo" / "dpo_preferences_hybrid_10k_preflight.json"),
    )
    parser.add_argument("--rollouts-path", default=str(ROOT / "reports" / "opd_lite" / "rollouts.jsonl"))
    parser.add_argument(
        "--teacher-traces-path",
        default=str(ROOT / "reports" / "opd_lite" / "phase8-teacher-traces" / "teacher_traces.jsonl"),
    )
    parser.add_argument(
        "--sparse-targets-path",
        default=str(ROOT / "reports" / "opd_lite" / "phase8-sparse-opd-targets" / "sparse_opd_targets.jsonl"),
    )
    parser.add_argument("--dpo-smoke-pairs", type=int, default=8)
    parser.add_argument("--dpo-full-pairs", type=int, default=10_000)
    parser.add_argument("--opd-smoke-rows", type=int, default=8)
    parser.add_argument("--opd-pilot-rows", type=int, default=256)
    parser.add_argument("--teacher-count", type=int, default=4)
    parser.add_argument("--trace-smoke-rollouts", type=int, default=8)
    parser.add_argument("--trace-pilot-rollouts", type=int, default=256)
    parser.add_argument("--eval-policies", type=int, default=5)
    parser.add_argument("--eval-samples-per-policy", type=int, default=500)
    parser.add_argument("--avg-prompt-tokens", type=int, default=80)
    parser.add_argument("--avg-sequence-tokens", type=int, default=256)
    parser.add_argument(
        "--teacher",
        action="append",
        default=[],
        help=(
            "Optional teacher spec to insert into the trace command, e.g. "
            "name=foldability,path=tinker://...,weight=0.35,temperature=0.7"
        ),
    )
    return parser.parse_args()


def inspect_dpo(*, args: argparse.Namespace, prices: Any) -> dict[str, Any]:
    pairs_path = repo_path(args.pairs_path)
    preflight_path = repo_path(args.preflight_path)
    exists = pairs_path.exists()
    rows = load_jsonl(pairs_path) if exists else []
    preflight_payload = read_json(preflight_path) if preflight_path.exists() else {}
    shape_ok = exists and bool(rows) and preflight_payload.get("ready_for_paid_dpo_smoke") is True
    return {
        "exists": exists,
        "path": str(pairs_path),
        "preflight_path": str(preflight_path),
        "pair_count": len(rows),
        "preflight_ready": preflight_payload.get("ready_for_paid_dpo_smoke"),
        "ready": shape_ok,
        "costs": {
            "smoke": estimate_dpo_cost(
                pair_rows=rows,
                prices=prices,
                pair_count=min(args.dpo_smoke_pairs, len(rows)),
            ),
            "full_10k_one_epoch": estimate_dpo_cost(
                pair_rows=rows,
                prices=prices,
                pair_count=min(args.dpo_full_pairs, len(rows)),
            ),
        },
    }


def inspect_teacher_traces(*, args: argparse.Namespace, prices: Any) -> dict[str, Any]:
    rollouts_path = repo_path(args.rollouts_path)
    traces_path = repo_path(args.teacher_traces_path)
    rollouts = load_jsonl(rollouts_path) if rollouts_path.exists() else []
    traces = load_jsonl(traces_path) if traces_path.exists() else []
    return {
        "rollouts_exist": rollouts_path.exists(),
        "rollouts_path": str(rollouts_path),
        "rollout_count": len(rollouts),
        "exists": traces_path.exists(),
        "path": str(traces_path),
        "trace_count": len(traces),
        "ready": traces_path.exists() and bool(traces),
        "costs": {
            "trace_smoke": estimate_teacher_trace_cost(
                rollout_rows=rollouts,
                prices=prices,
                rollout_count=min(args.trace_smoke_rollouts, len(rollouts)),
                teacher_count=args.teacher_count,
            ),
            "trace_pilot": estimate_teacher_trace_cost(
                rollout_rows=rollouts,
                prices=prices,
                rollout_count=min(args.trace_pilot_rollouts, len(rollouts)),
                teacher_count=args.teacher_count,
            ),
        },
    }


def inspect_sparse_targets(*, args: argparse.Namespace, prices: Any) -> dict[str, Any]:
    sparse_path = repo_path(args.sparse_targets_path)
    rows = load_jsonl(sparse_path) if sparse_path.exists() else []
    shape_summary: dict[str, Any] | None = None
    shape_error: str | None = None
    if rows:
        try:
            shape_summary = validate_sparse_target_rows(rows)
        except Exception as exc:  # noqa: BLE001 - report readiness instead of crashing.
            shape_error = str(exc)
    return {
        "exists": sparse_path.exists(),
        "path": str(sparse_path),
        "target_count": len(rows),
        "shape_summary": shape_summary,
        "shape_error": shape_error,
        "ready": sparse_path.exists() and bool(rows) and shape_error is None,
        "costs": {
            "smoke": estimate_sparse_opd_cost(
                target_rows=rows,
                prices=prices,
                row_count=min(args.opd_smoke_rows, len(rows)),
            ),
            "pilot": estimate_sparse_opd_cost(
                target_rows=rows,
                prices=prices,
                row_count=min(args.opd_pilot_rows, len(rows)),
            ),
        },
    }


def build_commands(args: argparse.Namespace) -> dict[str, str]:
    teacher_args = " ".join(f"--teacher {value}" for value in args.teacher) or (
        "--teacher name=foldability,path=tinker://...,weight=0.35,temperature=0.7 "
        "--teacher name=family_active_site,path=tinker://...,weight=0.35,temperature=0.7 "
        "--teacher name=developability,path=tinker://...,weight=0.20,temperature=0.7 "
        "--teacher name=novelty_diversity,path=tinker://...,weight=0.10,temperature=0.7"
    )
    return {
        "dpo_shape": (
            ".venv/bin/python scripts/run_tinker_dpo_smoke.py "
            "--name phase8-bio-dpo-shape "
            f"--pairs-path {rel(repo_path(args.pairs_path))} --shape-only"
        ),
        "dpo_smoke": (
            ".venv/bin/python scripts/run_tinker_dpo_smoke.py "
            "--name phase8-bio-dpo-smoke "
            f"--pairs-path {rel(repo_path(args.pairs_path))} "
            f"--max-pairs {args.dpo_smoke_pairs} --batch-pairs 2 --model {args.model}"
        ),
        "teacher_trace_shape": (
            ".venv/bin/python scripts/build_tinker_teacher_traces.py "
            "--name phase8-teacher-traces "
            f"--rollouts-path {rel(repo_path(args.rollouts_path))} "
            f"{teacher_args} --shape-only"
        ),
        "teacher_trace_paid": (
            ".venv/bin/python scripts/build_tinker_teacher_traces.py "
            "--name phase8-teacher-traces "
            f"--rollouts-path {rel(repo_path(args.rollouts_path))} "
            f"{teacher_args} --top-k 20 --max-rollouts {args.trace_smoke_rollouts}"
        ),
        "build_sparse_targets": (
            ".venv/bin/python scripts/build_sparse_opd_targets.py "
            "--name phase8-sparse-opd-targets "
            f"--teacher-trace-path {rel(repo_path(args.teacher_traces_path))} --top-k 20"
        ),
        "sparse_opd_shape": (
            ".venv/bin/python scripts/run_tinker_sparse_opd_smoke.py "
            "--name phase8-sparse-opd-shape "
            f"--targets-path {rel(repo_path(args.sparse_targets_path))} --shape-only"
        ),
        "sparse_opd_smoke": (
            ".venv/bin/python scripts/run_tinker_sparse_opd_smoke.py "
            "--name phase8-sparse-opd-smoke "
            f"--targets-path {rel(repo_path(args.sparse_targets_path))} "
            f"--max-rows {args.opd_smoke_rows} --batch-size 2 --epochs 1 --model {args.model}"
        ),
    }


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def sanitize_name(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "-" for char in value]
    sanitized = "".join(chars).strip("-")
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized or "phase8-paid-readiness"


if __name__ == "__main__":
    main()
