#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_PATH = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT_PATH / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.paths import resolve_repo_path


RUN_NAME_PATTERN = re.compile(r"-p(?P<prompt_count>\d+)-t(?P<temperature>[\dp]+)-s(?P<seed>\d+)$")
REQUESTED_LENGTH_PATTERNS = [
    re.compile(r"(?:length near|around|about)\s+(\d+)\s*(?:aa|amino acids)?", re.IGNORECASE),
    re.compile(r"(\d+)\s*(?:aa|amino acids)\s+long", re.IGNORECASE),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit manifold v1.1 p24 gate failures and produce a v1.2 offline-first postmortem"
    )
    parser.add_argument("--robustness-summary-path", required=True)
    parser.add_argument("--ablation-root", default="reports/ablations")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    return parser.parse_args()


def resolved(value: str) -> Path:
    path = resolve_repo_path(value)
    if path is None or path.startswith("tinker://"):
        raise ValueError(f"could not resolve local path: {value}")
    return Path(path)


def mirrored_report_path(value: str | None, *, default_name: str | None = None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.exists():
        return path
    if default_name is not None:
        sibling = path.parent / default_name
        if sibling.exists():
            return sibling
    parts = path.parts
    if "reports" in parts:
        index = parts.index("reports")
        mirrored = ROOT_PATH / Path(*parts[index:])
        if mirrored.exists():
            return mirrored
        if default_name is not None:
            return mirrored.parent / default_name
        return mirrored
    if default_name is not None:
        return path.parent / default_name
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def requested_length(prompt: str) -> int | None:
    for pattern in REQUESTED_LENGTH_PATTERNS:
        match = pattern.search(prompt)
        if match:
            return int(match.group(1))
    return None


def parse_run_name(name: str) -> dict[str, int | float] | None:
    match = RUN_NAME_PATTERN.search(name)
    if not match:
        return None
    return {
        "prompt_count": int(match.group("prompt_count")),
        "temperature": float(match.group("temperature").replace("p", ".")),
        "seed": int(match.group("seed")),
    }


def selected_candidate(record: dict[str, Any]) -> dict[str, Any] | None:
    selected = [candidate for candidate in record.get("candidates", []) if candidate.get("selected")]
    if selected:
        return selected[0]
    candidates = list(record.get("candidates", []))
    candidates.sort(
        key=lambda candidate: (
            int(candidate.get("stage2_rank") or 10**9),
            int(candidate.get("stage1_rank") or 10**9),
        )
    )
    return candidates[0] if candidates else None


def to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def candidate_sequence(candidate: dict[str, Any]) -> str:
    return str(candidate.get("extracted_sequence") or candidate.get("sequence") or "").strip().upper()


def candidate_length(candidate: dict[str, Any]) -> int:
    return to_int(candidate.get("length")) or len(candidate_sequence(candidate))


def candidate_mode(candidate: dict[str, Any] | None) -> str:
    if candidate is None:
        return "missing"
    motif_count = to_int(candidate.get("motif_count"))
    geometry = bool(candidate.get("geometry_passes"))
    esm = bool(candidate.get("esm_gate_pass"))
    functional = bool(candidate.get("functional_bridge_passes"))
    family = bool(candidate.get("family_faithful_bridge_passes"))
    if family:
        return "family_faithful"
    if functional:
        return "functional"
    if motif_count == 1 and geometry and esm:
        return "tier2_proxy"
    if motif_count == 1 and geometry and not esm:
        return "geometry_only"
    if motif_count == 1 and esm and not geometry:
        return "stability_only"
    if motif_count == 0:
        return "missing_motif"
    if motif_count > 1:
        return "motif_spam"
    return "single_motif_no_geom_no_esm"


def candidate_summary(candidate: dict[str, Any] | None) -> dict[str, Any]:
    if candidate is None:
        return {"mode": "missing"}
    sequence = candidate_sequence(candidate)
    return {
        "mode": candidate_mode(candidate),
        "sequence": sequence,
        "length": candidate_length(candidate),
        "stage1_rank": candidate.get("stage1_rank"),
        "stage2_rank": candidate.get("stage2_rank"),
        "stage2_score": to_float(candidate.get("stage2_score")),
        "hard_gate_pass": bool(candidate.get("hard_gate_pass")),
        "is_trainable": bool(candidate.get("is_trainable")),
        "trainability_reason": candidate.get("trainability_reason"),
        "motif_count": to_int(candidate.get("motif_count")),
        "has_family_serine_motif": bool(candidate.get("has_family_serine_motif")),
        "esm_gate_pass": bool(candidate.get("esm_gate_pass")),
        "geometry_passes": bool(candidate.get("geometry_passes")),
        "passes_core_screen": bool(candidate.get("passes_core_screen")),
        "functional_bridge_passes": bool(candidate.get("functional_bridge_passes")),
        "family_faithful_bridge_passes": bool(candidate.get("family_faithful_bridge_passes")),
        "raw_esm_score": to_float(candidate.get("raw_esm_score")),
        "geometry_score": to_float(candidate.get("geometry_score")),
        "best_gap_error": candidate.get("best_gap_error"),
        "ser_asp_gap_error": candidate.get("ser_asp_gap_error"),
        "asp_his_gap_error": candidate.get("asp_his_gap_error"),
        "ser_his_gap_error": candidate.get("ser_his_gap_error"),
    }


def iter_summary_runs(summary: dict[str, Any]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for group in summary.get("groups", []):
        prompt_count = int(group.get("prompt_count") or 0)
        temperature = float(group.get("temperature") or 0.0)
        for run in group.get("runs", []):
            payload = dict(run)
            payload.setdefault("prompt_count", prompt_count)
            payload.setdefault("temperature", temperature)
            parsed = parse_run_name(str(payload.get("run_name") or ""))
            if parsed:
                payload.setdefault("seed", parsed["seed"])
                payload.setdefault("prompt_count", parsed["prompt_count"])
                payload.setdefault("temperature", parsed["temperature"])
            runs.append(payload)
    return runs


def collect_runs_from_glob(summary_path: Path, ablation_root: Path) -> list[dict[str, Any]]:
    run_name = summary_path.parent.name
    runs: list[dict[str, Any]] = []
    for run_dir in sorted(ablation_root.glob(f"{run_name}-p*-t*-s*")):
        parsed = parse_run_name(run_dir.name)
        if parsed is None:
            continue
        runs.append(
            {
                "run_name": run_dir.name,
                "summary_path": str(run_dir / "summary.json"),
                "candidate_audit_path": str(run_dir / "candidate_audit.json"),
                **parsed,
            }
        )
    return runs


def collect_candidate_records(summary_path: Path, ablation_root: Path) -> dict[str, list[dict[str, Any]]]:
    summary = read_json(summary_path)
    runs = iter_summary_runs(summary)
    if not runs:
        runs = collect_runs_from_glob(summary_path, ablation_root)

    selected_records: list[dict[str, Any]] = []
    candidate_records: list[dict[str, Any]] = []
    missing_audits: list[dict[str, Any]] = []

    for run in runs:
        run_name = str(run.get("run_name") or "")
        seed = int(run.get("seed") or 0)
        prompt_count = int(run.get("prompt_count") or 0)
        temperature = float(run.get("temperature") or 0.0)
        audit_path = mirrored_report_path(str(run.get("candidate_audit_path") or ""), default_name="candidate_audit.json")
        if audit_path is None or not audit_path.exists():
            raw_summary_path = Path(str(run.get("summary_path") or ""))
            raw_sibling = raw_summary_path.parent / "candidate_audit.json"
            if raw_sibling.exists():
                audit_path = raw_sibling
            else:
                summary_local = mirrored_report_path(str(run.get("summary_path") or ""), default_name="summary.json")
                audit_path = summary_local.parent / "candidate_audit.json" if summary_local is not None else None
        if audit_path is None or not audit_path.exists():
            missing_audits.append({"run_name": run_name, "candidate_audit_path": str(audit_path)})
            continue

        audit = read_json(audit_path)
        for record in audit.get("records", []):
            prompt = str(record.get("prompt") or "").strip()
            req_len = requested_length(prompt)
            step = int(record.get("step") or 0)
            selected = selected_candidate(record)
            selected_info = candidate_summary(selected)
            selected_len = int(selected_info.get("length") or 0)
            selected_record = {
                "run_name": run_name,
                "prompt_count": prompt_count,
                "temperature": temperature,
                "seed": seed,
                "step": step,
                "prompt": prompt,
                "requested_length": req_len,
                "selected_length": selected_len,
                "selected_length_delta": selected_len - req_len if req_len is not None and selected_len else None,
                "selected_candidate": selected_info,
                "candidate_mode": str(selected_info["mode"]),
                "candidate_audit_path": str(audit_path),
            }
            selected_records.append(selected_record)

            for rank, candidate in enumerate(record.get("candidates", []), start=1):
                candidate_info = candidate_summary(candidate)
                candidate_len = int(candidate_info.get("length") or 0)
                candidate_records.append(
                    {
                        "run_name": run_name,
                        "prompt_count": prompt_count,
                        "temperature": temperature,
                        "seed": seed,
                        "step": step,
                        "prompt": prompt,
                        "requested_length": req_len,
                        "candidate_rank": rank,
                        "selected": bool(candidate.get("selected")),
                        "candidate_length": candidate_len,
                        "candidate_length_delta": candidate_len - req_len
                        if req_len is not None and candidate_len
                        else None,
                        "candidate": candidate_info,
                        "candidate_mode": str(candidate_info["mode"]),
                        "candidate_audit_path": str(audit_path),
                    }
                )

    return {
        "selected_records": selected_records,
        "candidate_records": candidate_records,
        "missing_audits": missing_audits,
    }


def numeric_summary(values: list[int | float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "median": None, "mean": None, "max": None}
    return {
        "count": len(values),
        "min": min(values),
        "median": round(float(statistics.median(values)), 3),
        "mean": round(float(sum(values) / len(values)), 3),
        "max": max(values),
    }


def candidate_population_summary(records: list[dict[str, Any]], *, field: str) -> dict[str, Any]:
    candidates = [record[field] for record in records if isinstance(record.get(field), dict)]
    mode_counts = Counter(str(candidate.get("mode")) for candidate in candidates)
    trainability_counts = Counter(str(candidate.get("trainability_reason")) for candidate in candidates)
    motif_count_histogram = Counter(str(candidate.get("motif_count")) for candidate in candidates)
    lengths = [int(candidate.get("length") or 0) for candidate in candidates if candidate.get("length")]

    motif_one = [candidate for candidate in candidates if int(candidate.get("motif_count") or 0) == 1]
    motif_one_geometry = [
        candidate for candidate in motif_one if bool(candidate.get("geometry_passes"))
    ]
    motif_one_esm = [candidate for candidate in motif_one if bool(candidate.get("esm_gate_pass"))]
    motif_one_geometry_esm = [
        candidate for candidate in motif_one if bool(candidate.get("geometry_passes")) and bool(candidate.get("esm_gate_pass"))
    ]

    return {
        "count": len(candidates),
        "mode_counts": dict(sorted(mode_counts.items())),
        "trainability_reason_counts": dict(trainability_counts.most_common()),
        "motif_count_histogram": dict(sorted(motif_count_histogram.items())),
        "length_summary": numeric_summary(lengths),
        "flag_counts": {
            "hard_gate_passes": sum(bool(candidate.get("hard_gate_pass")) for candidate in candidates),
            "is_trainable": sum(bool(candidate.get("is_trainable")) for candidate in candidates),
            "motif_count_eq_1": len(motif_one),
            "has_family_serine_motif": sum(bool(candidate.get("has_family_serine_motif")) for candidate in candidates),
            "geometry_passes": sum(bool(candidate.get("geometry_passes")) for candidate in candidates),
            "esm_gate_passes": sum(bool(candidate.get("esm_gate_pass")) for candidate in candidates),
            "passes_core_screen": sum(bool(candidate.get("passes_core_screen")) for candidate in candidates),
            "functional_bridge_passes": sum(bool(candidate.get("functional_bridge_passes")) for candidate in candidates),
            "family_faithful_bridge_passes": sum(
                bool(candidate.get("family_faithful_bridge_passes")) for candidate in candidates
            ),
        },
        "conjunction_counts": {
            "motif1_and_geometry": len(motif_one_geometry),
            "motif1_and_esm": len(motif_one_esm),
            "motif1_and_geometry_and_esm": len(motif_one_geometry_esm),
            "geometry_and_esm_any_motif": sum(
                bool(candidate.get("geometry_passes")) and bool(candidate.get("esm_gate_pass"))
                for candidate in candidates
            ),
        },
    }


def prompt_records(
    selected_records: list[dict[str, Any]],
    candidate_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected_by_prompt: dict[tuple[int, int, str], list[dict[str, Any]]] = defaultdict(list)
    candidates_by_prompt: dict[tuple[int, int, str], list[dict[str, Any]]] = defaultdict(list)
    for record in selected_records:
        selected_by_prompt[(int(record["prompt_count"]), int(record["step"]), str(record["prompt"]))].append(record)
    for record in candidate_records:
        candidates_by_prompt[(int(record["prompt_count"]), int(record["step"]), str(record["prompt"]))].append(record)

    output: list[dict[str, Any]] = []
    for key in sorted(selected_by_prompt):
        rows = selected_by_prompt[key]
        all_rows = candidates_by_prompt.get(key, [])
        modes = Counter(str(row["candidate_mode"]) for row in rows)
        all_modes = Counter(str(row["candidate_mode"]) for row in all_rows)
        deltas = [int(row["selected_length_delta"]) for row in rows if row.get("selected_length_delta") is not None]
        selected_candidates = [row["selected_candidate"] for row in rows]
        all_candidates = [row["candidate"] for row in all_rows]
        prompt_count, step, prompt = key
        output.append(
            {
                "prompt_count": prompt_count,
                "step": step,
                "prompt": prompt,
                "requested_length": rows[0].get("requested_length"),
                "seeds": [int(row["seed"]) for row in rows],
                "selected_mode_counts": dict(sorted(modes.items())),
                "all_candidate_mode_counts": dict(sorted(all_modes.items())),
                "selected_length_deltas": deltas,
                "mean_abs_selected_length_delta": round(
                    sum(abs(value) for value in deltas) / max(1, len(deltas)),
                    3,
                ),
                "selected_any_geometry": any(bool(candidate.get("geometry_passes")) for candidate in selected_candidates),
                "selected_any_esm": any(bool(candidate.get("esm_gate_pass")) for candidate in selected_candidates),
                "selected_any_tier2": any(str(candidate.get("mode")) in {"tier2_proxy", "functional", "family_faithful"} for candidate in selected_candidates),
                "all_any_geometry": any(bool(candidate.get("geometry_passes")) for candidate in all_candidates),
                "all_any_esm": any(bool(candidate.get("esm_gate_pass")) for candidate in all_candidates),
                "all_any_tier2": any(str(candidate.get("mode")) in {"tier2_proxy", "functional", "family_faithful"} for candidate in all_candidates),
            }
        )
    return output


def diagnose(audit: dict[str, Any]) -> list[str]:
    selected = audit["selected_population"]
    raw = audit["raw_population"]
    diagnoses: list[str] = []
    if raw["conjunction_counts"]["motif1_and_geometry_and_esm"] == 0:
        diagnoses.append("no_raw_candidate_satisfied_the_single_motif_geometry_esm_conjunction")
    if selected["conjunction_counts"]["motif1_and_geometry_and_esm"] == 0:
        diagnoses.append("stage2_selection_never_selected_a_tier2_proxy")
    if (
        int(selected["mode_counts"].get("geometry_only", 0)) > 0
        and int(selected["mode_counts"].get("stability_only", 0)) > 0
    ):
        diagnoses.append("selected_candidates_split_between_geometry_only_and_stability_only")
    if raw["flag_counts"]["motif_count_eq_1"] < raw["count"] * 0.5:
        diagnoses.append("raw_generator_still_spends_most_samples_outside_single_motif_space")
    prompt_summaries = audit["prompt_records"]
    if prompt_summaries and not any(bool(row["all_any_tier2"]) for row in prompt_summaries):
        diagnoses.append("failure_is_systemic_across_prompts_not_prompt_sparse_luck")
    length_deltas = audit["selected_length_delta_summary"]
    if length_deltas["count"] and float(length_deltas["mean"]) > 50.0:
        diagnoses.append("selected_outputs_are_poorly_length_conditioned")
    return diagnoses


def build_recommendations(audit: dict[str, Any]) -> list[str]:
    recommendations = [
        "Do not launch another paid gate from manifold v1.1; p24 completed with zero tier2/strict hits.",
        "Move the strict conjunction before paid sampling: reject candidates unless motif count, family motif, geometry, and ESM target are jointly satisfiable in offline replay.",
        "Train or construct against negative contrast from v9 and v1.1 stability-only/geometry-only rows instead of treating high proxy scores as positives.",
        "Split constructor repair into two explicit lanes: raise ESM for geometry-valid rows and repair geometry for ESM-valid rows, then require the conjunction before dataset inclusion.",
        "Add a length-conditioning gate; selected p24 outputs should be rejected when they drift far from requested scaffold length.",
    ]
    if audit["raw_population"]["conjunction_counts"]["motif1_and_geometry_and_esm"] == 0:
        recommendations.append(
            "Selector tuning alone is insufficient: the raw pool had no tier2 proxy candidates, so v1.2 must change generation/constructor constraints."
        )
    return recommendations


def build_audit(args: argparse.Namespace) -> dict[str, Any]:
    summary_path = resolved(args.robustness_summary_path)
    ablation_root = resolved(args.ablation_root)
    robustness_summary = read_json(summary_path)
    records = collect_candidate_records(summary_path, ablation_root)
    selected_records = records["selected_records"]
    candidate_records = records["candidate_records"]
    prompts = prompt_records(selected_records, candidate_records)
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
        "selected_population": candidate_population_summary(selected_records, field="selected_candidate"),
        "raw_population": candidate_population_summary(candidate_records, field="candidate"),
        "selected_length_delta_summary": numeric_summary(selected_deltas),
        "raw_length_delta_summary": numeric_summary(raw_deltas),
        "prompt_records": prompts,
    }
    audit["diagnoses"] = diagnose(audit)
    audit["recommendations"] = build_recommendations(audit)
    return audit


def write_markdown(path: Path, audit: dict[str, Any]) -> None:
    gate = audit.get("gate", {})
    group_results = gate.get("group_results") or []
    first_group = group_results[0] if group_results else {}
    selected = audit["selected_population"]
    raw = audit["raw_population"]
    prompt_records_ = audit["prompt_records"]
    selected_flags = selected["flag_counts"]
    raw_flags = raw["flag_counts"]
    raw_conjunction = raw["conjunction_counts"]

    lines = [
        "# Manifold v1.1 Gate Postmortem",
        "",
        f"- run: `{audit['run_name']}`",
        f"- generated: `{audit['generated_at_utc']}`",
        f"- completed runs: `{audit['completed_run_count']}`",
        f"- missing runs: `{audit['missing_run_count']}`",
        f"- gate passed: `{bool(gate.get('passed'))}`",
    ]
    if first_group:
        lines.extend(
            [
                f"- tier2 hits by seed: `{first_group.get('tier2_hits_by_seed')}`",
                f"- prompt coverage by seed: `{first_group.get('prompt_coverage_by_seed')}`",
                f"- prompts with any tier2 across seeds: `{first_group.get('conditions', [{}])[1].get('actual', {}).get('prompts_with_any_tier2_across_seeds')}`",
            ]
        )

    lines.extend(
        [
            "",
            "## Failure Taxonomy",
            "",
            f"- selected records: `{selected['count']}`",
            f"- selected mode counts: `{selected['mode_counts']}`",
            f"- raw candidate records: `{raw['count']}`",
            f"- raw mode counts: `{raw['mode_counts']}`",
            f"- selected motif1 / geometry / ESM: `{selected_flags['motif_count_eq_1']}` / `{selected_flags['geometry_passes']}` / `{selected_flags['esm_gate_passes']}`",
            f"- raw motif1 / geometry / ESM: `{raw_flags['motif_count_eq_1']}` / `{raw_flags['geometry_passes']}` / `{raw_flags['esm_gate_passes']}`",
            f"- raw motif1+geometry+ESM conjunction: `{raw_conjunction['motif1_and_geometry_and_esm']}`",
            f"- selected abs length delta mean: `{audit['selected_length_delta_summary']['mean']}`",
            f"- raw abs length delta mean: `{audit['raw_length_delta_summary']['mean']}`",
            "",
            "## Prompt Coverage",
            "",
            f"- prompts inspected: `{len(prompt_records_)}`",
            f"- prompts with any raw geometry-valid candidate: `{sum(bool(row['all_any_geometry']) for row in prompt_records_)}`",
            f"- prompts with any raw ESM-valid candidate: `{sum(bool(row['all_any_esm']) for row in prompt_records_)}`",
            f"- prompts with any raw tier2 proxy: `{sum(bool(row['all_any_tier2']) for row in prompt_records_)}`",
            "",
            "## Diagnosis",
            "",
        ]
    )
    lines.extend(f"- `{diagnosis}`" for diagnosis in audit["diagnoses"])
    lines.extend(["", "## Recommended v1.2 Direction", ""])
    lines.extend(f"- {recommendation}" for recommendation in audit["recommendations"])
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    audit = build_audit(args)
    output_json = resolved(args.output_json)
    output_md = resolved(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(output_md, audit)
    print(json.dumps({"output_json": str(output_json), "output_md": str(output_md)}, indent=2))


if __name__ == "__main__":
    main()
