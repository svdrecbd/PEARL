#!/usr/bin/env python3
"""Audit the frozen 168-sequence discovery-priority folding artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        rank = (cursor + 1 + end) / 2
        for index in order[cursor:end]:
            ranks[index] = rank
        cursor = end
    return ranks


def pearson(left: list[float], right: list[float]) -> float:
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    denominator = math.sqrt(
        sum((x - left_mean) ** 2 for x in left)
        * sum((y - right_mean) ** 2 for y in right)
    )
    return numerator / denominator if denominator else float("nan")


def spearman(left: list[float], right: list[float]) -> float:
    return pearson(average_ranks(left), average_ranks(right))


def fisher_enrichment_p(a: int, b: int, c: int, d: int) -> float:
    row_one = a + b
    row_two = c + d
    successes = a + c
    total = row_one + row_two
    upper = min(row_one, successes)
    denominator = math.comb(total, row_one)
    return sum(
        math.comb(successes, observed) * math.comb(total - successes, row_one - observed)
        for observed in range(a, upper + 1)
    ) / denominator


def comparison(a: int, b: int, c: int, d: int) -> dict[str, Any]:
    return {
        "selected_pass": a,
        "selected_fail": b,
        "control_pass": c,
        "control_fail": d,
        "selected_rate": a / (a + b),
        "control_rate": c / (c + d),
        "haldane_anscombe_odds_ratio": ((a + 0.5) * (d + 0.5))
        / ((b + 0.5) * (c + 0.5)),
        "fisher_exact_one_sided_enrichment_p": fisher_enrichment_p(a, b, c, d),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--shard", required=True)
    parser.add_argument("--discovery", required=True)
    parser.add_argument("--provider-receipt", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir)
    report_path = artifact_dir / "structure_report.json"
    contract_path = artifact_dir / "fold_contract.json"
    report = read_json(report_path)
    contract = read_json(contract_path)
    shard = read_json(Path(args.shard))
    discovery = read_json(Path(args.discovery))
    provider = read_json(Path(args.provider_receipt))

    provider_result = provider.get("result", {})
    if provider.get("status") != "succeeded" or not provider_result.get("complete"):
        raise RuntimeError("provider job is not complete and successful")
    if sha256_file(report_path) != provider_result.get("structure_report_sha256"):
        raise RuntimeError("structure report differs from the provider result hash")
    if report.get("contract") != contract:
        raise RuntimeError("fold contract file differs from the report contract")
    unsigned_contract = {key: value for key, value in contract.items() if key != "fold_contract_sha256"}
    if contract.get("fold_contract_sha256") != sha256_value(unsigned_contract):
        raise RuntimeError("fold contract self-hash mismatch")
    if contract.get("fold_contract_sha256") != provider_result.get("fold_contract_sha256"):
        raise RuntimeError("provider result is bound to a different fold contract")
    if shard.get("shard_sha256") != sha256_value(
        {key: value for key, value in shard.items() if key != "shard_sha256"}
    ):
        raise RuntimeError("priority shard self-hash mismatch")
    if discovery.get("funnel_sha256") != sha256_value(
        {key: value for key, value in discovery.items() if key != "funnel_sha256"}
    ):
        raise RuntimeError("discovery funnel self-hash mismatch")
    if contract.get("shard_file_sha256") != sha256_file(Path(args.shard)):
        raise RuntimeError("fold contract is bound to a different priority shard file")
    if contract.get("discovery_file_sha256") != sha256_file(Path(args.discovery)):
        raise RuntimeError("fold contract is bound to a different discovery file")

    results = list(report.get("results", []))
    if not report.get("complete") or report.get("status") != "complete":
        raise RuntimeError("structure report is incomplete")
    if report.get("expected_sequence_count") != 168 or len(results) != 168:
        raise RuntimeError("structure report does not contain exactly 168 results")

    shard_rows = {str(row["sequence_sha256"]): row for row in shard.get("sequences", [])}
    if len(shard_rows) != 168:
        raise RuntimeError("priority shard is not 168 unique sequences")
    discovery_rows: dict[str, tuple[str, dict[str, Any]]] = {}
    for role, field in (
        ("selected", "selected_sequences"),
        ("random_survivor", "random_survivor_sequences"),
        ("random_audit", "audit_pool_sequences"),
    ):
        for row in discovery.get(field, []):
            sequence_sha = str(row["sequence_sha256"])
            if sequence_sha in discovery_rows:
                raise RuntimeError(f"discovery panels overlap: {sequence_sha}")
            discovery_rows[sequence_sha] = (role, row)
    result_rows = {str(row["sequence_sha256"]): row for row in results}
    if len(result_rows) != 168 or set(result_rows) != set(shard_rows) or set(result_rows) != set(discovery_rows):
        raise RuntimeError("report, priority shard, and frozen discovery panels differ")

    for sequence_sha, row in result_rows.items():
        shard_row = shard_rows[sequence_sha]
        role, discovery_row = discovery_rows[sequence_sha]
        if row.get("discovery_panel_roles") != [role]:
            raise RuntimeError(f"report role mismatch: {sequence_sha}")
        if row.get("slot_count") != shard_row.get("slot_count") or row.get("slot_mappings") != shard_row.get("slot_mappings"):
            raise RuntimeError(f"slot mapping mismatch: {sequence_sha}")
        if hashlib.sha256(str(shard_row["sequence"]).encode()).hexdigest() != sequence_sha:
            raise RuntimeError(f"sequence hash mismatch: {sequence_sha}")
        if str(discovery_row["sequence"]) != str(shard_row["sequence"]):
            raise RuntimeError(f"discovery sequence mismatch: {sequence_sha}")
        expected_relative = Path("discovery-priority") / "pdb" / f"{sequence_sha}.pdb"
        if Path(str(row.get("pdb_path"))) != expected_relative:
            raise RuntimeError(f"unexpected PDB path: {sequence_sha}")
        pdb_path = artifact_dir.parent / expected_relative
        if not pdb_path.is_file() or sha256_file(pdb_path) != row.get("pdb_sha256"):
            raise RuntimeError(f"PDB hash mismatch: {sequence_sha}")

    roles = ("selected", "random_survivor", "random_audit")
    panel_metrics: dict[str, Any] = {}
    for role in roles:
        rows = [row for row in results if row["discovery_panel_roles"] == [role]]
        plddts = [float(row["mean_plddt"]) for row in rows]
        panel_metrics[role] = {
            "n": len(rows),
            "mean_plddt": statistics.fmean(plddts),
            "median_plddt": statistics.median(plddts),
            "plddt_pass": sum(bool(row["plddt_pass"]) for row in rows),
            "triad_found_sidechain": sum(row.get("triad", {}).get("method") == "sidechain" for row in rows),
            "triad_geometry_pass": sum(bool(row.get("triad", {}).get("passes")) for row in rows),
            "full_structural_gate_pass": sum(bool(row["full_structural_gate_pass"]) for row in rows),
        }

    selected = [row for row in results if row["discovery_panel_roles"] == ["selected"]]
    controls = [row for row in results if row["discovery_panel_roles"] != ["selected"]]
    comparisons = {}
    for field, predicate in (
        ("plddt_pass", lambda row: bool(row["plddt_pass"])),
        ("triad_geometry_pass", lambda row: bool(row.get("triad", {}).get("passes"))),
        ("full_structural_gate_pass", lambda row: bool(row["full_structural_gate_pass"])),
    ):
        selected_pass = sum(predicate(row) for row in selected)
        control_pass = sum(predicate(row) for row in controls)
        comparisons[field] = comparison(
            selected_pass,
            len(selected) - selected_pass,
            control_pass,
            len(controls) - control_pass,
        )

    failure_paths: dict[str, int] = {}
    for row in results:
        key = (
            f"plddt={str(bool(row['plddt_pass'])).lower()},"
            f"triad_found={str(bool(row.get('triad', {}).get('found'))).lower()},"
            f"triad_geometry={str(bool(row.get('triad', {}).get('passes'))).lower()},"
            f"full={str(bool(row['full_structural_gate_pass'])).lower()}"
        )
        failure_paths[key] = failure_paths.get(key, 0) + 1

    pass_rows = []
    for row in results:
        if not row["full_structural_gate_pass"]:
            continue
        sequence_sha = str(row["sequence_sha256"])
        role, discovery_row = discovery_rows[sequence_sha]
        pass_rows.append({
            "sequence_sha256": sequence_sha,
            "sequence": shard_rows[sequence_sha]["sequence"],
            "sequence_length": row["sequence_length"],
            "panel_role": role,
            "source_job_key": discovery_row.get("source_job_key"),
            "candidate_id": discovery_row.get("candidate_id"),
            "prompt_id": discovery_row.get("prompt_id"),
            "sample_seed": discovery_row.get("sample_seed"),
            "sample_index": discovery_row.get("sample_index"),
            "length_bin": discovery_row.get("length_bin"),
            "esm3_score": discovery_row.get("esm3_score"),
            "mean_plddt": row["mean_plddt"],
            "triad": row["triad"],
            "grade": row["grade"],
            "pdb_sha256": row["pdb_sha256"],
        })

    esm3_scores = [float(discovery_rows[str(row["sequence_sha256"])][1]["esm3_score"]) for row in results]
    plddts = [float(row["mean_plddt"]) for row in results]
    payload = {
        "contract": "pearl.frontier-replication-salvage-discovery-priority-folding-audit/1",
        "status": "complete",
        "analysis_scope": "posthoc_exploratory_replication_salvage",
        "integrity": {
            "provider_job_id": provider.get("job_id"),
            "provider_artifact_id": provider.get("artifact", {}).get("artifact_id"),
            "structure_report_sha256": sha256_file(report_path),
            "fold_contract_file_sha256": sha256_file(contract_path),
            "fold_contract_sha256": contract["fold_contract_sha256"],
            "priority_shard_file_sha256": sha256_file(Path(args.shard)),
            "discovery_file_sha256": sha256_file(Path(args.discovery)),
            "pdb_files_verified": 168,
            "membership_and_roles_verified": True,
            "slot_mappings_verified": True,
        },
        "counts": {
            "expected": 168,
            "completed": 168,
            "full_structural_gate_passes": len(pass_rows),
        },
        "panel_metrics": panel_metrics,
        "selected_vs_all_controls_exploratory": comparisons,
        "esm3_score_vs_plddt_spearman_rho": spearman(esm3_scores, plddts),
        "failure_path_counts": dict(sorted(failure_paths.items())),
        "full_structural_gate_passes": pass_rows,
        "interpretation_boundary": {
            "full_confirmatory_battery_complete": False,
            "remaining_confirmatory_only_folds_deferred": 10622,
            "confirmatory_claim_authorized": False,
            "endpoint_thresholds_changed": False,
            "panel_membership_changed": False,
        },
    }
    payload["audit_sha256"] = sha256_value(payload)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
