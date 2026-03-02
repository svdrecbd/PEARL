from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RUN_ABLATION = ROOT / "scripts" / "run_ablation.py"


def main() -> None:
    args = parse_args()
    python_executable = args.python_bin or sys.executable
    temperatures = [float(part.strip()) for part in args.temperatures.split(",") if part.strip()]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_summaries: list[dict[str, Any]] = []
    for temperature in temperatures:
        run_name = (
            f"{args.name_prefix}-t{format_temperature(temperature)}"
            f"-c{args.candidate_sample_count}"
            f"-p{args.prompt_count}"
        )
        run_path = output_dir / sanitize_name(run_name)
        if args.skip_existing and (run_path / "summary.json").exists() and (run_path / "candidate_audit.json").exists():
            summary = load_json(run_path / "summary.json")
            raw_metrics = compute_raw_pool_metrics(load_json(run_path / "candidate_audit.json"))
            run_summaries.append(
                {
                    "name": run_name,
                    "temperature": temperature,
                    "path": str(run_path),
                    "summary": summary,
                    "raw_pool": raw_metrics,
                    "skipped_existing": True,
                }
            )
            if args.stop_on_unicorn and raw_metrics["single_motif_geometry_esm_gate"] > 0:
                break
            continue

        env = os.environ.copy()
        env.update(
            {
                "SAMPLING_TEMPERATURE": str(temperature),
                "SAMPLING_TOP_P": str(args.top_p),
                "SAMPLING_TOP_K": str(args.top_k),
                "ESM2_BACKEND": args.esm2_backend,
                "ESM2_BATCH_SIZE": str(args.esm2_batch_size),
                "ESM2_SCORE_CACHE_SIZE": str(args.esm2_score_cache_size),
                "ESM2_DEVICE": args.esm2_device,
            }
        )
        if args.api_key:
            env["TINKER_API_KEY"] = args.api_key
        if args.tinker_python_bin:
            env["TINKER_PYTHON_BIN"] = args.tinker_python_bin

        command = [
            python_executable,
            str(RUN_ABLATION),
            "--name",
            run_name,
            "--variant",
            args.variant,
            "--model",
            args.model,
            "--prompts-path",
            args.prompts_path,
            "--reference-records-path",
            args.reference_records_path,
            "--prompt-count",
            str(args.prompt_count),
            "--candidate-sample-count",
            str(args.candidate_sample_count),
            "--second-stage-top-k",
            str(args.second_stage_top_k),
            "--plddt-gate-threshold",
            str(args.plddt_gate_threshold),
            "--output-dir",
            str(output_dir),
            "--capture-candidate-audit",
            "--eval-only",
            "--preserve-order",
        ]
        subprocess.run(command, check=True, cwd=ROOT, env=env)

        summary = load_json(run_path / "summary.json")
        raw_metrics = compute_raw_pool_metrics(load_json(run_path / "candidate_audit.json"))
        run_summaries.append(
            {
                "name": run_name,
                "temperature": temperature,
                "path": str(run_path),
                "summary": summary,
                "raw_pool": raw_metrics,
                "skipped_existing": False,
            }
        )
        if args.stop_on_unicorn and raw_metrics["single_motif_geometry_esm_gate"] > 0:
            break

    aggregate = {
        "name_prefix": args.name_prefix,
        "model": args.model,
        "prompts_path": args.prompts_path,
        "reference_records_path": args.reference_records_path,
        "prompt_count": args.prompt_count,
        "candidate_sample_count": args.candidate_sample_count,
        "temperatures": temperatures,
        "top_p": args.top_p,
        "top_k": args.top_k,
        "esm2_backend": args.esm2_backend,
        "esm2_batch_size": args.esm2_batch_size,
        "esm2_score_cache_size": args.esm2_score_cache_size,
        "esm2_device": args.esm2_device,
        "second_stage_top_k": args.second_stage_top_k,
        "plddt_gate_threshold": args.plddt_gate_threshold,
        "runs": run_summaries,
    }
    aggregate_path = output_dir / f"{sanitize_name(args.name_prefix)}-aggregate-summary.json"
    aggregate_path.write_text(json.dumps(aggregate, indent=2), encoding="utf-8")
    print(json.dumps(aggregate, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run stratified zero-shot Kimi search across multiple temperatures")
    parser.add_argument("--name-prefix", required=True)
    parser.add_argument("--model", default="moonshotai/Kimi-K2.5")
    parser.add_argument("--variant", default="motif_prior_soft_v2")
    parser.add_argument("--prompts-path", required=True)
    parser.add_argument("--reference-records-path", required=True)
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "ablations"))
    parser.add_argument("--prompt-count", type=int, default=100)
    parser.add_argument("--candidate-sample-count", type=int, default=256)
    parser.add_argument("--second-stage-top-k", type=int, default=8)
    parser.add_argument("--plddt-gate-threshold", type=float, default=85.0)
    parser.add_argument("--temperatures", default="0.7,0.85,1.0")
    parser.add_argument("--top-p", type=float, default=0.98)
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--esm2-backend", default="torch")
    parser.add_argument("--esm2-batch-size", type=int, default=64)
    parser.add_argument("--esm2-score-cache-size", type=int, default=8192)
    parser.add_argument("--esm2-device", default="mps")
    parser.add_argument("--stop-on-unicorn", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--api-key")
    parser.add_argument("--python-bin")
    parser.add_argument("--tinker-python-bin")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compute_raw_pool_metrics(candidate_audit: dict[str, Any]) -> dict[str, int]:
    counts = {
        "candidate_count": 0,
        "single_motif_count": 0,
        "single_motif_trainable": 0,
        "single_motif_esm_gate": 0,
        "geometry_count": 0,
        "single_motif_geometry_count": 0,
        "single_motif_geometry_trainable": 0,
        "single_motif_geometry_esm_gate": 0,
    }
    for record in candidate_audit["records"]:
        for candidate in record["candidates"]:
            counts["candidate_count"] += 1
            motif_count = int(candidate.get("motif_count") or 0)
            geometry_passes = bool(candidate.get("geometry_passes"))
            hard_gate_pass = bool(candidate.get("hard_gate_pass"))
            esm_gate_pass = bool(candidate.get("esm_gate_pass"))
            if motif_count == 1:
                counts["single_motif_count"] += 1
                if hard_gate_pass:
                    counts["single_motif_trainable"] += 1
                if esm_gate_pass:
                    counts["single_motif_esm_gate"] += 1
            if geometry_passes:
                counts["geometry_count"] += 1
            if motif_count == 1 and geometry_passes:
                counts["single_motif_geometry_count"] += 1
                if hard_gate_pass:
                    counts["single_motif_geometry_trainable"] += 1
                if esm_gate_pass:
                    counts["single_motif_geometry_esm_gate"] += 1
    return counts


def sanitize_name(value: str) -> str:
    chars = []
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("-")
    sanitized = "".join(chars).strip("-")
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized or "run"


def format_temperature(value: float) -> str:
    return str(value).replace(".", "p")


if __name__ == "__main__":
    main()
