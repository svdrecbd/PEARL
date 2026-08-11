from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pearl.scaling_campaign import (  # noqa: E402
    audit_evaluation_artifact,
    audit_provider_identity,
    audit_training_artifact,
    sha256_file,
    write_json,
)


def load_manager():
    path = ROOT / "scripts" / "manage_scaling_paradox_campaign.py"
    spec = importlib.util.spec_from_file_location("campaign_manager_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_analysis():
    path = ROOT / "scripts" / "analyze_scaling_paradox_optimization.py"
    spec = importlib.util.spec_from_file_location("optimization_analysis_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_gmn_manager():
    path = ROOT / "scripts" / "manage_scaling_paradox_gmn.py"
    spec = importlib.util.spec_from_file_location("gmn_manager_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def plan_entry() -> dict:
    return {
        "campaign_id": "campaign",
        "run_key": "cell-1",
        "run_contract_sha": "contract-sha",
        "training_seed": 17,
        "model": "model",
        "max_steps": 2,
        "holdout_sha256": "holdout-sha",
        "challenge_sha256": "challenge-sha",
    }


def test_training_and_evaluation_audits_fail_closed(tmp_path: Path) -> None:
    entry = plan_entry()
    run_dir = tmp_path / "run"
    write_json(run_dir / "run_contract.json", entry)
    write_json(
        run_dir / "report.json",
        {
            "contract_sha": "contract-sha",
            "run_key": "cell-1",
            "campaign_id": "campaign",
            "training_seed": 17,
            "base_model": "model",
            "batches": [{}, {}],
            "checkpoint_path": "tinker://terminal",
        },
    )
    write_json(
        run_dir / "checkpoint_lineage.json",
        {
            "contract_sha": "contract-sha",
            "checkpoints": [
                {"step": 1, "state_path": "tinker://one", "terminal": False},
                {"step": 2, "state_path": "tinker://terminal", "terminal": True},
            ],
        },
    )
    training = audit_training_artifact(plan_entry=entry, run_dir=run_dir, source_actions_run_id=42)
    assert training["training_terminal_valid"] is True
    assert training["source_actions_run_id"] == 42

    evaluation_dir = tmp_path / "evaluation"
    evaluation_report = {
        "status": "complete",
        "complete": True,
        "contract": {
            "source_run_key": "cell-1",
            "source_run_contract_sha": "contract-sha",
            "holdout_sha256": "holdout-sha",
            "challenge_sha256": "challenge-sha",
            "holdout_pair_count": 10,
            "challenge_pair_count": 5,
            "evaluation_contract_sha": "eval-sha",
            "source_run_contract_file_sha256": training["run_contract_file_sha256"],
            "source_training_report_file_sha256": training["training_report_file_sha256"],
            "checkpoint_path": "tinker://terminal",
            "checkpoint_step": 2,
            "primary_normalization": "chosen_and_rejected_logprob_sums_divided_by_respective_residue_counts",
            "evaluator_sha256": sha256_file(
                ROOT / "scripts" / "evaluate_scaling_paradox_checkpoint.py"
            ),
        },
        "holdout": {"pair_count": 10, "pair_fingerprint": "holdout-fingerprint"},
        "challenge": {"pair_count": 5, "pair_fingerprint": "challenge-fingerprint"},
    }
    write_json(evaluation_dir / "evaluation_report.json", evaluation_report)
    write_json(
        evaluation_dir / "operational_evaluation_receipt.json",
        {
            "holdout_complete": True,
            "holdout_pair_count": 10,
            "challenge_complete": True,
            "challenge_pair_count": 5,
            "evaluation_report_sha256": sha256_file(evaluation_dir / "evaluation_report.json"),
        },
    )
    write_json(
        evaluation_dir / "provider_identity_receipt.json",
        {
            "run_key": "cell-1",
            "run_contract_sha": "contract-sha",
            "provider_identity_valid": True,
            "provider_corrupted": False,
            "provider_dpo_trainer_count": 1,
        },
    )
    evaluation = audit_evaluation_artifact(
        plan_entry=entry,
        evaluation_dir=evaluation_dir,
        training_receipt=training,
        partition_contracts={
            "holdout": {"pair_count": 10, "pair_fingerprint": "holdout-fingerprint"},
            "challenge": {"pair_count": 5, "pair_fingerprint": "challenge-fingerprint"},
        },
    )
    assert evaluation["evaluation_terminal_valid"] is True
    assert evaluation["provider_identity_valid"] is True
    evaluation_report["contract"]["challenge_sha256"] = "wrong"
    write_json(evaluation_dir / "evaluation_report.json", evaluation_report)
    with pytest.raises(RuntimeError, match="wrong challenge"):
        audit_evaluation_artifact(
            plan_entry=entry,
            evaluation_dir=evaluation_dir,
            training_receipt=training,
            partition_contracts={
                "holdout": {"pair_count": 10, "pair_fingerprint": "holdout-fingerprint"},
                "challenge": {"pair_count": 5, "pair_fingerprint": "challenge-fingerprint"},
            },
        )


def test_provider_audit_distinguishes_reference_worker_and_duplicate_dpo() -> None:
    entry = plan_entry()
    metadata = {
        "campaign_id": "campaign",
        "run_key": "cell-1",
        "contract_sha": "contract-sha",
    }
    rows = [
        {"id": "reference", "corrupted": False, "user_metadata": {**metadata, "pearl_task": "reference_policy"}},
        {"id": "trainer", "corrupted": False, "user_metadata": {**metadata, "pearl_task": "physical_to_sequence_dpo"}},
    ]
    receipt = audit_provider_identity(plan_entry=entry, provider_rows=rows)
    assert receipt["provider_dpo_trainer_id"] == "trainer"
    with pytest.raises(RuntimeError, match="exactly one"):
        audit_provider_identity(plan_entry=entry, provider_rows=rows + [dict(rows[-1], id="duplicate")])


def test_manager_never_redispatches_a_partial_or_submitted_wave(tmp_path: Path) -> None:
    manager = load_manager()
    manifest = {
        "global_max_active_paid_cells": 6,
        "phases": [
            {
                "phase": "original:core",
                "campaign": "original",
                "stage": "core",
                "workflow": "scaling-paradox-v1.yml",
                "config": "config.json",
                "plan_dir": "reports",
                "plan_sha": "plan",
                "waves": [
                    {
                        "wave_index": 1,
                        "run_keys": ["a", "b"],
                        "estimated_training_cost_usd": 2.0,
                        "estimated_checkpoint_evaluation_cost_usd": 0.5,
                        "estimated_cost_usd": 2.5,
                    }
                ],
            }
        ],
    }
    first = manager.next_authorization(manifest=manifest, state_dir=tmp_path, active_paid_cells=0)
    assert first["action"] == "dispatch_training_wave"
    assert first["authorized_run_keys"] == ["a", "b"]
    write_json(
        tmp_path / "receipts" / "training" / "a.json",
        {"run_key": "a", "training_terminal_valid": True, "source_actions_run_id": 1},
    )
    with pytest.raises(RuntimeError, match="partially observed"):
        manager.next_authorization(manifest=manifest, state_dir=tmp_path, active_paid_cells=0)
    (tmp_path / "receipts" / "training" / "a.json").unlink()
    write_json(tmp_path / "submissions" / "training" / "a.json", {"run_key": "a"})
    with pytest.raises(RuntimeError, match="resume or escalation"):
        manager.next_authorization(manifest=manifest, state_dir=tmp_path, active_paid_cells=0)
    waiting = manager.next_authorization(manifest=manifest, state_dir=tmp_path, active_paid_cells=2)
    assert waiting["action"] == "wait"


def test_frozen_rescue_gate_is_six_seed_and_has_no_p_value_decision() -> None:
    analysis = load_analysis()
    capacity = [
        {
            "clean_4b_minus_9b": value,
            "extension_4b_minus_27b": value,
            "effect_4b": value,
        }
        for value in (0.3, 0.2, -0.05)
    ]
    cohort = {
        "capacity_contrasts": capacity,
        "summaries": {"clean_4b_minus_9b": analysis.mean_interval([0.3, 0.2, -0.05])},
    }
    gate = {
        "id": "combined_core_adapter_rescue",
        "original_clean_positive_seed_count_minimum": 2,
        "replication_clean_positive_seed_count_minimum": 2,
        "combined_clean_4b_minus_9b_positive_seed_count_minimum": 4,
        "combined_extension_4b_minus_27b_positive_seed_count_minimum": 4,
        "failure_action": "skip",
    }
    receipt = analysis.evaluate_rescue_gate(cohort, cohort, gate)
    assert receipt["pass"] is True
    assert "p_value" not in json.dumps(receipt)
    test = analysis.exact_sign_flip_test([0.3, 0.2, -0.05, 0.3, 0.2, -0.05])
    assert test["permutation_count"] == 64


def test_structural_manifest_is_exact_111_cells_and_budgeted(tmp_path: Path) -> None:
    manager = load_manager()
    executor = json.loads(
        (ROOT / "configs" / "experiments" / "scaling_paradox_executor_v1.json").read_text()
    )
    plans = manager.build_plans(executor)
    state = tmp_path / "state"
    for cohort in ("original", "replication"):
        for entry in plans[(cohort, "core")]["runs"]:
            run_key = entry["run_key"]
            lineage = [
                {"step": step, "state_path": f"tinker://{run_key}/{step}", "terminal": step == 2250}
                for step in (500, 1000, 1500, 2000, 2250)
            ]
            write_json(
                state / "receipts" / "training" / f"{run_key}.json",
                {
                    "run_key": run_key,
                    "training_terminal_valid": True,
                    "source_actions_run_id": 100,
                    "source_artifact_name": f"artifact-{run_key}",
                    "run_contract_file_sha256": "a",
                    "training_report_file_sha256": "b",
                    "checkpoint_lineage_file_sha256": "c",
                    "checkpoint_lineage": lineage,
                },
            )
            write_json(
                state / "receipts" / "evaluation" / f"{run_key}.json",
                {"run_key": run_key, "evaluation_terminal_valid": True},
            )
    output = tmp_path / "structural.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_scaling_paradox_structural_manifest.py"),
            "--state-dir",
            str(state),
            "--output",
            str(output),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    manifest = json.loads(output.read_text())
    assert manifest["job_count"] == 111
    assert manifest["candidate_slots_per_job"] == 96
    assert manifest["estimated_sampling_cost_usd"] == 13.51
    assert len(manifest["waves"]) == 19
    assert len({row["job_key"] for row in manifest["jobs"]}) == 111

    builder_path = ROOT / "scripts" / "build_scaling_paradox_gmn_manifest.py"
    builder_spec = importlib.util.spec_from_file_location("gmn_builder_test", builder_path)
    builder = importlib.util.module_from_spec(builder_spec)
    assert builder_spec.loader is not None
    builder_spec.loader.exec_module(builder)
    original_reports = tmp_path / "original_structures"
    replication_reports = tmp_path / "replication_structures"
    for job in manifest["jobs"]:
        generation = builder.expected_generation_contract(job)
        fold = builder.expected_fold_contract(job, generation)
        results = [
            {
                "candidate_id": f"candidate-{index}",
                "valid_generation": True,
                "duplicate_sequence": False,
                "full_structural_gate_pass": False,
            }
            for index in range(96)
        ]
        report_root = (
            replication_reports if job["campaign"] == "replication" else original_reports
        ) / generation["run_key"]
        write_json(report_root / "generation_contract.json", generation)
        write_json(
            report_root / "structure_report.json",
            {
                "contract": fold,
                "status": "complete",
                "complete": True,
                "expected_candidate_count": 96,
                "completed_candidate_count": 96,
                "full_structural_gate_passes": 0,
                "results": results,
            },
        )
    original_analysis = tmp_path / "original_analysis.json"
    replication_analysis = tmp_path / "replication_analysis.json"
    combined_analysis = tmp_path / "combined_analysis.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "analyze_scaling_paradox_structural.py"),
            "--reports-dir", str(original_reports),
            "--structural-manifest", str(output),
            "--output", str(original_analysis),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "analyze_scaling_paradox_structural.py"),
            "--config", str(ROOT / "configs/experiments/scaling_paradox_structural_v1_replication.json"),
            "--reports-dir", str(replication_reports),
            "--shared-base-reports-dir", str(original_reports),
            "--structural-manifest", str(output),
            "--output", str(replication_analysis),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "analyze_scaling_paradox_structural_combined.py"),
            "--original-analysis", str(original_analysis),
            "--replication-analysis", str(replication_analysis),
            "--structural-manifest", str(output),
            "--output", str(combined_analysis),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    original_payload = json.loads(original_analysis.read_text())
    replication_payload = json.loads(replication_analysis.read_text())
    assert len(original_payload["cells"]) == 93
    assert len(original_payload["secondary_checkpoint_trajectory"]["seed_level"]) == 45
    assert len(replication_payload["cells"]) == 21
    assert len(replication_payload["secondary_checkpoint_trajectory"]["seed_level"]) == 9
    assert json.loads(combined_analysis.read_text())["structural_manifest_sha"] == manifest[
        "structural_manifest_sha"
    ]


def test_structural_intervals_are_exact_clopper_pearson() -> None:
    path = ROOT / "scripts" / "analyze_scaling_paradox_structural.py"
    spec = importlib.util.spec_from_file_location("structural_analysis_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    zero = module.clopper_pearson_interval(0, 96)
    all_pass = module.clopper_pearson_interval(96, 96)
    assert zero[0] == 0.0 and 0.03 < zero[1] < 0.04
    assert all_pass[1] == 1.0 and 0.96 < all_pass[0] < 0.97


def test_legacy_actions_allowlist_binds_unique_exact_run_keys() -> None:
    executor = json.loads(
        (ROOT / "configs" / "experiments" / "scaling_paradox_executor_v1.json").read_text()
    )
    claims = executor["legacy_original_core_actions_runs"]
    assert len(claims) == 6
    assert len({row["run_key"] for row in claims.values()}) == 6
    assert all(len(row["head_sha"]) == 40 and row["run_key"].startswith("core-") for row in claims.values())


def test_gmn_manager_enforces_six_active_jobs_and_spend(tmp_path: Path) -> None:
    manager = load_gmn_manager()
    jobs = [
        {
            "job_key": f"job-{index}",
            "generation_report_sha256": "a" * 64,
            "context_archive": f"job-{index}.tar.zst",
            "execution": {},
        }
        for index in range(111)
    ]
    manifest = {
            "contract": "pearl.scaling-paradox-gmn-manifest/1",
            "source_commit_sha": "b" * 40,
            "anchor_ref": "scaling-paradox-executor-v1.0.1",
        "max_active_jobs": 6,
        "max_authorized_usd": 482.01,
        "jobs": jobs,
    }
    manifest["gmn_manifest_sha"] = manager.sha256_value(manifest)
    manager.validate_manifest(manifest)
    for index in range(6):
        event = {
            "contract": "pearl.scaling-paradox-gmn-ledger-event/1",
            "action": "authorized",
            "gmn_manifest_sha": manifest["gmn_manifest_sha"],
            "job_key": f"job-{index}",
            "authorization_sha256": f"authorization-{index}",
            "quoted_max_cost_usd": 1.0,
        }
        event["event_sha256"] = manager.sha256_value(event)
        manager.append_ledger(tmp_path, event)
    assert manager.authorize_next(manifest, tmp_path, 1.0)["action"] == "wait"
    with pytest.raises(RuntimeError, match="envelope"):
        manager.authorize_next(manifest, tmp_path / "empty", 482.02)
    reserve_state = tmp_path / "reserved"
    first = manager.authorize_next(manifest, reserve_state, 1.0)
    second = manager.authorize_next(manifest, reserve_state, 1.0)
    assert first["job_key"] == "job-0"
    assert second["job_key"] == "job-1"
    assert len(manager.ledger_rows(reserve_state)) == 2


def test_gmn_result_audit_binds_exact_generation_candidate_rows(tmp_path: Path) -> None:
    manager = load_gmn_manager()
    generation = {
        "candidates": [
            {
                "candidate_id": f"candidate-{index}",
                "prompt_id": f"prompt-{index // 4}",
                "sample_seed": index % 4,
                "target_length": 100,
                "sequence_sha256": None,
                "valid_sequence": False,
                "duplicate_sequence": False,
            }
            for index in range(96)
        ]
    }
    generation_path = tmp_path / "generation_report.json"
    write_json(generation_path, generation)
    job = {
        "job_key": "job-0",
        "generation_report": str(generation_path),
        "generation_report_sha256": sha256_file(generation_path),
        "expected_gmn_result_contract": "pearl.scaling-paradox-structural-job/1",
        "candidate_slots": 96,
        "generation_run_key": "generation-0",
        "generation_contract_sha": "generation-sha",
        "expected_fold_contract": {"fold_contract_sha": "fold-sha"},
    }
    manifest = {"gmn_manifest_sha": "manifest-sha", "jobs": [job]}
    state = tmp_path / "state"
    authorization_sha = "authorization-sha"
    for event in (
        {
            "action": "authorized",
            "authorization_sha256": authorization_sha,
            "quoted_max_cost_usd": 1.0,
        },
        {
            "action": "context_prepared",
            "authorization_sha256": authorization_sha,
            "context_archive_sha256": "context-sha",
            "prepared_context_sha256": "prepared-sha",
        },
        {
            "action": "submitted",
            "authorization_sha256": authorization_sha,
            "context_archive_sha256": "context-sha",
            "provider_job_id": "provider-0",
        },
    ):
        manager.append_ledger(
            state,
            {
                "contract": "pearl.scaling-paradox-gmn-ledger-event/1",
                "gmn_manifest_sha": "manifest-sha",
                "job_key": "job-0",
                **event,
            },
        )
    results = [
        {
            "candidate_id": row["candidate_id"],
            "prompt_id": row["prompt_id"],
            "sample_seed": row["sample_seed"],
            "target_length": row["target_length"],
            "sequence_sha256": None,
            "valid_generation": False,
            "duplicate_sequence": False,
            "full_structural_gate_pass": False,
        }
        for row in generation["candidates"]
    ]
    report = {
        "contract": job["expected_fold_contract"],
        "status": "complete",
        "complete": True,
        "expected_candidate_count": 96,
        "completed_candidate_count": 96,
        "full_structural_gate_passes": 0,
        "full_structural_gate_yield": 0.0,
        "results": results,
    }
    result = {
        "contract": job["expected_gmn_result_contract"],
        "complete": True,
        "expected_candidate_count": 96,
        "completed_candidate_count": 96,
        "full_structural_gate_passes": 0,
        "full_structural_gate_yield": 0.0,
        "generation_run_key": job["generation_run_key"],
        "generation_contract_sha": job["generation_contract_sha"],
        "fold_contract_sha": "fold-sha",
    }
    report_path = tmp_path / "structure_report.json"
    result_path = tmp_path / "gmn_result.json"
    report["results"][0]["candidate_id"] = "fabricated"
    write_json(report_path, report)
    write_json(result_path, result)
    with pytest.raises(RuntimeError, match="candidate IDs"):
        manager.audit_result(
            manifest, state, "job-0", "provider-0", result_path, report_path
        )
    report["results"][0]["candidate_id"] = "candidate-0"
    write_json(report_path, report)
    receipt = manager.audit_result(
        manifest, state, "job-0", "provider-0", result_path, report_path
    )
    assert receipt["terminal_valid"] is True


def test_gmn_pdb_sequence_identity_is_exact_and_single_chain() -> None:
    manager = load_gmn_manager()
    pdb = "\n".join(
        [
            "ATOM      1  CA  ALA A   1      10.000  10.000  10.000  1.00 90.00           C",
            "ATOM      2  CA  SER A   2      11.000  10.000  10.000  1.00 90.00           C",
        ]
    )
    assert manager.pdb_sequence(pdb) == "AS"
    with pytest.raises(RuntimeError, match="exactly one"):
        manager.pdb_sequence(pdb + "\n" + pdb.replace(" A   1", " B   1").splitlines()[0])


def test_frozen_launcher_defers_endpoint_forwards_to_dedicated_evaluator() -> None:
    source = (ROOT / "scripts" / "launch_scaling_paradox_v1.py").read_text()
    launch_body = source[source.index("command = [") : source.index("log_path =", source.index("command = ["))]
    assert "--holdout-pairs-path" not in launch_body
    assert "--challenge-pairs-path" not in launch_body
    assert "--max-challenge-pairs" not in launch_body
