#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from glob import glob
from pathlib import Path
from typing import Any, Iterable


ROOT_PATH = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT_PATH / "src"
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


DEFAULT_OUTPUT_DIR = ROOT_PATH / "reports/analysis/manifold_v2_objective_panel_20260424"
DEFAULT_V12_AUDIT_PATH = ROOT_PATH / "reports/analysis/manifold_v12_gate_audit_20260423/audit.json"
DEFAULT_V13_AUDIT_PATTERN = str(
    ROOT_PATH
    / "reports/ablations/pearl-topoff1m-a-manifold-v13-stagea-gate-p24-t08-s41s53s67-c128-p24-t0p8-s*/candidate_audit.json"
)
DEFAULT_V9_REJECT_PATH = (
    ROOT_PATH / "reports/repair/topoff1m-a-v9-p12p24-repair-20260421/repair_validated_reject.jsonl"
)
DEFAULT_V11_DRIFT_PATHS = [
    ROOT_PATH / "reports/analysis/manifold_v12_offline_lanes_20260423/geometry_valid_needs_esm.jsonl",
    ROOT_PATH / "reports/analysis/manifold_v12_offline_lanes_20260423/esm_valid_needs_geometry.jsonl",
    ROOT_PATH / "reports/analysis/manifold_v12_offline_lanes_20260423/length_offtarget_selected.jsonl",
    ROOT_PATH / "reports/analysis/manifold_v12_offline_lanes_20260423/motif_failure_negatives.jsonl",
]
DEFAULT_SUPPORT_POSITIVE_PATHS = [
    ROOT_PATH / "reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/family_faithful_bridges.jsonl",
    ROOT_PATH / "reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/lineage_family_representatives.jsonl",
    ROOT_PATH / "reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_selected_new_family_faithful.jsonl",
    ROOT_PATH / "reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_selected_repair_family_faithful.jsonl",
    ROOT_PATH / "reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_validated_strict.jsonl",
    ROOT_PATH / "data/petase_family_expanded/kimi_micro_sft_top9_unicorn_only.jsonl",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a manifold v2 objective panel from v1.2 family-faithful positives, "
            "v1.3 hard negatives, v9/v1.1 drift negatives, and historical support positives."
        )
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--v12-audit-path", default=str(DEFAULT_V12_AUDIT_PATH))
    parser.add_argument("--v13-candidate-audit-path", action="append", dest="v13_candidate_audit_paths")
    parser.add_argument("--v9-reject-path", default=str(DEFAULT_V9_REJECT_PATH))
    parser.add_argument("--v11-drift-path", action="append", dest="v11_drift_paths")
    parser.add_argument("--support-positive-path", action="append", dest="support_positive_paths")
    parser.add_argument("--max-v9-drift-negatives", type=int, default=128)
    parser.add_argument("--max-v11-drift-negatives-per-path", type=int, default=128)
    parser.add_argument("--max-support-positives-per-path", type=int, default=128)
    return parser.parse_args()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT_PATH / path
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def stable_id(sequence: str) -> str:
    return "sha1:" + hashlib.sha1(sequence.encode("utf-8")).hexdigest()


def bool_value(value: Any) -> bool:
    return bool(value)


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pick_sequence(row: dict[str, Any]) -> str:
    sequence = row.get("sequence") or row.get("extracted_sequence")
    if sequence is None and isinstance(row.get("selected_candidate"), dict):
        sequence = row["selected_candidate"].get("sequence")
    return str(sequence or "").strip().upper()


def infer_requested_length(prompt: str | None) -> int | None:
    if not prompt:
        return None
    patterns = (
        r"length\s+(?:about|around|near)\s+(\d+)\s+aa",
        r"around\s+(\d+)\s+amino acids",
        r"near\s+(\d+)\s+amino acids",
        r"about\s+(\d+)\s+aa",
    )
    for pattern in patterns:
        match = re.search(pattern, prompt, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def source_name(path: Path) -> str:
    return path.parent.name if path.name in {"candidate_audit.json", "summary.json", "audit.json"} else path.stem


def candidate_mode(candidate: dict[str, Any]) -> str:
    if bool_value(candidate.get("family_faithful_bridge_passes")):
        return "family_faithful"
    if bool_value(candidate.get("functional_bridge_passes")):
        return "functional_bridge"
    if bool_value(candidate.get("esm_gate_pass")) and not bool_value(candidate.get("geometry_passes")):
        return "stability_only"
    if bool_value(candidate.get("geometry_passes")) and not bool_value(candidate.get("esm_gate_pass")):
        return "geometry_only"
    return str(candidate.get("mode") or "other")


def panel_row(
    *,
    sequence: str,
    panel_role: str,
    panel_label: str,
    panel_source: str,
    source_path: Path,
    raw: dict[str, Any],
    candidate: dict[str, Any] | None = None,
    prompt: str | None = None,
    requested_length: int | None = None,
    source_run: str | None = None,
    source_seed: int | None = None,
    source_step: int | None = None,
) -> dict[str, Any]:
    metrics = candidate or raw
    length = int_or_none(metrics.get("length")) or len(sequence)
    prompt_text = prompt if prompt is not None else raw.get("prompt") or raw.get("source_prompt")
    requested = (
        requested_length
        if requested_length is not None
        else int_or_none(raw.get("requested_length")) or infer_requested_length(str(prompt_text or ""))
    )
    length_delta = length - requested if requested is not None else raw.get("length_delta")
    row = {
        "panel_id": stable_id(sequence),
        "panel_role": panel_role,
        "panel_label": panel_label,
        "panel_source": panel_source,
        "source_path": str(source_path),
        "source_name": source_name(source_path),
        "source_run": source_run
        or raw.get("run_name")
        or raw.get("source_run")
        or raw.get("source_parent_run")
        or source_name(source_path),
        "source_seed": source_seed if source_seed is not None else raw.get("seed"),
        "source_step": source_step if source_step is not None else raw.get("step") or raw.get("source_step"),
        "prompt": prompt_text,
        "requested_length": requested,
        "sequence": sequence,
        "length": length,
        "length_delta": length_delta,
        "mode": candidate_mode(metrics),
        "esm_score": float_or_none(metrics.get("raw_esm_score") or metrics.get("esm_score") or metrics.get("esm_reward")),
        "geometry_score": float_or_none(metrics.get("geometry_score")),
        "best_gap_error": int_or_none(metrics.get("best_gap_error")),
        "ser_asp_gap_error": int_or_none(metrics.get("ser_asp_gap_error")),
        "asp_his_gap_error": int_or_none(metrics.get("asp_his_gap_error")),
        "ser_his_gap_error": int_or_none(metrics.get("ser_his_gap_error")),
        "motif_count": int_or_none(metrics.get("motif_count")),
        "has_family_serine_motif": bool_value(metrics.get("has_family_serine_motif")),
        "geometry_passes": bool_value(metrics.get("geometry_passes") or metrics.get("catalytic_geometry_passes")),
        "esm_gate_pass": bool_value(metrics.get("esm_gate_pass")),
        "passes_core_screen": bool_value(metrics.get("passes_core_screen")),
        "functional_bridge_passes": bool_value(metrics.get("functional_bridge_passes")),
        "family_faithful_bridge_passes": bool_value(metrics.get("family_faithful_bridge_passes")),
        "strict_bridge": bool_value(metrics.get("strict_bridge")),
        "strict_family": bool_value(metrics.get("strict_family")),
        "strict_consensus": bool_value(metrics.get("strict_consensus")),
        "trainability_reason": metrics.get("trainability_reason"),
    }
    return row


def dedupe_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        sequence = str(row.get("sequence") or "")
        if not sequence:
            continue
        deduped.setdefault(row["panel_id"], row)
    return list(deduped.values())


def limit_rows(rows: Iterable[dict[str, Any]], max_rows: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        panel_id = str(row.get("panel_id") or "")
        if not panel_id or panel_id in seen:
            continue
        seen.add(panel_id)
        output.append(row)
        if len(output) >= max_rows:
            break
    return output


def extract_v12_family_hits(path: Path) -> list[dict[str, Any]]:
    audit = read_json(path)
    rows: list[dict[str, Any]] = []
    for record in audit.get("hit_seed_records", []):
        candidate = record.get("selected_candidate") or {}
        if not bool_value(candidate.get("family_faithful_bridge_passes")):
            continue
        sequence = pick_sequence(candidate)
        rows.append(
            panel_row(
                sequence=sequence,
                panel_role="positive_anchor",
                panel_label="positive",
                panel_source="v12_family_faithful_gate_hit",
                source_path=path,
                raw=record,
                candidate=candidate,
                prompt=record.get("prompt"),
                requested_length=int_or_none(record.get("requested_length")),
                source_run=record.get("run_name"),
                source_seed=int_or_none(record.get("seed")),
                source_step=int_or_none(record.get("step")),
            )
        )
    return dedupe_rows(rows)


def iter_selected_candidates(path: Path) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    audit = read_json(path)
    for record in audit.get("records", []):
        for candidate in record.get("candidates", []):
            if bool_value(candidate.get("selected")):
                yield record, candidate


def extract_v13_hard_negatives(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        for record, candidate in iter_selected_candidates(path):
            if not bool_value(candidate.get("is_trainable")):
                continue
            if bool_value(candidate.get("functional_bridge_passes")):
                continue
            stability_only = bool_value(candidate.get("esm_gate_pass")) and not bool_value(candidate.get("geometry_passes"))
            geometry_only = bool_value(candidate.get("geometry_passes")) and not bool_value(candidate.get("esm_gate_pass"))
            if not (stability_only or geometry_only):
                continue
            panel_source = "v13_stability_only_selected" if stability_only else "v13_geometry_only_selected"
            rows.append(
                panel_row(
                    sequence=pick_sequence(candidate),
                    panel_role="hard_negative",
                    panel_label="negative",
                    panel_source=panel_source,
                    source_path=path,
                    raw=record,
                    candidate=candidate,
                    prompt=record.get("prompt"),
                    source_step=int_or_none(record.get("step")),
                )
            )
    return dedupe_rows(rows)


def extract_jsonl_rows(
    *,
    path: Path,
    panel_role: str,
    panel_label: str,
    panel_source: str,
    max_rows: int,
    require_family_faithful: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in read_jsonl(path):
        if require_family_faithful and not bool_value(raw.get("family_faithful_bridge_passes") or raw.get("strict_family")):
            continue
        sequence = pick_sequence(raw)
        rows.append(
            panel_row(
                sequence=sequence,
                panel_role=panel_role,
                panel_label=panel_label,
                panel_source=panel_source,
                source_path=path,
                raw=raw,
                prompt=raw.get("prompt") or raw.get("source_prompt"),
                requested_length=int_or_none(raw.get("requested_length")),
                source_run=raw.get("run_name") or raw.get("source_run") or raw.get("source_parent_run"),
                source_seed=int_or_none(raw.get("seed")),
                source_step=int_or_none(raw.get("step") or raw.get("source_step")),
            )
        )
    return limit_rows(dedupe_rows(rows), max_rows)


def summarize_lengths(rows: list[dict[str, Any]]) -> dict[str, int]:
    bins: Counter[str] = Counter()
    for row in rows:
        length = int_or_none(row.get("length"))
        if length is None:
            continue
        bins[str((length // 25) * 25)] += 1
    return dict(sorted(bins.items(), key=lambda item: int(item[0])))


def summarize(rows_by_file: dict[str, list[dict[str, Any]]], *, output_dir: Path, inputs: dict[str, Any]) -> dict[str, Any]:
    all_rows = [row for rows in rows_by_file.values() for row in rows]
    role_counts = Counter(str(row.get("panel_role")) for row in all_rows)
    source_counts = Counter(str(row.get("panel_source")) for row in all_rows)
    mode_counts = Counter(str(row.get("mode")) for row in all_rows)
    total_unique = len({row["panel_id"] for row in all_rows})
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "output_dir": str(output_dir),
        "inputs": inputs,
        "outputs": {
            "positive_anchors": str(output_dir / "v2_positive_anchors.jsonl"),
            "hard_negatives": str(output_dir / "v2_hard_negatives.jsonl"),
            "drift_negatives": str(output_dir / "v2_drift_negatives.jsonl"),
            "support_positives": str(output_dir / "v2_support_positives.jsonl"),
        },
        "counts": {
            "positive_anchors": len(rows_by_file["positive_anchors"]),
            "hard_negatives": len(rows_by_file["hard_negatives"]),
            "drift_negatives": len(rows_by_file["drift_negatives"]),
            "support_positives": len(rows_by_file["support_positives"]),
            "total_rows": len(all_rows),
            "total_unique_sequences": total_unique,
        },
        "role_counts": dict(role_counts),
        "panel_source_counts": dict(sorted(source_counts.items())),
        "mode_counts": dict(sorted(mode_counts.items())),
        "length_bin_25aa_counts": summarize_lengths(all_rows),
        "readiness": {
            "ready_for_paid_gate": False,
            "reason": "objective panel only; build and validate manifold v2 candidates offline before any paid gate",
        },
        "next_pass": {
            "name": "manifold_v2_offline_constructor",
            "positive_rule": "preserve v1.2 family-faithful anchors and historical strict-family support",
            "negative_rule": "penalize v1.3 stability-only/geometry-only and v9/v1.1 drift rows",
            "hard_gates_before_ranking": [
                "single family serine motif",
                "family motif identity",
                "family length band",
                "catalytic S/D/H blueprint preservation",
                "family core screen",
                "prompt/length obedience",
            ],
        },
    }


def default_v13_paths() -> list[Path]:
    return [Path(path) for path in sorted(glob(DEFAULT_V13_AUDIT_PATTERN))]


def build_panel(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    v12_audit_path = repo_path(args.v12_audit_path)
    v13_paths = [repo_path(path) for path in (args.v13_candidate_audit_paths or [])] or default_v13_paths()
    v9_reject_path = repo_path(args.v9_reject_path)
    v11_paths = [repo_path(path) for path in (args.v11_drift_paths or DEFAULT_V11_DRIFT_PATHS)]
    support_paths = [repo_path(path) for path in (args.support_positive_paths or DEFAULT_SUPPORT_POSITIVE_PATHS)]

    positive_anchors = extract_v12_family_hits(v12_audit_path)
    hard_negatives = extract_v13_hard_negatives(v13_paths)

    drift_negatives: list[dict[str, Any]] = []
    drift_negatives.extend(
        extract_jsonl_rows(
            path=v9_reject_path,
            panel_role="drift_negative",
            panel_label="negative",
            panel_source="v9_repair_reject",
            max_rows=int(args.max_v9_drift_negatives),
        )
    )
    for path in v11_paths:
        drift_negatives.extend(
            extract_jsonl_rows(
                path=path,
                panel_role="drift_negative",
                panel_label="negative",
                panel_source=f"v11_{path.stem}",
                max_rows=int(args.max_v11_drift_negatives_per_path),
            )
        )
    drift_negatives = dedupe_rows(drift_negatives)

    support_positives: list[dict[str, Any]] = []
    for path in support_paths:
        support_positives.extend(
            extract_jsonl_rows(
                path=path,
                panel_role="support_positive",
                panel_label="positive",
                panel_source=f"support_{path.stem}",
                max_rows=int(args.max_support_positives_per_path),
                require_family_faithful=True,
            )
        )
    support_positives = dedupe_rows(support_positives)

    rows_by_file = {
        "positive_anchors": positive_anchors,
        "hard_negatives": hard_negatives,
        "drift_negatives": drift_negatives,
        "support_positives": support_positives,
    }
    write_jsonl(output_dir / "v2_positive_anchors.jsonl", positive_anchors)
    write_jsonl(output_dir / "v2_hard_negatives.jsonl", hard_negatives)
    write_jsonl(output_dir / "v2_drift_negatives.jsonl", drift_negatives)
    write_jsonl(output_dir / "v2_support_positives.jsonl", support_positives)

    inputs = {
        "v12_audit_path": str(v12_audit_path),
        "v13_candidate_audit_paths": [str(path) for path in v13_paths],
        "v9_reject_path": str(v9_reject_path),
        "v11_drift_paths": [str(path) for path in v11_paths],
        "support_positive_paths": [str(path) for path in support_paths],
        "max_v9_drift_negatives": int(args.max_v9_drift_negatives),
        "max_v11_drift_negatives_per_path": int(args.max_v11_drift_negatives_per_path),
        "max_support_positives_per_path": int(args.max_support_positives_per_path),
    }
    summary = summarize(rows_by_file, output_dir=output_dir, inputs=inputs)
    write_json(output_dir / "v2_objective_panel_summary.json", summary)
    return summary


def main() -> None:
    summary = build_panel(parse_args())
    print(json.dumps(summary["counts"], indent=2, sort_keys=True))
    print(summary["outputs"]["positive_anchors"])
    print(summary["outputs"]["hard_negatives"])
    print(summary["outputs"]["drift_negatives"])
    print(summary["outputs"]["support_positives"])
    print(str(Path(summary["output_dir"]) / "v2_objective_panel_summary.json"))


if __name__ == "__main__":
    main()
