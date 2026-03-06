from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_retrain_readiness import (  # noqa: E402
    DEFAULT_CLUSTER_IDENTITY_THRESHOLD,
    DEFAULT_HOLDOUT_FRACTION,
    DEFAULT_MAX_CLUSTER_SHARE,
    DEFAULT_MAX_SOURCE_SHARE,
    DEFAULT_MIN_CLUSTER_COUNT,
    DEFAULT_MIN_TIER1_PROXY,
    DEFAULT_MIN_TIER2,
    DEFAULT_MIN_TRAIN_TIER1_PROXY,
    DEFAULT_MIN_TRAIN_TIER2,
    assign_cluster_ids,
    choose_holdout_sequences,
    cluster_candidates,
    collect_positive_candidates,
    dedupe_candidates,
    evaluate_retrain_readiness,
    resolve_audit_paths,
)


def main() -> None:
    args = parse_args()
    audit_paths = resolve_audit_paths(args.inputs)
    base_positives = collect_positive_candidates(audit_paths=audit_paths, selected_only=args.selected_only)
    parent_source_map = load_parent_source_map(Path(args.parent_pool_path)) if args.parent_pool_path else {}
    survivor_positives = load_survivor_positives(
        path=Path(args.survivors_path),
        source_name=args.survivor_source_name,
        source_label=args.survivor_source_label,
        parent_source_map=parent_source_map,
    )

    deduped = dedupe_candidates(base_positives + survivor_positives)
    clusters = cluster_candidates(
        deduped_candidates=deduped,
        identity_threshold=args.cluster_identity_threshold,
    )
    assign_cluster_ids(deduped_candidates=deduped, clusters=clusters)
    holdout_sequences = choose_holdout_sequences(
        deduped_candidates=deduped,
        holdout_fraction=args.holdout_fraction,
    )
    train_candidates = [candidate for candidate in deduped if candidate["sequence"] not in holdout_sequences]
    holdout_candidates = [candidate for candidate in deduped if candidate["sequence"] in holdout_sequences]

    evaluation = evaluate_retrain_readiness(
        deduped_candidates=deduped,
        train_candidates=train_candidates,
        holdout_candidates=holdout_candidates,
        thresholds=args,
    )
    evaluation["input_breakdown"] = {
        "base_audit_count": len(audit_paths),
        "base_positive_count": len(base_positives),
        "survivor_positive_count": len(survivor_positives),
    }
    print(json.dumps(evaluation, indent=2))

    if args.output_path:
        output_path = Path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(evaluation, indent=2), encoding="utf-8")

    if args.require_ready and not evaluation["ready_for_retrain"]:
        raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check retrain readiness after adding repair survivors to one or more base candidate_audit runs."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Base candidate_audit.json files or directories that contain them.",
    )
    parser.add_argument("--survivors-path", required=True, help="Path to repair_survivors*.jsonl.")
    parser.add_argument(
        "--parent-pool-path",
        help="Optional repair pool JSONL to map source_parent_sequence -> source_run for legacy survivor files.",
    )
    parser.add_argument(
        "--survivor-source-name",
        default="repair_survivors",
        help="Source run name assigned to repair survivor positives.",
    )
    parser.add_argument(
        "--survivor-source-label",
        default="repair_survivor",
        help="Audit path label assigned to repair survivor positives.",
    )
    parser.add_argument(
        "--selected-only",
        action="store_true",
        help="Only use selected candidates from base audits.",
    )
    parser.add_argument(
        "--cluster-identity-threshold",
        type=float,
        default=DEFAULT_CLUSTER_IDENTITY_THRESHOLD,
    )
    parser.add_argument("--holdout-fraction", type=float, default=DEFAULT_HOLDOUT_FRACTION)
    parser.add_argument("--min-tier2", type=int, default=DEFAULT_MIN_TIER2)
    parser.add_argument("--min-tier1-proxy", type=int, default=DEFAULT_MIN_TIER1_PROXY)
    parser.add_argument("--min-cluster-count", type=int, default=DEFAULT_MIN_CLUSTER_COUNT)
    parser.add_argument("--max-cluster-share", type=float, default=DEFAULT_MAX_CLUSTER_SHARE)
    parser.add_argument("--min-train-tier2", type=int, default=DEFAULT_MIN_TRAIN_TIER2)
    parser.add_argument("--min-train-tier1-proxy", type=int, default=DEFAULT_MIN_TRAIN_TIER1_PROXY)
    parser.add_argument("--max-source-share", type=float, default=DEFAULT_MAX_SOURCE_SHARE)
    parser.add_argument("--output-path", help="Optional path to write the readiness JSON report.")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit with status 1 if the readiness gate fails.",
    )
    return parser.parse_args()


def load_survivor_positives(
    *,
    path: Path,
    source_name: str,
    source_label: str,
    parent_source_map: dict[str, str],
) -> list[dict[str, Any]]:
    positives: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            sequence = str(row.get("sequence") or "").strip()
            if not sequence:
                continue

            geometry = row.get("geometry") or {}
            geometry_passes = bool(geometry.get("passes"))
            raw_esm_score = float(row.get("esm_score") or 0.0)
            source_step = int(row.get("source_step") or -1)
            tier1_proxy = geometry_passes and raw_esm_score >= 85.0
            survivor_source_name = resolve_survivor_source_name(
                row=row,
                default_source_name=source_name,
                parent_source_map=parent_source_map,
            )
            survivor_source_label = str(row.get("source_parent_audit_path") or source_label)

            positives.append(
                {
                    "sequence": sequence,
                    "source_name": survivor_source_name,
                    "audit_path": survivor_source_label,
                    "step": source_step,
                    "selected": True,
                    "tier2": True,
                    "tier1_proxy": tier1_proxy,
                    "family_faithful_bridge_passes": tier1_proxy,
                    "has_family_serine_motif": True,
                    "passes_core_screen": tier1_proxy,
                    "raw_esm_score": raw_esm_score,
                    "stage1_score": 0.0,
                    "stage2_score": 0.0,
                    "motif_count": 1,
                    "geometry_passes": geometry_passes,
                }
            )
    return positives


def load_parent_source_map(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            sequence = str(row.get("sequence") or "").strip()
            source_run = str(row.get("source_run") or "").strip()
            if sequence and source_run:
                mapping[sequence] = source_run
    return mapping


def resolve_survivor_source_name(
    *,
    row: dict[str, Any],
    default_source_name: str,
    parent_source_map: dict[str, str],
) -> str:
    explicit_parent_run = str(row.get("source_parent_run") or "").strip()
    if explicit_parent_run:
        return explicit_parent_run

    source_parent_sequence = str(row.get("source_parent_sequence") or "").strip()
    if source_parent_sequence:
        mapped = parent_source_map.get(source_parent_sequence)
        if mapped:
            return mapped

    legacy_source_run = str(row.get("source_run") or "").strip()
    if legacy_source_run:
        return legacy_source_run

    return default_source_name


if __name__ == "__main__":
    main()
