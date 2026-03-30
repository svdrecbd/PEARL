from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    args = parse_args()
    python_executable = resolve_python_executable()
    output_dir = Path(args.output_dir) / sanitize_name(args.name)
    output_dir.mkdir(parents=True, exist_ok=True)

    subset_path = output_dir / "prompt_subset.jsonl"
    metadata_path = output_dir / "metadata.json"
    report_path = output_dir / "report.json"
    summary_path = output_dir / "summary.json"
    candidate_audit_path = output_dir / "candidate_audit.json" if args.capture_candidate_audit else None

    subset_rows = build_prompt_subset(
        source_path=Path(args.prompts_path),
        count=args.prompt_count,
        seed=args.seed,
        preserve_order=args.preserve_order,
    )
    write_jsonl(subset_path, subset_rows)

    metadata = {
        "name": args.name,
        "variant": args.variant,
        "model": args.model,
        "python_executable": python_executable,
        "init_state_path": args.init_state_path,
        "eval_only": args.eval_only,
        "stage1_only": args.stage1_only,
        "resume": args.resume,
        "prompt_count": args.prompt_count,
        "candidate_sample_count": args.candidate_sample_count,
        "second_stage_esm_weight": args.second_stage_esm_weight,
        "second_stage_motif_weight": args.second_stage_motif_weight,
        "second_stage_geometry_weight": args.second_stage_geometry_weight,
        "second_stage_template_weight": args.second_stage_template_weight,
        "seed": args.seed,
        "sampling_seed_base": args.seed,
        "source_prompts_path": args.prompts_path,
        "reference_records_path": args.reference_records_path,
        "subset_path": str(subset_path),
        "report_path": str(report_path),
        "summary_path": str(summary_path),
        "candidate_audit_path": str(candidate_audit_path) if candidate_audit_path is not None else None,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "PROMPTS_PATH": str(subset_path),
            "REFERENCE_RECORDS_PATH": args.reference_records_path,
            "DRY_RUN_PROMPT_COUNT": str(args.prompt_count),
            "TINKER_CANDIDATE_SAMPLE_COUNT": str(args.candidate_sample_count),
            "TINKER_BASE_MODEL": args.model,
            "PROMPT_VARIANT": args.variant,
            "CHECKPOINT_NAME": sanitize_name(args.name),
            "REPORT_PATH": str(report_path),
            "TINKER_SECOND_STAGE_TOP_K": str(args.second_stage_top_k),
            "TINKER_PLDDT_GATE_THRESHOLD": str(args.plddt_gate_threshold),
            "TINKER_SECOND_STAGE_ESM_WEIGHT": str(args.second_stage_esm_weight),
            "TINKER_SECOND_STAGE_MOTIF_WEIGHT": str(args.second_stage_motif_weight),
            "TINKER_SECOND_STAGE_GEOMETRY_WEIGHT": str(args.second_stage_geometry_weight),
            "TINKER_SECOND_STAGE_TEMPLATE_WEIGHT": str(args.second_stage_template_weight),
            "TINKER_SAMPLING_SEED": str(args.seed),
        }
    )
    if args.init_state_path:
        env["TINKER_INIT_STATE_PATH"] = args.init_state_path
    if args.eval_only:
        env["TINKER_EVAL_ONLY"] = "1"
    if args.stage1_only:
        env["TINKER_SKIP_STAGE2_ESM"] = "1"
    if args.resume:
        env["TINKER_RESUME_PROGRESS"] = "1"
    if candidate_audit_path is not None:
        env["CANDIDATE_AUDIT_PATH"] = str(candidate_audit_path)

    subprocess.run([python_executable, str(ROOT / "main.py")], check=True, env=env, cwd=ROOT)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = summarize_report(report)
    summary["name"] = args.name
    summary["variant"] = args.variant
    summary["model"] = args.model
    summary["init_state_path"] = args.init_state_path
    summary["eval_only"] = args.eval_only
    summary["stage1_only"] = args.stage1_only
    summary["prompt_count"] = args.prompt_count
    summary["candidate_sample_count"] = args.candidate_sample_count
    summary["second_stage_top_k"] = args.second_stage_top_k
    summary["plddt_gate_threshold"] = args.plddt_gate_threshold
    summary["second_stage_esm_weight"] = args.second_stage_esm_weight
    summary["second_stage_motif_weight"] = args.second_stage_motif_weight
    summary["second_stage_geometry_weight"] = args.second_stage_geometry_weight
    summary["second_stage_template_weight"] = args.second_stage_template_weight
    summary["seed"] = args.seed
    summary["subset_path"] = str(subset_path)
    summary["report_path"] = str(report_path)
    summary["candidate_audit_path"] = str(candidate_audit_path) if candidate_audit_path is not None else None
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a reproducible ablation against main.py")
    parser.add_argument("--name", required=True, help="Run name; used for output folder and checkpoint name")
    parser.add_argument(
        "--variant",
        choices=("baseline", "motif_prior_v1", "motif_prior_soft_v2"),
        default="baseline",
        help="Prompt variant to test",
    )
    parser.add_argument("--model", default="Qwen/Qwen3-8B")
    parser.add_argument("--prompts-path", required=True)
    parser.add_argument("--reference-records-path", required=True)
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "ablations"))
    parser.add_argument("--prompt-count", type=int, default=50)
    parser.add_argument("--candidate-sample-count", type=int, default=12)
    parser.add_argument("--second-stage-top-k", type=int, default=4)
    parser.add_argument("--plddt-gate-threshold", type=float, default=85.0)
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
    parser.add_argument("--init-state-path")
    parser.add_argument("--eval-only", action="store_true")
    parser.add_argument("--stage1-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--capture-candidate-audit", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--preserve-order", action="store_true")
    return parser.parse_args()


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


def build_prompt_subset(*, source_path: Path, count: int, seed: int, preserve_order: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with source_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if count > len(rows):
        raise RuntimeError(f"Requested {count} prompts but only found {len(rows)} in {source_path}")
    if preserve_order:
        return rows[:count]
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    return shuffled[:count]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    records = report["records"]
    trainable = [record for record in records if not record["training_skipped"]]
    family_evaluations = [record["family_evaluation"] for record in records if record["family_evaluation"] is not None]

    family_rewards = [record["reward_components"]["family_reward"] for record in records]
    esm_rewards = [record["reward_components"]["esm_reward"] for record in records]
    lengths = [record["sequence_quality"]["length"] for record in records]
    functional_bridge_steps = [
        record["step"]
        for record in records
        if (
            record["sequence_quality"]["motif_count"] == 1
            and bool(record["reward_components"].get("esm_gate_pass"))
            and record["family_evaluation"] is not None
            and bool(record["family_evaluation"]["catalytic_geometry"]["passes"])
        )
    ]
    family_faithful_bridge_steps = [
        record["step"]
        for record in records
        if (
            record["step"] in functional_bridge_steps
            and record["family_evaluation"] is not None
            and bool(record["family_evaluation"]["has_family_serine_motif"])
        )
    ]
    stability_dominant_steps = [
        record["step"]
        for record in records
        if (
            record["family_evaluation"] is not None
            and int(record["sequence_quality"]["motif_count"]) == 1
            and bool(record["reward_components"].get("esm_gate_pass"))
            and not bool(record["family_evaluation"]["catalytic_geometry"]["passes"])
        )
    ]
    geometry_dominant_steps = [
        record["step"]
        for record in records
        if (
            record["family_evaluation"] is not None
            and int(record["sequence_quality"]["motif_count"]) == 1
            and bool(record["family_evaluation"]["catalytic_geometry"]["passes"])
            and not bool(record["reward_components"].get("esm_gate_pass"))
        )
    ]

    return {
        "checkpoint_path": report["checkpoint_path"],
        "init_state_path": report.get("init_state_path"),
        "eval_only": bool(report.get("eval_only")),
        "steps": len(records),
        "trainable_count": len(trainable),
        "trainable_rate": safe_rate(len(trainable), len(records)),
        "average_reward": round(report["average_reward"], 4),
        "average_esm_reward": round(safe_mean(esm_rewards), 4),
        "average_family_reward": round(safe_mean(family_rewards), 4),
        "average_family_reward_trainable": round(
            sum(record["reward_components"]["family_reward"] for record in trainable) / max(1, len(trainable)),
            4,
        ),
        "mean_length": round(safe_mean(lengths), 2),
        "any_serine_motif_rate": safe_rate(
            sum(bool(evaluation["serine_motifs"]) for evaluation in family_evaluations),
            len(records),
        ),
        "family_serine_motif_rate": safe_rate(
            sum(bool(evaluation["has_family_serine_motif"]) for evaluation in family_evaluations),
            len(records),
        ),
        "catalytic_geometry_rate": safe_rate(
            sum(bool(evaluation["catalytic_geometry"]["passes"]) for evaluation in family_evaluations),
            len(records),
        ),
        "functional_bridge_rate": safe_rate(len(functional_bridge_steps), len(records)),
        "family_faithful_bridge_rate": safe_rate(len(family_faithful_bridge_steps), len(records)),
        "stability_dominant_rate": safe_rate(len(stability_dominant_steps), len(records)),
        "geometry_dominant_rate": safe_rate(len(geometry_dominant_steps), len(records)),
        "core_screen_rate": safe_rate(
            sum(bool(evaluation["passes_core_screen"]) for evaluation in family_evaluations),
            len(records),
        ),
        "esm_gate_pass_rate": safe_rate(
            sum(bool(record["reward_components"].get("esm_gate_pass")) for record in records),
            len(records),
        ),
        "motif_steps": [
            record["step"]
            for record in records
            if record["family_evaluation"] is not None and record["family_evaluation"]["serine_motifs"]
        ],
        "family_motif_steps": [
            record["step"]
            for record in records
            if record["family_evaluation"] is not None and record["family_evaluation"]["has_family_serine_motif"]
        ],
        "geometry_steps": [
            record["step"]
            for record in records
            if record["family_evaluation"] is not None and record["family_evaluation"]["catalytic_geometry"]["passes"]
        ],
        "stability_dominant_steps": stability_dominant_steps,
        "geometry_dominant_steps": geometry_dominant_steps,
        "functional_bridge_steps": functional_bridge_steps,
        "family_faithful_bridge_steps": family_faithful_bridge_steps,
    }


def safe_rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def safe_mean(values: list[float] | list[int]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


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


if __name__ == "__main__":
    main()
