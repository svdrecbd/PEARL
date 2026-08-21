#!/usr/bin/env python3
"""Build the exact 104-cell structural-generation manifest from audited core receipts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pearl.phase8_readiness import (  # noqa: E402
    TINKER_MODEL_PRICES,
    cost_from_million_tokens,
    estimate_prompt_tokens,
)
from pearl.scaling_campaign import read_json, sha256_file, sha256_value, write_json  # noqa: E402


def load_manager() -> Any:
    path = ROOT / "scripts" / "manage_scaling_paradox_campaign.py"
    spec = importlib.util.spec_from_file_location("structural_manifest_manager", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load campaign manager")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def structural_cost(model: str, panel: list[dict[str, Any]], sample_seeds: list[int], max_tokens: int) -> float:
    prices = TINKER_MODEL_PRICES[model]
    prefill = sum(estimate_prompt_tokens(str(row["prompt"])) for row in panel) * len(sample_seeds)
    sample = len(panel) * len(sample_seeds) * max_tokens
    return round(
        cost_from_million_tokens(prefill, prices.prefill_per_million)
        + cost_from_million_tokens(sample, prices.sample_per_million),
        6,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    state_dir = Path(args.state_dir)
    manager = load_manager()
    executor = read_json(ROOT / "configs/experiments/frontier_adaptation_v2_executor.json")
    plans = manager.build_plans(executor)
    structural_configs = {
        "original": ROOT / "configs/experiments/frontier_adaptation_structural_v2_original.json",
        "replication": ROOT / "configs/experiments/frontier_adaptation_structural_v2_replication.json",
    }
    original_structural = read_json(structural_configs["original"])
    replication_structural = read_json(structural_configs["replication"])
    if (
        original_structural.get("contract") != "pearl.frontier-adaptation-structural/3"
        or replication_structural.get("contract") != "pearl.frontier-adaptation-structural/3"
    ):
        raise RuntimeError("frontier structural configs must use the v3 amendment contract")
    shared_keys = ("prompt_panel", "prompt_count", "sampling", "structure_gate")
    if any(
        original_structural[key] != replication_structural[key] for key in shared_keys
    ):
        raise RuntimeError("original and replication structural methods must remain identical")
    panel_path = ROOT / original_structural["prompt_panel"]
    panel = [json.loads(line) for line in panel_path.read_text().splitlines() if line.strip()]
    if len(panel) != int(original_structural["prompt_count"]):
        raise RuntimeError("structural prompt panel count differs from its frozen config")
    sample_seeds = [int(value) for value in original_structural["sampling"]["sample_seeds"]]
    if len(panel) * len(sample_seeds) != int(executor["structural_scope"]["candidates_per_cell"]):
        raise RuntimeError("structural candidate count differs from the frozen executor")
    max_tokens = int(original_structural["sampling"]["max_tokens"])
    jobs: list[dict[str, Any]] = []

    for model in read_json(ROOT / executor["campaigns"]["original"]["config"])["models"]:
        job = {
            "campaign": "shared_base",
            "structural_config": str(structural_configs["original"].relative_to(ROOT)),
            "model": model["model"],
            "model_tag": model["tag"],
            "arm": "base",
            "training_seed": 0,
            "checkpoint_step": 0,
            "checkpoint_path": None,
            "source_training": None,
            "estimated_sampling_cost_usd": structural_cost(model["model"], panel, sample_seeds, max_tokens),
        }
        job["structural_job_sha"] = sha256_value(job)
        job["job_key"] = f"struct-base-{model['tag']}-{job['structural_job_sha'][:10]}"
        jobs.append(job)

    schedules = {
        "original": [2250],
        "replication": [2250],
    }
    for cohort in ("original", "replication"):
        plan = plans[(cohort, "core")]
        config_path = structural_configs[cohort]
        for entry in plan["runs"]:
            run_key = entry["run_key"]
            training_path = state_dir / "receipts" / "training" / f"{run_key}.json"
            evaluation_path = state_dir / "receipts" / "evaluation" / f"{run_key}.json"
            if not training_path.is_file() or not evaluation_path.is_file():
                raise RuntimeError(f"structural manifest requires audited core cell {run_key}")
            training = read_json(training_path)
            evaluation = read_json(evaluation_path)
            if not training.get("training_terminal_valid") or not evaluation.get("evaluation_terminal_valid"):
                raise RuntimeError(f"structural source is not terminal-valid: {run_key}")
            lineage = {int(row["step"]): row for row in training["checkpoint_lineage"]}
            for step in schedules[cohort]:
                if step not in lineage:
                    raise RuntimeError(f"structural checkpoint step {step} is absent for {run_key}")
                job = {
                    "campaign": cohort,
                    "structural_config": str(config_path.relative_to(ROOT)),
                    "model": entry["model"],
                    "model_tag": entry["model_tag"],
                    "arm": entry["arm"],
                    "training_seed": int(entry["training_seed"]),
                    "checkpoint_step": step,
                    "checkpoint_path": lineage[step]["state_path"],
                    "source_training": {
                        "run_key": run_key,
                        "run_contract_sha": entry["run_contract_sha"],
                        "actions_run_id": training["source_actions_run_id"],
                        "artifact_name": training["source_artifact_name"],
                        "run_contract_file_sha256": training["run_contract_file_sha256"],
                        "training_report_file_sha256": training["training_report_file_sha256"],
                        "checkpoint_lineage_file_sha256": training[
                            "checkpoint_lineage_file_sha256"
                        ],
                    },
                    "estimated_sampling_cost_usd": structural_cost(
                        entry["model"], panel, sample_seeds, max_tokens
                    ),
                }
                job["structural_job_sha"] = sha256_value(job)
                job["job_key"] = (
                    f"struct-{cohort}-{entry['model_tag']}-{entry['arm']}-"
                    f"seed{entry['training_seed']}-step{step}-{job['structural_job_sha'][:10]}"
                )
                jobs.append(job)
    if len(jobs) != 104 or len({job["job_key"] for job in jobs}) != 104:
        raise RuntimeError("structural manifest must contain exactly 104 unique cells")
    waves = [
        {
            "wave_index": index // 6 + 1,
            "job_keys": [job["job_key"] for job in jobs[index : index + 6]],
        }
        for index in range(0, len(jobs), 6)
    ]
    payload = {
        "contract": "pearl.frontier-adaptation-structural-manifest/3",
        "source_commit_sha": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=ROOT,
        ).stdout.strip(),
        "scope": "eight shared base cells; original and replication core terminal only",
        "excluded_stages": ["smoke"],
        "prompt_panel_sha256": sha256_file(panel_path),
        "candidate_slots_per_job": len(panel) * len(sample_seeds),
        "job_count": len(jobs),
        "estimated_sampling_cost_usd": round(sum(job["estimated_sampling_cost_usd"] for job in jobs), 2),
        "jobs": jobs,
        "waves": waves,
    }
    if payload["estimated_sampling_cost_usd"] > float(executor["planned_structural_sampling_ceiling_usd"]):
        raise RuntimeError("structural sampling estimate exceeds the frozen ceiling")
    if float(executor["planned_total_tinker_ceiling_usd"]) > float(
        executor["max_authorized_tinker_usd"]
    ):
        raise RuntimeError("frozen total Tinker ceiling exceeds the authorized envelope")
    if round(
        float(executor["planned_pre_structural_tinker_ceiling_usd"])
        + float(executor["planned_structural_sampling_ceiling_usd"]),
        2,
    ) != float(executor["planned_total_tinker_ceiling_usd"]):
        raise RuntimeError("frozen Tinker component ceilings do not sum to the total ceiling")
    payload["structural_manifest_sha"] = sha256_value(payload)
    write_json(Path(args.output), payload)
    print(json.dumps({"status": "complete", "job_count": len(jobs), "waves": len(waves)}))


if __name__ == "__main__":
    main()
