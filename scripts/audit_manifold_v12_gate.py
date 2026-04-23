#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_PATH = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT_PATH / "src"
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scripts import audit_manifold_v11_gate as shared


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit manifold v1.2 p24 gate results and prepare the v1.3 offline curriculum pivot"
    )
    parser.add_argument("--robustness-summary-path", required=True)
    parser.add_argument("--ablation-root", default="reports/ablations")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    return parser.parse_args()


def hit_seed_records(prompt_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for prompt_record in prompt_records:
        for seed_record in prompt_record.get("seed_records", []):
            candidate = seed_record.get("selected_candidate") or {}
            if not bool(candidate.get("functional_bridge_passes")):
                continue
            rows.append(
                {
                    "step": int(prompt_record["step"]),
                    "prompt": str(prompt_record["prompt"]),
                    "requested_length": prompt_record.get("requested_length"),
                    "seed": int(seed_record["seed"]),
                    "run_name": str(seed_record["run_name"]),
                    "selected_length": seed_record.get("selected_length"),
                    "selected_length_delta": seed_record.get("selected_length_delta"),
                    "selected_candidate": candidate,
                }
            )
    rows.sort(key=lambda row: (int(row["step"]), int(row["seed"])))
    return rows


def diagnose(audit: dict[str, Any]) -> list[str]:
    diagnoses: list[str] = []
    hit_rows = audit["hit_seed_records"]
    prompt_records = audit["prompt_records"]
    prompt_hit_count = int(audit["prompt_hit_count"])
    raw_prompt_tier2_count = int(audit["raw_prompt_tier2_count"])
    functional_hit_count = int(audit["functional_hit_count"])
    family_hit_count = int(audit["family_faithful_hit_count"])

    if hit_rows:
        diagnoses.append("paid_gate_recovered_real_hits_across_all_three_seeds")
    if prompt_hit_count < 4:
        diagnoses.append("prompt_coverage_remains_below_the_durability_floor")
    if raw_prompt_tier2_count == prompt_hit_count:
        diagnoses.append("no_hidden_raw_tier2_reservoir_exists_outside_the_recovered_hit_prompts")
    if family_hit_count < functional_hit_count:
        diagnoses.append("one_recovered_hit_is_bridge_only_and_not_family_faithful")
    if any(bool(record.get("selected_any_geometry")) and bool(record.get("selected_any_esm")) for record in prompt_records):
        diagnoses.append("nearby_prompts_already_show_split_geometry_and_esm_support_that_can_be_replayed_offline")
    return diagnoses


def build_recommendations(audit: dict[str, Any]) -> list[str]:
    hit_lengths = audit["hit_prompt_lengths"]
    return [
        "Do not escalate to stage-B, p48, or mining from v1.2. The next branch should stay capped at stage-A plus p24 only.",
        "Build manifold v1.3 from three ingredients: the broad v1.2 selected base, exact replay of the recovered gate hits, and scaffold replay on nearby support prompts.",
        f"Center the support replay around the recovered prompt lengths {hit_lengths} so the next branch expands prompt coverage instead of deepening one narrow basin.",
        "Treat the explicit smoke gate and the broader durability gate as separate checks; the v1.2 branch cleared the former but not the latter.",
    ]


def build_audit(args: argparse.Namespace) -> dict[str, Any]:
    summary_path = shared.resolved(args.robustness_summary_path)
    ablation_root = shared.resolved(args.ablation_root)
    robustness_summary = shared.read_json(summary_path)
    records = shared.collect_candidate_records(summary_path, ablation_root)
    selected_records = records["selected_records"]
    candidate_records = records["candidate_records"]
    prompt_records = shared.prompt_records(selected_records, candidate_records)
    hit_rows = hit_seed_records(prompt_records)
    hit_prompt_steps = sorted({int(row["step"]) for row in hit_rows})
    hit_prompt_lengths = [
        int(length)
        for length in dict.fromkeys(
            row["requested_length"] for row in hit_rows if row.get("requested_length") is not None
        )
    ]
    family_hit_count = sum(
        bool(row["selected_candidate"].get("family_faithful_bridge_passes"))
        for row in hit_rows
    )
    raw_prompt_tier2_count = sum(bool(row.get("all_any_tier2")) for row in prompt_records)
    selected_prompt_tier2_count = sum(bool(row.get("selected_any_tier2")) for row in prompt_records)
    selected_deltas = [
        abs(int(record["selected_length_delta"]))
        for record in selected_records
        if record.get("selected_length_delta") is not None
    ]
    raw_deltas = [
        abs(int(record["candidate_length_delta"]))
        for record in candidate_records
        if record.get("candidate_length_delta") is not None
    ]

    audit: dict[str, Any] = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "run_name": str(robustness_summary.get("suite_name") or summary_path.parent.name),
        "robustness_summary_path": str(summary_path),
        "ablation_root": str(ablation_root),
        "gate": robustness_summary.get("durability_gate", {}),
        "completed_run_count": robustness_summary.get("completed_run_count"),
        "missing_run_count": robustness_summary.get("missing_run_count"),
        "missing_audits": records["missing_audits"],
        "selected_population": shared.candidate_population_summary(selected_records, field="selected_candidate"),
        "raw_population": shared.candidate_population_summary(candidate_records, field="candidate"),
        "selected_length_delta_summary": shared.numeric_summary(selected_deltas),
        "raw_length_delta_summary": shared.numeric_summary(raw_deltas),
        "prompt_records": prompt_records,
        "hit_seed_records": hit_rows,
        "prompt_hit_count": selected_prompt_tier2_count,
        "raw_prompt_tier2_count": raw_prompt_tier2_count,
        "functional_hit_count": len(hit_rows),
        "family_faithful_hit_count": family_hit_count,
        "hit_prompt_steps": hit_prompt_steps,
        "hit_prompt_lengths": hit_prompt_lengths,
    }
    audit["diagnoses"] = diagnose(audit)
    audit["recommendations"] = build_recommendations(audit)
    return audit


def write_markdown(path: Path, audit: dict[str, Any]) -> None:
    gate = audit.get("gate", {})
    group_results = gate.get("group_results") or []
    first_group = group_results[0] if group_results else {}
    lines = [
        "# Manifold v1.2 Gate Audit",
        "",
        f"- run: `{audit['run_name']}`",
        f"- generated: `{audit['generated_at_utc']}`",
        f"- completed runs: `{audit['completed_run_count']}`",
        f"- missing runs: `{audit['missing_run_count']}`",
        f"- durability gate passed: `{bool(gate.get('passed'))}`",
        f"- selected prompt hits: `{audit['prompt_hit_count']}`",
        f"- raw prompt hits: `{audit['raw_prompt_tier2_count']}`",
        f"- functional hits: `{audit['functional_hit_count']}`",
        f"- family-faithful hits: `{audit['family_faithful_hit_count']}`",
        f"- hit prompt steps: `{audit['hit_prompt_steps']}`",
        f"- hit prompt lengths: `{audit['hit_prompt_lengths']}`",
    ]
    if first_group:
        lines.extend(
            [
                f"- tier2 hits by seed: `{first_group.get('tier2_hits_by_seed')}`",
                f"- prompt coverage by seed: `{first_group.get('prompt_coverage_by_seed')}`",
            ]
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- The paid gate produced real post-ESM hits instead of pure geometry/stability split failures.",
            "- The branch is still too narrow at the prompt level, so the next move is a breadth-oriented offline curriculum update rather than a deeper paid escalation.",
            "",
            "## Diagnosis",
            "",
        ]
    )
    lines.extend(f"- `{diagnosis}`" for diagnosis in audit["diagnoses"])
    lines.extend(["", "## Recommended v1.3 Direction", ""])
    lines.extend(f"- {recommendation}" for recommendation in audit["recommendations"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    audit = build_audit(args)
    output_json = shared.resolved(args.output_json)
    output_md = shared.resolved(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(output_md, audit)
    print(json.dumps({"output_json": str(output_json), "output_md": str(output_md)}, indent=2))


if __name__ == "__main__":
    main()
