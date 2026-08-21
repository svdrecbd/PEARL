#!/usr/bin/env python3
"""Authorize and audit the manual GiveMeANode boundary without scientific discretion."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pearl.structure_gate import StructurePrediction, gate_prediction, parse_pdb  # noqa: E402


AMINO_ACID_3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_value(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("contract") != "pearl.frontier-adaptation-gmn-manifest/3":
        raise RuntimeError("wrong GMN manifest contract")
    supplied = manifest.get("gmn_manifest_sha")
    unsigned = {key: value for key, value in manifest.items() if key != "gmn_manifest_sha"}
    if supplied != sha256_value(unsigned):
        raise RuntimeError("GMN manifest self-hash mismatch")
    jobs = manifest.get("jobs", [])
    if len(jobs) != 104 or len({row["job_key"] for row in jobs}) != 104:
        raise RuntimeError("GMN manifest must contain 104 unique jobs")
    if int(manifest.get("max_active_jobs", -1)) != 6:
        raise RuntimeError("GMN manifest must retain the frozen six-job cap")
    if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("source_commit_sha") or "")):
        raise RuntimeError("GMN manifest lacks an exact source commit")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", str(manifest.get("anchor_ref") or "")):
        raise RuntimeError("GMN manifest lacks a valid frozen anchor branch/tag")


def ledger_rows(state_dir: Path) -> list[dict[str, Any]]:
    path = state_dir / "gmn_ledger.jsonl"
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    previous = "ROOT"
    for row in rows:
        if row.get("previous_event_sha256") != previous:
            raise RuntimeError("GMN ledger hash chain is broken")
        supplied = row.get("event_sha256")
        if supplied != sha256_value(
            {key: value for key, value in row.items() if key != "event_sha256"}
        ):
            raise RuntimeError("GMN ledger event hash mismatch")
        previous = str(supplied)
    return rows


def append_ledger(state_dir: Path, row: dict[str, Any]) -> None:
    path = state_dir / "gmn_ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = ledger_rows(state_dir)
    row = dict(row)
    row.pop("event_sha256", None)
    row.pop("previous_event_sha256", None)
    row["previous_event_sha256"] = (
        existing[-1]["event_sha256"] if existing else "ROOT"
    )
    row["event_sha256"] = sha256_value(row)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def job_for(manifest: dict[str, Any], job_key: str) -> dict[str, Any]:
    matches = [row for row in manifest["jobs"] if row["job_key"] == job_key]
    if len(matches) != 1:
        raise RuntimeError("GMN job key is absent or non-unique")
    return matches[0]


def pdb_sequence(pdb_text: str) -> str:
    residues: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    chains: set[str] = set()
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM") or line[12:16].strip() != "CA":
            continue
        chain = line[21:22]
        residue_id = (chain, line[22:26], line[26:27])
        if residue_id in seen:
            continue
        seen.add(residue_id)
        chains.add(chain)
        residues.append((*residue_id, line[17:20].strip()))
    if len(chains) != 1 or not residues:
        raise RuntimeError("GMN PDB must contain exactly one nonempty residue chain")
    if [int(row[1]) for row in residues] != list(range(1, len(residues) + 1)) or any(
        row[2].strip() for row in residues
    ):
        raise RuntimeError("GMN PDB residue numbering must exactly match candidate positions")
    try:
        return "".join(AMINO_ACID_3_TO_1[row[3]] for row in residues)
    except KeyError as error:
        raise RuntimeError(f"GMN PDB contains a noncanonical residue: {error.args[0]}") from error


def ownership(
    rows: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    set[str],
]:
    claims: dict[str, dict[str, Any]] = {}
    prepared: dict[str, dict[str, Any]] = {}
    submissions: dict[str, dict[str, Any]] = {}
    completed: set[str] = set()
    provider_ids: dict[str, str] = {}
    for row in rows:
        action = row.get("action")
        key = str(row.get("job_key") or "")
        if action == "authorized":
            if key in claims:
                raise RuntimeError(f"duplicate GMN authorization claim for {key}")
            claims[key] = row
        elif action == "context_prepared":
            if key not in claims or key in prepared:
                raise RuntimeError(f"invalid GMN context preparation for {key}")
            if row.get("authorization_sha256") != claims[key].get("authorization_sha256"):
                raise RuntimeError("GMN context used the wrong authorization claim")
            prepared[key] = row
        elif action == "submitted":
            if key not in prepared or key in submissions:
                raise RuntimeError(f"duplicate GMN submission ownership for {key}")
            if row.get("authorization_sha256") != claims[key].get("authorization_sha256"):
                raise RuntimeError("GMN submission used the wrong authorization claim")
            if row.get("context_archive_sha256") != prepared[key].get("context_archive_sha256"):
                raise RuntimeError("GMN submission used an unprepared context archive")
            provider_id = str(row.get("provider_job_id") or "")
            if not provider_id or provider_id in provider_ids:
                raise RuntimeError("GMN provider job IDs must be nonempty and unique")
            submissions[key] = row
            provider_ids[provider_id] = key
        elif action == "terminal_valid":
            if key not in submissions or key in completed:
                raise RuntimeError(f"invalid GMN terminal transition for {key}")
            if row.get("provider_job_id") != submissions[key].get("provider_job_id"):
                raise RuntimeError("GMN terminal event has the wrong provider owner")
            completed.add(key)
        else:
            raise RuntimeError(f"unknown GMN ledger action: {action}")
    return claims, prepared, submissions, completed


def campaign_state(
    manifest: dict[str, Any], state_dir: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    set[str],
]:
    rows = ledger_rows(state_dir)
    if any(row.get("gmn_manifest_sha") != manifest["gmn_manifest_sha"] for row in rows):
        raise RuntimeError("GMN ledger contains an event from another manifest")
    state = ownership(rows)
    completed = state[3]
    for job_key in completed:
        terminal = next(
            row for row in rows
            if row.get("action") == "terminal_valid" and row.get("job_key") == job_key
        )
        receipt_path = state_dir / "receipts" / f"{job_key}.json"
        if not receipt_path.is_file():
            raise RuntimeError("GMN terminal ledger event lacks its result receipt")
        receipt = read_json(receipt_path)
        supplied = receipt.get("receipt_sha256")
        if (
            supplied != terminal.get("receipt_sha256")
            or supplied != sha256_value(
                {key: value for key, value in receipt.items() if key != "receipt_sha256"}
            )
            or not receipt.get("terminal_valid")
            or receipt.get("gmn_manifest_sha") != manifest["gmn_manifest_sha"]
        ):
            raise RuntimeError("GMN terminal receipt is invalid or ledger-mismatched")
    return state


def authorize_next(manifest: dict[str, Any], state_dir: Path, quoted_cost: float) -> dict[str, Any]:
    if quoted_cost <= 0 or not (quoted_cost < float("inf")):
        raise RuntimeError("provider quote must be a positive finite amount")
    claims, _, _, completed = campaign_state(manifest, state_dir)
    active = set(claims) - completed
    if len(active) >= int(manifest["max_active_jobs"]):
        return {"contract": "pearl.frontier-adaptation-gmn-authorization/1", "action": "wait"}
    spent_exposure = sum(float(row["quoted_max_cost_usd"]) for row in claims.values())
    if spent_exposure + quoted_cost > float(manifest["max_authorized_usd"]):
        raise RuntimeError("GMN quote would exceed the frozen campaign envelope")
    pending = [row for row in manifest["jobs"] if row["job_key"] not in claims]
    if not pending:
        action = "complete" if len(completed) == len(manifest["jobs"]) else "wait"
        return {"contract": "pearl.frontier-adaptation-gmn-authorization/1", "action": action}
    job = pending[0]
    payload = {
        "contract": "pearl.frontier-adaptation-gmn-authorization/1",
        "action": "submit_one",
        "gmn_manifest_sha": manifest["gmn_manifest_sha"],
        "job_key": job["job_key"],
        "generation_report_sha256": job["generation_report_sha256"],
        "context_archive": job["context_archive"],
        "execution": job["execution"],
        "quoted_max_cost_usd": quoted_cost,
        "active_after_submission_max": len(active) + 1,
    }
    payload["authorization_sha256"] = sha256_value(payload)
    event = {
        "contract": "pearl.frontier-adaptation-gmn-ledger-event/1",
        "action": "authorized",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "gmn_manifest_sha": manifest["gmn_manifest_sha"],
        "job_key": job["job_key"],
        "authorization_sha256": payload["authorization_sha256"],
        "quoted_max_cost_usd": quoted_cost,
        "command_output": payload,
    }
    append_ledger(state_dir, event)
    return payload


def prepare_submission(
    manifest: dict[str, Any], state_dir: Path, authorization: dict[str, Any],
    context_archive: Path,
) -> dict[str, Any]:
    unsigned = {key: value for key, value in authorization.items() if key != "authorization_sha256"}
    if authorization.get("authorization_sha256") != sha256_value(unsigned):
        raise RuntimeError("GMN authorization hash mismatch")
    if authorization.get("action") != "submit_one":
        raise RuntimeError("GMN authorization does not permit submission")
    if authorization.get("gmn_manifest_sha") != manifest["gmn_manifest_sha"]:
        raise RuntimeError("GMN authorization belongs to another manifest")
    job = job_for(manifest, str(authorization["job_key"]))
    claims, prepared, submissions, _ = campaign_state(manifest, state_dir)
    if job["job_key"] not in claims:
        raise RuntimeError("GMN submission lacks a reserved authorization claim")
    if claims[job["job_key"]].get("authorization_sha256") != authorization["authorization_sha256"]:
        raise RuntimeError("GMN submission authorization differs from its reserved claim")
    if job["job_key"] in submissions:
        raise RuntimeError("GMN job already has a provider owner")
    if job["job_key"] in prepared:
        raise RuntimeError("GMN job already has a prepared context")
    if not context_archive.is_file():
        raise RuntimeError("context archive does not exist")
    members = job["execution"]["context_member_sha256s"]
    for member, expected_sha in members.items():
        result = subprocess.run(
            ["tar", "--use-compress-program=unzstd", "-xOf", str(context_archive), member],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0 or hashlib.sha256(result.stdout).hexdigest() != expected_sha:
            raise RuntimeError(f"context archive member is missing or hash-mismatched: {member}")
    receipt = {
        "contract": "pearl.frontier-adaptation-gmn-prepared-context/1",
        "gmn_manifest_sha": manifest["gmn_manifest_sha"],
        "authorization_sha256": authorization["authorization_sha256"],
        "job_key": job["job_key"],
        "context_archive_sha256": sha256_file(context_archive),
        "context_member_count": len(members),
        "source_commit_sha": manifest["source_commit_sha"],
    }
    receipt["prepared_context_sha256"] = sha256_value(receipt)
    event = {
        "contract": "pearl.frontier-adaptation-gmn-ledger-event/1",
        "action": "context_prepared",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "gmn_manifest_sha": manifest["gmn_manifest_sha"],
        "authorization_sha256": authorization["authorization_sha256"],
        "job_key": job["job_key"],
        "context_archive_sha256": receipt["context_archive_sha256"],
        "prepared_context_sha256": receipt["prepared_context_sha256"],
        "command_output": receipt,
    }
    append_ledger(state_dir, event)
    return receipt


def record_submission(
    manifest: dict[str, Any], state_dir: Path, prepared_receipt: dict[str, Any],
    provider_job_id: str,
) -> dict[str, Any]:
    supplied = prepared_receipt.get("prepared_context_sha256")
    if supplied != sha256_value(
        {key: value for key, value in prepared_receipt.items() if key != "prepared_context_sha256"}
    ):
        raise RuntimeError("prepared GMN context receipt hash mismatch")
    if prepared_receipt.get("gmn_manifest_sha") != manifest["gmn_manifest_sha"]:
        raise RuntimeError("prepared GMN context belongs to another manifest")
    job = job_for(manifest, str(prepared_receipt["job_key"]))
    claims, prepared, submissions, completed = campaign_state(manifest, state_dir)
    if job["job_key"] not in prepared or job["job_key"] in submissions:
        raise RuntimeError("GMN submission lacks exactly one prepared context")
    if prepared[job["job_key"]].get("prepared_context_sha256") != supplied:
        raise RuntimeError("GMN prepared context differs from its ledger reservation")
    active = set(claims) - completed
    exposure = sum(float(row["quoted_max_cost_usd"]) for row in claims.values())
    if len(active) > int(manifest["max_active_jobs"]):
        raise RuntimeError("GMN active reservation cap is exceeded")
    if exposure > float(manifest["max_authorized_usd"]):
        raise RuntimeError("GMN reserved exposure exceeds the frozen envelope")
    if not provider_job_id.strip():
        raise RuntimeError("provider job ID is required")
    row = {
        "contract": "pearl.frontier-adaptation-gmn-ledger-event/1",
        "action": "submitted",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "gmn_manifest_sha": manifest["gmn_manifest_sha"],
        "authorization_sha256": prepared_receipt["authorization_sha256"],
        "job_key": job["job_key"],
        "provider_job_id": provider_job_id.strip(),
        "context_archive_sha256": prepared_receipt["context_archive_sha256"],
        "generation_report_sha256": job["generation_report_sha256"],
        "quoted_max_cost_usd": float(claims[job["job_key"]]["quoted_max_cost_usd"]),
        "hardware": job["execution"]["hardware"],
        "dockerfile_sha256": job["execution"]["dockerfile_sha256"],
        "entrypoint_sha256": job["execution"]["entrypoint_sha256"],
    }
    append_ledger(state_dir, {**row, "command_output": row})
    return row


def audit_result(
    manifest: dict[str, Any], state_dir: Path, job_key: str,
    provider_job_id: str, result_path: Path, structure_report_path: Path,
) -> dict[str, Any]:
    job = job_for(manifest, job_key)
    _, _, submissions, completed = campaign_state(manifest, state_dir)
    if job_key not in submissions or job_key in completed:
        raise RuntimeError("GMN result lacks exactly one active submission owner")
    submission = submissions[job_key]
    if submission["provider_job_id"] != provider_job_id:
        raise RuntimeError("GMN result has the wrong provider job owner")
    result = read_json(result_path)
    report = read_json(structure_report_path)
    generation_path = Path(job["generation_report"])
    if not generation_path.is_absolute():
        generation_path = ROOT / generation_path
    if (
        not generation_path.is_file()
        or sha256_file(generation_path) != job["generation_report_sha256"]
    ):
        raise RuntimeError("GMN audit lacks the exact hashed generation report")
    generation = read_json(generation_path)
    fold = report.get("contract") or {}
    expected = {
        "contract": job["expected_gmn_result_contract"],
        "complete": True,
        "expected_candidate_count": job["candidate_slots"],
        "completed_candidate_count": job["candidate_slots"],
        "generation_run_key": job["generation_run_key"],
        "generation_contract_sha": job["generation_contract_sha"],
    }
    if any(result.get(key) != value for key, value in expected.items()):
        raise RuntimeError("GMN result summary differs from its manifest row")
    if (
        report.get("status") != "complete"
        or report.get("complete") is not True
        or int(report.get("expected_candidate_count", -1)) != job["candidate_slots"]
        or int(report.get("completed_candidate_count", -1)) != job["candidate_slots"]
        or len(report.get("results", [])) != job["candidate_slots"]
        or fold != job["expected_fold_contract"]
        or fold.get("fold_contract_sha") != result.get("fold_contract_sha")
        or int(report.get("full_structural_gate_passes", -1))
        != sum(bool(row.get("full_structural_gate_pass")) for row in report["results"])
    ):
        raise RuntimeError("GMN structure report is incomplete or contract-mismatched")
    expected_candidates = {
        str(row["candidate_id"]): row for row in generation.get("candidates", [])
    }
    observed_candidates = {
        str(row.get("candidate_id") or ""): row for row in report["results"]
    }
    if (
        len(expected_candidates) != job["candidate_slots"]
        or len(observed_candidates) != job["candidate_slots"]
        or "" in observed_candidates
        or set(observed_candidates) != set(expected_candidates)
    ):
        raise RuntimeError("GMN result candidate IDs differ from the generation panel")
    recomputed_passes = 0
    pdb_hashes: dict[str, str] = {}
    for candidate_id, candidate in expected_candidates.items():
        row = observed_candidates[candidate_id]
        immutable = {
            "prompt_id": candidate["prompt_id"],
            "sample_seed": candidate["sample_seed"],
            "target_length": candidate["target_length"],
            "sequence_sha256": candidate.get("sequence_sha256"),
            "valid_generation": bool(candidate.get("valid_sequence")),
            "duplicate_sequence": bool(candidate.get("duplicate_sequence")),
        }
        if any(row.get(key) != value for key, value in immutable.items()):
            raise RuntimeError(f"GMN result row differs from generation candidate {candidate_id}")
        if not candidate.get("valid_sequence"):
            if row.get("full_structural_gate_pass") is not False:
                raise RuntimeError("invalid generation was not retained as a denominator failure")
            continue
        pdb_path = structure_report_path.parent / "pdb" / f"{candidate_id}.pdb"
        if not pdb_path.is_file() or row.get("pdb_sha256") != sha256_file(pdb_path):
            raise RuntimeError(f"GMN result lacks the exact PDB for {candidate_id}")
        pdb_text = pdb_path.read_text(encoding="utf-8")
        if pdb_sequence(pdb_text) != str(candidate["sequence"]):
            raise RuntimeError(f"GMN PDB sequence differs from candidate {candidate_id}")
        residues, mean_plddt = parse_pdb(pdb_text)
        structural = gate_prediction(
            StructurePrediction(
                sequence=str(candidate["sequence"]),
                residues=residues,
                mean_plddt=mean_plddt,
                backend=str(fold["backend"]),
                pdb_text=pdb_text,
            ),
            plddt_gate=float(fold["plddt_gate"]),
            hbond_max=float(fold["triad_hbond_max_angstrom"]),
        )
        expected_full = bool(
            structural["structural_gate_pass"]
            and structural["triad"]["method"] == fold["required_triad_method"]
        )
        if (
            row.get("mean_plddt") != structural["mean_plddt"]
            or row.get("triad") != structural["triad"]
            or row.get("structural_gate_pass") != structural["structural_gate_pass"]
            or row.get("full_structural_gate_pass") != expected_full
        ):
            raise RuntimeError(f"GMN structural gate fields do not recompute for {candidate_id}")
        recomputed_passes += int(expected_full)
        pdb_hashes[candidate_id] = sha256_file(pdb_path)
    if (
        int(report.get("full_structural_gate_passes", -1)) != recomputed_passes
        or result.get("full_structural_gate_passes") != recomputed_passes
        or report.get("full_structural_gate_yield") != recomputed_passes / job["candidate_slots"]
        or result.get("full_structural_gate_yield") != recomputed_passes / job["candidate_slots"]
    ):
        raise RuntimeError("GMN aggregate structural yield does not recompute from candidate rows")
    receipt = {
        "contract": "pearl.frontier-adaptation-gmn-result-receipt/1",
        "job_key": job_key,
        "provider_job_id": provider_job_id,
        "gmn_manifest_sha": manifest["gmn_manifest_sha"],
        "context_archive_sha256": submission["context_archive_sha256"],
        "generation_report_sha256": job["generation_report_sha256"],
        "gmn_result_sha256": sha256_file(result_path),
        "structure_report_sha256": sha256_file(structure_report_path),
        "fold_contract_sha": fold["fold_contract_sha"],
        "pdb_sha256s": pdb_hashes,
        "terminal_valid": True,
    }
    receipt["receipt_sha256"] = sha256_value(receipt)
    write_json(state_dir / "receipts" / f"{job_key}.json", receipt)
    event = {
        "contract": "pearl.frontier-adaptation-gmn-ledger-event/1",
        "action": "terminal_valid",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "gmn_manifest_sha": manifest["gmn_manifest_sha"],
        "job_key": job_key,
        "provider_job_id": provider_job_id,
        "receipt_sha256": receipt["receipt_sha256"],
        "command_output": receipt,
    }
    append_ledger(state_dir, event)
    return receipt


@contextmanager
def campaign_lock(state_dir: Path):
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / "gmn.lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def remote_anchor_head() -> tuple[dict[str, Any], int] | None:
    repository = json.loads(
        subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner"],
            check=True,
            capture_output=True,
            text=True,
            cwd=ROOT,
        ).stdout
    )["nameWithOwner"]
    artifacts = json.loads(
        subprocess.run(
            [
                "gh", "api", "--method", "GET",
                f"repos/{repository}/actions/artifacts",
                "-f", "name=frontier-adaptation-v2-gmn-anchor-head",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=ROOT,
        ).stdout
    )["artifacts"]
    live = sorted(
        (row for row in artifacts if not row.get("expired")),
        key=lambda row: str(row["created_at"]),
    )
    if not live:
        return None
    run_id = int(live[-1]["workflow_run"]["id"])
    with tempfile.TemporaryDirectory(prefix="gmn-anchor-") as temporary:
        subprocess.run(
            [
                "gh", "run", "download", str(run_id),
                "--name", "frontier-adaptation-v2-gmn-anchor-head", "--dir", temporary,
            ],
            check=True,
            cwd=ROOT,
        )
        receipt = read_json(Path(temporary) / "anchor.json")
    return receipt, run_id


def validate_remote_anchor(manifest: dict[str, Any], state_dir: Path) -> None:
    rows = ledger_rows(state_dir)
    remote = remote_anchor_head()
    if not rows:
        if remote is not None and remote[0].get("manifest_sha256") == manifest["gmn_manifest_sha"]:
            raise RuntimeError("remote GMN ledger exists but local state is empty")
        return
    if remote is None:
        raise RuntimeError("local GMN ledger lacks its canonical remote anchor")
    receipt, run_id = remote
    latest = rows[-1]
    if (
        receipt.get("contract") != "pearl.frontier-adaptation-gmn-remote-anchor/1"
        or receipt.get("manifest_sha256") != manifest["gmn_manifest_sha"]
        or receipt.get("source_commit_sha") != manifest["source_commit_sha"]
        or receipt.get("event_sha256") != latest["event_sha256"]
        or receipt.get("previous_event_sha256") != latest["previous_event_sha256"]
        or int(receipt.get("actions_run_id", -1)) != run_id
    ):
        raise RuntimeError("local GMN ledger differs from the canonical remote anchor")
    run = json.loads(
        subprocess.run(
            [
                "gh", "run", "view", str(run_id),
                "--json", "workflowName,headSha,status,conclusion,displayTitle",
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=ROOT,
        ).stdout
    )
    if (
        run.get("workflowName") != "Frontier adaptation v2 GMN — append one remote ledger anchor"
        or run.get("headSha") != manifest["source_commit_sha"]
        or run.get("status") != "completed"
        or run.get("displayTitle") != f"Frontier GMN anchor {latest['event_sha256']}"
    ):
        raise RuntimeError("canonical GMN remote anchor has the wrong Actions identity")


def anchor_latest_event(manifest: dict[str, Any], state_dir: Path) -> None:
    latest = ledger_rows(state_dir)[-1]
    title = f"Frontier GMN anchor {latest['event_sha256']}"

    def matching_runs() -> list[dict[str, Any]]:
        rows = json.loads(
            subprocess.run(
                [
                    "gh", "run", "list", "--workflow", "frontier-adaptation-v2-gmn-anchor.yml",
                    "--limit", "100",
                    "--json", "databaseId,displayTitle,headSha,status,conclusion",
                ],
                check=True,
                capture_output=True,
                text=True,
                cwd=ROOT,
            ).stdout
        )
        return sorted(
            (
                row
                for row in rows
                if row["displayTitle"] == title
                and row.get("headSha") == manifest["source_commit_sha"]
            ),
            key=lambda row: int(row["databaseId"]),
        )

    for _ in range(4):
        matches = matching_runs()
        remote = remote_anchor_head()
        if remote is not None and remote[0].get("event_sha256") == latest["event_sha256"]:
            validate_remote_anchor(manifest, state_dir)
            return
        successful = [
            row
            for row in matches
            if row.get("status") == "completed" and row.get("conclusion") == "success"
        ]
        if successful:
            for _ in range(60):
                remote = remote_anchor_head()
                if remote is not None and remote[0].get("event_sha256") == latest["event_sha256"]:
                    validate_remote_anchor(manifest, state_dir)
                    return
                if (
                    remote is not None
                    and remote[0].get("event_sha256") != latest["previous_event_sha256"]
                ):
                    raise RuntimeError("canonical GMN head advanced to another event")
                time.sleep(2)
            raise RuntimeError("successful GMN anchor artifact did not become observable")
        active = [
            row
            for row in matches
            if row.get("status") in {"queued", "in_progress", "waiting", "pending"}
        ]
        if active:
            subprocess.run(
                ["gh", "run", "watch", str(active[0]["databaseId"]), "--exit-status"],
                check=False,
                cwd=ROOT,
            )
            continue
        prior_ids = {int(row["databaseId"]) for row in matches}
        subprocess.run(
            [
                "gh", "workflow", "run", "frontier-adaptation-v2-gmn-anchor.yml",
                "--ref", manifest["anchor_ref"],
                "-f", f"manifest_sha256={manifest['gmn_manifest_sha']}",
                "-f", f"source_commit_sha={manifest['source_commit_sha']}",
                "-f", f"event_sha256={latest['event_sha256']}",
                "-f", f"previous_event_sha256={latest['previous_event_sha256']}",
            ],
            check=True,
            cwd=ROOT,
        )
        for _ in range(60):
            if any(int(row["databaseId"]) not in prior_ids for row in matching_runs()):
                break
            time.sleep(2)
        else:
            raise RuntimeError("GMN remote anchor dispatch did not become observable")
    raise RuntimeError("GMN remote anchor did not reach a successful terminal state")


def retry_pending_anchor(manifest: dict[str, Any], state_dir: Path) -> dict[str, Any]:
    rows = ledger_rows(state_dir)
    if not rows:
        raise RuntimeError("there is no pending GMN ledger event to anchor")
    latest = rows[-1]
    remote = remote_anchor_head()
    if remote is not None and remote[0].get("event_sha256") == latest["event_sha256"]:
        validate_remote_anchor(manifest, state_dir)
        return dict(latest["command_output"])
    if latest["previous_event_sha256"] == "ROOT":
        if remote is not None and remote[0].get("manifest_sha256") == manifest["gmn_manifest_sha"]:
            raise RuntimeError("pending first GMN event conflicts with a remote campaign head")
    else:
        if remote is None:
            raise RuntimeError("pending GMN event lost its required remote predecessor")
        receipt = remote[0]
        if (
            receipt.get("manifest_sha256") != manifest["gmn_manifest_sha"]
            or receipt.get("source_commit_sha") != manifest["source_commit_sha"]
            or receipt.get("event_sha256") != latest["previous_event_sha256"]
        ):
            raise RuntimeError("pending GMN event would fork the canonical remote ledger")
    anchor_latest_event(manifest, state_dir)
    return dict(latest["command_output"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    next_parser = sub.add_parser("next")
    next_parser.add_argument("--state-dir", required=True)
    next_parser.add_argument("--quoted-max-cost-usd", type=float, required=True)
    next_parser.add_argument("--output", required=True)
    submit = sub.add_parser("record-submission")
    submit.add_argument("--state-dir", required=True)
    submit.add_argument("--prepared-context", required=True)
    submit.add_argument("--provider-job-id", required=True)
    submit.add_argument("--output", required=True)
    prepare = sub.add_parser("prepare-submission")
    prepare.add_argument("--state-dir", required=True)
    prepare.add_argument("--authorization", required=True)
    prepare.add_argument("--context-archive", required=True)
    prepare.add_argument("--output", required=True)
    audit = sub.add_parser("audit-result")
    audit.add_argument("--state-dir", required=True)
    audit.add_argument("--job-key", required=True)
    audit.add_argument("--provider-job-id", required=True)
    audit.add_argument("--gmn-result", required=True)
    audit.add_argument("--structure-report", required=True)
    audit.add_argument("--output", required=True)
    retry = sub.add_parser("retry-anchor")
    retry.add_argument("--state-dir", required=True)
    retry.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest = read_json(Path(args.manifest))
    validate_manifest(manifest)
    state_dir = Path(args.state_dir)
    with campaign_lock(state_dir):
        if args.command == "retry-anchor":
            payload = retry_pending_anchor(manifest, state_dir)
            write_json(Path(args.output), payload)
            print(json.dumps({"status": "complete", "action": "anchor_recovered"}))
            return
        validate_remote_anchor(manifest, state_dir)
        prior_event_count = len(ledger_rows(state_dir))
        if args.command == "next":
            payload = authorize_next(manifest, state_dir, args.quoted_max_cost_usd)
        elif args.command == "prepare-submission":
            payload = prepare_submission(
                manifest, state_dir, read_json(Path(args.authorization)),
                Path(args.context_archive),
            )
        elif args.command == "record-submission":
            payload = record_submission(
                manifest, state_dir, read_json(Path(args.prepared_context)),
                args.provider_job_id,
            )
        else:
            payload = audit_result(
                manifest, state_dir, args.job_key, args.provider_job_id,
                Path(args.gmn_result), Path(args.structure_report),
            )
        if len(ledger_rows(state_dir)) != prior_event_count:
            anchor_latest_event(manifest, state_dir)
    write_json(Path(args.output), payload)
    print(json.dumps({"status": "complete", "action": payload.get("action")}))


if __name__ == "__main__":
    main()
