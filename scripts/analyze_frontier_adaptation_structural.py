#!/usr/bin/env python3
"""Fail-closed terminal structural analysis for the frontier-adaptation confirmatory matrix."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "experiments" / "frontier_adaptation_structural_v2_original.json"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_value(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_launcher() -> Any:
    path = ROOT / "scripts" / "launch_scaling_paradox_v1.py"
    spec = importlib.util.spec_from_file_location("structural_analysis_launcher", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load frozen training plans")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def binomial_cdf(successes: int, total: int, probability: float) -> float:
    return sum(
        math.comb(total, value)
        * (probability**value)
        * ((1.0 - probability) ** (total - value))
        for value in range(successes + 1)
    )


def clopper_pearson_interval(
    successes: int, total: int, alpha: float = 0.05
) -> list[float]:
    if total <= 0 or successes < 0 or successes > total:
        raise ValueError("exact binomial interval requires 0 <= successes <= total")
    if successes == 0:
        lower = 0.0
    else:
        lo, hi = 0.0, successes / total
        for _ in range(80):
            mid = (lo + hi) / 2.0
            upper_tail = 1.0 - binomial_cdf(successes - 1, total, mid)
            if upper_tail < alpha / 2.0:
                lo = mid
            else:
                hi = mid
        lower = (lo + hi) / 2.0
    if successes == total:
        upper = 1.0
    else:
        lo, hi = successes / total, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if binomial_cdf(successes, total, mid) > alpha / 2.0:
                lo = mid
            else:
                hi = mid
        upper = (lo + hi) / 2.0
    return [round(lower, 6), round(upper, 6)]


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def load_structural_reports(
    reports_dir: Path,
    *,
    terminal_step: int,
    shared_base_reports_dir: Path | None = None,
) -> dict[tuple[str, str, int, int], dict[str, Any]]:
    cells: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    paths = [(path, False) for path in sorted(reports_dir.rglob("structure_report.json"))]
    if shared_base_reports_dir is not None:
        paths.extend(
            (path, True) for path in sorted(shared_base_reports_dir.rglob("structure_report.json"))
        )
    for path, shared_base_only in paths:
        report = read_json(path)
        if report.get("status") != "complete" or not report.get("complete"):
            raise RuntimeError(f"incomplete structural report: {path}")
        generation = report["contract"]
        source_contract_path = path.with_name("generation_contract.json")
        if source_contract_path.exists():
            source = read_json(source_contract_path)
        else:
            source = None
            generation_report_path = path.with_name("generation_report.json")
            if generation_report_path.exists():
                source = read_json(generation_report_path).get("contract")
        if source is None:
            run_key = str(generation["generation_run_key"])
            candidates = list(reports_dir.rglob(f"{run_key}/generation_contract.json"))
            if len(candidates) == 1:
                source = read_json(candidates[0])
        if source is None:
            raise RuntimeError(f"missing generation contract for {path}")
        step = int(source["checkpoint_step"])
        if shared_base_only and source.get("arm") != "base":
            continue
        key = (
            str(source["model"]), str(source["arm"]),
            int(source["training_seed"]), step,
        )
        if key in cells:
            raise RuntimeError(f"duplicate terminal structural cell {key}")
        cells[key] = {"path": str(path), "source": source, "report": report}
    return cells


def validate_matrix(
    cells: dict[tuple[str, str, int, int], dict[str, Any]],
    training: dict[str, Any],
    *,
    config: dict[str, Any],
    config_path: Path,
    base_config: dict[str, Any],
    base_config_path: Path,
    structural_manifest: dict[str, Any],
) -> None:
    models = [str(row["model"]) for row in training["models"]]
    seeds = [int(value) for value in training["training_seeds"]]
    steps = sorted(
        set(int(value) for value in config["checkpoints"]["primary"] if int(value) != 0)
        | set(int(value) for value in config["checkpoints"]["secondary_timecourse"])
    )
    required = {(model, "base", 0, 0) for model in models}
    required |= {
        (model, arm, seed, step)
        for model in models
        for arm in ("true", "shuffled")
        for seed in seeds
        for step in steps
    }
    missing = sorted(required - set(cells))
    unexpected = sorted(set(cells) - required)
    if missing or unexpected:
        raise RuntimeError(f"terminal structural matrix mismatch: missing={missing}, unexpected={unexpected}")
    launcher = load_launcher()
    manifest = read_json(repo_path(training["dataset_manifest"]))
    core_plan = launcher.build_plan(training, manifest, "core")
    expected_training = {
        (row["model"], row["arm"], int(row["training_seed"])): row for row in core_plan["runs"]
    }
    cohort_label = "replication" if config.get("shared_base_config") else "original"
    expected_jobs = {
        (
            row["model"], row["arm"], int(row["training_seed"]), int(row["checkpoint_step"])
        ): row
        for row in structural_manifest["jobs"]
        if row["campaign"] in {"shared_base", cohort_label}
    }
    for key, cell in cells.items():
        source = cell["source"]
        fold = cell["report"]["contract"]
        manifest_job = expected_jobs.get(
            (source["model"], source["arm"], int(source["training_seed"]), int(source["checkpoint_step"]))
        )
        if manifest_job is None:
            raise RuntimeError("structural cell is absent from the frozen structural manifest")
        unsigned_job = {
            name: value
            for name, value in manifest_job.items()
            if name not in {"structural_job_sha", "job_key"}
        }
        if manifest_job.get("structural_job_sha") != sha256_value(unsigned_job):
            raise RuntimeError("structural manifest contains a corrupt job")
        source_unsigned = {
            name: value
            for name, value in source.items()
            if name not in {"generation_contract_sha", "run_key"}
        }
        if source.get("generation_contract_sha") != sha256_value(source_unsigned):
            raise RuntimeError("generation contract self-hash mismatch")
        expected_source_fields = {
            "model": manifest_job["model"],
            "model_tag": manifest_job["model_tag"],
            "arm": manifest_job["arm"],
            "training_seed": manifest_job["training_seed"],
            "checkpoint_step": manifest_job["checkpoint_step"],
            "checkpoint_path": manifest_job["checkpoint_path"],
        }
        if any(source.get(name) != value for name, value in expected_source_fields.items()):
            raise RuntimeError("generation contract differs from its exact structural manifest job")
        if source.get("arm") == "base":
            if (
                source.get("campaign_id") != base_config["campaign_id"]
                or source.get("structural_config_sha256") != sha256_file(base_config_path)
                or source.get("source_training") is not None
            ):
                raise RuntimeError("base structural cell is not the exact frozen shared base")
        else:
            expected = expected_training.get(key[:3])
            source_training = source.get("source_training") or {}
            if (
                source.get("campaign_id") != config["campaign_id"]
                or source.get("structural_config_sha256") != sha256_file(config_path)
                or expected is None
                or source_training.get("source_run_key") != expected["run_key"]
                or source_training.get("source_run_contract_sha") != expected["run_contract_sha"]
                or int(expected["rank"]) != 32
            ):
                raise RuntimeError("trained structural cell is not bound to the frozen rank-32 core")
            manifest_source = manifest_job["source_training"]
            file_bindings = {
                "source_run_contract_file_sha256": "run_contract_file_sha256",
                "source_training_report_file_sha256": "training_report_file_sha256",
                "source_checkpoint_lineage_file_sha256": "checkpoint_lineage_file_sha256",
            }
            if any(
                source_training.get(source_key) != manifest_source[manifest_key]
                for source_key, manifest_key in file_bindings.items()
            ):
                raise RuntimeError("structural generation source files differ from audited training evidence")
        expected_config = base_config if source.get("arm") == "base" else config
        expected_config_path = base_config_path if source.get("arm") == "base" else config_path
        gate = expected_config["structure_gate"]
        expected_fold = {
            "campaign_id": expected_config["campaign_id"],
            "structural_contract": expected_config["contract"],
            "structural_config_sha256": sha256_file(expected_config_path),
            "generation_contract_sha": source["generation_contract_sha"],
            "generation_run_key": source["run_key"],
            "expected_candidate_count": 96,
            "backend": gate["backend"],
            "model_name": gate["model_name"],
            "model_revision": gate["model_revision"],
            "transformers_version": gate["transformers_version"],
            "torch_version": gate["torch_version"],
            "plddt_gate": gate["plddt_gate"],
            "triad_hbond_max_angstrom": gate["triad_hbond_max_angstrom"],
            "required_triad_method": gate["required_triad_method"],
            "calibration_sha256": sha256_file(repo_path(gate["calibration"])),
            "evaluator_sha256": sha256_file(ROOT / "scripts/run_scaling_paradox_structure.py"),
            "structure_gate_library_sha256": sha256_file(ROOT / "src/pearl/structure_gate.py"),
        }
        expected_fold["fold_contract_sha"] = sha256_value(expected_fold)
        if (
            source.get("prompt_panel_sha256")
            != sha256_file(repo_path(expected_config["prompt_panel"]))
            or source.get("sampling") != expected_config["sampling"]
            or fold != expected_fold
        ):
            raise RuntimeError("fold contract differs from the frozen structural contract")
        results = cell["report"].get("results", [])
        if (
            len(results) != 96
            or int(cell["report"].get("full_structural_gate_passes", -1))
            != sum(bool(row.get("full_structural_gate_pass")) for row in results)
        ):
            raise RuntimeError("structure report result list/count is inconsistent")


def summarize_cell(cell: dict[str, Any]) -> dict[str, Any]:
    report = cell["report"]
    total = int(report["expected_candidate_count"])
    completed = int(report["completed_candidate_count"])
    if completed != total:
        raise RuntimeError(f"cell is not fully observed: {cell['path']}")
    passes = int(report["full_structural_gate_passes"])
    results = report.get("results", [])
    if len(results) != total or passes != sum(
        bool(row.get("full_structural_gate_pass")) for row in results
    ):
        raise RuntimeError(f"cell result list/pass count is inconsistent: {cell['path']}")
    return {
        "model": cell["source"]["model"],
        "arm": cell["source"]["arm"],
        "training_seed": int(cell["source"]["training_seed"]),
        "checkpoint_step": int(cell["source"]["checkpoint_step"]),
        "attempts": total,
        "passes": passes,
        "yield": passes / total,
        "yield_exact_binomial_95ci": clopper_pearson_interval(passes, total),
        "invalid_generations": sum(not bool(row.get("valid_generation")) for row in results),
        "duplicate_generations": sum(bool(row.get("duplicate_sequence")) for row in results),
        "source_report": cell["path"],
        "source_report_sha256": sha256_file(Path(cell["path"])),
    }


def hierarchical_seed_bootstrap(
    contrasts: list[dict[str, Any]], *, seeds: list[int], samples: int = 10_000, seed: int = 20260811
) -> dict[str, Any]:
    rng = random.Random(seed)
    by_model: dict[str, dict[int, float]] = {}
    for row in contrasts:
        by_model.setdefault(str(row["model"]), {})[int(row["training_seed"])] = float(row["delta"])
    draws: list[float] = []
    for _ in range(samples):
        model_means: list[float] = []
        for model in sorted(by_model):
            sampled_seeds = rng.choices(seeds, k=len(seeds))
            model_means.append(statistics.fmean(by_model[model][value] for value in sampled_seeds))
        draws.append(statistics.fmean(model_means))
    observed = statistics.fmean(row["delta"] for row in contrasts)
    return {
        "mean_delta": observed,
        "hierarchical_seed_bootstrap_95ci": [percentile(draws, 0.025), percentile(draws, 0.975)],
        "bootstrap_samples": samples,
        "bootstrap_seed": seed,
    }


def seed_mean_interval(values: list[float]) -> dict[str, Any]:
    if not values:
        raise RuntimeError("cannot summarize an empty seed-level contrast")
    mean = statistics.fmean(values)
    critical = {3: 4.3026527297, 6: 2.5705818356}.get(len(values), 1.9599639845)
    half = critical * statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {
        "n_training_seeds": len(values),
        "mean": mean,
        "mean_t_95ci": [mean - half, mean + half],
        "positive_seed_count": sum(value > 0.0 for value in values),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--reports-dir", default=str(ROOT / "reports" / "frontier_adaptation_v2_original" / "structural"))
    parser.add_argument("--shared-base-reports-dir")
    parser.add_argument("--structural-manifest", required=True)
    parser.add_argument("--output", default=str(ROOT / "reports" / "frontier_adaptation_v2_original" / "structural_analysis.json"))
    args = parser.parse_args()
    config_path = repo_path(args.config)
    config = read_json(config_path)
    training = read_json(repo_path(config["training_config"]))
    base_config_path = repo_path(config.get("shared_base_config", args.config))
    base_config = read_json(base_config_path)
    structural_manifest = read_json(repo_path(args.structural_manifest))
    if structural_manifest.get("contract") != "pearl.frontier-adaptation-structural-manifest/2":
        raise RuntimeError("structural analysis requires the frozen structural manifest")
    if structural_manifest.get("structural_manifest_sha") != sha256_value(
        {
            key: value
            for key, value in structural_manifest.items()
            if key != "structural_manifest_sha"
        }
    ):
        raise RuntimeError("structural manifest self-hash mismatch")
    if structural_manifest.get("prompt_panel_sha256") != sha256_file(
        repo_path(config["prompt_panel"])
    ):
        raise RuntimeError("structural manifest has the wrong prompt panel")
    terminal_step = max(int(value) for value in config["checkpoints"]["primary"])
    cells = load_structural_reports(
        repo_path(args.reports_dir),
        terminal_step=terminal_step,
        shared_base_reports_dir=(
            repo_path(args.shared_base_reports_dir) if args.shared_base_reports_dir else None
        ),
    )
    if config.get("shared_base_config") and not args.shared_base_reports_dir:
        raise RuntimeError("replication structural analysis requires the exact shared original base reports")
    validate_matrix(
        cells,
        training,
        config=config,
        config_path=config_path,
        base_config=base_config,
        base_config_path=base_config_path,
        structural_manifest=structural_manifest,
    )
    summaries = [summarize_cell(cells[key]) for key in sorted(cells)]
    index = {
        (row["model"], row["arm"], row["training_seed"], row["checkpoint_step"]): row
        for row in summaries
    }
    seeds = [int(value) for value in training["training_seeds"]]
    contrasts: list[dict[str, Any]] = []
    for model in [str(row["model"]) for row in training["models"]]:
        base = index[(model, "base", 0, 0)]["yield"]
        for seed in seeds:
            true_yield = index[(model, "true", seed, terminal_step)]["yield"]
            shuffled_yield = index[(model, "shuffled", seed, terminal_step)]["yield"]
            contrasts.extend(
                [
                    {"model": model, "training_seed": seed, "contrast": "true_minus_base", "delta": true_yield - base},
                    {"model": model, "training_seed": seed, "contrast": "shuffled_minus_base", "delta": shuffled_yield - base},
                    {"model": model, "training_seed": seed, "contrast": "true_minus_shuffled", "delta": true_yield - shuffled_yield},
                ]
            )
    inference = {
        model["tag"]: {
            name: seed_mean_interval(
                [
                    float(row["delta"])
                    for row in contrasts
                    if row["model"] == model["model"] and row["contrast"] == name
                ]
            )
            for name in ("true_minus_base", "shuffled_minus_base", "true_minus_shuffled")
        }
        for model in training["models"]
    }
    true_shuffled = {
        (row["model"], int(row["training_seed"])): float(row["delta"])
        for row in contrasts
        if row["contrast"] == "true_minus_shuffled"
    }
    tags = {str(row["tag"]): str(row["model"]) for row in training["models"]}
    executor = read_json(ROOT / "configs/experiments/frontier_adaptation_v2_executor.json")
    capacity_contrasts: dict[str, Any] = {}
    for small, large in executor["analysis_contract"]["primary_pairs"]:
        values = [
            true_shuffled[(tags[small], seed)] - true_shuffled[(tags[large], seed)]
            for seed in seeds
        ]
        capacity_contrasts[f"{small}_minus_{large}"] = {
            "direction": "positive_means_smaller_model_has_larger_true_minus_shuffled_structural_yield",
            "seed_level": [
                {"training_seed": seed, "value": value}
                for seed, value in zip(seeds, values, strict=True)
            ],
            "summary": seed_mean_interval(values),
        }
    release_controls: dict[str, Any] = {}
    for older, newer in executor["analysis_contract"]["release_controls"]:
        values = [
            true_shuffled[(tags[newer], seed)] - true_shuffled[(tags[older], seed)]
            for seed in seeds
        ]
        release_controls[f"{newer}_minus_{older}"] = {
            "direction": "positive_means_new_release_has_larger_effect_at_matched_capacity",
            "seed_level": [
                {"training_seed": seed, "value": value}
                for seed, value in zip(seeds, values, strict=True)
            ],
            "summary": seed_mean_interval(values),
        }
    trajectory_steps = sorted(
        set(int(value) for value in config["checkpoints"]["secondary_timecourse"])
        | {terminal_step}
    )
    trajectory: list[dict[str, Any]] = []
    for model in [str(row["model"]) for row in training["models"]]:
        base = index[(model, "base", 0, 0)]["yield"]
        for seed in seeds:
            for step in trajectory_steps:
                true_yield = index[(model, "true", seed, step)]["yield"]
                shuffled_yield = index[(model, "shuffled", seed, step)]["yield"]
                trajectory.append(
                    {
                        "model": model,
                        "training_seed": seed,
                        "checkpoint_step": step,
                        "true_yield": true_yield,
                        "shuffled_yield": shuffled_yield,
                        "true_minus_base": true_yield - base,
                        "shuffled_minus_base": shuffled_yield - base,
                        "true_minus_shuffled": true_yield - shuffled_yield,
                    }
                )
    payload = {
        "contract": "pearl.frontier-adaptation-structural-analysis/2",
        "campaign_id": config["campaign_id"],
        "structural_config_sha256": sha256_file(config_path),
        "core_plan_sha": load_launcher().build_plan(
            training,
            read_json(repo_path(training["dataset_manifest"])),
            "core",
        )["launch_plan_contract_sha"],
        "shared_base_report_sha256s": sorted(
            row["source_report_sha256"] for row in summaries if row["arm"] == "base"
        ),
        "analysis_unit": config["analysis"]["experimental_unit"],
        "candidate_observations_are_nested": True,
        "matrix_complete": True,
        "structural_manifest_sha": structural_manifest["structural_manifest_sha"],
        "cells": summaries,
        "seed_level_contrasts": contrasts,
        "inference": inference,
        "capacity_contrasts": capacity_contrasts,
        "matched_capacity_release_controls": release_controls,
        "model_families_are_not_pooled": True,
        "secondary_checkpoint_trajectory": {
            "checkpoint_steps": trajectory_steps,
            "seed_level": trajectory,
            "estimand": "full_gate_yield_by_frozen_checkpoint_with_matched_true_minus_shuffled_and_base_contrasts",
        },
    }
    output = repo_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "cells"}, indent=2))


if __name__ == "__main__":
    main()
