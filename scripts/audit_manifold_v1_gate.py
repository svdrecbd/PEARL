#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
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
    parser = argparse.ArgumentParser(description="Audit manifold v1 p12/p24 gate prompt failures")
    parser.add_argument("--robustness-summary-path", required=True)
    parser.add_argument("--ablation-root", default="reports/ablations")
    parser.add_argument("--selected-path", required=True)
    parser.add_argument("--scaffold-bank-path", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    return parser.parse_args()


def resolved(value: str) -> Path:
    path = resolve_repo_path(value)
    if path is None or path.startswith("tinker://"):
        raise ValueError(f"could not resolve local path: {value}")
    return Path(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


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


def candidate_mode(candidate: dict[str, Any] | None) -> str:
    if not candidate:
        return "missing"
    motif_count = int(candidate.get("motif_count") or 0)
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
    if motif_count != 1:
        return "motif_failure"
    return "other_failure"


def summarize_candidate(candidate: dict[str, Any] | None) -> dict[str, Any]:
    if candidate is None:
        return {"mode": "missing"}
    sequence = str(candidate.get("extracted_sequence") or "").strip().upper()
    return {
        "mode": candidate_mode(candidate),
        "sequence": sequence,
        "length": int(candidate.get("length") or len(sequence) or 0),
        "stage1_rank": candidate.get("stage1_rank"),
        "stage2_rank": candidate.get("stage2_rank"),
        "stage2_score": candidate.get("stage2_score"),
        "hard_gate_pass": bool(candidate.get("hard_gate_pass")),
        "is_trainable": bool(candidate.get("is_trainable")),
        "trainability_reason": candidate.get("trainability_reason"),
        "motif_count": int(candidate.get("motif_count") or 0),
        "esm_gate_pass": bool(candidate.get("esm_gate_pass")),
        "geometry_passes": bool(candidate.get("geometry_passes")),
        "functional_bridge_passes": bool(candidate.get("functional_bridge_passes")),
        "family_faithful_bridge_passes": bool(candidate.get("family_faithful_bridge_passes")),
        "raw_esm_score": candidate.get("raw_esm_score"),
        "geometry_score": candidate.get("geometry_score"),
        "best_gap_error": candidate.get("best_gap_error"),
        "ser_asp_gap_error": candidate.get("ser_asp_gap_error"),
        "asp_his_gap_error": candidate.get("asp_his_gap_error"),
        "ser_his_gap_error": candidate.get("ser_his_gap_error"),
        "passes_core_screen": bool(candidate.get("passes_core_screen")),
    }


def selected_length_set(rows: list[dict[str, Any]]) -> set[int]:
    return {int(row.get("length") or len(str(row.get("sequence") or ""))) for row in rows}


def strict_scaffold_length_counts(rows: list[dict[str, Any]]) -> Counter[int]:
    counts: Counter[int] = Counter()
    for row in rows:
        if row.get("strict_manifold_passes") and not row.get("negative_example"):
            counts[int(row.get("length") or len(str(row.get("sequence") or "")))] += 1
    return counts


def collect_run_records(ablation_root: Path, run_prefix: str) -> list[dict[str, Any]]:
    run_records: list[dict[str, Any]] = []
    for run_dir in sorted(ablation_root.glob(f"{run_prefix}-p*-t*-s*")):
        if not run_dir.is_dir():
            continue
        parsed = parse_run_name(run_dir.name)
        if parsed is None:
            continue
        summary_path = run_dir / "summary.json"
        audit_path = run_dir / "candidate_audit.json"
        if not summary_path.exists() or not audit_path.exists():
            continue
        summary = read_json(summary_path)
        audit = read_json(audit_path)
        for record in audit.get("records", []):
            candidate = selected_candidate(record)
            prompt = str(record.get("prompt") or "").strip()
            req_len = requested_length(prompt)
            candidate_summary = summarize_candidate(candidate)
            selected_len = int(candidate_summary.get("length") or 0)
            run_records.append(
                {
                    "run_name": run_dir.name,
                    "prompt_count": parsed["prompt_count"],
                    "temperature": parsed["temperature"],
                    "seed": parsed["seed"],
                    "step": int(record.get("step") or 0),
                    "prompt": prompt,
                    "requested_length": req_len,
                    "selected_length": selected_len,
                    "selected_length_delta": selected_len - req_len if req_len is not None and selected_len else None,
                    "selected_candidate": candidate_summary,
                    "candidate_mode": candidate_summary["mode"],
                    "summary_path": str(summary_path),
                    "candidate_audit_path": str(audit_path),
                    "run_trainable_count": summary.get("trainable_count"),
                    "run_average_reward": summary.get("average_reward"),
                }
            )
    return run_records


def aggregate_prompt_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(int(record["prompt_count"]), int(record["step"]), str(record["prompt"]))].append(record)

    prompt_records: list[dict[str, Any]] = []
    for (prompt_count, step, prompt), rows in sorted(grouped.items()):
        rows.sort(key=lambda row: int(row["seed"]))
        modes = Counter(str(row["candidate_mode"]) for row in rows)
        selected_lengths = [int(row["selected_length"]) for row in rows if int(row.get("selected_length") or 0)]
        deltas = [int(row["selected_length_delta"]) for row in rows if row.get("selected_length_delta") is not None]
        functional_seeds = [
            int(row["seed"])
            for row in rows
            if bool(row["selected_candidate"].get("functional_bridge_passes"))
        ]
        family_seeds = [
            int(row["seed"])
            for row in rows
            if bool(row["selected_candidate"].get("family_faithful_bridge_passes"))
        ]
        requested = rows[0].get("requested_length")
        if prompt_count == 24 and not functional_seeds:
            replay_role = "p24_hole"
        elif prompt_count == 24 and functional_seeds:
            replay_role = "p24_weak_hit"
        elif prompt_count == 12 and functional_seeds:
            replay_role = "p12_hit"
        else:
            replay_role = "background"
        prompt_records.append(
            {
                "prompt_count": prompt_count,
                "step": step,
                "prompt": prompt,
                "requested_length": requested,
                "seed_count": len(rows),
                "seeds": [int(row["seed"]) for row in rows],
                "functional_hit_seeds": functional_seeds,
                "family_hit_seeds": family_seeds,
                "functional_hit_count": len(functional_seeds),
                "family_hit_count": len(family_seeds),
                "candidate_modes": dict(sorted(modes.items())),
                "selected_lengths": selected_lengths,
                "selected_length_deltas": deltas,
                "mean_abs_selected_length_delta": round(
                    sum(abs(value) for value in deltas) / max(1, len(deltas)),
                    3,
                ),
                "replay_role": replay_role,
                "seed_records": rows,
            }
        )
    return prompt_records


def build_length_coverage(
    prompt_records: list[dict[str, Any]],
    *,
    selected_lengths: set[int],
    strict_scaffold_counts: Counter[int],
) -> list[dict[str, Any]]:
    requested_lengths = sorted(
        {
            int(record["requested_length"])
            for record in prompt_records
            if record["prompt_count"] == 24 and record.get("requested_length") is not None
        }
    )
    rows: list[dict[str, Any]] = []
    for length in requested_lengths:
        nearest_selected = min(selected_lengths, key=lambda value: abs(value - length)) if selected_lengths else None
        nearest_strict = (
            min(strict_scaffold_counts, key=lambda value: abs(value - length)) if strict_scaffold_counts else None
        )
        rows.append(
            {
                "requested_length": length,
                "in_phase2_selected_lengths": length in selected_lengths,
                "nearest_phase2_selected_length": nearest_selected,
                "nearest_phase2_selected_delta": nearest_selected - length if nearest_selected is not None else None,
                "strict_scaffold_count_exact": int(strict_scaffold_counts.get(length, 0)),
                "nearest_strict_scaffold_length": nearest_strict,
                "nearest_strict_scaffold_delta": nearest_strict - length if nearest_strict is not None else None,
            }
        )
    return rows


def aggregate_groups(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[int(record["prompt_count"])].append(record)
    groups: list[dict[str, Any]] = []
    for prompt_count, rows in sorted(grouped.items()):
        modes = Counter(str(row["candidate_mode"]) for row in rows)
        run_trainable = {
            str(row["run_name"]): int(row.get("run_trainable_count") or 0)
            for row in rows
        }
        by_seed: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_seed[int(row["seed"])].append(row)
        groups.append(
            {
                "prompt_count": prompt_count,
                "selected_records": len(rows),
                "mode_counts": dict(sorted(modes.items())),
                "functional_hits": sum(
                    int(bool(row["selected_candidate"].get("functional_bridge_passes"))) for row in rows
                ),
                "family_faithful_hits": sum(
                    int(bool(row["selected_candidate"].get("family_faithful_bridge_passes"))) for row in rows
                ),
                "esm_gate_passes": sum(int(bool(row["selected_candidate"].get("esm_gate_pass"))) for row in rows),
                "geometry_passes": sum(int(bool(row["selected_candidate"].get("geometry_passes"))) for row in rows),
                "final_trainable": sum(run_trainable.values()),
                "candidate_audit_trainable_flags": sum(
                    int(bool(row["selected_candidate"].get("is_trainable"))) for row in rows
                ),
                "by_seed": {
                    str(seed): {
                        "functional_hits": sum(
                            int(bool(row["selected_candidate"].get("functional_bridge_passes"))) for row in seed_rows
                        ),
                        "family_faithful_hits": sum(
                            int(bool(row["selected_candidate"].get("family_faithful_bridge_passes")))
                            for row in seed_rows
                        ),
                        "mode_counts": dict(Counter(str(row["candidate_mode"]) for row in seed_rows)),
                    }
                    for seed, seed_rows in sorted(by_seed.items())
                },
            }
        )
    return groups


def write_markdown(path: Path, audit: dict[str, Any]) -> None:
    p24_rows = [row for row in audit["prompt_records"] if row["prompt_count"] == 24]
    holes = [row for row in p24_rows if row["replay_role"] == "p24_hole"]
    weak = [row for row in p24_rows if row["replay_role"] == "p24_weak_hit"]
    missing_selected_lengths = [
        row for row in audit["p24_requested_length_coverage"] if not row["in_phase2_selected_lengths"]
    ]
    unique_p24_lengths = len(audit["p24_requested_length_coverage"])
    lines = [
        "# Manifold v1 Gate Audit",
        "",
        f"- run: `{audit['run_name']}`",
        f"- generated: `{audit['generated_at_utc']}`",
        f"- p24 prompt holes: `{len(holes)}`",
        f"- p24 weak-hit prompts: `{len(weak)}`",
        f"- p24 requested lengths absent from Phase 2 selected pool: `{len(missing_selected_lengths)} / {unique_p24_lengths}` unique lengths",
        "",
        "## Group Summary",
        "",
    ]
    for group in audit["groups"]:
        lines.extend(
            [
                f"- `p{group['prompt_count']}`: functional `{group['functional_hits']}`, "
                f"family-faithful `{group['family_faithful_hits']}`, ESM-gate `{group['esm_gate_passes']}`, "
                f"geometry `{group['geometry_passes']}`, final trainable `{group['final_trainable']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Main Diagnosis",
            "",
            "- v1 transferred enough to create strict hits at p12, but p24 remained prompt-sparse.",
            "- The Phase 2 selected curriculum covered only 8 length buckets, while p24 requested many shorter and intermediate lengths.",
            "- v1.1 should replay the exact p24 hole prompts and target strict scaffold anchors at or near their requested lengths.",
            "",
            "## Recommended v1.1 Recipe",
            "",
            "- keep a balanced subset of high-ESM Phase 2 selected rows",
            "- add p24-hole prompt replay rows using strict scaffold anchors",
            "- do not directly replay the actual v1 hits unless length-delta filtering is added; the observed hits were strict but length-mismatched to their prompts",
            "- keep canonical purebred anchors",
            "- do not launch training until this offline curriculum is reviewed",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_audit(args: argparse.Namespace) -> dict[str, Any]:
    summary_path = resolved(args.robustness_summary_path)
    ablation_root = resolved(args.ablation_root)
    selected_path = resolved(args.selected_path)
    scaffold_bank_path = resolved(args.scaffold_bank_path)

    robustness_summary = read_json(summary_path)
    run_name = str(robustness_summary.get("suite_name") or summary_path.parent.name)
    run_records = collect_run_records(ablation_root, run_name)
    prompt_records = aggregate_prompt_records(run_records)
    selected_rows = read_jsonl(selected_path)
    scaffold_rows = read_jsonl(scaffold_bank_path)
    strict_counts = strict_scaffold_length_counts(scaffold_rows)
    coverage = build_length_coverage(
        prompt_records,
        selected_lengths=selected_length_set(selected_rows),
        strict_scaffold_counts=strict_counts,
    )
    audit = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "run_name": run_name,
        "robustness_summary_path": str(summary_path),
        "ablation_root": str(ablation_root),
        "selected_path": str(selected_path),
        "scaffold_bank_path": str(scaffold_bank_path),
        "groups": aggregate_groups(run_records),
        "prompt_records": prompt_records,
        "p24_requested_length_coverage": coverage,
        "recommendations": {
            "build_v11": True,
            "use_exact_p24_prompt_replay": True,
            "add_strict_scaffold_anchors_for_p24_lengths": True,
            "preserve_v1_hits_as_replay": True,
            "do_not_launch_paid_training_from_v1": True,
        },
    }
    return audit


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
