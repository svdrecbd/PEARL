#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a p48-only smoke robustness summary")
    parser.add_argument("--summary-path", required=True)
    parser.add_argument("--prompt-count", type=int, default=48)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--min-seeds-with-hit", type=int, default=1)
    parser.add_argument("--min-prompts-with-hit", type=int, default=1)
    parser.add_argument("--output-path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(Path(args.summary_path).read_text(encoding="utf-8"))
    groups = payload.get("groups") or []
    group = next(
        (
            item
            for item in groups
            if int(item.get("prompt_count", -1)) == args.prompt_count
            and float(item.get("temperature", -1.0)) == args.temperature
        ),
        None,
    )
    if group is None:
        raise SystemExit(f"No matching group found in {args.summary_path}")

    tier2_hits_by_seed = [int(value) for value in group.get("tier2_hits_by_seed", [])]
    prompts_with_hits = int(group.get("prompts_with_any_tier2_across_seeds") or 0)
    seeds_with_hits = sum(1 for value in tier2_hits_by_seed if value > 0)
    decision = {
        "summary_path": str(Path(args.summary_path).resolve()),
        "prompt_count": args.prompt_count,
        "temperature": args.temperature,
        "tier2_hits_by_seed": tier2_hits_by_seed,
        "seeds_with_hits": seeds_with_hits,
        "prompts_with_any_tier2_across_seeds": prompts_with_hits,
        "thresholds": {
            "min_seeds_with_hit": args.min_seeds_with_hit,
            "min_prompts_with_hit": args.min_prompts_with_hit,
        },
        "passed": seeds_with_hits >= args.min_seeds_with_hit and prompts_with_hits >= args.min_prompts_with_hit,
    }

    if args.output_path:
        Path(args.output_path).write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(decision, indent=2))
    if not decision["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
