from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pearl.family import levenshtein


DEFAULT_CLUSTER_IDENTITY_THRESHOLD = 0.85
DEFAULT_HOLDOUT_FRACTION = 0.20
DEFAULT_MIN_TIER2 = 12
DEFAULT_MIN_TIER1_PROXY = 3
DEFAULT_MIN_CLUSTER_COUNT = 4
DEFAULT_MAX_CLUSTER_SHARE = 0.40
DEFAULT_MIN_TRAIN_TIER2 = 8
DEFAULT_MIN_TRAIN_TIER1_PROXY = 2
DEFAULT_MAX_SOURCE_SHARE = 0.60


def main() -> None:
    args = parse_args()
    audit_paths = resolve_audit_paths(args.inputs)
    positives = collect_positive_candidates(audit_paths=audit_paths, selected_only=args.selected_only)
    deduped = dedupe_candidates(positives)
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
    print(json.dumps(evaluation, indent=2))

    if args.require_ready and not evaluation["ready_for_retrain"]:
        raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Judge whether a mined positive pool is strong enough to justify retraining."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Candidate audit JSON files or directories containing candidate_audit.json files.",
    )
    parser.add_argument(
        "--selected-only",
        action="store_true",
        help="Only consider the selected candidate per prompt step instead of the full audit pool.",
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
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit with status 1 if the pool does not satisfy all retrain thresholds.",
    )
    return parser.parse_args()


def resolve_audit_paths(inputs: list[str]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for raw in inputs:
        path = Path(raw).expanduser().resolve()
        candidates: list[Path]
        if path.is_dir():
            candidates = sorted(path.rglob("candidate_audit.json"))
        else:
            candidates = [path]
        for candidate in candidates:
            if candidate.name != "candidate_audit.json":
                raise SystemExit(f"Expected candidate_audit.json, got: {candidate}")
            if candidate in seen:
                continue
            seen.add(candidate)
            resolved.append(candidate)
    if not resolved:
        raise SystemExit("No candidate_audit.json files found")
    return resolved


def collect_positive_candidates(*, audit_paths: list[Path], selected_only: bool) -> list[dict[str, Any]]:
    positives: list[dict[str, Any]] = []
    for audit_path in audit_paths:
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
        source_name = audit_path.parent.name
        for record in payload.get("records", []):
            step = int(record.get("step", -1))
            for candidate in record.get("candidates", []):
                if selected_only and not bool(candidate.get("selected")):
                    continue
                sequence = str(candidate.get("extracted_sequence") or "").strip()
                if not sequence:
                    continue
                tier2 = bool(candidate.get("functional_bridge_passes"))
                if not tier2:
                    continue
                tier1_proxy = bool(
                    tier2
                    and candidate.get("has_family_serine_motif")
                    and candidate.get("passes_core_screen")
                )
                positives.append(
                    {
                        "sequence": sequence,
                        "source_name": source_name,
                        "audit_path": str(audit_path),
                        "step": step,
                        "selected": bool(candidate.get("selected")),
                        "tier2": tier2,
                        "tier1_proxy": tier1_proxy,
                        "family_faithful_bridge_passes": bool(candidate.get("family_faithful_bridge_passes")),
                        "has_family_serine_motif": bool(candidate.get("has_family_serine_motif")),
                        "passes_core_screen": bool(candidate.get("passes_core_screen")),
                        "raw_esm_score": float(candidate.get("raw_esm_score") or 0.0),
                        "stage1_score": float(candidate.get("stage1_score") or 0.0),
                        "stage2_score": float(candidate.get("stage2_score") or 0.0),
                        "motif_count": int(candidate.get("motif_count") or 0),
                        "geometry_passes": bool(candidate.get("geometry_passes")),
                    }
                )
    return positives


def dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        sequence = candidate["sequence"]
        existing = deduped.get(sequence)
        if existing is None:
            deduped[sequence] = {
                **candidate,
                "sources": {candidate["source_name"]},
                "source_runs": {candidate["source_name"]},
                "occurrence_count": 1,
            }
            continue

        existing["sources"].add(candidate["source_name"])
        existing["source_runs"].add(candidate["source_name"])
        existing["occurrence_count"] += 1
        existing["tier1_proxy"] = bool(existing["tier1_proxy"] or candidate["tier1_proxy"])
        existing["family_faithful_bridge_passes"] = bool(
            existing["family_faithful_bridge_passes"] or candidate["family_faithful_bridge_passes"]
        )
        existing["has_family_serine_motif"] = bool(
            existing["has_family_serine_motif"] or candidate["has_family_serine_motif"]
        )
        existing["passes_core_screen"] = bool(existing["passes_core_screen"] or candidate["passes_core_screen"])
        if candidate_sort_key(candidate) > candidate_sort_key(existing):
            best_sources = existing["sources"]
            best_source_runs = existing["source_runs"]
            best_occurrence_count = existing["occurrence_count"]
            deduped[sequence] = {
                **candidate,
                "sources": best_sources,
                "source_runs": best_source_runs,
                "occurrence_count": best_occurrence_count,
            }

    result = list(deduped.values())
    for candidate in result:
        candidate["sources"] = sorted(candidate["sources"])
        candidate["source_runs"] = sorted(candidate["source_runs"])
        candidate["primary_source"] = candidate["sources"][0]
    return sorted(result, key=lambda candidate: candidate_sort_key(candidate), reverse=True)


def candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, ...]:
    return (
        float(bool(candidate.get("tier1_proxy"))),
        float(bool(candidate.get("family_faithful_bridge_passes"))),
        float(candidate.get("raw_esm_score") or 0.0),
        float(candidate.get("stage2_score") or 0.0),
        float(candidate.get("stage1_score") or 0.0),
        float(len(candidate.get("sequence", ""))),
    )


def cluster_candidates(
    *,
    deduped_candidates: list[dict[str, Any]],
    identity_threshold: float,
) -> list[list[dict[str, Any]]]:
    if not deduped_candidates:
        return []

    parent = list(range(len(deduped_candidates)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left in range(len(deduped_candidates)):
        left_sequence = deduped_candidates[left]["sequence"]
        for right in range(left + 1, len(deduped_candidates)):
            right_sequence = deduped_candidates[right]["sequence"]
            if normalized_identity(left_sequence, right_sequence) >= identity_threshold:
                union(left, right)

    grouped: dict[int, list[dict[str, Any]]] = {}
    for index, candidate in enumerate(deduped_candidates):
        grouped.setdefault(find(index), []).append(candidate)

    clusters = list(grouped.values())
    for cluster in clusters:
        cluster.sort(key=candidate_sort_key, reverse=True)
    clusters.sort(key=len, reverse=True)
    return clusters


def assign_cluster_ids(*, deduped_candidates: list[dict[str, Any]], clusters: list[list[dict[str, Any]]]) -> None:
    for cluster_index, cluster in enumerate(clusters, start=1):
        cluster_size = len(cluster)
        for candidate in cluster:
            candidate["cluster_id"] = cluster_index
            candidate["cluster_size"] = cluster_size


def choose_holdout_sequences(
    *,
    deduped_candidates: list[dict[str, Any]],
    holdout_fraction: float,
) -> set[str]:
    if not deduped_candidates:
        return set()
    holdout_count = int(math.ceil(len(deduped_candidates) * holdout_fraction))
    if holdout_count <= 0:
        return set()
    ordered = sorted(
        deduped_candidates,
        key=lambda candidate: (
            int(candidate.get("cluster_size", 1)),
            int(bool(candidate.get("tier1_proxy"))),
            float(candidate.get("raw_esm_score") or 0.0),
            float(candidate.get("stage2_score") or 0.0),
            candidate["sequence"],
        ),
        reverse=True,
    )
    return {candidate["sequence"] for candidate in ordered[:holdout_count]}


def evaluate_retrain_readiness(
    *,
    deduped_candidates: list[dict[str, Any]],
    train_candidates: list[dict[str, Any]],
    holdout_candidates: list[dict[str, Any]],
    thresholds: argparse.Namespace,
) -> dict[str, Any]:
    total_tier2 = len(deduped_candidates)
    total_tier1 = sum(bool(candidate["tier1_proxy"]) for candidate in deduped_candidates)
    cluster_sizes = cluster_size_counts(deduped_candidates)
    source_counts = source_contribution_counts(deduped_candidates)
    largest_cluster_share = safe_ratio(max(cluster_sizes.values(), default=0), total_tier2)
    max_source_share = safe_ratio(max(source_counts.values(), default=0), total_tier2)
    train_tier2 = len(train_candidates)
    train_tier1 = sum(bool(candidate["tier1_proxy"]) for candidate in train_candidates)

    checks = [
        build_check(
            name="min_tier2_positives",
            passed=total_tier2 >= thresholds.min_tier2,
            observed=total_tier2,
            threshold=thresholds.min_tier2,
        ),
        build_check(
            name="min_tier1_proxy_positives",
            passed=total_tier1 >= thresholds.min_tier1_proxy,
            observed=total_tier1,
            threshold=thresholds.min_tier1_proxy,
        ),
        build_check(
            name="min_cluster_count",
            passed=len(cluster_sizes) >= thresholds.min_cluster_count,
            observed=len(cluster_sizes),
            threshold=thresholds.min_cluster_count,
        ),
        build_check(
            name="max_cluster_share",
            passed=largest_cluster_share <= thresholds.max_cluster_share,
            observed=round(largest_cluster_share, 4),
            threshold=thresholds.max_cluster_share,
        ),
        build_check(
            name="min_train_tier2_after_holdout",
            passed=train_tier2 >= thresholds.min_train_tier2,
            observed=train_tier2,
            threshold=thresholds.min_train_tier2,
        ),
        build_check(
            name="min_train_tier1_proxy_after_holdout",
            passed=train_tier1 >= thresholds.min_train_tier1_proxy,
            observed=train_tier1,
            threshold=thresholds.min_train_tier1_proxy,
        ),
        build_check(
            name="max_source_share",
            passed=max_source_share <= thresholds.max_source_share,
            observed=round(max_source_share, 4),
            threshold=thresholds.max_source_share,
        ),
    ]

    return {
        "ready_for_retrain": all(check["passed"] for check in checks),
        "thresholds": {
            "min_tier2": thresholds.min_tier2,
            "min_tier1_proxy": thresholds.min_tier1_proxy,
            "cluster_identity_threshold": thresholds.cluster_identity_threshold,
            "min_cluster_count": thresholds.min_cluster_count,
            "max_cluster_share": thresholds.max_cluster_share,
            "holdout_fraction": thresholds.holdout_fraction,
            "min_train_tier2": thresholds.min_train_tier2,
            "min_train_tier1_proxy": thresholds.min_train_tier1_proxy,
            "max_source_share": thresholds.max_source_share,
            "selected_only": thresholds.selected_only,
        },
        "summary": {
            "deduped_tier2_count": total_tier2,
            "deduped_tier1_proxy_count": total_tier1,
            "cluster_count": len(cluster_sizes),
            "largest_cluster_share": round(largest_cluster_share, 4),
            "max_source_share": round(max_source_share, 4),
            "holdout_count": len(holdout_candidates),
            "train_tier2_count": train_tier2,
            "train_tier1_proxy_count": train_tier1,
        },
        "checks": checks,
        "cluster_sizes": cluster_sizes,
        "source_contributions": source_counts,
        "holdout_sequences": [candidate["sequence"] for candidate in holdout_candidates],
        "tier1_proxy_sequences": [
            candidate["sequence"] for candidate in deduped_candidates if candidate["tier1_proxy"]
        ],
        "deduped_positives": [
            {
                "sequence": candidate["sequence"],
                "primary_source": candidate["primary_source"],
                "sources": candidate["sources"],
                "cluster_id": candidate.get("cluster_id"),
                "cluster_size": candidate.get("cluster_size"),
                "tier1_proxy": candidate["tier1_proxy"],
                "family_faithful_bridge_passes": candidate["family_faithful_bridge_passes"],
                "has_family_serine_motif": candidate["has_family_serine_motif"],
                "passes_core_screen": candidate["passes_core_screen"],
                "raw_esm_score": round(candidate["raw_esm_score"], 4),
                "stage2_score": round(candidate["stage2_score"], 4),
                "occurrence_count": candidate["occurrence_count"],
                "selected": candidate["selected"],
            }
            for candidate in deduped_candidates
        ],
    }


def build_check(*, name: str, passed: bool, observed: int | float, threshold: int | float) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "observed": observed,
        "threshold": threshold,
    }


def cluster_size_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        cluster_id = candidate.get("cluster_id")
        if cluster_id is None:
            continue
        counts[str(cluster_id)] = counts.get(str(cluster_id), 0) + 1
    return counts


def source_contribution_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        source = str(candidate["primary_source"])
        counts[source] = counts.get(source, 0) + 1
    return counts


def normalized_identity(left: str, right: str) -> float:
    denominator = max(len(left), len(right), 1)
    return 1.0 - (levenshtein(left, right) / denominator)


def safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


if __name__ == "__main__":
    main()
