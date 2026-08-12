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
    assert {
        (row["total_parameters_b"], row["active_parameters_b"]) for row in lightning
    } == {(30, 3)}
    assert {row["analysis_role"] for row in lightning} == {
        "matched_capacity_release_control"
    }


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


def test_frontier_manifest_budget_and_smoke_transition_are_fail_closed(
    tmp_path: Path,
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    executor = json.loads(
        (ROOT / "configs/experiments/frontier_adaptation_v2_executor.json").read_text()
    )
    manifest = manager.build_manifest(executor)
    assert len(manifest["phases"]) == 3
    smoke = manifest["phases"][0]
    assert smoke["evaluation_required"] is False
    assert (
        sum(wave["estimated_checkpoint_evaluation_cost_usd"] for wave in smoke["waves"])
        == 0
    )
    observed_training = sum(
        wave["estimated_training_cost_usd"]
        for phase in manifest["phases"]
        for wave in phase["waves"]
    )
    assert observed_training == 1910.2628
    assert observed_training <= executor["planned_training_ceiling_usd"]
    assert manifest["observed_continuation_recovery_overhead_usd"] == 3.3477
    assert manifest["planned_total_with_recovery_ceiling_usd"] == 2084.39
    assert (
        manifest["planned_total_with_recovery_ceiling_usd"]
        < executor["max_authorized_tinker_usd"]
    )
    assert (
        round(
            sum(
                wave["estimated_checkpoint_evaluation_cost_usd"]
                for phase in manifest["phases"]
                for wave in phase["waves"]
            ),
            2,
        )
        == 139.12
    )

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
        {
            "run_key": "smoke-a",
            "training_terminal_valid": True,
            "source_actions_run_id": 1,
        },
    )
    authorization = manager.next_authorization(
        manifest=tiny, state_dir=tmp_path, active_paid_cells=0
    )
    assert authorization["action"] == "training_and_checkpoint_evaluation_complete"

    tiny["phases"][0]["evaluation_required"] = True
    tiny["phases"][0]["waves"][0]["estimated_checkpoint_evaluation_cost_usd"] = 0.1
    waiting = manager.next_authorization(
        manifest=tiny, state_dir=tmp_path, active_paid_cells=1
    )
    assert waiting["action"] == "wait"
    assert waiting["reason"] == "paid_cells_are_active"


def test_frontier_ultra_continuation_authorizes_only_the_next_exact_segment(
    tmp_path: Path,
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    manifest = {
        "global_max_active_paid_cells": 6,
        "training_slicing": {
            "model_overrides": {
                "nemotron3-ultra": {
                    "initial_segment_steps": 100,
                    "continuation_segment_steps": 150,
                }
            }
        },
        "phases": [
            {
                "phase": "original:core",
                "campaign": "original",
                "stage": "core",
                "workflow": "frontier-adaptation-v2.yml",
                "config": "config.json",
                "plan_dir": "reports",
                "plan_sha": "plan",
                "artifact_prefix": "frontier-adaptation-v2-original-",
                "evaluation_workflow": "frontier-adaptation-v2-checkpoint-evaluation.yml",
                "evaluation_required": True,
                "waves": [
                    {
                        "wave_index": 1,
                        "run_keys": ["ultra-a"],
                        "run_model_tags": {"ultra-a": "nemotron3-ultra"},
                        "run_max_steps": {"ultra-a": 2250},
                        "estimated_training_cost_by_run_key": {"ultra-a": 57.4983},
                        "estimated_training_cost_usd": 57.4983,
                        "estimated_checkpoint_evaluation_cost_usd": 1.0,
                    }
                ],
            }
        ],
    }
    write_json(
        tmp_path / "continuations/training/ultra-a.json",
        {
            "run_key": "ultra-a",
            "training_continuation_valid": True,
            "completed_steps": 1,
            "source_actions_run_id": 31554744343,
        },
    )
    write_json(
        tmp_path / "submissions/training/ultra-a.json",
        {"run_key": "ultra-a", "source_actions_run_id": 31554744343},
    )
    authorization = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=0,
    )
    assert authorization["action"] == "dispatch_training_resume"
    assert authorization["authorized_run_keys"] == ["ultra-a"]
    assert authorization["source_actions_run_ids"] == {"ultra-a": 31554744343}
    assert authorization["completed_steps"] == {"ultra-a": 1}
    assert authorization["segment_end_steps"] == {"ultra-a": 151}
    assert 0 < authorization["estimated_cost_usd"] < 57.4983

    waiting = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=1,
    )
    assert waiting["action"] == "wait"


def rolling_manifest() -> dict:
    keys = ["sentinel", "a", "b", "c", "d", "e", "f", "g"]
    waves = []
    for wave_index, selected in enumerate((keys[:1], keys[1:6], keys[6:]), start=1):
        waves.append(
            {
                "wave_index": wave_index,
                "execution_orders": [keys.index(key) + 1 for key in selected],
                "run_keys": selected,
                "run_model_tags": {key: "test-model" for key in selected},
                "run_max_steps": {key: 100 for key in selected},
                "estimated_training_cost_by_run_key": {key: 1.0 for key in selected},
                "estimated_checkpoint_evaluation_cost_by_run_key": {
                    key: 0.1 for key in selected
                },
                "estimated_training_cost_usd": float(len(selected)),
                "estimated_checkpoint_evaluation_cost_usd": 0.1 * len(selected),
            }
        )
    return {
        "global_max_active_paid_cells": 6,
        "training_slicing": {
            "model_overrides": {
                "test-model": {
                    "initial_segment_steps": 20,
                    "continuation_segment_steps": 30,
                }
            }
        },
        "phases": [
            {
                "phase": "original:core",
                "campaign": "original",
                "stage": "core",
                "workflow": "frontier-adaptation-v2.yml",
                "config": "config.json",
                "plan_dir": "reports",
                "plan_sha": "plan",
                "artifact_prefix": "frontier-adaptation-v2-original-",
                "evaluation_workflow": "frontier-adaptation-v2-checkpoint-evaluation.yml",
                "evaluation_required": True,
                "scheduling": {
                    "mode": "rolling_ordered",
                    "sentinel_execution_orders": [1],
                },
                "waves": waves,
            }
        ],
    }


def active_row(run_key: str, run_id: int, *, kind: str = "training") -> dict:
    return {
        "actions_run_id": run_id,
        "kind": kind,
        "campaign": "original",
        "phase": "original:core",
        "run_key": run_key,
        "status": "in_progress",
    }


def write_terminal_pair(state_dir: Path, run_key: str, run_id: int = 1) -> None:
    write_json(
        state_dir / "receipts/training" / f"{run_key}.json",
        {
            "run_key": run_key,
            "training_terminal_valid": True,
            "source_actions_run_id": run_id,
        },
    )
    write_json(
        state_dir / "receipts/evaluation" / f"{run_key}.json",
        {"run_key": run_key, "evaluation_terminal_valid": True},
    )


def test_frontier_rolling_queue_opens_only_after_sentinel_and_fills_free_slots(
    tmp_path: Path,
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    manifest = rolling_manifest()
    waiting = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=1,
        active_runs=[active_row("sentinel", 10)],
    )
    assert waiting["action"] == "wait"
    assert waiting["reason"] == "eligible_rolling_cells_are_active"

    write_terminal_pair(tmp_path, "sentinel", 10)
    authorization = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=2,
        active_runs=[active_row("a", 11), active_row("b", 12)],
    )
    assert authorization["action"] == "dispatch_training_wave"
    assert authorization["authorized_run_keys"] == ["c", "d", "e", "f"]
    assert authorization["wave_indices_by_run_key"] == {"c": 2, "d": 2, "e": 2, "f": 3}
    assert authorization["max_active_after_dispatch"] == 6
    assert authorization["segment_end_steps"] == {
        "c": 20,
        "d": 20,
        "e": 20,
        "f": 20,
    }


def test_frontier_rolling_queue_prioritizes_resume_then_evaluation(
    tmp_path: Path,
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    manifest = rolling_manifest()
    write_terminal_pair(tmp_path, "sentinel")
    write_json(
        tmp_path / "continuations/training/a.json",
        {
            "run_key": "a",
            "training_continuation_valid": True,
            "completed_steps": 20,
            "source_actions_run_id": 20,
        },
    )
    write_json(
        tmp_path / "receipts/training/b.json",
        {"run_key": "b", "training_terminal_valid": True, "source_actions_run_id": 21},
    )
    resume = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=2,
        active_runs=[active_row("c", 22), active_row("d", 23)],
    )
    assert resume["action"] == "dispatch_training_resume"
    assert resume["authorized_run_keys"] == ["a"]
    assert resume["segment_end_steps"] == {"a": 50}
    assert resume["max_active_after_dispatch"] == 3

    (tmp_path / "continuations/training/a.json").unlink()
    write_terminal_pair(tmp_path, "a", 20)
    evaluate = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=2,
        active_runs=[active_row("c", 22), active_row("d", 23)],
    )
    assert evaluate["action"] == "dispatch_evaluation_wave"
    assert evaluate["authorized_run_keys"] == ["b"]
    assert evaluate["source_actions_run_ids"] == {"b": 21}


def test_frontier_rolling_queue_rejects_unknown_or_ambiguous_active_ownership(
    tmp_path: Path,
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    manifest = rolling_manifest()
    try:
        manager.next_authorization(
            manifest=manifest,
            state_dir=tmp_path,
            active_paid_cells=1,
            active_runs=[],
        )
    except RuntimeError as exc:
        assert "inventory disagrees" in str(exc)
    else:
        raise AssertionError("mismatched active inventory did not fail closed")

    duplicated = [active_row("sentinel", 30), active_row("sentinel", 31)]
    try:
        manager.next_authorization(
            manifest=manifest,
            state_dir=tmp_path,
            active_paid_cells=2,
            active_runs=duplicated,
        )
    except RuntimeError as exc:
        assert "duplicate or invalid ownership" in str(exc)
    else:
        raise AssertionError("duplicate active ownership did not fail closed")


def test_frontier_rolling_queue_allows_active_replication_after_original_completion(
    tmp_path: Path,
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    manifest = rolling_manifest()
    original = manifest["phases"][0]
    replication = json.loads(json.dumps(original))
    replication.update(
        {
            "phase": "replication:core",
            "campaign": "replication",
            "plan_sha": "replication-plan",
            "artifact_prefix": "frontier-adaptation-v2-replication-",
        }
    )
    for wave in replication["waves"]:
        wave["run_keys"] = [f"r-{key}" for key in wave["run_keys"]]
        wave["run_model_tags"] = {
            f"r-{key}": value for key, value in wave["run_model_tags"].items()
        }
        wave["run_max_steps"] = {
            f"r-{key}": value for key, value in wave["run_max_steps"].items()
        }
        wave["estimated_training_cost_by_run_key"] = {
            f"r-{key}": value
            for key, value in wave["estimated_training_cost_by_run_key"].items()
        }
        wave["estimated_checkpoint_evaluation_cost_by_run_key"] = {
            f"r-{key}": value
            for key, value in wave[
                "estimated_checkpoint_evaluation_cost_by_run_key"
            ].items()
        }
    manifest["phases"].append(replication)
    for wave in original["waves"]:
        for run_key in wave["run_keys"]:
            write_terminal_pair(tmp_path, run_key)
    active = active_row("r-sentinel", 40)
    active.update({"campaign": "replication", "phase": "replication:core"})
    waiting = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=1,
        active_runs=[active],
    )
    assert waiting["action"] == "wait"
    assert waiting["reason"] == "eligible_rolling_cells_are_active"


def test_frontier_executor_segments_every_frozen_model_without_changing_plan_hashes() -> (
    None
):
    manager = load_script("manage_scaling_paradox_campaign.py")
    executor = json.loads(
        (ROOT / "configs/experiments/frontier_adaptation_v2_executor.json").read_text()
    )
    manifest = manager.build_manifest(executor)
    assert set(manifest["training_slicing"]["model_overrides"]) == {
        "inkling-small",
        "inkling",
        "nemotron3-nano",
        "nemotron3-super",
        "nemotron3-ultra",
        "nemotron3p5-lightning",
        "gptoss-20b",
        "gptoss-120b",
    }
    for phase in manifest["phases"]:
        if phase["stage"] != "core":
            continue
        assert phase["scheduling"]["mode"] == "rolling_ordered"
        assert phase["scheduling"]["sentinel_execution_orders"] == [1]
        for wave in phase["waves"]:
            for run_key in wave["run_keys"]:
                assert (
                    0
                    < manager.training_segment_end(
                        manifest=manifest,
                        wave=wave,
                        run_key=run_key,
                        completed_steps=0,
                    )
                    < wave["run_max_steps"][run_key]
                )


def test_frontier_resume_worker_restores_inside_the_immutable_run_directory() -> None:
    worker = (ROOT / ".github/workflows/frontier-adaptation-v2.yml").read_text()
    supervisor = (
        ROOT / ".github/workflows/frontier-adaptation-v2-supervisor.yml"
    ).read_text()
    evaluator = (
        ROOT / ".github/workflows/frontier-adaptation-v2-checkpoint-evaluation.yml"
    ).read_text()
    trainer = (ROOT / "scripts/run_tinker_dpo_smoke.py").read_text()
    assert '--dir "$restore_dir"' in worker
    assert (
        'restore_dir="reports/frontier_adaptation_v2_original/runs/$INPUT_RUN_KEY"'
        in worker
    )
    assert (
        'restore_dir="reports/frontier_adaptation_v2_replication/runs/$INPUT_RUN_KEY"'
        in worker
    )
    assert "--dir ." not in worker
    assert "authorization_action={action}" in supervisor
    assert (
        "resume_run_id={authorization['source_actions_run_ids'][run_key]}" in supervisor
    )
    assert "create_training_client_from_state_with_optimizer" in trainer
    assert '--checkpoint-lineage "$lineage"' in evaluator


def test_frontier_structural_manifest_is_terminal_only_104_cells(
    tmp_path: Path,
) -> None:
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
                        {
                            "step": 2250,
                            "state_path": f"tinker://{row['run_key']}",
                            "terminal": True,
                        }
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
        "anchor_ref": "frontier-adaptation-v2-executor-v1.0.1",
        "jobs": [{"job_key": f"job-{index}"} for index in range(104)],
    }
    manifest["gmn_manifest_sha"] = sha256_value(manifest)
    manager.validate_manifest(manifest)
