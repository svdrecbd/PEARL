from __future__ import annotations

import importlib.util
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
