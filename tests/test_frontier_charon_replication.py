from __future__ import annotations

import importlib.util
from argparse import Namespace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(filename: str):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(filename, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_charon_takeover_authorizes_exact_full_post_sentinel_ramp() -> None:
    controller = load_script("manage_frontier_charon_replication.py")
    ordered = ["sentinel", *[f"cell-{index:02d}" for index in range(1, 48)]]
    plan = {
        "runs": [
            {
                "run_key": key,
                "run_contract_sha": f"contract-{key}",
                "cost_estimate": {"estimated_training_cost_usd": 1.0},
            }
            for key in ordered
        ]
    }
    bootstrap = {"bootstrap_sha256": "bootstrap"}
    authorization = controller.build_takeover_authorization(
        bootstrap=bootstrap,
        plan=plan,
        ordered=ordered,
        provider_sha="provider",
        source_commit="commit",
        estimated_evaluation_cost_usd=4.7,
    )
    assert authorization["authorized_run_keys"] == ordered[1:]
    assert len(authorization["authorized_run_keys"]) == 47
    assert authorization["capacity_tier_prefixes"] == [12, 24, 47]
    assert set(authorization["segment_end_steps"].values()) == {2250}
    assert authorization["max_active_after_dispatch"] == 47
    assert authorization["estimated_training_cost_usd"] == 47.0
    assert authorization["estimated_evaluation_cost_usd"] == 4.7
    assert authorization["analysis_authorized"] is False
    assert authorization["scientific_contract_changed"] is False
    assert controller.validate_signed(authorization, "authorization_sha256")


def test_charon_ambiguous_launch_intent_is_never_retried(tmp_path: Path) -> None:
    controller = load_script("manage_frontier_charon_replication.py")
    local = load_script("manage_frontier_local_wave.py")
    state = tmp_path / "state"
    mirror = tmp_path / "mirror"
    local.append_ledger(
        state,
        mirror,
        "charon_training_launch_intent",
        {"run_key": "cell", "authorization_sha256": "auth", "tier_prefix": 12},
    )
    local.github_nonterminal_runs = lambda: []
    local.require_supervisor_disabled = lambda: None

    class NeverLaunch:
        def launch_one(self, *args, **kwargs):
            raise AssertionError("ambiguous Charon intent must stop before launch")

    with pytest.raises(controller.SafetyStop, match="intent without start"):
        controller.launch_keys(
            args=Namespace(),
            state_dir=state,
            mirror_dir=mirror,
            launcher=NeverLaunch(),
            local=local,
            plan={},
            entries={"cell": {"run_contract_sha": "contract"}},
            authorization={"authorization_sha256": "auth"},
            keys=["cell"],
            tier=12,
        )


def test_charon_controller_has_no_analysis_or_post_replication_entrypoint() -> None:
    source = (ROOT / "scripts" / "manage_frontier_charon_replication.py").read_text()
    assert 'TIER_PREFIXES = (12, 24, 47)' in source
    assert '"charon_replication_complete"' in source
    assert '"analysis_started": False' in source
    assert "run_analysis" not in source
    assert "run_structural" not in source
