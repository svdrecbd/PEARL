#!/usr/bin/env python3
"""Plan and safely launch one immutable PEARL scaling-paradox run at a time."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.phase8_readiness import (  # noqa: E402
    TINKER_MODEL_PRICES,
    estimate_dpo_cost,
    estimate_preference_evaluation_cost,
)
from pearl.model_rendering import RendererContract  # noqa: E402
from pearl.preference_distillation import load_jsonl  # noqa: E402


DEFAULT_CONFIG = ROOT / "configs" / "experiments" / "scaling_paradox_v1.json"
DEFAULT_PLAN_DIR = ROOT / "reports" / "scaling_paradox_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--stage", choices=("smoke", "core", "data_exposure", "adapter_rescue"), required=True)
    parser.add_argument("--plan-dir", default=str(DEFAULT_PLAN_DIR))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--run-key", help="Required with --execute; launches exactly one planned run")
    parser.add_argument("--confirm-contract-sha", help="Required with --execute")
    parser.add_argument("--resume", action="store_true", help="Resume the same immutable local run directory")
    parser.add_argument("--wait", action="store_true", help="Supervise the trainer and return only after it exits")
    return parser.parse_args()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def model_index(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["tag"]): dict(row) for row in config["models"]}


def dataset_for_arm(stage: dict[str, Any], arm: str) -> str:
    if stage.get("dataset_by_arm"):
        return str(stage["dataset_by_arm"][arm])
    return str(stage["dataset"])


def holdout_partition(dataset: str) -> str:
    return "d2p5_holdout_true" if dataset.startswith("d2p5") else "d10_holdout_true"


def base_contract(
    *,
    config: dict[str, Any],
    manifest: dict[str, Any],
    stage_name: str,
    model: dict[str, Any],
    dataset: str,
    arm: str,
    seed: int,
    tag: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    common = dict(config["common"])
    common.update(overrides or {})
    partition = manifest["partitions"][dataset]
    holdout_name = holdout_partition(dataset)
    holdout = manifest["partitions"][holdout_name]
    challenge = manifest["partitions"]["real_failure_challenge"]
    identity = {
        "campaign_id": config["campaign_id"],
        "stage": stage_name,
        "tag": tag,
        "model_tag": model["tag"],
        "model": model["model"],
        "arm": arm,
        "dataset_partition": dataset,
        "dataset_sha256": partition["sha256"],
        "holdout_partition": holdout_name,
        "holdout_sha256": holdout["sha256"],
        "challenge_sha256": challenge["sha256"],
        "dataset_manifest_sha256": manifest["manifest_sha256"],
        "training_seed": int(seed),
        "renderer": common["renderer"],
        "renderer_contract_fingerprint": RendererContract(
            name=common["renderer"], model_name=model["model"]
        ).fingerprint(),
        "rank": int(common["rank"]),
        "beta": float(common["beta"]),
        "learning_rate": float(common["learning_rate"]),
        "batch_pairs": int(common["batch_pairs"]),
        "max_steps": int(common["max_steps"]),
        "save_every_steps": int(common["save_every_steps"]),
        "max_pairs": common.get("max_pairs"),
        "max_challenge_pairs": common.get("max_challenge_pairs"),
    }
    identity["run_contract_sha"] = sha256_value(identity)
    identity["run_key"] = (
        f"{stage_name}-{tag}-{model['tag']}-{arm}-seed{seed}-"
        f"{identity['run_contract_sha'][:10]}"
    )
    identity["dataset_path"] = partition["path"]
    identity["holdout_path"] = holdout["path"]
    identity["challenge_path"] = challenge["path"]
    return identity


def build_stage_runs(config: dict[str, Any], manifest: dict[str, Any], stage_name: str) -> list[dict[str, Any]]:
    stage = config["stages"][stage_name]
    models = model_index(config)
    runs: list[dict[str, Any]] = []
    if stage_name in {"smoke", "core"}:
        for model_tag in stage["models"]:
            for arm in stage["arms"]:
                for seed in stage["seeds"]:
                    overrides = {
                        key: stage[key]
                        for key in ("max_pairs", "max_challenge_pairs", "max_steps", "rank")
                        if key in stage
                    }
                    runs.append(
                        base_contract(
                            config=config,
                            manifest=manifest,
                            stage_name=stage_name,
                            model=models[model_tag],
                            dataset=dataset_for_arm(stage, arm),
                            arm=arm,
                            seed=seed,
                            tag="fixed-rank",
                            overrides=overrides,
                        )
                    )
    elif stage_name == "data_exposure":
        for model_tag in stage["models"]:
            for cell in stage["cells"]:
                for seed in stage["seeds"]:
                    runs.append(
                        base_contract(
                            config=config,
                            manifest=manifest,
                            stage_name=stage_name,
                            model=models[model_tag],
                            dataset=cell["dataset"],
                            arm="true",
                            seed=seed,
                            tag=cell["tag"],
                            overrides={"max_steps": cell["max_steps"]},
                        )
                    )
    else:
        for model_tag in stage["models"]:
            for seed in stage["seeds"]:
                runs.append(
                    base_contract(
                        config=config,
                        manifest=manifest,
                        stage_name=stage_name,
                        model=models[model_tag],
                        dataset=stage["dataset"],
                        arm="true",
                        seed=seed,
                        tag=f"rank{stage['rank']}",
                        overrides={"rank": stage["rank"], "max_steps": stage["max_steps"]},
                    )
                )
    return runs


def estimate_run_cost(run: dict[str, Any]) -> dict[str, float]:
    rows = load_jsonl(repo_path(run["dataset_path"]))
    holdout_rows = load_jsonl(repo_path(run["holdout_path"]))
    pair_count = min(len(rows), int(run["max_pairs"])) if run.get("max_pairs") else len(rows)
    holdout_pair_count = (
        min(len(holdout_rows), int(run["max_challenge_pairs"]))
        if run.get("max_challenge_pairs")
        else len(holdout_rows)
    )
    batches_per_epoch = math.ceil(pair_count / int(run["batch_pairs"]))
    epochs = max(1, math.ceil(int(run["max_steps"]) / batches_per_epoch))
    prices = TINKER_MODEL_PRICES[str(run["model"])]
    training = estimate_dpo_cost(
        pair_rows=rows,
        prices=prices,
        pair_count=pair_count,
        epochs=epochs,
    )
    evaluation = estimate_preference_evaluation_cost(
        pair_rows=holdout_rows,
        prices=prices,
        pair_count=holdout_pair_count,
        policy_count=2,
    )
    return {
        **training,
        "estimated_epochs": float(epochs),
        "holdout_pair_count": float(holdout_pair_count),
        "estimated_holdout_prefill_tokens": evaluation["estimated_prefill_tokens"],
        "estimated_training_cost_usd": training["estimated_cost_usd"],
        "estimated_evaluation_cost_usd": evaluation["estimated_cost_usd"],
        "estimated_cost_usd": round(
            training["estimated_cost_usd"] + evaluation["estimated_cost_usd"], 4
        ),
    }


def build_plan(config: dict[str, Any], manifest: dict[str, Any], stage_name: str) -> dict[str, Any]:
    runs = build_stage_runs(config, manifest, stage_name)
    for run in runs:
        run["cost_estimate"] = estimate_run_cost(run)
    execution_order_seed = config["stages"][stage_name].get("execution_order_seed")
    if execution_order_seed is not None:
        runs.sort(
            key=lambda run: hashlib.sha256(
                f"{execution_order_seed}\0{run['run_contract_sha']}".encode("utf-8")
            ).hexdigest()
        )
    for execution_order, run in enumerate(runs, start=1):
        run["execution_order"] = execution_order
    contract_payload = {
        "campaign_id": config["campaign_id"],
        "stage": stage_name,
        "dataset_manifest_sha256": manifest["manifest_sha256"],
        "execution_order_seed": execution_order_seed,
        "runs": runs,
    }
    return {
        **contract_payload,
        "launch_plan_contract_sha": sha256_value(contract_payload),
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "estimated_stage_cost_usd": round(
            sum(run["cost_estimate"]["estimated_cost_usd"] for run in runs), 2
        ),
        "available_tinker_credit_usd": config["available_tinker_credit_usd"],
        "run_count": len(runs),
        "description": config["stages"][stage_name]["description"],
    }


def resolve_tinker_cli() -> str:
    explicit = os.environ.get("TINKER_CLI", "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise RuntimeError(f"TINKER_CLI is not an executable file: {candidate}")
        return str(candidate)
    sibling = Path(sys.executable).resolve().parent / "tinker"
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return str(sibling)
    local = ROOT / ".venv" / "bin" / "tinker"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    discovered = shutil.which("tinker")
    if discovered:
        return discovered
    raise RuntimeError("could not find the tinker CLI on PATH or in the project virtual environment")


def provider_contracts() -> tuple[set[str], set[str]]:
    cli = resolve_tinker_cli()
    result = subprocess.run(
        [cli, "-f", "json", "run", "list", "--limit=0"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    contract_shas: set[str] = set()
    run_keys: set[str] = set()
    for row in payload.get("runs", []):
        metadata = row.get("user_metadata") or {}
        if metadata.get("contract_sha"):
            contract_shas.add(str(metadata["contract_sha"]))
        if metadata.get("run_key"):
            run_keys.add(str(metadata["run_key"]))
    return contract_shas, run_keys


def launch_one(
    run: dict[str, Any], plan: dict[str, Any], plan_dir: Path, *, resume: bool, wait: bool
) -> tuple[int, int | None]:
    run_dir = plan_dir / "runs" / str(run["run_key"])
    contract_path = run_dir / "run_contract.json"
    if contract_path.exists() and not resume:
        raise RuntimeError(f"local run contract already exists: {contract_path}; use --resume only for this run")
    if resume:
        if not contract_path.exists():
            raise RuntimeError("--resume requires an existing local immutable run contract")
        if read_json(contract_path) != run:
            raise RuntimeError("local run contract differs from the current immutable launch plan")
        checkpoint_meta = run_dir / "checkpoint_meta.json"
        if not checkpoint_meta.exists():
            raise RuntimeError("--resume requires checkpoint_meta.json in the immutable run directory")
        active = subprocess.run(
            ["pgrep", "-f", f"--run-key {run['run_key']}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if active.returncode == 0:
            raise RuntimeError("an active local process already owns this run key")
    run_dir.mkdir(parents=True, exist_ok=True)
    preflight_path = run_dir / "launch_preflight.json"
    preflight = {
        "run_key": run["run_key"],
        "run_contract_sha": run["run_contract_sha"],
        "launch_plan_contract_sha": plan["launch_plan_contract_sha"],
        "status": "checking_provider",
        "paid_training_started": False,
    }
    preflight_path.write_text(json.dumps(preflight, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        provider_shas, provider_keys = provider_contracts()
    except Exception as error:
        preflight.update(
            {
                "status": "provider_preflight_failed",
                "failure": f"{type(error).__name__}: {error}",
            }
        )
        preflight_path.write_text(json.dumps(preflight, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise
    if not resume and (run["run_contract_sha"] in provider_shas or run["run_key"] in provider_keys):
        preflight["status"] = "duplicate_provider_contract"
        preflight_path.write_text(json.dumps(preflight, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise RuntimeError("provider already contains this immutable run contract; refusing a duplicate launch")

    preflight["status"] = "provider_preflight_passed"
    preflight_path.write_text(json.dumps(preflight, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not contract_path.exists():
        contract_path.write_text(json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    command = [
        sys.executable,
        "-u",
        str(ROOT / "scripts" / "run_tinker_dpo_smoke.py"),
        "--name",
        str(run["run_key"]),
        "--campaign-id",
        str(plan["campaign_id"]),
        "--run-key",
        str(run["run_key"]),
        "--contract-sha",
        str(run["run_contract_sha"]),
        "--model",
        str(run["model"]),
        "--renderer",
        str(run["renderer"]),
        "--pairs-path",
        str(run["dataset_path"]),
        "--output-dir",
        str(plan_dir / "runs"),
        "--challenge-pairs-path",
        str(run["holdout_path"]),
        "--require-challenge-chosen-disjoint",
        "--training-seed",
        str(run["training_seed"]),
        "--max-steps",
        str(run["max_steps"]),
        "--batch-pairs",
        str(run["batch_pairs"]),
        "--learning-rate",
        str(run["learning_rate"]),
        "--beta",
        str(run["beta"]),
        "--rank",
        str(run["rank"]),
        "--save-every-steps",
        str(run["save_every_steps"]),
    ]
    if run.get("max_pairs"):
        command.extend(["--max-pairs", str(run["max_pairs"])])
    if run.get("max_challenge_pairs"):
        command.extend(["--max-challenge-pairs", str(run["max_challenge_pairs"])])
    log_path = run_dir / "trainer.log"
    with log_path.open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(command, cwd=ROOT, env=os.environ.copy(), stdout=log_handle, stderr=subprocess.STDOUT)
    preflight.update({"status": "trainer_started", "paid_training_started": True, "pid": process.pid})
    preflight_path.write_text(json.dumps(preflight, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    launch_record = {
        "pid": process.pid,
        "launched_at_utc": datetime.now(UTC).isoformat(),
        "command": command,
        "launch_plan_contract_sha": plan["launch_plan_contract_sha"],
    }
    (run_dir / "launch_record.json").write_text(
        json.dumps(launch_record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return process.pid, process.wait() if wait else None


def main() -> None:
    args = parse_args()
    config = read_json(repo_path(args.config))
    manifest = read_json(repo_path(config["dataset_manifest"]))
    plan = build_plan(config, manifest, args.stage)
    plan_dir = repo_path(args.plan_dir)
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / f"{args.stage}_launch_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if not args.execute:
        print(json.dumps({"plan_path": str(plan_path), **plan}, indent=2, sort_keys=True))
        return
    if not args.run_key:
        raise SystemExit("--execute requires --run-key; bulk paid launch is intentionally unsupported")
    if args.confirm_contract_sha != plan["launch_plan_contract_sha"]:
        raise SystemExit("--confirm-contract-sha does not match the immutable launch plan")
    matches = [run for run in plan["runs"] if run["run_key"] == args.run_key]
    if len(matches) != 1:
        raise SystemExit(f"run key {args.run_key!r} is not unique in {plan_path}")
    if not os.environ.get("TINKER_API_KEY"):
        raise SystemExit("TINKER_API_KEY is required for paid execution")
    pid, returncode = launch_one(matches[0], plan, plan_dir, resume=args.resume, wait=args.wait)
    print(
        json.dumps(
            {"launched": args.run_key, "pid": pid, "returncode": returncode, "plan": str(plan_path)},
            indent=2,
        )
    )
    if returncode not in (None, 0):
        raise SystemExit(returncode)


if __name__ == "__main__":
    main()
