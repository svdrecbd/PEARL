from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.finalize_ablation_from_candidate_audit import finalize_ablation_dir
from scripts.run_robustness_suite import (
    build_frozen_prompt_sets,
    build_run_name,
    load_jsonl,
    parse_float_list,
    parse_int_list,
    resolve_python_executable,
    sanitize_name,
)


RUN_ABLATION = ROOT / "scripts" / "run_ablation.py"
RUN_ROBUSTNESS_SUITE = ROOT / "scripts" / "run_robustness_suite.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a two-phase robustness suite: stockpile first, H100 rescore second")
    parser.add_argument("--name", required=True)
    parser.add_argument("--init-state-path", required=True)
    parser.add_argument("--model", default="moonshotai/Kimi-K2.5")
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
    parser.add_argument("--plddt-gate-threshold", type=float, default=85.0)
    parser.add_argument("--second-stage-esm-weight", type=float, default=0.2)
    parser.add_argument("--second-stage-motif-weight", type=float, default=0.2)
    parser.add_argument("--second-stage-geometry-weight", type=float, default=0.6)
    parser.add_argument("--second-stage-template-weight", type=float, default=0.15)
    parser.add_argument("--prompt-suite-seed", type=int, default=1337)
    parser.add_argument("--api-key")
    parser.add_argument("--esm2-device", default=os.environ.get("ESM2_DEVICE", "cuda"))
    parser.add_argument("--stockpile-jobs", type=int, default=4)
    parser.add_argument("--stockpile-retries", type=int, default=2)
    parser.add_argument("--baseline-summary-path")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", action="store_false", dest="skip_existing")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    python_executable = resolve_python_executable()
    suite_name = sanitize_name(args.name)
    suite_dir = Path(args.output_dir) / suite_name
    frozen_prompts_dir = suite_dir / "frozen_prompts"
    frozen_prompts_dir.mkdir(parents=True, exist_ok=True)

    suite_sizes = parse_int_list(args.suite_sizes)
    temperatures = parse_float_list(args.temperatures)
    seeds = parse_int_list(args.seeds)
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
                run_dir = Path(args.ablation_output_dir) / sanitize_name(run_name)
                runs.append(
                    {
                        "run_name": run_name,
                        "run_dir": run_dir,
                        "prompts_path": prompts_path,
                        "prompt_count": prompt_count,
                        "temperature": temperature,
                        "seed": seed,
                    }
                )

    print(
        json.dumps(
            {
                "event": "stockpile_start",
                "suite_name": suite_name,
                "run_count": len(runs),
                "suite_sizes": suite_sizes,
                "temperatures": temperatures,
                "seeds": seeds,
                "stockpile_jobs": args.stockpile_jobs,
                "stockpile_retries": args.stockpile_retries,
            }
        ),
        flush=True,
    )

    finalized_runs: list[dict[str, Any]] = []
    pending_runs = [{**run, "attempt": 1} for run in runs]
    active_runs: dict[str, dict[str, Any]] = {}
    print(json.dumps({"event": "finalize_start", "suite_name": suite_name}), flush=True)
    while pending_runs or active_runs:
        while pending_runs and len(active_runs) < max(1, args.stockpile_jobs):
            run = pending_runs.pop(0)
            launched = launch_stage1_stockpile(
                python_executable=python_executable,
                run_name=run["run_name"],
                prompts_path=Path(run["prompts_path"]),
                prompt_count=int(run["prompt_count"]),
                temperature=float(run["temperature"]),
                seed=int(run["seed"]),
                variant=args.variant,
                model=args.model,
                reference_records_path=Path(args.reference_records_path),
                output_dir=Path(args.ablation_output_dir),
                candidate_sample_count=args.candidate_sample_count,
                second_stage_top_k=args.second_stage_top_k,
                plddt_gate_threshold=args.plddt_gate_threshold,
                second_stage_esm_weight=args.second_stage_esm_weight,
                second_stage_motif_weight=args.second_stage_motif_weight,
                second_stage_geometry_weight=args.second_stage_geometry_weight,
                second_stage_template_weight=args.second_stage_template_weight,
                init_state_path=args.init_state_path,
                api_key=args.api_key,
                skip_existing=args.skip_existing,
                attempt=int(run["attempt"]),
            )
            if launched is None:
                result = finalize_ablation_dir(
                    ablation_dir=Path(run["run_dir"]),
                    esm2_device=args.esm2_device,
                    skip_finalized=args.skip_existing,
                )
                finalized_runs.append(result)
                print(json.dumps({"event": "finalize_run", **result}), flush=True)
                continue
            active_runs[run["run_name"]] = {
                "run": run,
                "process": launched["process"],
                "log_handle": launched["log_handle"],
                "stage1_log_path": launched["stage1_log_path"],
            }

        completed_run_names: list[str] = []
        for run_name, active in active_runs.items():
            process = active["process"]
            return_code = process.poll()
            if return_code is None:
                continue
            if active["log_handle"] is not None:
                active["log_handle"].close()
            if return_code != 0:
                attempt = int(active["run"]["attempt"])
                print(
                    json.dumps(
                        {
                            "event": "stockpile_failed",
                            "run_name": run_name,
                            "attempt": attempt,
                            "return_code": return_code,
                            "stage1_log_path": active["stage1_log_path"],
                        }
                    ),
                    flush=True,
                )
                if attempt < max(1, args.stockpile_retries):
                    retry_run = dict(active["run"])
                    retry_run["attempt"] = attempt + 1
                    pending_runs.insert(0, retry_run)
                    print(
                        json.dumps(
                            {
                                "event": "stockpile_retry_scheduled",
                                "run_name": run_name,
                                "next_attempt": retry_run["attempt"],
                            }
                        ),
                        flush=True,
                    )
                    completed_run_names.append(run_name)
                    continue
                raise subprocess.CalledProcessError(return_code, process.args)
            print(
                json.dumps(
                    {
                        "event": "stockpile_complete",
                        "run_name": run_name,
                        "attempt": int(active["run"]["attempt"]),
                        "stage1_log_path": active["stage1_log_path"],
                    }
                ),
                flush=True,
            )
            result = finalize_ablation_dir(
                ablation_dir=Path(active["run"]["run_dir"]),
                esm2_device=args.esm2_device,
                skip_finalized=args.skip_existing,
            )
            finalized_runs.append(result)
            print(json.dumps({"event": "finalize_run", **result}), flush=True)
            completed_run_names.append(run_name)

        for run_name in completed_run_names:
            active_runs.pop(run_name, None)

        if active_runs and not completed_run_names:
            time.sleep(5)

    run_summary_only(
        python_executable=python_executable,
        args=args,
    )

    print(
        json.dumps(
            {
                "event": "suite_complete",
                "suite_name": suite_name,
                "robustness_summary_path": str(Path(args.output_dir) / suite_name / "robustness_summary.json"),
                "runs_manifest_path": str(Path(args.output_dir) / suite_name / "runs_manifest.json"),
                "finalized_run_count": len(finalized_runs),
            }
        ),
        flush=True,
    )


def stage1_stockpile_complete(run_dir: Path) -> bool:
    metadata_path = run_dir / "metadata.json"
    candidate_audit_path = run_dir / "candidate_audit.json"
    report_path = run_dir / "report.json"
    if not (metadata_path.exists() and candidate_audit_path.exists() and report_path.exists()):
        return False
    try:
        report = json.loads(report_path.read_text())
    except json.JSONDecodeError:
        return False
    return report.get("summary") is not None


def launch_stage1_stockpile(
    *,
    python_executable: str,
    run_name: str,
    prompts_path: Path,
    prompt_count: int,
    temperature: float,
    seed: int,
    variant: str,
    model: str,
    reference_records_path: Path,
    output_dir: Path,
    candidate_sample_count: int,
    second_stage_top_k: int,
    plddt_gate_threshold: float,
    second_stage_esm_weight: float,
    second_stage_motif_weight: float,
    second_stage_geometry_weight: float,
    second_stage_template_weight: float,
    init_state_path: str,
    api_key: str | None,
    skip_existing: bool,
    attempt: int,
) -> dict[str, Any] | None:
    run_dir = output_dir / sanitize_name(run_name)
    run_dir.mkdir(parents=True, exist_ok=True)
    stage1_log_path = run_dir / "stage1.log"
    if skip_existing and stage1_stockpile_complete(run_dir):
        print(
            json.dumps(
                {
                    "event": "stockpile_skip",
                    "run_name": run_name,
                    "reason": "completed_stage1_stockpile",
                    "attempt": attempt,
                    "stage1_log_path": str(stage1_log_path),
                }
            ),
            flush=True,
        )
        return None

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
        "--plddt-gate-threshold",
        str(plddt_gate_threshold),
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
        "--stage1-only",
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
    env["PYTHONUNBUFFERED"] = "1"

    print(
        json.dumps(
            {
                "event": "stockpile_run",
                "run_name": run_name,
                "prompt_count": prompt_count,
                "temperature": temperature,
                "seed": seed,
                "attempt": attempt,
                "stage1_log_path": str(stage1_log_path),
            }
        ),
        flush=True,
    )
    log_handle = stage1_log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return {
        "process": process,
        "log_handle": log_handle,
        "stage1_log_path": str(stage1_log_path),
    }


def run_summary_only(*, python_executable: str, args: argparse.Namespace) -> None:
    command = [
        python_executable,
        str(RUN_ROBUSTNESS_SUITE),
        "--name",
        args.name,
        "--init-state-path",
        args.init_state_path,
        "--model",
        args.model,
        "--variant",
        args.variant,
        "--prompts-path",
        args.prompts_path,
        "--reference-records-path",
        args.reference_records_path,
        "--output-dir",
        args.output_dir,
        "--ablation-output-dir",
        args.ablation_output_dir,
        "--suite-sizes",
        args.suite_sizes,
        "--temperatures",
        args.temperatures,
        "--seeds",
        args.seeds,
        "--candidate-sample-count",
        str(args.candidate_sample_count),
        "--second-stage-top-k",
        str(args.second_stage_top_k),
        "--plddt-gate-threshold",
        str(args.plddt_gate_threshold),
        "--second-stage-esm-weight",
        str(args.second_stage_esm_weight),
        "--second-stage-motif-weight",
        str(args.second_stage_motif_weight),
        "--second-stage-geometry-weight",
        str(args.second_stage_geometry_weight),
        "--second-stage-template-weight",
        str(args.second_stage_template_weight),
        "--prompt-suite-seed",
        str(args.prompt_suite_seed),
        "--esm2-device",
        args.esm2_device,
        "--summary-only",
    ]
    if args.baseline_summary_path:
        command.extend(["--baseline-summary-path", args.baseline_summary_path])
    print(json.dumps({"event": "summary_only_start", "command": command}), flush=True)
    subprocess.run(command, check=True, cwd=ROOT, env=os.environ.copy())


if __name__ == "__main__":
    main()
