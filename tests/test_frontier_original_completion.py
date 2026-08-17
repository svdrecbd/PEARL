from __future__ import annotations

import importlib.util
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(filename: str):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(filename, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evaluation_worker_requires_original_only_hard_stop(tmp_path: Path) -> None:
    worker = load_script("run_frontier_local_evaluation.py")
    payload = {
        "contract": "pearl.frontier-local-evaluation-authorization/1",
        "action": "evaluate_missing_original_endpoints",
        "campaign": "original",
        "stage": "core",
        "authorized_run_keys": ["key"],
        "run_contract_shas": {"key": "sha"},
        "replication_authorized": False,
        "analysis_authorized": False,
        "evaluator_sha256": worker.sha256_file(ROOT / "scripts" / "evaluate_scaling_paradox_checkpoint.py"),
        "evaluation_worker_sha256": worker.sha256_file(ROOT / "scripts" / "run_frontier_local_evaluation.py"),
    }
    payload["authorization_sha256"] = worker.sha256_value(payload)
    path = tmp_path / "authorization.json"
    path.write_text(worker.json.dumps(payload), encoding="utf-8")
    assert worker.validate_authorization(path, "key")["campaign"] == "original"

    payload["replication_authorized"] = True
    unsigned = dict(payload)
    unsigned.pop("authorization_sha256")
    payload["authorization_sha256"] = worker.sha256_value(unsigned)
    path.write_text(worker.json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="bounded original-only"):
        worker.validate_authorization(path, "key")


def test_terminal_authorization_targets_only_supplied_original_keys() -> None:
    controller = load_script("manage_frontier_original_completion.py")
    keys = ["a", "b"]
    current = {
        "authorization_sha256": "source",
        "segment_end_steps": {"a": 1000, "b": 1750},
    }
    entries = {key: {"run_contract_sha": f"sha-{key}"} for key in keys}
    waves = {key: {"unused": True} for key in keys}
    manager = SimpleNamespace(
        estimated_segment_cost=lambda **kwargs: (kwargs["end_step"] - kwargs["start_step"]) / 100
    )
    authorization = controller.build_terminal_authorization(
        current=current,
        keys=keys,
        entries=entries,
        waves=waves,
        manager=manager,
        provider_snapshot_sha="provider",
        backup_shas={key: f"backup-{key}" for key in keys},
        provider_audit_shas={key: f"provider-{key}" for key in keys},
        controller_source_commit="commit",
    )
    assert authorization["authorized_run_keys"] == keys
    assert authorization["segment_end_steps"] == {"a": 2250, "b": 2250}
    assert authorization["replication_authorized"] is False
    assert authorization["analysis_authorized"] is False
    assert controller.validate_signed(authorization, "authorization_sha256")


def test_ambiguous_training_intent_is_never_retried(tmp_path: Path) -> None:
    controller = load_script("manage_frontier_original_completion.py")
    state = tmp_path / "state"
    mirror = tmp_path / "mirror"
    controller.append_ledger(
        state,
        mirror,
        "terminal_training_launch_intent",
        {"run_key": "key", "authorization_sha256": "auth"},
    )
    authorization = {
        "authorized_run_keys": ["key"],
        "authorization_sha256": "auth",
        "completed_steps": {"key": 1000},
    }

    class NeverLaunch:
        def launch_one(self, *args, **kwargs):
            raise AssertionError("ambiguous intent must stop before launch")

    with pytest.raises(controller.SafetyStop, match="intent without start"):
        controller.run_training_to_terminal(
            args=Namespace(poll_seconds=0),
            state_dir=state,
            mirror_dir=mirror,
            launcher=NeverLaunch(),
            plan={},
            entries={"key": {"run_contract_sha": "sha"}},
            authorization=authorization,
        )


def test_completion_wrapper_has_original_only_entrypoint() -> None:
    wrapper = (ROOT / "scripts" / "run_frontier_original_completion.sh").read_text()
    controller = (ROOT / "scripts" / "manage_frontier_original_completion.py").read_text()
    launch_agent = (ROOT / "deploy" / "macos" / "org.pearl.frontier-original-completion.plist").read_text()
    assert "manage_frontier_original_completion.py _run" in wrapper
    assert "frontier_adaptation_v2_replication" not in wrapper
    assert '"original_optimization_complete"' in controller
    assert '"replication_started": False' in controller
    assert '"analysis_started": False' in controller
    assert "SuccessfulExit" in launch_agent
    assert "run_frontier_original_completion.sh" in launch_agent
