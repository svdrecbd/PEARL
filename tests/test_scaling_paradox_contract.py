from __future__ import annotations

import hashlib
import importlib.util
import json
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_row(record_id: str, variant: int) -> dict[str, object]:
    chosen = ("ACDEFGHIKLMNPQRSTVWY" * 10) + record_id[-1]
    rejected = chosen[:50] + ("Y" if chosen[50] != "Y" else "A") + chosen[51:]
    return {
        "prompt": f"prompt-{record_id}-{variant}",
        "chosen": chosen,
        "rejected": rejected,
        "chosen_record_id": record_id,
        "chosen_source_type": "natural_reference_record",
        "chosen_reviewed": True,
        "chosen_active_site_count": 3,
        "chosen_confidence_basis": "fixture",
        "synthetic_artifact_class": f"artifact-{variant % 2}",
    }


def test_nested_selection_uses_one_distinct_positive_per_small_row() -> None:
    module = load_script("build_scaling_paradox_datasets.py")
    rows = [synthetic_row(f"record-{group}", variant) for group in range(8) for variant in range(4)]
    groups = module.group_rows(rows)
    holdout_ids = module.select_holdout_group_ids(
        groups,
        holdout_groups=2,
        max_chosen_uses=4,
        seed=17,
    )
    selected = module.select_one_per_group(
        groups,
        sorted(set(groups) - holdout_ids),
        target_size=5,
        seed=29,
    )

    summary = module.validate_partition(selected, max_chosen_uses=1)
    assert summary["rows"] == 5
    assert summary["unique_chosen_record_ids"] == 5
    assert summary["max_observed_chosen_uses"] == 1
    assert {module.canonical_json(row) for row in selected}.issubset(
        {module.canonical_json(row) for row in rows}
    )


def test_shuffled_control_is_balanced_and_preserves_pair_content() -> None:
    module = load_script("build_scaling_paradox_datasets.py")
    rows = [synthetic_row(f"record-{group}", 0) for group in range(6)]
    shuffled = module.shuffled_label_control(rows, seed=43)

    summary = module.validate_partition(
        shuffled,
        max_chosen_uses=1,
        require_positive_labels=False,
    )
    assert summary["label_swaps"] == 3
    for original, control in zip(rows, shuffled, strict=True):
        assert {original["chosen"], original["rejected"]} == {control["chosen"], control["rejected"]}
        assert control["positive_sequence"] == original["chosen"]
        assert control["negative_sequence"] == original["rejected"]


def test_runner_metadata_carries_seed_and_contract_identity() -> None:
    runner = load_script("run_tinker_dpo_smoke.py")
    args = Namespace(
        campaign_id="scaling-paradox-v1",
        run_key="qwen-4b-true-seed17",
        name="fallback-name",
        training_seed=17,
        contract_sha="abc123",
    )

    assert runner.training_user_metadata(args, task="physical_to_sequence_dpo") == {
        "pearl_task": "physical_to_sequence_dpo",
        "campaign_id": "scaling-paradox-v1",
        "run_key": "qwen-4b-true-seed17",
        "training_seed": "17",
        "contract_sha": "abc123",
    }


def test_launcher_resolves_tinker_cli_portably(tmp_path, monkeypatch) -> None:
    launcher = load_script("launch_scaling_paradox_v1.py")
    fake_cli = tmp_path / "tinker"
    fake_cli.write_text("#!/bin/sh\nexit 0\n")
    fake_cli.chmod(0o755)

    monkeypatch.setenv("TINKER_CLI", str(fake_cli))
    assert launcher.resolve_tinker_cli() == str(fake_cli)
    monkeypatch.delenv("TINKER_CLI")
    monkeypatch.setattr(launcher.sys, "executable", str(tmp_path / "python"))
    assert launcher.resolve_tinker_cli() == str(fake_cli)
    source = (ROOT / "scripts" / "launch_scaling_paradox_v1.py").read_text()
    assert 'command = [\n        sys.executable,' in source


def test_checkpoint_lineage_is_durable_ordered_and_idempotent() -> None:
    runner = load_script("run_tinker_dpo_smoke.py")
    lineage = runner.record_checkpoint(
        [], step=500, state_path="tinker://step500", checkpoint_name="step500", terminal=False
    )
    lineage = runner.record_checkpoint(
        lineage, step=1, state_path="tinker://step1", checkpoint_name="step1", terminal=False
    )
    lineage = runner.record_checkpoint(
        lineage, step=500, state_path="tinker://step500-new", checkpoint_name="step500", terminal=False
    )
    lineage = runner.record_checkpoint(
        lineage, step=2250, state_path="tinker://terminal", checkpoint_name="terminal", terminal=True
    )

    assert [row["step"] for row in lineage] == [1, 500, 2250]
    assert lineage[1]["state_path"] == "tinker://step500-new"
    assert lineage[-1]["terminal"] is True


def test_frozen_structural_panel_is_balanced_and_unique() -> None:
    panel_path = ROOT / "configs" / "experiments" / "scaling_paradox_structural_panel_v1.jsonl"
    rows = [json.loads(line) for line in panel_path.read_text().splitlines() if line.strip()]
    assert len(rows) == 24
    assert len({row["prompt_id"] for row in rows}) == 24
    assert len({row["prompt"] for row in rows}) == 24
    assert len({row["withheld_positive_group_sha256"] for row in rows}) == 24
    assert {name: sum(row["length_bin"] == name for row in rows) for name in ("short", "medium", "long")} == {
        "short": 8,
        "medium": 8,
        "long": 8,
    }


def test_dataset_manifest_uses_portable_repository_relative_paths() -> None:
    manifest = json.loads(
        (ROOT / "data" / "phase8_dpo" / "scaling_paradox_v1" / "dataset_manifest.json").read_text()
    )
    for partition in manifest["partitions"].values():
        path = Path(partition["path"])
        assert not path.is_absolute()
        assert path.parts[:3] == ("data", "phase8_dpo", "scaling_paradox_v1")


def test_structural_generation_contract_has_96_deterministic_candidate_slots() -> None:
    generator = load_script("run_scaling_paradox_generation.py")
    config_path = ROOT / "configs" / "experiments" / "scaling_paradox_structural_v1.json"
    config = json.loads(config_path.read_text())
    panel_path = ROOT / config["prompt_panel"]
    args = Namespace(
        config=str(config_path),
        model="Qwen/Qwen3.5-4B",
        arm="base",
        training_seed=0,
        checkpoint_step=0,
        checkpoint_path=None,
    )
    contract = generator.build_contract(args, config, panel_path)
    panel = [json.loads(line) for line in panel_path.read_text().splitlines() if line.strip()]
    candidate_ids = {
        generator.candidate_id(contract["generation_contract_sha"], row["prompt_id"], seed)
        for row in panel
        for seed in config["sampling"]["sample_seeds"]
    }
    assert len(candidate_ids) == 96
    assert contract["renderer_contract_fingerprint"]
    assert contract["run_key"].startswith("struct-qwen3p5-4b-base-seed0-step0-")


def test_structural_image_embeds_immutable_generation_report() -> None:
    dockerfile = (ROOT / "deploy" / "scaling_paradox_v1" / "Dockerfile.esmfold").read_text()
    assert "COPY input/generation_report.json /workspace/input/generation_report.json" in dockerfile
    entrypoint = (ROOT / "deploy" / "scaling_paradox_v1" / "run_esmf_job.sh").read_text()
    assert "GENERATION_REPORT:-/workspace/input/generation_report.json" in entrypoint
    builder = (ROOT / "deploy" / "scaling_paradox_v1" / "build_esmf_context.sh").read_text()
    assert 'git archive --format=tar "$git_ref"' in builder
    assert 'cp "$generation_report" "$context_root/input/generation_report.json"' in builder
    assert '"$context_root/Dockerfile.esmfold"' in builder


def test_remote_validation_exercises_provider_access_without_spending() -> None:
    workflow = (ROOT / ".github" / "workflows" / "scaling-paradox-v1.yml").read_text()
    assert "Verify Tinker provider access without spending" in workflow
    assert '"paid_execution": False' in workflow
    assert "contract_shas, run_keys = module.provider_contracts()" in workflow


def test_prospective_replication_is_separate_deterministic_and_frozen() -> None:
    launcher = load_script("launch_scaling_paradox_v1.py")
    manifest = json.loads(
        (ROOT / "data" / "phase8_dpo" / "scaling_paradox_v1" / "dataset_manifest.json").read_text()
    )
    original = json.loads(
        (ROOT / "configs" / "experiments" / "scaling_paradox_v1.json").read_text()
    )
    replication = json.loads(
        (ROOT / "configs" / "experiments" / "scaling_paradox_v1_replication.json").read_text()
    )

    namespace = replication["training_seed_derivation"]["namespace"]
    derived = [
        int.from_bytes(
            hashlib.sha256(f"{namespace}/training-seed/{index}".encode()).digest()[:4], "big"
        )
        % 1_000_000
        for index in (1, 2, 3)
    ]
    assert derived == [362034, 257621, 520620]
    assert replication["training_seeds"] == derived
    assert set(derived).isdisjoint(original["training_seeds"])
    assert original["training_seeds"] == [17, 29, 43]

    original_plan = launcher.build_plan(original, manifest, "core")
    replication_plan = launcher.build_plan(replication, manifest, "core")
    assert original_plan["launch_plan_contract_sha"] == (
        "f63f3bd2f9f0654c819f3f5a806145847c9b899ae16859d870c7a3b320d43226"
    )
    assert replication_plan["launch_plan_contract_sha"] == (
        "ac90ed77143986eeaec127983df8306c7ced37cd7aed38b87fdc2cb6e7c66b5d"
    )
    assert replication_plan["run_count"] == 18
    assert replication_plan["estimated_stage_cost_usd"] == 416.83
    assert len({run["run_key"] for run in replication_plan["runs"]}) == 18
    assert len({run["run_contract_sha"] for run in replication_plan["runs"]}) == 18
    assert {run["run_key"] for run in original_plan["runs"]}.isdisjoint(
        run["run_key"] for run in replication_plan["runs"]
    )
    assert {run["run_contract_sha"] for run in original_plan["runs"]}.isdisjoint(
        run["run_contract_sha"] for run in replication_plan["runs"]
    )


def test_replication_workflow_is_dedicated_and_no_spend_validatable() -> None:
    workflow = (ROOT / ".github" / "workflows" / "scaling-paradox-v1-replication.yml").read_text()
    assert "configs/experiments/scaling_paradox_v1_replication.json" in workflow
    assert "reports/scaling_paradox_v1_replication" in workflow
    assert "scaling-paradox-v1-replication-${{ inputs.run_key }}" in workflow
    assert "Verify Tinker provider access without spending" in workflow
    assert "configs/experiments/scaling_paradox_v1_replication_gate.json" in workflow
    assert "reviewed v1 core gate receipt is absent" in workflow
    assert "if: inputs.mode == 'validate'" in workflow
    assert '"paid_execution": False' in workflow
    assert "--confirm-contract-sha \"${{ inputs.launch_plan_sha }}\"" in workflow


def test_subagent_runbook_is_bound_to_frozen_contract_and_contamination_rules() -> None:
    root_rules = (ROOT / "AGENTS.md").read_text()
    runbook = (ROOT / "docs" / "SUBAGENT_RUNBOOK.md").read_text()
    assert "docs/SUBAGENT_RUNBOOK.md" in root_rules
    assert "docs/scaling_paradox_v1_replication_protocol.md" in root_rules
    assert "The primary agent owns engineering and research judgment" in root_rules
    assert "A subagent is an executor, not a decision-maker" in root_rules
    assert "A subagent must never delegate or spawn another agent" in root_rules
    assert "A subagent has no engineering or research decision authority" in runbook
    assert "If there is any doubt, the issue is not minor" in runbook
    assert "## Low-stakes autonomy FAQ" in runbook
    assert "read-only, or a locally reversible mechanical change" in runbook
    assert "up to three bounded attempts" in runbook
    assert "Stopping a local" in runbook
    assert "`gh run watch` is harmless; cancelling the GitHub workflow is not" in runbook
    assert '"Useful" is scope expansion, not low-stakes autonomy' in runbook
    assert "f63f3bd2f9f0654c819f3f5a806145847c9b899ae16859d870c7a3b320d43226" in runbook
    assert "ac90ed77143986eeaec127983df8306c7ced37cd7aed38b87fdc2cb6e7c66b5d" in runbook
    assert "1f410d4346b354b789408729c2c7cfc1f0bdef3b9580716171d86593bd9e9a22" in runbook
    assert "at most six active core cells" in runbook
    assert "| A | 2–6 |" in runbook and "| B | 7–12 |" in runbook and "| C | 13–18 |" in runbook
    assert "Never use `git add -A`" in runbook
    assert "Do not use old untracked H100, ESM3, LigandMPNN, Concord, or California scripts" in runbook


def test_core_launch_contracts_are_unique_across_arm_model_and_seed() -> None:
    launcher = load_script("launch_scaling_paradox_v1.py")
    config = {
        "campaign_id": "campaign",
        "common": {
            "beta": 0.05,
            "learning_rate": 5e-7,
            "batch_pairs": 4,
            "rank": 32,
            "save_every_steps": 500,
            "max_steps": 2250,
            "renderer": "qwen3_5_disable_thinking",
        },
        "models": [
            {"tag": "m4", "model": "Qwen/Qwen3.5-4B"},
            {"tag": "m9", "model": "Qwen/Qwen3.5-9B"},
            {"tag": "m27", "model": "Qwen/Qwen3.6-27B"},
        ],
        "stages": {
            "core": {
                "models": ["m4", "m9", "m27"],
                "arms": ["true", "shuffled"],
                "seeds": [17, 29, 43],
                "dataset_by_arm": {"true": "d10_train_true", "shuffled": "d10_train_shuffled"},
                "max_steps": 2250,
            }
        },
    }
    manifest = {
        "manifest_sha256": "manifest-sha",
        "partitions": {
            "d10_train_true": {"path": "/tmp/true", "sha256": "true-sha"},
            "d10_train_shuffled": {"path": "/tmp/shuffled", "sha256": "shuffled-sha"},
            "d10_holdout_true": {"path": "/tmp/holdout", "sha256": "holdout-sha"},
            "real_failure_challenge": {"path": "/tmp/challenge", "sha256": "challenge-sha"},
        },
    }

    runs = launcher.build_stage_runs(config, manifest, "core")
    assert len(runs) == 18
    assert len({run["run_key"] for run in runs}) == 18
    assert len({run["run_contract_sha"] for run in runs}) == 18
    assert {run["arm"] for run in runs} == {"true", "shuffled"}
    assert {run["training_seed"] for run in runs} == {17, 29, 43}
