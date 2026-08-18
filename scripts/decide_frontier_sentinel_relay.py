#!/usr/bin/env python3
"""Make the result-blind, no-spend decision for the Frontier v2 sentinel relay."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SUPERVISOR_TITLE = re.compile(
    r"^Frontier supervisor (?P<run_id>[1-9][0-9]*) (?P<mode>advance|auto-advance)$"
)


def read_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError(f"{path} must contain a JSON array of objects")
    return payload


def run_id(row: dict[str, Any]) -> int:
    value = row.get("databaseId")
    if isinstance(value, bool):
        raise ValueError("Actions run databaseId must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Actions run databaseId must be an integer") from error
    if parsed <= 0:
        raise ValueError("Actions run databaseId must be positive")
    return parsed


def decision(action: str, reason: str, **details: Any) -> dict[str, Any]:
    return {"action": action, "reason": reason, **details}


def decide(
    *,
    supervisor_rows: list[dict[str, Any]],
    training_rows: list[dict[str, Any]],
    evaluation_rows: list[dict[str, Any]],
    sentinel_run_key: str,
) -> dict[str, Any]:
    escaped_key = re.escape(sentinel_run_key)
    child_patterns = {
        "training": re.compile(
            rf"^Frontier train replication {escaped_key} "
            r"supervisor-(?P<supervisor_id>[1-9][0-9]*)$"
        ),
        "evaluation": re.compile(
            rf"^Frontier eval replication {escaped_key} "
            r"supervisor-(?P<supervisor_id>[1-9][0-9]*)$"
        ),
    }

    relevant_children: list[tuple[str, dict[str, Any], re.Match[str] | None]] = []
    for kind, rows in (("training", training_rows), ("evaluation", evaluation_rows)):
        for row in rows:
            title = str(row.get("displayTitle") or "")
            if sentinel_run_key in title:
                relevant_children.append((kind, row, child_patterns[kind].fullmatch(title)))
    if not relevant_children:
        return decision("wait", "no_replication_sentinel_child")

    kind, child, child_match = max(relevant_children, key=lambda item: run_id(item[1]))
    child_id = run_id(child)
    child_details = {
        "child_actions_run_id": child_id,
        "child_kind": kind,
        "child_head_sha": str(child.get("headSha") or ""),
    }
    if child_match is None:
        return decision("stop", "latest_sentinel_child_title_is_unrecognized", **child_details)
    source_supervisor_id = int(child_match.group("supervisor_id"))
    child_details["source_supervisor_actions_run_id"] = source_supervisor_id

    if child.get("event") != "workflow_dispatch":
        return decision("stop", "latest_sentinel_child_event_is_not_workflow_dispatch", **child_details)
    status = str(child.get("status") or "")
    if status != "completed":
        return decision("wait", "latest_sentinel_child_is_nonterminal", **child_details)
    if child.get("conclusion") != "success":
        return decision("stop", "latest_sentinel_child_did_not_succeed", **child_details)
    if not child_details["child_head_sha"]:
        return decision("stop", "latest_sentinel_child_has_no_head_sha", **child_details)

    supervisors_by_id = {run_id(row): row for row in supervisor_rows}
    source_supervisor = supervisors_by_id.get(source_supervisor_id)
    if source_supervisor is None:
        return decision("stop", "source_supervisor_is_absent_from_snapshot", **child_details)
    source_title = str(source_supervisor.get("displayTitle") or "")
    source_match = SUPERVISOR_TITLE.fullmatch(source_title)
    if source_match is None or int(source_match.group("run_id")) != source_supervisor_id:
        return decision("stop", "source_supervisor_title_is_unrecognized", **child_details)
    if (
        source_supervisor.get("status") != "completed"
        or source_supervisor.get("conclusion") != "success"
        or source_supervisor.get("event") not in {"workflow_dispatch", "workflow_run"}
    ):
        return decision("stop", "source_supervisor_is_not_terminal_success", **child_details)
    if str(source_supervisor.get("headSha") or "") != child_details["child_head_sha"]:
        return decision("stop", "source_supervisor_and_child_head_sha_differ", **child_details)

    recognized_supervisors = [
        row
        for row in supervisor_rows
        if SUPERVISOR_TITLE.fullmatch(str(row.get("displayTitle") or ""))
    ]
    active_supervisors = [
        row for row in recognized_supervisors if str(row.get("status") or "") != "completed"
    ]
    if active_supervisors:
        latest_active = max(active_supervisors, key=run_id)
        return decision(
            "wait",
            "supervisor_transition_is_nonterminal",
            active_supervisor_actions_run_id=run_id(latest_active),
            **child_details,
        )
    if recognized_supervisors:
        latest_supervisor = max(recognized_supervisors, key=run_id)
        latest_supervisor_id = run_id(latest_supervisor)
        if latest_supervisor_id > child_id:
            if latest_supervisor.get("event") not in {"workflow_dispatch", "workflow_run"}:
                return decision(
                    "stop",
                    "newer_supervisor_transition_has_unrecognized_event",
                    latest_supervisor_actions_run_id=latest_supervisor_id,
                    **child_details,
                )
            if latest_supervisor.get("conclusion") != "success":
                return decision(
                    "stop",
                    "newer_supervisor_transition_did_not_succeed",
                    latest_supervisor_actions_run_id=latest_supervisor_id,
                    **child_details,
                )
            return decision(
                "wait",
                "sentinel_child_already_has_a_newer_supervisor_transition",
                latest_supervisor_actions_run_id=latest_supervisor_id,
                **child_details,
            )

    return decision("dispatch", "successful_sentinel_child_requires_supervisor_advance", **child_details)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supervisor-runs", type=Path, required=True)
    parser.add_argument("--training-runs", type=Path, required=True)
    parser.add_argument("--evaluation-runs", type=Path, required=True)
    parser.add_argument("--sentinel-run-key", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = decide(
        supervisor_rows=read_rows(args.supervisor_runs),
        training_rows=read_rows(args.training_runs),
        evaluation_rows=read_rows(args.evaluation_runs),
        sentinel_run_key=args.sentinel_run_key,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
