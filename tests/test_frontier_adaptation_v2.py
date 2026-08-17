from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

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


def test_local_controller_ledger_is_mirrored_and_hash_chained(tmp_path: Path) -> None:
    controller = load_script("manage_frontier_local_wave.py")
    state_dir = tmp_path / "state"
    mirror_dir = tmp_path / "mirror"

    first = controller.append_ledger(state_dir, mirror_dir, "prepared", {"value": 1})
    second = controller.append_ledger(state_dir, mirror_dir, "started", {"value": 2})

    assert second["previous_event_sha256"] == first["event_sha256"]
    assert controller.read_ledger(state_dir / "ledger.jsonl") == controller.read_ledger(
        mirror_dir / "ledger.jsonl"
    )

    mirror = mirror_dir / "ledger.jsonl"
    mirror.write_text(mirror.read_text().replace('"value":2', '"value":3'))
    with pytest.raises(RuntimeError):
        controller.append_ledger(state_dir, mirror_dir, "forbidden", {})


def test_local_controller_refuses_non_resume_authorization() -> None:
    controller = load_script("manage_frontier_local_wave.py")
    authorization = {
        "contract": "pearl.scaling-paradox-authorization/1",
        "action": "dispatch_training_wave",
    }
    authorization["authorization_sha256"] = sha256_value(authorization)
    executor = {"global_max_active_paid_cells": 47}
    manager = type("Manager", (), {"build_plans": staticmethod(lambda _: {})})

    with pytest.raises(RuntimeError, match="training-resume"):
        controller.validate_authorization(
            authorization,
            executor=executor,
            manager=manager,
        )


def test_local_controller_semantic_comparison_removes_only_snapshot_attestations() -> None:
    controller = load_script("manage_frontier_local_wave.py")
    first = {
        "authorization_sha256": "a" * 64,
        "capacity_gate_sha256": "b" * 64,
        "authorized_run_keys": ["cell-a"],
        "segment_end_steps": {"cell-a": 900},
        "capacity_gate": {
            "gate_sha256": "c" * 64,
            "provider_snapshot_sha256": "d" * 64,
            "operational_evidence": [{"run_key": "cell-a", "completed_steps": 100}],
        },
    }
    second = json.loads(json.dumps(first))
    second["authorization_sha256"] = "e" * 64
    second["capacity_gate_sha256"] = "f" * 64
    second["capacity_gate"]["gate_sha256"] = "0" * 64
    second["capacity_gate"]["provider_snapshot_sha256"] = "1" * 64

    assert controller.semantic_authorization_payload(first) == (
        controller.semantic_authorization_payload(second)
    )
    second["segment_end_steps"]["cell-a"] = 901
    assert controller.semantic_authorization_payload(first) != (
        controller.semantic_authorization_payload(second)
    )


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
    assert manifest["executor_contract"] == "pearl.frontier-adaptation-executor/7"
    assert executor["operational_amendment"] == {
        "contract": "pearl.frontier-operational-amendment/1",
        "frozen_date": "2026-08-16",
        "source_supervisor_actions_run_id": 31978917585,
        "source_child_count": 35,
        "evidence_fields": [
            "actions_run_id",
            "model_tag",
            "authorized_optimizer_updates",
            "created_at",
            "updated_at",
            "conclusion",
        ],
        "scientific_outcomes_consulted": False,
        "applies_only_to_future_continuation_authorizations": True,
        "automatic_refill_trigger": (
            "successful_supervisor_owned_training_or_evaluation_workflow_run_bound_to_immutable_supervisor_tag"
        ),
        "time_based_schedule": False,
    }
    assert manifest["global_max_active_paid_cells"] == 47
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
    assert manifest["observed_continuation_recovery_overhead_usd"] == 6.5524
    assert manifest["preauthorization_failure_quarantine_count"] == 34
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
                "run_contract_shas": [f"contract-{key}" for key in selected],
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


def ramped_manifest() -> dict:
    manifest = rolling_manifest()
    keys = ["sentinel", *[f"cell-{index:02d}" for index in range(1, 48)]]
    phase = manifest["phases"][0]
    phase["campaign_id"] = "pearl-frontier-adaptation-v2-original"
    phase["waves"] = []
    for wave_index, selected in enumerate((keys[:1], keys[1:]), start=1):
        phase["waves"].append(
            {
                "wave_index": wave_index,
                "execution_orders": [keys.index(key) + 1 for key in selected],
                "run_keys": selected,
                "run_contract_shas": [f"contract-{key}" for key in selected],
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
    phase["scheduling"]["capacity_ramp"] = {
        "contract": "pearl.frontier-capacity-ramp/1",
        "tiers": [
            {
                "name": "twelve",
                "max_active_cells": 12,
                "minimum_started_cells": 0,
                "observation_minutes": 0,
                "max_provider_staleness_minutes": 15,
            },
            {
                "name": "twenty_four",
                "max_active_cells": 24,
                "minimum_started_cells": 12,
                "observation_minutes": 20,
                "max_provider_staleness_minutes": 15,
            },
            {
                "name": "full_original_or_replication_cohort",
                "max_active_cells": 47,
                "minimum_started_cells": 24,
                "observation_minutes": 20,
                "max_provider_staleness_minutes": 15,
            },
        ],
    }
    manifest["global_max_active_paid_cells"] = 47
    return manifest


def ramp_active_row(run_key: str, run_id: int, *, minutes_old: int = 21) -> dict:
    row = active_row(run_key, run_id)
    row.update(
        {
            "run_contract_sha": f"contract-{run_key}",
            "started_at": (
                datetime.now(UTC) - timedelta(minutes=minutes_old)
            ).isoformat(),
        }
    )
    return row


def provider_snapshot(run_keys: list[str]) -> dict:
    now = datetime.now(UTC).isoformat()
    payload = {
        "contract": "pearl.frontier-provider-operational-snapshot/1",
        "observed_at_utc": now,
        "scientific_values_omitted": True,
        "runs": [
            {
                "provider_training_run_id": f"provider-{run_key}",
                "campaign_id": "pearl-frontier-adaptation-v2-original",
                "run_key": run_key,
                "run_contract_sha": f"contract-{run_key}",
                "corrupted": False,
                "last_request_time": now,
            }
            for run_key in run_keys
        ],
    }
    payload["snapshot_sha256"] = sha256_value(payload)
    return payload


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
    assert waiting["reason"] == "global_paid_cell_cap_is_full"

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
    assert waiting["reason"] == "global_paid_cell_cap_is_full"


def test_frontier_capacity_ramp_is_twelve_then_twenty_four_then_remaining_cohort(
    tmp_path: Path,
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    manifest = ramped_manifest()
    write_terminal_pair(tmp_path, "sentinel")

    first = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=0,
        active_runs=[],
        provider_snapshot=provider_snapshot([]),
    )
    assert first["action"] == "dispatch_training_wave"
    assert first["authorized_run_keys"] == [
        f"cell-{index:02d}" for index in range(1, 13)
    ]
    assert first["capacity_tier"] == "twelve"
    assert first["capacity_limit"] == 12

    first_keys = first["authorized_run_keys"]
    first_active = [
        ramp_active_row(key, 100 + index) for index, key in enumerate(first_keys)
    ]
    second = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=12,
        active_runs=first_active,
        provider_snapshot=provider_snapshot(first_keys),
    )
    assert second["action"] == "dispatch_training_wave"
    assert second["authorized_run_keys"] == [
        f"cell-{index:02d}" for index in range(13, 25)
    ]
    assert second["capacity_tier"] == "twenty_four"
    assert second["capacity_limit"] == 24
    assert second["capacity_gate_sha256"]

    first_twenty_four = [f"cell-{index:02d}" for index in range(1, 25)]
    all_active = [
        ramp_active_row(key, 200 + index) for index, key in enumerate(first_twenty_four)
    ]
    final = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=24,
        active_runs=all_active,
        provider_snapshot=provider_snapshot(first_twenty_four),
    )
    assert final["action"] == "dispatch_training_wave"
    assert final["authorized_run_keys"] == [
        f"cell-{index:02d}" for index in range(25, 48)
    ]
    assert final["capacity_tier"] == "full_original_or_replication_cohort"
    assert final["capacity_limit"] == 47
    assert final["max_active_after_dispatch"] == 47

    all_keys = [f"cell-{index:02d}" for index in range(1, 48)]
    full_active = [
        ramp_active_row(key, 500 + index, minutes_old=1)
        for index, key in enumerate(all_keys)
    ]
    full_wait = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=47,
        active_runs=full_active,
        provider_snapshot=provider_snapshot(all_keys),
    )
    assert full_wait["action"] == "wait"
    assert full_wait["reason"] == "global_paid_cell_cap_is_full"


def test_frontier_capacity_ramp_revalidates_gate_after_completed_cells_refill_slots(
    tmp_path: Path,
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    manifest = ramped_manifest()
    write_terminal_pair(tmp_path, "sentinel")

    for index in range(1, 13):
        run_key = f"cell-{index:02d}"
        training = {
            "run_key": run_key,
            "training_terminal_valid": True,
            "source_actions_run_id": index,
        }
        training["receipt_sha256"] = sha256_value(training)
        write_json(tmp_path / "receipts/training" / f"{run_key}.json", training)
        write_json(
            tmp_path / "receipts/evaluation" / f"{run_key}.json",
            {"run_key": run_key, "evaluation_terminal_valid": True},
        )

    active_keys = [f"cell-{index:02d}" for index in range(13, 37)]
    young = [
        ramp_active_row(run_key, 600 + index, minutes_old=1)
        for index, run_key in enumerate(active_keys)
    ]
    waiting = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=24,
        active_runs=young,
        provider_snapshot=provider_snapshot(active_keys),
    )
    assert waiting["action"] == "wait"
    assert waiting["reason"] == "global_paid_cell_cap_is_full"

    mature = [
        ramp_active_row(run_key, 700 + index)
        for index, run_key in enumerate(active_keys)
    ]
    final = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=24,
        active_runs=mature,
        provider_snapshot=provider_snapshot(active_keys),
    )
    assert final["action"] == "dispatch_training_wave"
    assert final["authorized_run_keys"] == [
        f"cell-{index:02d}" for index in range(37, 48)
    ]
    assert final["capacity_tier"] == "full_original_or_replication_cohort"
    assert len(final["capacity_gate"]["operational_evidence"]) == 24


def test_frontier_full_tier_starts_unexposed_cells_before_resuming(
    tmp_path: Path,
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    manifest = ramped_manifest()
    write_terminal_pair(tmp_path, "sentinel")

    for index in range(1, 13):
        run_key = f"cell-{index:02d}"
        training = {
            "run_key": run_key,
            "training_terminal_valid": True,
            "source_actions_run_id": index,
        }
        training["receipt_sha256"] = sha256_value(training)
        write_json(tmp_path / "receipts/training" / f"{run_key}.json", training)
        write_json(
            tmp_path / "receipts/evaluation" / f"{run_key}.json",
            {"run_key": run_key, "evaluation_terminal_valid": True},
        )

    for index in range(13, 37):
        run_key = f"cell-{index:02d}"
        continuation = {
            "run_key": run_key,
            "training_continuation_valid": True,
            "completed_steps": 20,
            "source_actions_run_id": 1000 + index,
        }
        continuation["receipt_sha256"] = sha256_value(continuation)
        write_json(
            tmp_path / "continuations/training" / f"{run_key}.json",
            continuation,
        )

    active_keys = [f"cell-{index:02d}" for index in range(30, 37)]
    active = [
        ramp_active_row(run_key, 2000 + index)
        for index, run_key in enumerate(active_keys)
    ]
    authorization = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=len(active),
        active_runs=active,
        provider_snapshot=provider_snapshot(active_keys),
    )

    assert authorization["action"] == "dispatch_training_wave"
    assert authorization["authorized_run_keys"] == [
        f"cell-{index:02d}" for index in range(37, 48)
    ]
    assert authorization["capacity_tier"] == (
        "full_original_or_replication_cohort"
    )
    assert authorization["scheduling_priority"] == (
        "full_tier_complete_cohort_exposure"
    )
    assert authorization["max_active_after_dispatch"] == 18

    for index in range(37, 48):
        run_key = f"cell-{index:02d}"
        continuation = {
            "run_key": run_key,
            "training_continuation_valid": True,
            "completed_steps": 20,
            "source_actions_run_id": 3000 + index,
        }
        continuation["receipt_sha256"] = sha256_value(continuation)
        write_json(
            tmp_path / "continuations/training" / f"{run_key}.json",
            continuation,
        )

    resumed = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=len(active),
        active_runs=active,
        provider_snapshot=provider_snapshot(active_keys),
    )
    assert resumed["action"] == "dispatch_training_resume"
    assert resumed["authorized_run_keys"][0] == "cell-13"
    assert resumed["scheduling_priority"] == "resume_then_evaluate_then_new"


def test_frontier_capacity_ramp_waits_for_observation_and_rejects_duplicate_provider_owner(
    tmp_path: Path,
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    manifest = ramped_manifest()
    write_terminal_pair(tmp_path, "sentinel")
    keys = [f"cell-{index:02d}" for index in range(1, 13)]
    young = [
        ramp_active_row(key, 300 + index, minutes_old=5)
        for index, key in enumerate(keys)
    ]
    waiting = manager.next_authorization(
        manifest=manifest,
        state_dir=tmp_path,
        active_paid_cells=12,
        active_runs=young,
        provider_snapshot=provider_snapshot(keys),
    )
    assert waiting["action"] == "wait"
    assert waiting["reason"] == "global_paid_cell_cap_is_full"

    duplicated = provider_snapshot(keys)
    duplicated["runs"].append(
        {
            **duplicated["runs"][0],
            "provider_training_run_id": "unexpected-second-owner",
        }
    )
    duplicated["snapshot_sha256"] = sha256_value(
        {key: value for key, value in duplicated.items() if key != "snapshot_sha256"}
    )
    mature = [ramp_active_row(key, 400 + index) for index, key in enumerate(keys)]
    try:
        manager.next_authorization(
            manifest=manifest,
            state_dir=tmp_path,
            active_paid_cells=12,
            active_runs=mature,
            provider_snapshot=duplicated,
        )
    except RuntimeError as exc:
        assert "duplicate provider DPO ownership" in str(exc)
    else:
        raise AssertionError("capacity ramp accepted duplicate provider ownership")


def test_frontier_inventory_stops_when_a_worker_finishes_after_reconstruction(
    tmp_path: Path,
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    manifest = {
        "phases": [
            {
                "phase": "original:core",
                "campaign": "original",
                "waves": [
                    {
                        "run_keys": ["cell-a"],
                        "run_contract_shas": ["contract-a"],
                    }
                ],
            }
        ]
    }
    terminal = {
        "databaseId": 101,
        "displayTitle": "Frontier train original cell-a supervisor-99",
        "status": "completed",
    }
    with pytest.raises(
        manager.TerminalAfterReconstructionError,
        match="became terminal after artifact reconstruction",
    ):
        manager.build_paid_actions_inventory(
            manifest=manifest,
            state_dir=tmp_path,
            rows_by_kind={"training": [terminal], "evaluation": []},
        )

    write_json(
        tmp_path / "actions_runs/training/101.json",
        {"actions_run_id": 101, "run_key": "cell-a"},
    )
    assert (
        manager.build_paid_actions_inventory(
            manifest=manifest,
            state_dir=tmp_path,
            rows_by_kind={"training": [terminal], "evaluation": []},
        )
        == []
    )

    active = {
        **terminal,
        "databaseId": 102,
        "status": "in_progress",
        "createdAt": "2026-08-15T00:00:00Z",
        "startedAt": "2026-08-15T00:00:01Z",
        "updatedAt": "2026-08-15T00:00:02Z",
    }
    inventory = manager.build_paid_actions_inventory(
        manifest=manifest,
        state_dir=tmp_path,
        rows_by_kind={"training": [active], "evaluation": []},
    )
    assert [row["actions_run_id"] for row in inventory] == [102]


def test_frontier_inventory_exposes_only_terminal_boundary_as_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")

    def terminal_boundary(**_: object) -> list[dict[str, object]]:
        raise manager.TerminalAfterReconstructionError("crossed boundary")

    monkeypatch.setattr(manager, "query_paid_actions_inventory", terminal_boundary)
    with pytest.raises(SystemExit) as retryable:
        manager.write_paid_actions_inventory(
            executor={}, manifest={}, state_dir=tmp_path, output=tmp_path / "active.json"
        )
    assert retryable.value.code == manager.TERMINAL_AFTER_RECONSTRUCTION_EXIT_CODE == 75
    assert not (tmp_path / "active.json").exists()

    def other_failure(**_: object) -> list[dict[str, object]]:
        raise RuntimeError("not retryable")

    monkeypatch.setattr(manager, "query_paid_actions_inventory", other_failure)
    with pytest.raises(RuntimeError, match="not retryable"):
        manager.write_paid_actions_inventory(
            executor={}, manifest={}, state_dir=tmp_path, output=tmp_path / "active.json"
        )


def test_frontier_inventory_convergence_absorbs_more_than_three_crossings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    query_count = 0
    sync_count = 0

    def changing_inventory(**_: object) -> list[dict[str, object]]:
        nonlocal query_count
        query_count += 1
        if query_count <= 4:
            raise manager.TerminalAfterReconstructionError(
                f"crossed boundary {query_count}"
            )
        return [{"actions_run_id": 900, "run_key": "still-active"}]

    def reconstruct(**_: object) -> dict[str, int]:
        nonlocal sync_count
        sync_count += 1
        write_json(
            tmp_path / "actions_runs/training" / f"{sync_count}.json",
            {"actions_run_id": sync_count},
        )
        return {"training": 1, "evaluation": 0}

    monkeypatch.setattr(manager, "query_paid_actions_inventory", changing_inventory)
    monkeypatch.setattr(manager, "sync_github_state", reconstruct)
    monkeypatch.setattr(
        manager,
        "build_provider_snapshot",
        lambda _: {"scientific_values_omitted": True},
    )
    monkeypatch.setattr(manager.time, "sleep", lambda _: None)

    inventory = manager.converge_paid_actions_inventory(
        executor={},
        plans={},
        manifest={"global_max_active_paid_cells": 47},
        state_dir=tmp_path,
        output=tmp_path / "active.json",
        provider_output=tmp_path / "provider.json",
    )

    assert inventory == [{"actions_run_id": 900, "run_key": "still-active"}]
    assert query_count == 5
    assert sync_count == 4
    assert json.loads((tmp_path / "active.json").read_text()) == inventory
    assert json.loads((tmp_path / "provider.json").read_text()) == {
        "scientific_values_omitted": True
    }


def test_frontier_inventory_convergence_requires_auditable_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")

    def terminal_boundary(**_: object) -> list[dict[str, object]]:
        raise manager.TerminalAfterReconstructionError("crossed boundary")

    monkeypatch.setattr(manager, "query_paid_actions_inventory", terminal_boundary)
    monkeypatch.setattr(
        manager,
        "sync_github_state",
        lambda **_: {"training": 0, "evaluation": 0},
    )
    monkeypatch.setattr(manager.time, "sleep", lambda _: None)

    with pytest.raises(RuntimeError, match="made no auditable progress"):
        manager.converge_paid_actions_inventory(
            executor={},
            plans={},
            manifest={"global_max_active_paid_cells": 47},
            state_dir=tmp_path,
            output=tmp_path / "active.json",
            provider_output=tmp_path / "provider.json",
        )


def test_frontier_inventory_convergence_cannot_exceed_active_cell_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    sync_count = 0

    def terminal_boundary(**_: object) -> list[dict[str, object]]:
        raise manager.TerminalAfterReconstructionError("crossed boundary")

    def reconstruct(**_: object) -> dict[str, int]:
        nonlocal sync_count
        sync_count += 1
        write_json(
            tmp_path / "actions_runs/training" / f"{sync_count}.json",
            {"actions_run_id": sync_count},
        )
        return {"training": 1, "evaluation": 0}

    monkeypatch.setattr(manager, "query_paid_actions_inventory", terminal_boundary)
    monkeypatch.setattr(manager, "sync_github_state", reconstruct)
    monkeypatch.setattr(
        manager,
        "build_provider_snapshot",
        lambda _: {"scientific_values_omitted": True},
    )
    monkeypatch.setattr(manager.time, "sleep", lambda _: None)

    with pytest.raises(RuntimeError, match="exceeded the frozen active-cell cap"):
        manager.converge_paid_actions_inventory(
            executor={},
            plans={},
            manifest={"global_max_active_paid_cells": 2},
            state_dir=tmp_path,
            output=tmp_path / "active.json",
            provider_output=tmp_path / "provider.json",
        )
    assert sync_count == 2


def test_frontier_semantic_dispatch_claim_cannot_be_consumed_twice(
    tmp_path: Path,
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    authorization = {
        "action": "dispatch_training_resume",
        "campaign": "original",
        "stage": "core",
        "authorized_run_keys": ["cell-a"],
        "source_actions_run_ids": {"cell-a": 100},
        "segment_end_steps": {"cell-a": 650},
    }
    consumed = manager.dispatch_claim(
        action="dispatch_training_resume",
        campaign="original",
        stage="core",
        run_key="cell-a",
        source_actions_run_id=100,
        segment_end_step=650,
    )
    write_json(
        tmp_path / "actions_runs/training/200.json",
        {
            "actions_run_id": 200,
            "run_key": "cell-a",
            "dispatch_claim_sha256": consumed["dispatch_claim_sha256"],
        },
    )
    with pytest.raises(RuntimeError, match="semantic dispatch claim was already consumed"):
        manager.attach_and_validate_dispatch_claims(tmp_path, authorization)

    authorization["segment_end_steps"]["cell-a"] = 900
    manager.attach_and_validate_dispatch_claims(tmp_path, authorization)
    assert authorization["dispatch_claims"]["cell-a"]["segment_end_step"] == 900


def test_frontier_redundant_quarantine_claims_are_exact_and_unique() -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    executor = json.loads(
        (ROOT / "configs/experiments/frontier_adaptation_v2_executor.json").read_text()
    )
    claims = manager.validate_redundant_quarantine(
        executor, manager.build_plans(executor)
    )
    assert set(map(int, claims)) == {
        31872368393,
        31872376941,
        31872940776,
        31872956133,
    }
    assert len({row["canonical_actions_run_id"] for row in claims.values()}) == 4
    assert len(
        {row["redundant_provider_training_run_id"] for row in claims.values()}
    ) == 4
    assert all(
        row["reason"]
        == "duplicate concurrent continuation dispatched before prior slice became observable"
        for row in claims.values()
    )


def test_frontier_quarantine_preserves_canonical_branch_and_rejects_prefix_drift(
    tmp_path: Path,
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    prior = {
        "run_key": "cell-a",
        "source_actions_run_id": 200,
        "completed_steps": 650,
        "receipt_sha256": "a" * 64,
        "checkpoint_lineage": [
            {
                "step": 400,
                "state_path": "tinker://source/weights/400",
                "terminal": False,
            },
            {
                "step": 650,
                "state_path": "tinker://canonical/weights/650",
                "terminal": False,
            },
        ],
    }
    redundant = {
        "run_key": "cell-a",
        "source_actions_run_id": 201,
        "completed_steps": 650,
        "receipt_sha256": "b" * 64,
        "checkpoint_lineage": [
            {
                "step": 400,
                "state_path": "tinker://source/weights/400",
                "terminal": False,
            },
            {
                "step": 650,
                "state_path": "tinker://redundant/weights/650",
                "terminal": False,
            },
        ],
    }
    claim = {
        "canonical_actions_run_id": 200,
        "expected_source_actions_run_id": 100,
        "expected_source_completed_steps": 400,
        "expected_completed_steps": 650,
        "canonical_provider_training_run_id": "canonical",
        "redundant_provider_training_run_id": "redundant",
    }
    worker_auth = {
        "action": "dispatch_training_resume",
        "campaign": "original",
        "stage": "core",
        "run_key": "cell-a",
        "source_training_actions_run_id": 100,
        "segment_end_step": 650,
    }
    source_marker = {
        "run_key": "cell-a",
        "checkpoint_lineage": [
            {
                "step": 400,
                "state_path": "tinker://source/weights/400",
                "terminal": False,
            }
        ],
    }
    write_json(tmp_path / "actions_runs/training/100.json", source_marker)
    manager.quarantine_redundant_continuation(
        state_dir=tmp_path,
        actions_run_id=201,
        claim=claim,
        prior=prior,
        receipt=redundant,
        worker_auth=worker_auth,
    )
    quarantine = json.loads(
        (tmp_path / "quarantines/training/201.json").read_text()
    )
    assert quarantine["canonical_actions_run_id"] == 200
    assert quarantine["disposition"] == (
        "excluded_operational_duplicate_not_a_replicate"
    )
    assert prior["source_actions_run_id"] == 200

    drifted = json.loads(json.dumps(redundant))
    drifted["checkpoint_lineage"][0]["state_path"] = (
        "tinker://different-source/weights/400"
    )
    write_json(
        tmp_path / "drifted/actions_runs/training/100.json", source_marker
    )
    with pytest.raises(RuntimeError, match="diverges before"):
        manager.quarantine_redundant_continuation(
            state_dir=tmp_path / "drifted",
            actions_run_id=202,
            claim=claim,
            prior=prior,
            receipt=drifted,
            worker_auth=worker_auth,
        )


def test_frontier_executor_segments_every_frozen_model_without_changing_plan_hashes() -> (
    None
):
    manager = load_script("manage_scaling_paradox_campaign.py")
    executor = json.loads(
        (ROOT / "configs/experiments/frontier_adaptation_v2_executor.json").read_text()
    )
    manifest = manager.build_manifest(executor)
    assert manifest["training_slicing"]["contract"] == (
        "pearl.frontier-training-slicing/3"
    )
    expected_segment_widths = {
        "inkling-small": (150, 500),
        "inkling": (100, 300),
        "nemotron3-nano": (250, 800),
        "nemotron3-super": (150, 500),
        "nemotron3-ultra": (100, 250),
        "nemotron3p5-lightning": (250, 800),
        "gptoss-20b": (300, 900),
        "gptoss-120b": (250, 800),
    }
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
        assert [
            row["max_active_cells"]
            for row in phase["scheduling"]["capacity_ramp"]["tiers"]
        ] == [12, 24, 47]
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
                initial, continuation = expected_segment_widths[
                    wave["run_model_tags"][run_key]
                ]
                assert manager.training_segment_end(
                    manifest=manifest,
                    wave=wave,
                    run_key=run_key,
                    completed_steps=0,
                ) == min(initial, wave["run_max_steps"][run_key])
                assert manager.training_segment_end(
                    manifest=manifest,
                    wave=wave,
                    run_key=run_key,
                    completed_steps=initial,
                ) == min(
                    initial + continuation,
                    wave["run_max_steps"][run_key],
                )


def test_frontier_resume_worker_restores_inside_the_immutable_run_directory() -> None:
    worker = (ROOT / ".github/workflows/frontier-adaptation-v2.yml").read_text()
    supervisor = (
        ROOT / ".github/workflows/frontier-adaptation-v2-supervisor.yml"
    ).read_text()
    evaluator = (
        ROOT / ".github/workflows/frontier-adaptation-v2-checkpoint-evaluation.yml"
    ).read_text()
    manager = (ROOT / "scripts/manage_scaling_paradox_campaign.py").read_text()
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
    assert "provider-snapshot" in supervisor
    assert "secrets.TINKER_API_KEY" in supervisor
    assert "write-active-inventory" in manager
    assert "converge-active-inventory" in supervisor
    assert "terminal_boundary_crossings_reconciled" in manager
    assert "terminal-boundary reconstruction made no auditable progress" in manager
    assert supervisor.count("sync-github --state-dir") == 1
    assert "provider-snapshot \\" in supervisor
    assert '--provider-output "$STATE_DIR/provider_snapshot.json"' in supervisor
    assert (
        '"createdAt,databaseId,displayTitle,startedAt,status,updatedAt"' in manager
    )
    assert '--provider-snapshot "$STATE_DIR/provider_snapshot.json"' in supervisor
    assert "workflow_run:" in supervisor
    assert "frontier-supervisor-" in supervisor
    assert "github.event.workflow_run.conclusion == 'success'" in supervisor
    assert "github.event.workflow_run.event == 'workflow_dispatch'" in supervisor
    assert "supervisor-validate" in supervisor
    assert 'SUPERVISOR_MODE: ${{' in supervisor
    assert '"$SUPERVISOR_MODE" == advance' in supervisor
    assert "schedule:" not in supervisor
    assert supervisor.count('"--ref", os.environ["DISPATCH_REF"]') == 2
    assert '"--ref", "main"' not in supervisor
    assert "frontier-supervisor-${GITHUB_RUN_ID}" in supervisor
    assert "gh api graphql" in supervisor
    assert "ref(qualifiedName: $qualifiedName)" in supervisor
    assert ".data.repository.ref.target.oid // \"\"" in supervisor
    assert '== *"Not Found"*' not in supervisor
    assert "|| echo \"\"" not in supervisor
    assert "|| true" not in supervisor
    assert 'test "$observed" = "$GITHUB_SHA"' in supervisor
    assert "contents: write" in supervisor
    assert "TRIGGER_HEAD_SHA" in supervisor
    assert "automatic trigger differs from its immutable supervisor tag" in supervisor
    refuse_index = supervisor.index("- name: Refuse reuse of a prior authorization")
    tag_index = supervisor.index(
        "- name: Create and verify the immutable supervisor dispatch tag"
    )
    publish_index = supervisor.index("- name: Publish one-time supervisor authorization")
    dispatch_index = supervisor.index(
        "- name: Dispatch and identify every authorized child"
    )
    assert refuse_index < tag_index < publish_index < dispatch_index
    assert (
        'receipt_path.write_text(json.dumps({"dispatches": records}' in supervisor
    )


def test_frontier_dataset_restore_does_not_use_the_installation_api() -> None:
    workflow_paths = (
        ".github/workflows/frontier-adaptation-v2-supervisor.yml",
        ".github/workflows/frontier-adaptation-v2.yml",
        ".github/workflows/frontier-adaptation-v2-checkpoint-evaluation.yml",
        ".github/workflows/frontier-adaptation-v2-structural-supervisor.yml",
    )
    expected_digest = (
        "ffad79ec8e104bf06979882e186290ea4d94b87531e48b111e954b6c09e8e962"
    )
    for workflow_path in workflow_paths:
        workflow = (ROOT / workflow_path).read_text()
        assert 'gh release download "$DATA_RELEASE_TAG"' not in workflow
        assert "curl --fail --location --silent --show-error" in workflow
        assert "--retry 5 --retry-all-errors --retry-delay 2" in workflow
        assert "--connect-timeout 20 --max-time 300" in workflow
        assert (
            "https://github.com/${GITHUB_REPOSITORY}/releases/download/"
            "${DATA_RELEASE_TAG}/${DATA_ARCHIVE}"
        ) in workflow
        assert expected_digest in workflow
        assert "sha256sum --check --strict" in workflow


def test_frontier_preauthorization_failure_is_exact_zero_spend_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = load_script("manage_scaling_paradox_campaign.py")
    run_key = "core-fixed-rank-model-true-seed17-deadbeef00"
    actions_run_id = 123
    supervisor_id = 100
    claim = {
        "run_key": run_key,
        "source_supervisor_actions_run_id": supervisor_id,
        "source_supervisor_head_sha": "a" * 40,
        "source_authorization_sha256": "b" * 64,
        "worker_head_sha": "c" * 40,
        "expected_job_name": "train",
        "expected_step_conclusions": {
            "Verify immutable plan identity": "success",
            "Verify one-time supervisor authorization": "failure",
            "Verify Tinker provider access without spending": "skipped",
            "Run one supervised Tinker cell": "skipped",
            "Validate terminal or resumable segment report": "skipped",
        },
        "expected_failure_message": "worker and supervisor source commits differ",
        "disposition": (
            "excluded_pre_authorization_shell_zero_spend_no_scientific_observation"
        ),
    }
    title = f"Frontier train original {run_key} supervisor-{supervisor_id}"
    row = {
        "databaseId": actions_run_id,
        "status": "completed",
        "conclusion": "failure",
        "headSha": "c" * 40,
        "displayTitle": title,
    }
    steps = [
        {"name": name, "conclusion": conclusion}
        for name, conclusion in claim["expected_step_conclusions"].items()
    ]
    detail = {
        **row,
        "jobs": [
            {
                "name": "train",
                "status": "completed",
                "conclusion": "failure",
                "steps": steps,
            }
        ],
    }

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if "--json" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps(detail), "")
        return subprocess.CompletedProcess(
            command,
            0,
            "worker and supervisor source commits differ",
            "",
        )

    monkeypatch.setattr(manager.subprocess, "run", fake_run)
    receipt = manager.audit_preauthorization_failure(
        state_dir=tmp_path,
        actions_run_id=actions_run_id,
        row=row,
        claim=claim,
        kind="training",
    )
    assert receipt["provider_accessed"] is False
    assert receipt["training_started"] is False
    assert receipt["estimated_tinker_spend_usd"] == 0.0
    assert receipt["scientific_observation_created"] is False
    assert receipt["scientific_dispatch_claim_consumed"] is False
    marker = json.loads(
        (tmp_path / f"actions_runs/training/{actions_run_id}.json").read_text()
    )
    assert "dispatch_claim_sha256" not in marker

    detail["jobs"][0]["steps"][3]["conclusion"] = "success"
    with pytest.raises(RuntimeError, match="crossed its zero-spend boundary"):
        manager.audit_preauthorization_failure(
            state_dir=tmp_path / "unsafe",
            actions_run_id=actions_run_id,
            row=row,
            claim=claim,
            kind="training",
        )


def test_frontier_provider_snapshot_is_result_blind_and_rejects_unknown_contracts() -> (
    None
):
    manager = load_script("manage_scaling_paradox_campaign.py")
    plan_row = {
        "campaign_id": "pearl-frontier-adaptation-v2-original",
        "run_key": "run-a",
        "run_contract_sha": "contract-a",
    }
    provider_rows = [
        {
            "training_run_id": "provider-a",
            "corrupted": False,
            "last_request_time": datetime.now(UTC).isoformat(),
            "user_metadata": {
                "pearl_task": "physical_to_sequence_dpo",
                "campaign_id": plan_row["campaign_id"],
                "run_key": plan_row["run_key"],
                "contract_sha": plan_row["run_contract_sha"],
            },
            "scientific_loss_that_must_not_escape": 123.0,
        }
    ]
    manager.load_launcher = lambda: type(
        "Launcher", (), {"provider_runs": staticmethod(lambda: provider_rows)}
    )
    snapshot = manager.build_provider_snapshot(
        {("original", "core"): {"runs": [plan_row]}}
    )
    serialized = json.dumps(snapshot)
    assert snapshot["scientific_values_omitted"] is True
    assert "scientific_loss" not in serialized
    assert snapshot["runs"][0]["provider_training_run_id"] == "provider-a"
    assert snapshot["snapshot_sha256"] == sha256_value(
        {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    )

    provider_rows[:] = [
        {
            "training_run_id": "provider-b",
            "corrupted": False,
            "last_request_time": datetime.now(UTC).isoformat(),
            "user_metadata": {
                "pearl_task": "physical_to_sequence_dpo",
                "campaign_id": "pearl-frontier-adaptation-v2-original",
                "run_key": "unknown",
                "contract_sha": "unknown",
            },
        }
    ]
    try:
        manager.build_provider_snapshot({("original", "core"): {"runs": [plan_row]}})
    except RuntimeError as exc:
        assert "outside the frozen plans" in str(exc)
    else:
        raise AssertionError("unknown provider contract was accepted")


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
