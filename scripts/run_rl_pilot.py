from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir) / sanitize_name(args.name)
    output_dir.mkdir(parents=True, exist_ok=True)

    subset_path = output_dir / "prompt_subset.jsonl"
    report_path = output_dir / "report.json"
    summary_path = output_dir / "summary.json"
    candidate_audit_path = output_dir / "candidate_audit.json"
    metadata_path = output_dir / "metadata.json"

    subset_rows = build_prompt_subset(
        source_path=Path(args.prompts_path),
        count=args.prompt_count,
        seed=args.seed,
        preserve_order=args.preserve_order,
    )
    write_jsonl(subset_path, subset_rows)

    metadata = {
        "name": args.name,
        "init_state_path": args.init_state_path,
        "model": args.model,
        "loss_fn": args.loss_fn,
        "reward_mode": "bridge_tiers",
        "prompt_count": args.prompt_count,
        "candidate_sample_count": args.candidate_sample_count,
        "second_stage_top_k": args.second_stage_top_k,
        "learning_rate": args.learning_rate,
        "ppo_clip_low_threshold": args.ppo_clip_low_threshold,
        "ppo_clip_high_threshold": args.ppo_clip_high_threshold,
        "bridge_tier2_reward": args.bridge_tier2_reward,
        "bridge_tier1_bonus": args.bridge_tier1_bonus,
        "subset_path": str(subset_path),
        "report_path": str(report_path),
        "summary_path": str(summary_path),
        "candidate_audit_path": str(candidate_audit_path),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "PROMPTS_PATH": str(subset_path),
            "REFERENCE_RECORDS_PATH": args.reference_records_path,
            "DRY_RUN_PROMPT_COUNT": str(args.prompt_count),
            "TINKER_CANDIDATE_SAMPLE_COUNT": str(args.candidate_sample_count),
            "TINKER_SECOND_STAGE_TOP_K": str(args.second_stage_top_k),
            "TINKER_BASE_MODEL": args.model,
            "CHECKPOINT_NAME": sanitize_name(args.name),
            "REPORT_PATH": str(report_path),
            "CANDIDATE_AUDIT_PATH": str(candidate_audit_path),
            "TINKER_INIT_STATE_PATH": args.init_state_path,
            "TINKER_RL_LOSS_FN": args.loss_fn,
            "TINKER_RL_REWARD_MODE": "bridge_tiers",
            "TINKER_PPO_CLIP_LOW_THRESHOLD": str(args.ppo_clip_low_threshold),
            "TINKER_PPO_CLIP_HIGH_THRESHOLD": str(args.ppo_clip_high_threshold),
            "TINKER_BRIDGE_TIER2_REWARD": str(args.bridge_tier2_reward),
            "TINKER_BRIDGE_TIER1_BONUS": str(args.bridge_tier1_bonus),
            "RL_LEARNING_RATE": str(args.learning_rate),
            "PROMPT_VARIANT": args.prompt_variant,
            "SAMPLING_TEMPERATURE": str(args.sampling_temperature),
            "SAMPLING_TOP_P": str(args.sampling_top_p),
            "SAMPLING_TOP_K": str(args.sampling_top_k),
            "TINKER_PLDDT_GATE_THRESHOLD": str(args.plddt_gate_threshold),
        }
    )

    python_bin = args.python_bin or sys.executable
    subprocess.run([python_bin, str(ROOT / "main.py")], check=True, cwd=ROOT, env=env)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = summarize_report(report)
    summary.update(
        {
            "name": args.name,
            "init_state_path": args.init_state_path,
            "model": args.model,
            "loss_fn": args.loss_fn,
            "reward_mode": "bridge_tiers",
            "prompt_count": args.prompt_count,
            "candidate_sample_count": args.candidate_sample_count,
            "second_stage_top_k": args.second_stage_top_k,
            "learning_rate": args.learning_rate,
            "ppo_clip_low_threshold": args.ppo_clip_low_threshold,
            "ppo_clip_high_threshold": args.ppo_clip_high_threshold,
            "bridge_tier2_reward": args.bridge_tier2_reward,
            "bridge_tier1_bonus": args.bridge_tier1_bonus,
            "subset_path": str(subset_path),
            "report_path": str(report_path),
            "candidate_audit_path": str(candidate_audit_path),
        }
    )
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a short PPO/IS RL pilot with bridge-tier rewards")
    parser.add_argument("--name", required=True)
    parser.add_argument("--init-state-path", required=True)
    parser.add_argument("--prompts-path", required=True)
    parser.add_argument("--reference-records-path", required=True)
    parser.add_argument("--output-dir", default=str(ROOT / "reports" / "rl_pilot"))
    parser.add_argument("--model", default="moonshotai/Kimi-K2.5")
    parser.add_argument("--prompt-count", type=int, default=20)
    parser.add_argument("--candidate-sample-count", type=int, default=2048)
    parser.add_argument("--second-stage-top-k", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=1e-6)
    parser.add_argument("--loss-fn", choices=("ppo", "importance_sampling"), default="ppo")
    parser.add_argument("--ppo-clip-low-threshold", type=float, default=0.9)
    parser.add_argument("--ppo-clip-high-threshold", type=float, default=1.1)
    parser.add_argument("--bridge-tier2-reward", type=float, default=1.0)
    parser.add_argument("--bridge-tier1-bonus", type=float, default=5.0)
    parser.add_argument("--plddt-gate-threshold", type=float, default=85.0)
    parser.add_argument("--sampling-temperature", type=float, default=0.8)
    parser.add_argument("--sampling-top-p", type=float, default=0.95)
    parser.add_argument("--sampling-top-k", type=int, default=50)
    parser.add_argument("--prompt-variant", default="baseline")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--preserve-order", action="store_true")
    parser.add_argument("--python-bin")
    return parser.parse_args()


def build_prompt_subset(*, source_path: Path, count: int, seed: int, preserve_order: bool) -> list[dict[str, Any]]:
    rows = load_jsonl(source_path)
    if count > len(rows):
        raise RuntimeError(f"Requested {count} prompts but only found {len(rows)} in {source_path}")
    if preserve_order:
        return rows[:count]
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    return shuffled[:count]


def summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    records = report["records"]
    reward_values = [float(record["reward"]) for record in records]
    functional_steps = [
        record["step"]
        for record in records
        if bool(record["reward_components"].get("functional_bridge_passes"))
    ]
    faithful_steps = [
        record["step"]
        for record in records
        if bool(record["reward_components"].get("family_faithful_bridge_passes"))
    ]
    updated_steps = [
        record["step"]
        for record in records
        if bool(record.get("update_performed"))
    ]
    return {
        "checkpoint_path": report["checkpoint_path"],
        "steps": len(records),
        "average_reward": round(sum(reward_values) / max(1, len(reward_values)), 4),
        "trainable_count": sum(1 for record in records if not record["training_skipped"]),
        "update_count": len(updated_steps),
        "functional_bridge_rate": round(len(functional_steps) / max(1, len(records)), 4),
        "family_faithful_bridge_rate": round(len(faithful_steps) / max(1, len(records)), 4),
        "functional_bridge_steps": functional_steps,
        "family_faithful_bridge_steps": faithful_steps,
        "updated_steps": updated_steps,
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def sanitize_name(value: str) -> str:
    chars = []
    for char in value.lower():
        chars.append(char if char.isalnum() else "-")
    return "".join(chars).strip("-")


if __name__ == "__main__":
    main()
