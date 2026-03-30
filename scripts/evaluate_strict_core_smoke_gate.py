#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.smoke_gate import evaluate_smoke_summary


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
    try:
        decision = evaluate_smoke_summary(
            payload,
            summary_path=args.summary_path,
            prompt_count=args.prompt_count,
            temperature=args.temperature,
            min_seeds_with_hit=args.min_seeds_with_hit,
            min_prompts_with_hit=args.min_prompts_with_hit,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.output_path:
        Path(args.output_path).write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(decision, indent=2))
    if not decision["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
