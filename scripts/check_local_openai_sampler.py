#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.openai_compat_sampler import OpenAICompatibleSamplingClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe a local OpenAI-compatible sampler server")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", default="gemma-local")
    parser.add_argument("--tokenizer")
    parser.add_argument("--api-key")
    parser.add_argument("--prompt", default="Design a short PETase-like enzyme sequence.")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--seed", type=int, default=7)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = OpenAICompatibleSamplingClient(
        base_url=args.base_url,
        model_name=args.model,
        tokenizer_name=args.tokenizer,
        api_key=args.api_key,
    )
    health = client.healthcheck()
    sampling_params = SimpleNamespace(
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        top_k=args.top_k,
        stop=[],
        seed=args.seed,
    )
    sample_result = client.sample_text(
        prompt=args.prompt,
        num_samples=args.samples,
        sampling_params=sampling_params,
    ).result()
    payload = {
        "base_url": args.base_url,
        "model": args.model,
        "tokenizer": args.tokenizer or args.model,
        "healthcheck_model_count": len(health.get("data", [])) if isinstance(health, dict) else None,
        "sample_count": len(sample_result.sequences),
        "sample_token_lengths": [len(sequence.tokens) for sequence in sample_result.sequences],
        "finish_reasons": [sequence.stop_reason for sequence in sample_result.sequences],
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
