from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


RUN_ABLATION = ROOT / "scripts" / "run_ablation.py"
DEFAULT_DURABILITY_REQUIRED_SEED_COUNT = 3
DEFAULT_DURABILITY_MIN_SEEDS_WITH_HIT = 2
DEFAULT_DURABILITY_PROMPT_COVERAGE_THRESHOLD = 0.15
DEFAULT_DURABILITY_SMALL_PROMPT_COUNT = 12
DEFAULT_DURABILITY_SEED_SPREAD_LIMIT_SMALL = 2
DEFAULT_DURABILITY_SEED_SPREAD_LIMIT_LARGE = 4
TEMPERATURE_TOKEN_PATTERN = re.compile(r"-t([0-9p]+)(?=-|$)")


def main() -> None:
    args = parse_args()
    validate_args(args)
    python_executable = resolve_python_executable()
    suite_name = sanitize_name(args.name)
    suite_dir = Path(args.output_dir) / suite_name
    frozen_prompts_dir = suite_dir / "frozen_prompts"
    frozen_prompts_dir.mkdir(parents=True, exist_ok=True)
    baseline_summary_path = (
        Path(args.baseline_summary_path).expanduser().resolve() if args.baseline_summary_path else None
    )
    baseline_summary = load_baseline_summary(baseline_summary_path) if baseline_summary_path else None
    durability_config = {
        "required_seed_count": args.durability_required_seed_count,
        "min_seeds_with_hit": args.durability_min_seeds_with_hit,
        "prompt_coverage_threshold": args.durability_prompt_coverage_threshold,
        "small_prompt_count": args.durability_small_prompt_count,
        "seed_spread_limit_small": args.durability_seed_spread_limit_small,
        "seed_spread_limit_large": args.durability_seed_spread_limit_large,
    }

    suite_sizes = parse_int_list(args.suite_sizes)
    temperatures = parse_float_list(args.temperatures)
    seeds = parse_int_list(args.seeds)
    ablation_output_dir = Path(args.ablation_output_dir)
    ablation_index = build_ablation_index(ablation_output_dir)

    prompt_rows = load_jsonl(Path(args.prompts_path))
    frozen_prompt_paths = build_frozen_prompt_sets(
        prompt_rows=prompt_rows,
        sizes=suite_sizes,
        seed=args.prompt_suite_seed,
        output_dir=frozen_prompts_dir,
    )

    runs: list[dict[str, Any]] = []
    for prompt_count in suite_sizes:
        prompts_path = frozen_prompt_paths[prompt_count]
        for temperature in temperatures:
            for seed in seeds:
                run_name = build_run_name(
                    suite_name=suite_name,
                    prompt_count=prompt_count,
                    temperature=temperature,
                    seed=seed,
                )
                run_dir = ablation_output_dir / sanitize_name(run_name)
                summary_path = run_dir / "summary.json"
                report_path = run_dir / "report.json"

                resolved_paths = resolve_existing_run_paths(
                    expected_summary_path=summary_path,
                    expected_report_path=report_path,
                    ablation_index=ablation_index,
                    suite_name=suite_name,
                    prompt_count=prompt_count,
                    temperature=temperature,
                    seed=seed,
                    init_state_path=args.init_state_path,
                    model=args.model,
                    variant=args.variant,
                    prompts_path=prompts_path,
                )
                if resolved_paths is not None:
                    summary_path = resolved_paths["summary_path"]
                    report_path = resolved_paths["report_path"]

                run_entry = {
                    "run_name": run_name,
                    "prompt_count": prompt_count,
                    "temperature": temperature,
                    "seed": seed,
                    "prompts_path": str(prompts_path),
                    "summary_path": str(summary_path),
                    "report_path": str(report_path),
                    "executed": False,
                    "completed": False,
                }

                run_entry["completed"] = summary_path.exists() and report_path.exists()
                should_execute = not args.summary_only and (not args.skip_existing or not run_entry["completed"])
                if should_execute:
                    execute_run_ablation(
                        python_executable=python_executable,
                        run_name=run_name,
                        variant=args.variant,
                        model=args.model,
                        prompts_path=prompts_path,
                        reference_records_path=Path(args.reference_records_path),
                        output_dir=Path(args.ablation_output_dir),
                        prompt_count=prompt_count,
                        candidate_sample_count=args.candidate_sample_count,
                        second_stage_top_k=args.second_stage_top_k,
                        esm_pll_gate_percentile=args.esm_pll_gate_percentile,
                        second_stage_esm_weight=args.second_stage_esm_weight,
                        second_stage_motif_weight=args.second_stage_motif_weight,
                        second_stage_geometry_weight=args.second_stage_geometry_weight,
                        second_stage_template_weight=args.second_stage_template_weight,
                        init_state_path=args.init_state_path,
                        seed=seed,
                        temperature=temperature,
                        api_key=args.api_key,
                        esm2_device=args.esm2_device,
                    )
                    run_entry["executed"] = True
                    if run_dir.joinpath("summary.json").exists() and run_dir.joinpath("report.json").exists():
                        summary_path = run_dir / "summary.json"
                        report_path = run_dir / "report.json"
                        run_entry["summary_path"] = str(summary_path)
                        run_entry["report_path"] = str(report_path)

                if summary_path.exists() and report_path.exists():
                    run_entry["completed"] = True
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                    run_entry["summary"] = summary
                    run_entry["metrics"] = extract_metrics(report)

                runs.append(run_entry)

    manifest = {
        "name": args.name,
        "suite_name": suite_name,
        "init_state_path": args.init_state_path,
        "model": args.model,
        "variant": args.variant,
        "prompts_path": args.prompts_path,
        "reference_records_path": args.reference_records_path,
        "suite_sizes": suite_sizes,
        "temperatures": temperatures,
        "seeds": seeds,
        "baseline_summary_path": str(baseline_summary_path) if baseline_summary_path else None,
        "candidate_sample_count": args.candidate_sample_count,
        "second_stage_top_k": args.second_stage_top_k,
        "esm_pll_gate_percentile": args.esm_pll_gate_percentile,
        "second_stage_esm_weight": args.second_stage_esm_weight,
        "second_stage_motif_weight": args.second_stage_motif_weight,
        "second_stage_geometry_weight": args.second_stage_geometry_weight,
        "second_stage_template_weight": args.second_stage_template_weight,
        "prompt_suite_seed": args.prompt_suite_seed,
        "durability_config": durability_config,
        "frozen_prompts": {str(size): str(path) for size, path in frozen_prompt_paths.items()},
        "runs": runs,
    }
    manifest_path = suite_dir / "runs_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    robustness_summary = build_robustness_summary(
        suite_name=suite_name,
        init_state_path=args.init_state_path,
        model=args.model,
        variant=args.variant,
        suite_sizes=suite_sizes,
        temperatures=temperatures,
        seeds=seeds,
        runs=runs,
        durability_config=durability_config,
        baseline_summary=baseline_summary,
        baseline_summary_path=baseline_summary_path,
    )
    summary_path = suite_dir / "robustness_summary.json"
    summary_path.write_text(json.dumps(robustness_summary, indent=2), encoding="utf-8")
    
    # W&B Logging for the Sweep Evaluation
    try:
        import wandb
        wandb.init(
            project="pearl-eval",
            name=f"robustness-{suite_name}",
            config={
                "suite_name": suite_name,
                "init_state_path": args.init_state_path,
                "model": args.model,
                "variant": args.variant,
                "candidate_sample_count": args.candidate_sample_count,
                "second_stage_top_k": args.second_stage_top_k,
                "esm_pll_gate_percentile": args.esm_pll_gate_percentile,
                "esm_weight": args.second_stage_esm_weight,
                "motif_weight": args.second_stage_motif_weight,
                "geometry_weight": args.second_stage_geometry_weight,
                "template_weight": args.second_stage_template_weight,
                "durability_config": durability_config,
            }
        )
        
        # Log global durability gate status
        wandb.log({
            "durability/gate_passed": int(robustness_summary["durability_gate"]["passed"]),
            "durability/baseline_locked": int(robustness_summary["durability_gate"]["baseline_locked"]),
        })
        
        # Log group-level metrics (e.g., prompt size & temperature combinations)
        for group in robustness_summary.get("groups", []):
            p_count = group["prompt_count"]
            temp = group["temperature"]
            prefix = f"group_p{p_count}_t{temp}"
            
            group_data = {
                f"{prefix}/run_count": group["run_count"],
                f"{prefix}/bridge_hits_rate_mean": group["bridge_hits_per_prompt"]["mean"],
                f"{prefix}/bridge_hits_rate_min": group["bridge_hits_per_prompt"]["min"],
                f"{prefix}/bridge_hits_rate_max": group["bridge_hits_per_prompt"]["max"],
                f"{prefix}/stability_dominant_rate_mean": group["stability_dominant_rate"]["mean"],
                f"{prefix}/geometry_dominant_rate_mean": group["geometry_dominant_rate"]["mean"],
                f"{prefix}/prompts_with_hits": group["prompts_with_any_tier2_across_seeds"],
            }
            wandb.log(group_data)
            
        wandb.finish()
    except Exception as e:
        # Gracefully log warning but do not crash the evaluation script
        print(f"Warning: W&B logging failed during evaluation summary: {e}", flush=True)

    print(json.dumps({"manifest_path": str(manifest_path), "summary_path": str(summary_path)}, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run and summarize a frozen robustness benchmark suite")
    parser.add_argument("--name", required=True)
    parser.add_argument("--init-state-path", required=True)
    parser.add_argument("--model", default="moonshotai/Kimi-K2.6")
    parser.add_argument(
        "--variant",
        choices=("baseline", "motif_prior_v1", "motif_prior_soft_v2"),
        default="baseline",
    )
    parser.add_argument(
        "--prompts-path",
        default=str(ROOT / "data" / "petase_family_expanded" / "val_prompts_relevance_ge10.jsonl"),
    )
    parser.add_argument(
        "--reference-records-path",
        default=str(ROOT / "data" / "petase_family_expanded" / "petase_records.jsonl"),
    )
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "robustness"))
    parser.add_argument("--ablation-output-dir", default=str(ROOT / "reports" / "ablations"))
    parser.add_argument("--suite-sizes", default="12,24,48")
    parser.add_argument("--temperatures", default="0.6,0.8,1.0")
    parser.add_argument("--seeds", default="7,19,31")
    parser.add_argument("--candidate-sample-count", type=int, default=128)
    parser.add_argument("--second-stage-top-k", type=int, default=16)
    parser.add_argument("--esm-pll-gate-percentile", type=float, default=0.05)
    parser.add_argument(
        "--second-stage-esm-weight",
        type=float,
        default=float(os.environ.get("TINKER_SECOND_STAGE_ESM_WEIGHT", "0.2")),
    )
    parser.add_argument(
        "--second-stage-motif-weight",
        type=float,
        default=float(os.environ.get("TINKER_SECOND_STAGE_MOTIF_WEIGHT", "0.2")),
    )
    parser.add_argument(
        "--second-stage-geometry-weight",
        type=float,
        default=float(os.environ.get("TINKER_SECOND_STAGE_GEOMETRY_WEIGHT", "0.6")),
    )
    parser.add_argument(
        "--second-stage-template-weight",
        type=float,
        default=float(os.environ.get("TINKER_SECOND_STAGE_TEMPLATE_WEIGHT", "0.15")),
    )
    parser.add_argument("--prompt-suite-seed", type=int, default=1337)
    parser.add_argument("--api-key")
    parser.add_argument("--esm2-device", default=os.environ.get("ESM2_DEVICE", "mps"))
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", action="store_false", dest="skip_existing")
    parser.add_argument(
        "--baseline-summary-path",
        help="Path to a frozen robustness_summary.json used for baseline-locked durability comparison.",
    )
    parser.add_argument(
        "--durability-required-seed-count",
        type=int,
        default=DEFAULT_DURABILITY_REQUIRED_SEED_COUNT,
    )
    parser.add_argument(
        "--durability-min-seeds-with-hit",
        type=int,
        default=DEFAULT_DURABILITY_MIN_SEEDS_WITH_HIT,
    )
    parser.add_argument(
        "--durability-prompt-coverage-threshold",
        type=float,
        default=DEFAULT_DURABILITY_PROMPT_COVERAGE_THRESHOLD,
    )
    parser.add_argument(
        "--durability-small-prompt-count",
        type=int,
        default=DEFAULT_DURABILITY_SMALL_PROMPT_COUNT,
    )
    parser.add_argument(
        "--durability-seed-spread-limit-small",
        type=int,
        default=DEFAULT_DURABILITY_SEED_SPREAD_LIMIT_SMALL,
    )
    parser.add_argument(
        "--durability-seed-spread-limit-large",
        type=int,
        default=DEFAULT_DURABILITY_SEED_SPREAD_LIMIT_LARGE,
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.durability_required_seed_count < 1:
        raise SystemExit("--durability-required-seed-count must be >= 1")
    if args.durability_min_seeds_with_hit < 1:
        raise SystemExit("--durability-min-seeds-with-hit must be >= 1")
    if args.durability_min_seeds_with_hit > args.durability_required_seed_count:
        raise SystemExit("--durability-min-seeds-with-hit cannot exceed --durability-required-seed-count")
    if not 0.0 < args.durability_prompt_coverage_threshold <= 1.0:
        raise SystemExit("--durability-prompt-coverage-threshold must be in the range (0, 1]")
    if args.durability_small_prompt_count < 1:
        raise SystemExit("--durability-small-prompt-count must be >= 1")
    if args.durability_seed_spread_limit_small < 0:
        raise SystemExit("--durability-seed-spread-limit-small must be >= 0")
    if args.durability_seed_spread_limit_large < 0:
        raise SystemExit("--durability-seed-spread-limit-large must be >= 0")


def load_baseline_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Baseline summary does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    groups = payload.get("groups")
    if not isinstance(groups, list):
        raise SystemExit(f"Baseline summary missing 'groups' list: {path}")
    return payload


def parse_int_list(raw_value: str) -> list[int]:
    values = [int(part.strip()) for part in raw_value.split(",") if part.strip()]
    if not values:
        raise SystemExit("Expected at least one integer value")
    if len(set(values)) != len(values):
        raise SystemExit("Integer list contains duplicates")
    return values


def parse_float_list(raw_value: str) -> list[float]:
    values = [float(part.strip()) for part in raw_value.split(",") if part.strip()]
    if not values:
        raise SystemExit("Expected at least one float value")
    if len(set(values)) != len(values):
        raise SystemExit("Float list contains duplicates")
    return values


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def build_frozen_prompt_sets(
    *,
    prompt_rows: list[dict[str, Any]],
    sizes: list[int],
    seed: int,
    output_dir: Path,
) -> dict[int, Path]:
    max_size = max(sizes)
    if max_size > len(prompt_rows):
        raise SystemExit(f"Requested max suite size {max_size} but only found {len(prompt_rows)} prompts")

    shuffled_rows = list(prompt_rows)
    random.Random(seed).shuffle(shuffled_rows)
    paths: dict[int, Path] = {}
    for size in sizes:
        subset = shuffled_rows[:size]
        path = output_dir / f"prompts_p{size}.jsonl"
        write_jsonl(path, subset)
        paths[size] = path
    return paths


def build_ablation_index(ablation_output_dir: Path) -> dict[tuple[int, int, str, str, str], list[dict[str, Any]]]:
    if not ablation_output_dir.exists():
        return {}

    index: dict[tuple[int, int, str, str, str], list[dict[str, Any]]] = {}
    for run_dir in sorted(ablation_output_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        summary_path = run_dir / "summary.json"
        report_path = run_dir / "report.json"
        if not summary_path.exists() or not report_path.exists():
            continue
        try:
            summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        try:
            prompt_count = int(summary_payload.get("prompt_count"))
            seed = int(summary_payload.get("seed"))
        except (TypeError, ValueError):
            continue

        init_state_path = str(summary_payload.get("init_state_path") or "")
        model = str(summary_payload.get("model") or "")
        variant = str(summary_payload.get("variant") or "")
        run_name = str(summary_payload.get("name") or run_dir.name)
        temperature = parse_temperature_from_run_name(run_name)
        source_prompts_path = read_source_prompts_path(run_dir)
        key = (prompt_count, seed, init_state_path, model, variant)
        index.setdefault(key, []).append(
            {
                "run_name": run_name,
                "summary_path": str(summary_path.resolve()),
                "report_path": str(report_path.resolve()),
                "temperature": temperature,
                "source_prompts_path": source_prompts_path,
            }
        )
    return index


def read_source_prompts_path(run_dir: Path) -> str | None:
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        return None
    try:
        metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    source_path = metadata_payload.get("source_prompts_path")
    if not source_path:
        return None
    return str(Path(source_path).expanduser().resolve())


def resolve_existing_run_paths(
    *,
    expected_summary_path: Path,
    expected_report_path: Path,
    ablation_index: dict[tuple[int, int, str, str, str], list[dict[str, Any]]],
    suite_name: str,
    prompt_count: int,
    temperature: float,
    seed: int,
    init_state_path: str,
    model: str,
    variant: str,
    prompts_path: Path,
) -> dict[str, Path] | None:
    if expected_summary_path.exists() and expected_report_path.exists():
        return {
            "summary_path": expected_summary_path,
            "report_path": expected_report_path,
        }

    key = (prompt_count, seed, init_state_path, model, variant)
    candidates = list(ablation_index.get(key, []))
    if not candidates:
        return None

    source_prompts_path = str(prompts_path.expanduser().resolve())
    source_matches = [
        candidate for candidate in candidates if candidate.get("source_prompts_path") == source_prompts_path
    ]
    if source_matches:
        candidates = source_matches

    temperature_matches = [
        candidate
        for candidate in candidates
        if is_temperature_match(candidate.get("temperature"), temperature)
    ]
    if temperature_matches:
        candidates = temperature_matches
    elif len(candidates) != 1:
        return None

    candidates.sort(
        key=lambda candidate: candidate_match_score(
            candidate_run_name=str(candidate.get("run_name") or ""),
            suite_name=suite_name,
            desired_temperature=temperature,
            candidate_temperature=candidate.get("temperature"),
        ),
        reverse=True,
    )
    best = candidates[0]
    summary_path = Path(str(best["summary_path"]))
    report_path = Path(str(best["report_path"]))
    if not summary_path.exists() or not report_path.exists():
        return None
    return {
        "summary_path": summary_path,
        "report_path": report_path,
    }


def candidate_match_score(
    *,
    candidate_run_name: str,
    suite_name: str,
    desired_temperature: float,
    candidate_temperature: float | None,
) -> int:
    score = 0
    if suite_name and suite_name in candidate_run_name:
        score += 4
    suite_prefix = strip_trailing_run_index(suite_name)
    if suite_prefix and suite_prefix in candidate_run_name:
        score += 2
    if is_temperature_match(candidate_temperature, desired_temperature):
        score += 8
    return score


def strip_trailing_run_index(value: str) -> str:
    return re.sub(r"-r\d+$", "", value)


def parse_temperature_from_run_name(run_name: str) -> float | None:
    if not run_name:
        return None
    matches = TEMPERATURE_TOKEN_PATTERN.findall(run_name.lower())
    for token in reversed(matches):
        parsed = parse_temperature_token(token)
        if parsed is not None:
            return parsed
    return None


def parse_temperature_token(token: str) -> float | None:
    token = token.strip().lower()
    if not token:
        return None
    if "p" in token:
        try:
            return float(token.replace("p", "."))
        except ValueError:
            return None

    candidates: list[float] = []
    try:
        candidates.append(float(token))
    except ValueError:
        return None

    if len(token) > 1 and token.isdigit():
        try:
            candidates.append(float(f"{token[0]}.{token[1:]}"))
        except ValueError:
            pass
        if token.startswith("0"):
            try:
                candidates.append(float(f"0.{token[1:]}"))
            except ValueError:
                pass

    plausible = [value for value in candidates if 0.0 < value <= 2.0]
    if plausible:
        return plausible[0]
    return candidates[0] if candidates else None


def is_temperature_match(candidate_temperature: float | None, desired_temperature: float) -> bool:
    if candidate_temperature is None:
        return False
    return math.isclose(candidate_temperature, desired_temperature, abs_tol=1e-6)


def execute_run_ablation(
    *,
    python_executable: str,
    run_name: str,
    variant: str,
    model: str,
    prompts_path: Path,
    reference_records_path: Path,
    output_dir: Path,
    prompt_count: int,
    candidate_sample_count: int,
    second_stage_top_k: int,
    esm_pll_gate_percentile: float,
    second_stage_esm_weight: float,
    second_stage_motif_weight: float,
    second_stage_geometry_weight: float,
    second_stage_template_weight: float,
    init_state_path: str,
    seed: int,
    temperature: float,
    api_key: str | None,
    esm2_device: str,
) -> None:
    command = [
        python_executable,
        str(RUN_ABLATION),
        "--name",
        run_name,
        "--variant",
        variant,
        "--model",
        model,
        "--prompts-path",
        str(prompts_path),
        "--reference-records-path",
        str(reference_records_path),
        "--output-dir",
        str(output_dir),
        "--prompt-count",
        str(prompt_count),
        "--candidate-sample-count",
        str(candidate_sample_count),
        "--second-stage-top-k",
        str(second_stage_top_k),
        "--esm-pll-gate-percentile",
        str(esm_pll_gate_percentile),
        "--second-stage-esm-weight",
        str(second_stage_esm_weight),
        "--second-stage-motif-weight",
        str(second_stage_motif_weight),
        "--second-stage-geometry-weight",
        str(second_stage_geometry_weight),
        "--second-stage-template-weight",
        str(second_stage_template_weight),
        "--init-state-path",
        init_state_path,
        "--eval-only",
        "--resume",
        "--capture-candidate-audit",
        "--seed",
        str(seed),
        "--preserve-order",
    ]
    env = os.environ.copy()
    if api_key:
        env["TINKER_API_KEY"] = api_key
    if not env.get("TINKER_API_KEY"):
        raise SystemExit("TINKER_API_KEY is required via --api-key or environment")
    env["SAMPLING_TEMPERATURE"] = str(temperature)
    env["ESM2_DEVICE"] = esm2_device
    subprocess.run(command, check=True, cwd=ROOT, env=env)


def extract_metrics(report: dict[str, Any]) -> dict[str, Any]:
    records = sorted(report.get("records", []), key=lambda record: int(record.get("step", 0)))
    tier2_by_step: list[int] = []
    stable_only_by_step: list[int] = []
    geometry_only_by_step: list[int] = []

    for record in records:
        quality = record.get("sequence_quality") or {}
        reward_components = record.get("reward_components") or {}
        family_evaluation = record.get("family_evaluation") or {}
        motif_count = int(quality.get("motif_count") or 0)
        geometry_passes = bool((family_evaluation.get("catalytic_geometry") or {}).get("passes"))
        esm_gate_pass = bool(reward_components.get("esm_gate_pass"))

        tier2 = int(motif_count == 1 and geometry_passes and esm_gate_pass)
        stable_only = int(motif_count == 1 and esm_gate_pass and not geometry_passes)
        geometry_only = int(motif_count == 1 and geometry_passes and not esm_gate_pass)
        tier2_by_step.append(tier2)
        stable_only_by_step.append(stable_only)
        geometry_only_by_step.append(geometry_only)

    steps = len(records)
    tier2_count = sum(tier2_by_step)
    stable_only_count = sum(stable_only_by_step)
    geometry_only_count = sum(geometry_only_by_step)

    return {
        "steps": steps,
        "average_reward": float(report.get("average_reward") or 0.0),
        "trainable_count": sum(1 for record in records if not bool(record.get("training_skipped"))),
        "tier2_count": tier2_count,
        "tier2_rate": safe_fraction(tier2_count, steps),
        "stable_only_count": stable_only_count,
        "stable_only_rate": safe_fraction(stable_only_count, steps),
        "geometry_only_count": geometry_only_count,
        "geometry_only_rate": safe_fraction(geometry_only_count, steps),
        "tier2_by_step": tier2_by_step,
        "stable_only_by_step": stable_only_by_step,
        "geometry_only_by_step": geometry_only_by_step,
    }


def build_robustness_summary(
    *,
    suite_name: str,
    init_state_path: str,
    model: str,
    variant: str,
    suite_sizes: list[int],
    temperatures: list[float],
    seeds: list[int],
    runs: list[dict[str, Any]],
    durability_config: dict[str, Any],
    baseline_summary: dict[str, Any] | None,
    baseline_summary_path: Path | None,
) -> dict[str, Any]:
    completed_runs = [run for run in runs if run.get("completed") and run.get("metrics") is not None]
    groups: list[dict[str, Any]] = []
    for prompt_count in suite_sizes:
        for temperature in temperatures:
            group_runs = [
                run
                for run in completed_runs
                if int(run["prompt_count"]) == prompt_count and float(run["temperature"]) == temperature
            ]
            groups.append(aggregate_group(prompt_count=prompt_count, temperature=temperature, runs=group_runs))

    missing_runs = [run for run in runs if not run.get("completed")]
    durability_gate = build_durability_gate(
        groups=groups,
        suite_sizes=suite_sizes,
        temperatures=temperatures,
        durability_config=durability_config,
        baseline_summary=baseline_summary,
        baseline_summary_path=baseline_summary_path,
    )
    return {
        "suite_name": suite_name,
        "init_state_path": init_state_path,
        "model": model,
        "variant": variant,
        "suite_sizes": suite_sizes,
        "temperatures": temperatures,
        "seeds": seeds,
        "run_count": len(runs),
        "completed_run_count": len(completed_runs),
        "missing_run_count": len(missing_runs),
        "missing_run_names": [run["run_name"] for run in missing_runs],
        "durability_config": durability_config,
        "baseline_summary_path": str(baseline_summary_path) if baseline_summary_path else None,
        "baseline_suite_name": baseline_summary.get("suite_name") if baseline_summary else None,
        "durability_gate": durability_gate,
        "groups": groups,
    }


def aggregate_group(*, prompt_count: int, temperature: float, runs: list[dict[str, Any]]) -> dict[str, Any]:
    runs_sorted = sorted(runs, key=lambda run: int(run["seed"]))
    if not runs_sorted:
        return {
            "prompt_count": prompt_count,
            "temperature": temperature,
            "run_count": 0,
            "seeds": [],
            "runs": [],
        }

    tier2_counts = [int(run["metrics"]["tier2_count"]) for run in runs_sorted]
    tier2_rates = [float(run["metrics"]["tier2_rate"]) for run in runs_sorted]
    stable_rates = [float(run["metrics"]["stable_only_rate"]) for run in runs_sorted]
    geometry_rates = [float(run["metrics"]["geometry_only_rate"]) for run in runs_sorted]

    aligned_step_count = min(int(run["metrics"]["steps"]) for run in runs_sorted)
    prompt_hit_fraction_by_index: list[float] = []
    for step_index in range(aligned_step_count):
        prompt_hits = sum(int(run["metrics"]["tier2_by_step"][step_index]) for run in runs_sorted)
        prompt_hit_fraction_by_index.append(prompt_hits / len(runs_sorted))

    return {
        "prompt_count": prompt_count,
        "temperature": temperature,
        "run_count": len(runs_sorted),
        "seeds": [int(run["seed"]) for run in runs_sorted],
        "tier2_hits_by_seed": [int(value) for value in tier2_counts],
        "prompt_coverage_by_seed": [int(value) for value in tier2_counts],
        "prompt_coverage_rate_by_seed": [round(float(value), 6) for value in tier2_rates],
        "stability_dominant_rate_by_seed": [round(float(value), 6) for value in stable_rates],
        "geometry_dominant_rate_by_seed": [round(float(value), 6) for value in geometry_rates],
        "bridge_hits_per_prompt": summarize_numeric(tier2_rates),
        "bridge_hits_count": summarize_numeric(tier2_counts),
        "per_seed_bridge_count_variance": round(statistics.pvariance(tier2_counts), 6) if len(tier2_counts) > 1 else 0.0,
        "per_seed_bridge_rate_variance": round(statistics.pvariance(tier2_rates), 8) if len(tier2_rates) > 1 else 0.0,
        "prompts_with_any_tier2_across_seeds": sum(1 for value in prompt_hit_fraction_by_index if value > 0.0),
        "prompt_tier2_hit_fraction": summarize_numeric(prompt_hit_fraction_by_index),
        "stability_dominant_rate": summarize_numeric(stable_rates),
        "geometry_dominant_rate": summarize_numeric(geometry_rates),
        "runs": [
            {
                "run_name": run["run_name"],
                "seed": int(run["seed"]),
                "summary_path": run["summary_path"],
                "report_path": run["report_path"],
                "average_reward": float(run["metrics"]["average_reward"]),
                "trainable_count": int(run["metrics"]["trainable_count"]),
                "tier2_count": int(run["metrics"]["tier2_count"]),
                "tier2_rate": float(run["metrics"]["tier2_rate"]),
                "stable_only_count": int(run["metrics"]["stable_only_count"]),
                "stable_only_rate": float(run["metrics"]["stable_only_rate"]),
                "geometry_only_count": int(run["metrics"]["geometry_only_count"]),
                "geometry_only_rate": float(run["metrics"]["geometry_only_rate"]),
            }
            for run in runs_sorted
        ],
    }


def build_durability_gate(
    *,
    groups: list[dict[str, Any]],
    suite_sizes: list[int],
    temperatures: list[float],
    durability_config: dict[str, Any],
    baseline_summary: dict[str, Any] | None,
    baseline_summary_path: Path | None,
) -> dict[str, Any]:
    baseline_locked = baseline_summary is not None
    baseline_group_index: dict[tuple[int, float], dict[str, Any]] = {}
    if baseline_locked:
        assert baseline_summary is not None
        for baseline_group in baseline_summary.get("groups", []):
            key = (
                int(baseline_group.get("prompt_count", -1)),
                float(baseline_group.get("temperature", -1.0)),
            )
            baseline_group_index[key] = baseline_group

    group_results: list[dict[str, Any]] = []
    for prompt_count in suite_sizes:
        for temperature in temperatures:
            current_group = find_group(groups=groups, prompt_count=prompt_count, temperature=temperature)
            baseline_group = baseline_group_index.get((prompt_count, temperature))
            group_results.append(
                evaluate_durability_group(
                    prompt_count=prompt_count,
                    temperature=temperature,
                    group=current_group,
                    baseline_group=baseline_group,
                    baseline_locked=baseline_locked,
                    durability_config=durability_config,
                )
            )

    per_prompt_size: dict[str, dict[str, Any]] = {}
    for prompt_count in suite_sizes:
        size_results = [result for result in group_results if int(result["prompt_count"]) == prompt_count]
        passed = bool(size_results) and all(bool(result["passed"]) for result in size_results)
        per_prompt_size[str(prompt_count)] = {
            "passed": passed,
            "temperatures": [float(result["temperature"]) for result in size_results],
            "failing_temperatures": [
                float(result["temperature"]) for result in size_results if not bool(result["passed"])
            ],
        }

    overall_pass = all(bool(entry["passed"]) for entry in per_prompt_size.values()) if per_prompt_size else False
    return {
        "passed": overall_pass,
        "baseline_locked": baseline_locked,
        "baseline_summary_path": str(baseline_summary_path) if baseline_summary_path else None,
        "baseline_suite_name": baseline_summary.get("suite_name") if baseline_summary else None,
        "per_prompt_size": per_prompt_size,
        "group_results": group_results,
    }


def find_group(*, groups: list[dict[str, Any]], prompt_count: int, temperature: float) -> dict[str, Any] | None:
    for group in groups:
        if int(group.get("prompt_count", -1)) == prompt_count and float(group.get("temperature", -1.0)) == temperature:
            return group
    return None


def evaluate_durability_group(
    *,
    prompt_count: int,
    temperature: float,
    group: dict[str, Any] | None,
    baseline_group: dict[str, Any] | None,
    baseline_locked: bool,
    durability_config: dict[str, Any],
) -> dict[str, Any]:
    required_seed_count = int(durability_config["required_seed_count"])
    min_seeds_with_hit = int(durability_config["min_seeds_with_hit"])
    coverage_threshold = float(durability_config["prompt_coverage_threshold"])
    small_prompt_count = int(durability_config["small_prompt_count"])
    spread_limit_small = int(durability_config["seed_spread_limit_small"])
    spread_limit_large = int(durability_config["seed_spread_limit_large"])

    if group is None or int(group.get("run_count", 0)) == 0:
        return {
            "prompt_count": prompt_count,
            "temperature": temperature,
            "passed": False,
            "reason": "No completed runs in this group",
            "tier2_hits_by_seed": [],
            "prompt_coverage_by_seed": [],
            "prompt_coverage_rate_by_seed": [],
            "conditions": [],
        }

    tier2_hits_by_seed = [int(value) for value in group.get("tier2_hits_by_seed", [])]
    prompt_coverage_by_seed = [int(value) for value in group.get("prompt_coverage_by_seed", [])]
    prompt_coverage_rate_by_seed = [float(value) for value in group.get("prompt_coverage_rate_by_seed", [])]
    run_count = int(group.get("run_count", 0))
    seeds_with_hit = sum(1 for value in tier2_hits_by_seed if value >= 1)
    required_coverage_count = int(math.ceil(prompt_count * coverage_threshold))
    coverage_count = int(group.get("prompts_with_any_tier2_across_seeds", 0))
    spread_limit = spread_limit_small if prompt_count <= small_prompt_count else spread_limit_large
    seed_spread = (max(tier2_hits_by_seed) - min(tier2_hits_by_seed)) if tier2_hits_by_seed else 0

    current_bridge_rate = float((group.get("bridge_hits_per_prompt") or {}).get("mean") or 0.0)
    current_stability_rate = float((group.get("stability_dominant_rate") or {}).get("mean") or 0.0)
    current_geometry_rate = float((group.get("geometry_dominant_rate") or {}).get("mean") or 0.0)

    baseline_bridge_rate = float((baseline_group.get("bridge_hits_per_prompt") or {}).get("mean") or 0.0) if baseline_group else None
    baseline_stability_rate = float((baseline_group.get("stability_dominant_rate") or {}).get("mean") or 0.0) if baseline_group else None
    baseline_geometry_rate = float((baseline_group.get("geometry_dominant_rate") or {}).get("mean") or 0.0) if baseline_group else None

    baseline_condition: dict[str, Any]
    if not baseline_locked:
        baseline_condition = {
            "id": "basin_pressure_vs_baseline",
            "applicable": False,
            "passed": True,
            "reason": "no_baseline_summary_supplied",
            "actual": {
                "bridge_hits_per_prompt_mean": round(current_bridge_rate, 6),
                "stability_dominant_rate_mean": round(current_stability_rate, 6),
                "geometry_dominant_rate_mean": round(current_geometry_rate, 6),
            },
            "target": {
                "baseline_bridge_hits_per_prompt_mean": None,
                "baseline_stability_dominant_rate_mean": None,
                "baseline_geometry_dominant_rate_mean": None,
            },
        }
    elif baseline_group is None:
        baseline_condition = {
            "id": "basin_pressure_vs_baseline",
            "applicable": True,
            "passed": False,
            "reason": "baseline_group_missing",
            "actual": {
                "bridge_hits_per_prompt_mean": round(current_bridge_rate, 6),
                "stability_dominant_rate_mean": round(current_stability_rate, 6),
                "geometry_dominant_rate_mean": round(current_geometry_rate, 6),
            },
            "target": {
                "baseline_bridge_hits_per_prompt_mean": None,
                "baseline_stability_dominant_rate_mean": None,
                "baseline_geometry_dominant_rate_mean": None,
            },
        }
    else:
        baseline_condition = {
            "id": "basin_pressure_vs_baseline",
            "applicable": True,
            "passed": (
                current_bridge_rate > float(baseline_bridge_rate)
                and current_stability_rate < float(baseline_stability_rate)
                and current_geometry_rate < float(baseline_geometry_rate)
            ),
            "actual": {
                "bridge_hits_per_prompt_mean": round(current_bridge_rate, 6),
                "stability_dominant_rate_mean": round(current_stability_rate, 6),
                "geometry_dominant_rate_mean": round(current_geometry_rate, 6),
            },
            "target": {
                "baseline_bridge_hits_per_prompt_mean": round(float(baseline_bridge_rate), 6)
                if baseline_bridge_rate is not None
                else None,
                "baseline_stability_dominant_rate_mean": round(float(baseline_stability_rate), 6)
                if baseline_stability_rate is not None
                else None,
                "baseline_geometry_dominant_rate_mean": round(float(baseline_geometry_rate), 6)
                if baseline_geometry_rate is not None
                else None,
            },
        }

    conditions = [
        {
            "id": "seed_support",
            "passed": run_count >= required_seed_count and seeds_with_hit >= min_seeds_with_hit,
            "actual": {
                "run_count": run_count,
                "seeds_with_tier2": seeds_with_hit,
            },
            "target": {
                "required_seed_count": required_seed_count,
                "min_seeds_with_tier2": min_seeds_with_hit,
            },
        },
        {
            "id": "prompt_coverage",
            "passed": coverage_count >= required_coverage_count,
            "actual": {
                "prompts_with_any_tier2_across_seeds": coverage_count,
                "coverage_threshold_fraction": coverage_threshold,
            },
            "target": {
                "required_prompt_coverage_count": required_coverage_count,
            },
        },
        {
            "id": "seed_spread",
            "passed": seed_spread <= spread_limit,
            "actual": {
                "tier2_hit_spread": seed_spread,
                "tier2_hits_by_seed": tier2_hits_by_seed,
            },
            "target": {
                "max_spread": spread_limit,
            },
        },
        baseline_condition,
    ]
    passed = all(bool(condition["passed"]) for condition in conditions)
    return {
        "prompt_count": prompt_count,
        "temperature": temperature,
        "passed": passed,
        "tier2_hits_by_seed": tier2_hits_by_seed,
        "prompt_coverage_by_seed": prompt_coverage_by_seed,
        "prompt_coverage_rate_by_seed": [round(value, 6) for value in prompt_coverage_rate_by_seed],
        "conditions": conditions,
    }


def summarize_numeric(values: list[float | int]) -> dict[str, float]:
    if not values:
        return {
            "min": 0.0,
            "median": 0.0,
            "max": 0.0,
            "mean": 0.0,
        }
    numeric_values = [float(value) for value in values]
    return {
        "min": round(min(numeric_values), 6),
        "median": round(statistics.median(numeric_values), 6),
        "max": round(max(numeric_values), 6),
        "mean": round(statistics.fmean(numeric_values), 6),
    }


def safe_fraction(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def build_run_name(*, suite_name: str, prompt_count: int, temperature: float, seed: int) -> str:
    return (
        f"{suite_name}-p{prompt_count}-t{format_temperature_for_name(temperature)}-s{seed}"
    )


def format_temperature_for_name(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text.replace(".", "p")


def resolve_python_executable() -> str:
    explicit = os.environ.get("TINKER_PYTHON_BIN")
    candidates = [
        explicit,
        sys.executable,
        str(ROOT / ".venv" / "bin" / "python"),
        shutil.which("python"),
        shutil.which("python3"),
        "/opt/anaconda3/bin/python",
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if not Path(candidate).exists():
            continue
        probe = subprocess.run(
            [candidate, "-c", "import tinker"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode == 0:
            return candidate
    raise RuntimeError(
        "Could not find a Python interpreter with the tinker package installed. "
        "Set TINKER_PYTHON_BIN to a working interpreter."
    )


def sanitize_name(value: str) -> str:
    chars: list[str] = []
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("-")
    sanitized = "".join(chars).strip("-")
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized or "robustness-suite"


if __name__ == "__main__":
    main()
