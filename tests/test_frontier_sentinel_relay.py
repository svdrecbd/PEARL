from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "core-fixed-rank-nemotron3-ultra-true-seed520620-8751f7ee9f"
HEAD = "0d168bd40126232911e6413b65a60a43f5293c76"


def load_relay() -> Any:
    path = ROOT / "scripts/decide_frontier_sentinel_relay.py"
    spec = importlib.util.spec_from_file_location("frontier_sentinel_relay", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def supervisor(
    database_id: int,
    *,
    status: str = "completed",
    conclusion: str = "success",
    mode: str = "advance",
    head_sha: str = HEAD,
) -> dict[str, Any]:
    return {
        "databaseId": database_id,
        "displayTitle": f"Frontier supervisor {database_id} {mode}",
        "event": "workflow_dispatch" if mode == "advance" else "workflow_run",
        "status": status,
        "conclusion": conclusion,
        "headSha": head_sha,
    }


def child(
    database_id: int,
    *,
    source_supervisor: int,
    kind: str = "training",
    status: str = "completed",
    conclusion: str = "success",
    head_sha: str = HEAD,
    suffix: str | None = None,
) -> dict[str, Any]:
    label = "train" if kind == "training" else "eval"
    owner = suffix if suffix is not None else str(source_supervisor)
    return {
        "databaseId": database_id,
        "displayTitle": f"Frontier {label} replication {SENTINEL} supervisor-{owner}",
        "event": "workflow_dispatch",
        "status": status,
        "conclusion": conclusion,
        "headSha": head_sha,
    }


def decide(
    supervisors: list[dict[str, Any]],
    training: list[dict[str, Any]],
    evaluation: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    relay = load_relay()
    return relay.decide(
        supervisor_rows=supervisors,
        training_rows=training,
        evaluation_rows=evaluation or [],
        sentinel_run_key=SENTINEL,
    )


def test_successful_unadvanced_sentinel_child_dispatches_only_the_supervisor() -> None:
    result = decide([supervisor(100)], [child(101, source_supervisor=100)])
    assert result == {
        "action": "dispatch",
        "reason": "successful_sentinel_child_requires_supervisor_advance",
        "child_actions_run_id": 101,
        "child_kind": "training",
        "child_head_sha": HEAD,
        "source_supervisor_actions_run_id": 100,
    }


def test_newer_supervisor_transition_makes_relay_idempotently_wait() -> None:
    result = decide(
        [supervisor(102), supervisor(100)],
        [child(101, source_supervisor=100)],
    )
    assert result["action"] == "wait"
    assert result["reason"] == "sentinel_child_already_has_a_newer_supervisor_transition"
    assert result["latest_supervisor_actions_run_id"] == 102


def test_failed_newer_supervisor_transition_stops_instead_of_masking_failure() -> None:
    result = decide(
        [supervisor(102, conclusion="failure"), supervisor(100)],
        [child(101, source_supervisor=100)],
    )
    assert result["action"] == "stop"
    assert result["reason"] == "newer_supervisor_transition_did_not_succeed"
    assert result["latest_supervisor_actions_run_id"] == 102


def test_nonterminal_child_and_nonterminal_supervisor_both_wait() -> None:
    active_child = decide(
        [supervisor(100)],
        [child(101, source_supervisor=100, status="in_progress", conclusion="")],
    )
    assert active_child["action"] == "wait"
    assert active_child["reason"] == "latest_sentinel_child_is_nonterminal"

    active_supervisor = decide(
        [
            supervisor(102, status="in_progress", conclusion=""),
            supervisor(100),
        ],
        [child(101, source_supervisor=100)],
    )
    assert active_supervisor["action"] == "wait"
    assert active_supervisor["reason"] == "supervisor_transition_is_nonterminal"


def test_failed_or_unrecognized_latest_child_stops_without_dispatch() -> None:
    failed = decide(
        [supervisor(100)],
        [child(101, source_supervisor=100, conclusion="failure")],
    )
    assert failed["action"] == "stop"
    assert failed["reason"] == "latest_sentinel_child_did_not_succeed"

    unrecognized = decide(
        [supervisor(100)],
        [child(101, source_supervisor=100, suffix="validate")],
    )
    assert unrecognized["action"] == "stop"
    assert unrecognized["reason"] == "latest_sentinel_child_title_is_unrecognized"


def test_source_supervisor_identity_and_head_must_match() -> None:
    absent = decide([], [child(101, source_supervisor=100)])
    assert absent["action"] == "stop"
    assert absent["reason"] == "source_supervisor_is_absent_from_snapshot"

    mismatch = decide(
        [supervisor(100, head_sha="different")],
        [child(101, source_supervisor=100)],
    )
    assert mismatch["action"] == "stop"
    assert mismatch["reason"] == "source_supervisor_and_child_head_sha_differ"


def test_successful_evaluation_child_is_eligible_for_the_final_hold_advance() -> None:
    result = decide(
        [supervisor(200)],
        [],
        [child(201, source_supervisor=200, kind="evaluation")],
    )
    assert result["action"] == "dispatch"
    assert result["child_kind"] == "evaluation"


def test_relay_workflow_is_sentinel_only_and_has_no_direct_paid_authority() -> None:
    workflow = (
        ROOT / ".github/workflows/frontier-adaptation-v2-sentinel-relay.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "cron:" not in workflow
    assert "group: frontier-adaptation-v2-campaign-supervisor" in workflow
    assert "actions: write" in workflow
    assert "contents: read" in workflow
    assert SENTINEL in workflow
    assert "TINKER_API_KEY" not in workflow
    assert "secrets." not in workflow
    assert workflow.count("gh workflow run frontier-adaptation-v2-supervisor.yml") == 1
    assert "--ref main -f mode=advance" in workflow
    assert "frontier-adaptation-v2-dispatch-$source_supervisor" in workflow
    assert "frontier-supervisor-$source_supervisor" in workflow
    assert "Recheck immediately before the only mutation" in workflow
