from __future__ import annotations

import argparse
import glob
import json
import re
import statistics
from pathlib import Path
from typing import Any


DEFAULT_ESM_WEIGHT_VALUES = (0.2, 0.3, 0.4, 0.5)
DEFAULT_MOTIF_WEIGHT_VALUES = (0.1, 0.2, 0.3)
DEFAULT_TEMPLATE_WEIGHT_VALUES = (0.05, 0.1, 0.15)
DEFAULT_PLDTT_GATE_THRESHOLD = 85.0
DEFAULT_TOP_N = 12
SECOND_STAGE_ESM_SCORE_NORMALIZER = 100.0
MAX_NORMALIZED_SCORE = 1.0
SEED_PATTERN = re.compile(r"-s(\d+)(?:$|[^0-9])")


def main() -> None:
    args = parse_args()
    audit_paths = resolve_audit_paths(args)
    runs = load_runs(audit_paths)
    if not runs:
        raise SystemExit("No usable runs found")

    configs = build_config_grid(
        esm_weight_values=parse_float_values(args.esm_weight_values),
        motif_weight_values=parse_float_values(args.motif_weight_values),
        template_weight_values=parse_float_values(args.template_weight_values),
    )
    if not configs:
        raise SystemExit("No valid selector configs generated")

    baseline = evaluate_config(
        config_name="baseline",
        config={
            "esm_weight": args.baseline_esm_weight,
            "motif_weight": args.baseline_motif_weight,
            "geometry_weight": args.baseline_geometry_weight,
            "template_weight": args.baseline_template_weight,
        },
        runs=runs,
        plddt_gate_threshold=args.plddt_gate_threshold,
    )

    results: list[dict[str, Any]] = []
    for config in configs:
        config_name = config_to_name(config)
        result = evaluate_config(
            config_name=config_name,
            config=config,
            runs=runs,
            plddt_gate_threshold=args.plddt_gate_threshold,
        )
        results.append(result)

    results.sort(key=ranking_key, reverse=True)
    top_results = results[: args.top_n]

    payload = {
        "audit_paths": [str(path) for path in audit_paths],
        "run_count": len(runs),
        "seed_order": [run["seed"] for run in runs],
        "config_count": len(results),
        "baseline": baseline,
        "top_results": top_results,
    }

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay stage-2 selector decisions from candidate_audit.json files using alternate "
            "weight configurations."
        )
    )
    parser.add_argument("--audit-glob", help="Glob for candidate_audit.json files.")
    parser.add_argument("--audit-paths", help="Comma-separated candidate_audit.json paths.")
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--plddt-gate-threshold", type=float, default=DEFAULT_PLDTT_GATE_THRESHOLD)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--esm-weight-values", default="0.2,0.3,0.4,0.5")
    parser.add_argument("--motif-weight-values", default="0.1,0.2,0.3")
    parser.add_argument("--template-weight-values", default="0.05,0.1,0.15")
    parser.add_argument("--baseline-esm-weight", type=float, default=0.2)
    parser.add_argument("--baseline-motif-weight", type=float, default=0.2)
    parser.add_argument("--baseline-geometry-weight", type=float, default=0.6)
    parser.add_argument("--baseline-template-weight", type=float, default=0.15)
    args = parser.parse_args()
    if args.top_n < 1:
        raise SystemExit("--top-n must be >= 1")
    if args.plddt_gate_threshold <= 0:
        raise SystemExit("--plddt-gate-threshold must be > 0")
    return args


def resolve_audit_paths(args: argparse.Namespace) -> list[Path]:
    paths: list[Path] = []
    if args.audit_glob:
        paths.extend(Path(path) for path in sorted(glob.glob(args.audit_glob)))
    if args.audit_paths:
        paths.extend(Path(part.strip()) for part in args.audit_paths.split(",") if part.strip())
    seen: set[Path] = set()
    resolved: list[Path] = []
    for path in paths:
        item = path.expanduser().resolve()
        if item in seen:
            continue
        if item.name != "candidate_audit.json":
            raise SystemExit(f"Expected candidate_audit.json path, got: {item}")
        if not item.exists():
            raise SystemExit(f"Audit path does not exist: {item}")
        seen.add(item)
        resolved.append(item)
    if not resolved:
        raise SystemExit("No candidate_audit.json files found")
    return resolved


def load_runs(audit_paths: list[Path]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for path in audit_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("records")
        if not isinstance(records, list):
            continue
        metadata_path = path.parent / "metadata.json"
        seed = extract_seed(path.parent.name)
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            seed = int(metadata.get("seed", seed))
        run = {
            "seed": seed,
            "run_name": path.parent.name,
            "audit_path": str(path),
            "records": sorted(records, key=lambda record: int(record.get("step", -1))),
        }
        runs.append(run)
    runs.sort(key=lambda run: run["seed"])
    return runs


def extract_seed(run_name: str) -> int:
    match = SEED_PATTERN.search(run_name)
    if not match:
        return -1
    return int(match.group(1))


def parse_float_values(raw_value: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in raw_value.split(",") if part.strip())
    if not values:
        raise SystemExit("Expected at least one float value")
    return values


def build_config_grid(
    *,
    esm_weight_values: tuple[float, ...],
    motif_weight_values: tuple[float, ...],
    template_weight_values: tuple[float, ...],
) -> list[dict[str, float]]:
    configs: list[dict[str, float]] = []
    for esm_weight in esm_weight_values:
        for motif_weight in motif_weight_values:
            geometry_weight = 1.0 - esm_weight - motif_weight
            if geometry_weight < 0.0:
                continue
            for template_weight in template_weight_values:
                configs.append(
                    {
                        "esm_weight": round(esm_weight, 4),
                        "motif_weight": round(motif_weight, 4),
                        "geometry_weight": round(geometry_weight, 4),
                        "template_weight": round(template_weight, 4),
                    }
                )
    return configs


def config_to_name(config: dict[str, float]) -> str:
    return (
        f"esm{format_weight(config['esm_weight'])}"
        f"-motif{format_weight(config['motif_weight'])}"
        f"-geom{format_weight(config['geometry_weight'])}"
        f"-temp{format_weight(config['template_weight'])}"
    )


def format_weight(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", "p")


def evaluate_config(
    *,
    config_name: str,
    config: dict[str, float],
    runs: list[dict[str, Any]],
    plddt_gate_threshold: float,
) -> dict[str, Any]:
    run_metrics: list[dict[str, Any]] = []
    for run in runs:
        metrics = replay_run(
            records=run["records"],
            config=config,
            plddt_gate_threshold=plddt_gate_threshold,
        )
        run_metrics.append(
            {
                "seed": run["seed"],
                "run_name": run["run_name"],
                "audit_path": run["audit_path"],
                **metrics,
            }
        )

    tier2_counts = [int(run["tier2_count"]) for run in run_metrics]
    tier2_rates = [float(run["tier2_rate"]) for run in run_metrics]
    stable_rates = [float(run["stable_only_rate"]) for run in run_metrics]
    geometry_rates = [float(run["geometry_only_rate"]) for run in run_metrics]

    aligned_steps = min((len(run["tier2_by_step"]) for run in run_metrics), default=0)
    prompts_with_any_tier2 = 0
    for step_index in range(aligned_steps):
        if any(run["tier2_by_step"][step_index] == 1 for run in run_metrics):
            prompts_with_any_tier2 += 1

    aggregate = {
        "config_name": config_name,
        "config": config,
        "run_count": len(run_metrics),
        "seeds": [int(run["seed"]) for run in run_metrics],
        "tier2_hits_by_seed": tier2_counts,
        "prompt_coverage_by_seed": tier2_counts,
        "bridge_hits_per_prompt_mean": round(statistics.fmean(tier2_rates), 6) if tier2_rates else 0.0,
        "stability_dominant_rate_mean": round(statistics.fmean(stable_rates), 6) if stable_rates else 0.0,
        "geometry_dominant_rate_mean": round(statistics.fmean(geometry_rates), 6) if geometry_rates else 0.0,
        "prompts_with_any_tier2_across_seeds": prompts_with_any_tier2,
        "seeds_with_tier2": sum(1 for value in tier2_counts if value >= 1),
        "runs": run_metrics,
    }
    return aggregate


def replay_run(
    *,
    records: list[dict[str, Any]],
    config: dict[str, float],
    plddt_gate_threshold: float,
) -> dict[str, Any]:
    selected_rows: list[dict[str, Any]] = []
    tier2_by_step: list[int] = []
    for record in records:
        candidates = list(record.get("candidates") or [])
        if not candidates:
            continue
        stage2_pool = [candidate for candidate in candidates if bool(candidate.get("in_stage2_pool"))]
        if not stage2_pool:
            stage2_pool = candidates[:1]

        scored_pool = sorted(
            stage2_pool,
            key=lambda candidate: (
                replay_stage2_score(candidate=candidate, config=config),
                to_float(candidate.get("stage1_score")),
            ),
            reverse=True,
        )
        selected = (
            next(
                (
                    candidate
                    for candidate in scored_pool
                    if bool(candidate.get("is_trainable"))
                    and to_float(candidate.get("raw_esm_score")) >= plddt_gate_threshold
                ),
                None,
            )
            or next((candidate for candidate in scored_pool if bool(candidate.get("is_trainable"))), None)
            or scored_pool[0]
        )
        selected_rows.append(selected)
        tier2_by_step.append(int(is_tier2(selected)))

    steps = len(selected_rows)
    tier2_count = sum(1 for candidate in selected_rows if is_tier2(candidate))
    stable_only_count = sum(1 for candidate in selected_rows if is_stable_only(candidate))
    geometry_only_count = sum(1 for candidate in selected_rows if is_geometry_only(candidate))
    return {
        "steps": steps,
        "tier2_count": tier2_count,
        "tier2_rate": safe_rate(tier2_count, steps),
        "stable_only_count": stable_only_count,
        "stable_only_rate": safe_rate(stable_only_count, steps),
        "geometry_only_count": geometry_only_count,
        "geometry_only_rate": safe_rate(geometry_only_count, steps),
        "tier2_by_step": tier2_by_step,
    }


def replay_stage2_score(*, candidate: dict[str, Any], config: dict[str, float]) -> float:
    raw_esm_score = to_float(candidate.get("raw_esm_score"))
    motif_strength = to_float(candidate.get("motif_strength"))
    geometry_score = to_float(candidate.get("geometry_score"))
    template_penalty = to_float(candidate.get("template_penalty"))
    normalized_esm = max(0.0, min(MAX_NORMALIZED_SCORE, raw_esm_score / SECOND_STAGE_ESM_SCORE_NORMALIZER))
    return (
        (config["esm_weight"] * normalized_esm)
        + (config["motif_weight"] * motif_strength)
        + (config["geometry_weight"] * geometry_score)
        + (config["template_weight"] * template_penalty)
    )


def is_tier2(candidate: dict[str, Any]) -> bool:
    return (
        to_int(candidate.get("motif_count")) == 1
        and bool(candidate.get("geometry_passes"))
        and bool(candidate.get("esm_gate_pass"))
    )


def is_stable_only(candidate: dict[str, Any]) -> bool:
    return (
        to_int(candidate.get("motif_count")) == 1
        and bool(candidate.get("esm_gate_pass"))
        and not bool(candidate.get("geometry_passes"))
    )


def is_geometry_only(candidate: dict[str, Any]) -> bool:
    return (
        to_int(candidate.get("motif_count")) == 1
        and bool(candidate.get("geometry_passes"))
        and not bool(candidate.get("esm_gate_pass"))
    )


def ranking_key(result: dict[str, Any]) -> tuple[float | int, ...]:
    return (
        int(result["seeds_with_tier2"]),
        int(result["prompts_with_any_tier2_across_seeds"]),
        float(result["bridge_hits_per_prompt_mean"]),
        -float(result["geometry_dominant_rate_mean"]),
        -float(result["stability_dominant_rate_mean"]),
    )


def safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def to_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    main()
