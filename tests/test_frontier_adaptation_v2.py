from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pearl.scaling_campaign import sha256_value, write_json  # noqa: E402
from pearl.model_rendering import RendererContract, renderer_diagnostics  # noqa: E402


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_frontier_plans_freeze_96_unique_confirmatory_cells_and_renderers() -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    executor = json.loads(
        (ROOT / "configs/experiments/frontier_adaptation_v2_executor.json").read_text()
    )
    plans = manager.build_plans(executor)
    assert plans[("original", "smoke")]["launch_plan_contract_sha"] == (
        "5c81d3419992415bc7b4681027e2c79b4f9ccfd30a0364581fb376e2aa67bb8f"
    )
    assert plans[("original", "core")]["launch_plan_contract_sha"] == (
        "ce4fd33d9f5f8d62d42a4ddc383222adc18c48ba1399920073beaf44879842c6"
    )
    assert plans[("replication", "core")]["launch_plan_contract_sha"] == (
        "85660f7b99193e34a546f9eb50dfe18ff10fe42d3127232686be9b5ee7fd2593"
    )
    core = plans[("original", "core")]["runs"] + plans[("replication", "core")]["runs"]
    assert len(core) == len({row["run_key"] for row in core}) == 96
    assert {row["model_family"] for row in core} == {"inkling", "nemotron", "gpt_oss"}
    assert all(row["renderer"] != "raw_completion_v1" for row in core)
    lightning = [row for row in core if row["model_tag"] == "nemotron3p5-lightning"]
    assert {(row["total_parameters_b"], row["active_parameters_b"]) for row in lightning} == {(30, 3)}
    assert {row["analysis_role"] for row in lightning} == {"matched_capacity_release_control"}


def test_new_release_renderers_preserve_supervised_prefix_and_target_mask() -> None:
    for renderer, model in (
        ("inkling_tml_v0", "thinkingmachines/Inkling-Small"),
        (
            "nemotron3_disable_thinking",
            "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16",
        ),
    ):
        diagnostics = renderer_diagnostics(
            "Design a protein. Output only uppercase amino acid letters.",
            "ACDEFGHIKLMNPQRSTVWY",
            tokenizer=None,
            contract=RendererContract(name=renderer, model_name=model),
        )
        assert diagnostics["generation_is_supervised_prefix"] is True
        assert diagnostics["weighted_target_count"] > 0


def test_frontier_manifest_budget_and_smoke_transition_are_fail_closed(tmp_path: Path) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    executor = json.loads(
        (ROOT / "configs/experiments/frontier_adaptation_v2_executor.json").read_text()
    )
    manifest = manager.build_manifest(executor)
    assert len(manifest["phases"]) == 3
    smoke = manifest["phases"][0]
    assert smoke["evaluation_required"] is False
    assert sum(wave["estimated_checkpoint_evaluation_cost_usd"] for wave in smoke["waves"]) == 0
    observed_training = sum(
        wave["estimated_training_cost_usd"]
        for phase in manifest["phases"]
        for wave in phase["waves"]
    )
    assert observed_training == 1910.2628
    assert observed_training <= executor["planned_training_ceiling_usd"]
    assert round(
        sum(
            wave["estimated_checkpoint_evaluation_cost_usd"]
            for phase in manifest["phases"]
            for wave in phase["waves"]
        ),
        2,
    ) == 139.12

    tiny = {
        "global_max_active_paid_cells": 6,
        "phases": [
            {
                "phase": "original:smoke",
                "campaign": "original",
                "stage": "smoke",
                "workflow": "frontier-adaptation-v2.yml",
                "config": "config.json",
                "plan_dir": "reports",
                "plan_sha": "plan",
                "artifact_prefix": "frontier-adaptation-v2-original-",
                "evaluation_workflow": "frontier-adaptation-v2-checkpoint-evaluation.yml",
                "evaluation_required": False,
                "waves": [
                    {
                        "wave_index": 1,
                        "run_keys": ["smoke-a"],
                        "estimated_training_cost_usd": 1.0,
                        "estimated_checkpoint_evaluation_cost_usd": 0.0,
                    }
                ],
            }
        ],
    }
    write_json(
        tmp_path / "receipts/training/smoke-a.json",
        {"run_key": "smoke-a", "training_terminal_valid": True, "source_actions_run_id": 1},
    )
    authorization = manager.next_authorization(manifest=tiny, state_dir=tmp_path, active_paid_cells=0)
    assert authorization["action"] == "training_and_checkpoint_evaluation_complete"

    tiny["phases"][0]["evaluation_required"] = True
    tiny["phases"][0]["waves"][0]["estimated_checkpoint_evaluation_cost_usd"] = 0.1
    waiting = manager.next_authorization(manifest=tiny, state_dir=tmp_path, active_paid_cells=1)
    assert waiting["action"] == "wait"
    assert waiting["reason"] == "paid_cells_are_active"


def test_frontier_structural_manifest_is_terminal_only_104_cells(tmp_path: Path) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    executor = json.loads(
        (ROOT / "configs/experiments/frontier_adaptation_v2_executor.json").read_text()
    )
    plans = manager.build_plans(executor)
    state = tmp_path / "state"
    for cohort in ("original", "replication"):
        for row in plans[(cohort, "core")]["runs"]:
            write_json(
                state / "receipts/training" / f"{row['run_key']}.json",
                {
                    "training_terminal_valid": True,
                    "source_actions_run_id": 1,
                    "source_artifact_name": "artifact",
                    "run_contract_file_sha256": "a" * 64,
                    "training_report_file_sha256": "b" * 64,
                    "checkpoint_lineage_file_sha256": "c" * 64,
                    "checkpoint_lineage": [
                        {"step": 2250, "state_path": f"tinker://{row['run_key']}", "terminal": True}
                    ],
                },
            )
            write_json(
                state / "receipts/evaluation" / f"{row['run_key']}.json",
                {"evaluation_terminal_valid": True},
            )
    output = tmp_path / "structural_manifest.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_frontier_adaptation_structural_manifest.py"),
            "--state-dir",
            str(state),
            "--output",
            str(output),
        ],
        check=True,
        cwd=ROOT,
    )
    manifest = json.loads(output.read_text())
    assert manifest["job_count"] == len(manifest["jobs"]) == 104
    assert {row["checkpoint_step"] for row in manifest["jobs"]} == {0, 2250}
    assert sum(row["checkpoint_step"] == 0 for row in manifest["jobs"]) == 8
    assert manifest["estimated_sampling_cost_usd"] == 8.97


def test_frontier_gmn_contract_requires_104_unique_jobs() -> None:
    manager = load_script("manage_frontier_adaptation_gmn.py")
    manifest = {
        "contract": "pearl.frontier-adaptation-gmn-manifest/2",
        "max_active_jobs": 6,
        "source_commit_sha": "a" * 40,
        "anchor_ref": "frontier-adaptation-v2-executor-v1.0.0",
        "jobs": [{"job_key": f"job-{index}"} for index in range(104)],
    }
    manifest["gmn_manifest_sha"] = sha256_value(manifest)
    manager.validate_manifest(manifest)
