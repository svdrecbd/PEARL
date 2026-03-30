from __future__ import annotations

from pathlib import Path
from typing import Any


def evaluate_smoke_summary(
    payload: dict[str, Any],
    *,
    summary_path: str | Path,
    prompt_count: int,
    temperature: float,
    min_seeds_with_hit: int,
    min_prompts_with_hit: int,
) -> dict[str, Any]:
    groups = payload.get("groups") or []
    group = next(
        (
            item
            for item in groups
            if int(item.get("prompt_count", -1)) == prompt_count
            and float(item.get("temperature", -1.0)) == temperature
        ),
        None,
    )
    if group is None:
        raise ValueError(f"No matching group found in {summary_path}")

    tier2_hits_by_seed = [int(value) for value in group.get("tier2_hits_by_seed", [])]
    prompts_with_hits = int(group.get("prompts_with_any_tier2_across_seeds") or 0)
    seeds_with_hits = sum(1 for value in tier2_hits_by_seed if value > 0)
    return {
        "summary_path": str(Path(summary_path).resolve()),
        "prompt_count": prompt_count,
        "temperature": temperature,
        "tier2_hits_by_seed": tier2_hits_by_seed,
        "seeds_with_hits": seeds_with_hits,
        "prompts_with_any_tier2_across_seeds": prompts_with_hits,
        "thresholds": {
            "min_seeds_with_hit": min_seeds_with_hit,
            "min_prompts_with_hit": min_prompts_with_hit,
        },
        "passed": seeds_with_hits >= min_seeds_with_hit and prompts_with_hits >= min_prompts_with_hit,
    }
