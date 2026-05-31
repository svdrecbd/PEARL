#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.io_utils import atomic_write_json
from pearl.preference_distillation import load_jsonl, write_jsonl


def main() -> None:
    args = parse_args()
    pairs_path = repo_path(args.pairs_path)
    output_path = repo_path(args.output_path)
    manifest_path = output_path.with_suffix(".manifest.json")
    pairs = load_jsonl(pairs_path)
    rows = build_seed_rows(pairs, max_rows=args.max_rows, role=args.role)
    if not rows:
        raise RuntimeError("No rollout seed rows were built")
    write_jsonl(output_path, rows)
    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "pairs_path": str(pairs_path),
        "output_path": str(output_path),
        "role": args.role,
        "source_pair_count": len(pairs),
        "rollout_count": len(rows),
        "purpose": "static_seed_for_sparse_opd_paid_smoke_not_final_on_policy_readout",
    }
    atomic_write_json(manifest_path, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a static rollout seed file from DPO pairs for sparse OPD trace/smoke readiness."
    )
    parser.add_argument("--pairs-path", default=str(ROOT / "data" / "phase8_dpo" / "dpo_preferences_hybrid_10k.jsonl"))
    parser.add_argument("--output-path", default=str(ROOT / "reports" / "opd_lite" / "rollouts.jsonl"))
    parser.add_argument("--max-rows", type=int, default=256)
    parser.add_argument("--role", choices=("chosen", "rejected", "both"), default="chosen")
    return parser.parse_args()


def build_seed_rows(pairs: list[dict[str, Any]], *, max_rows: int, role: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair_index, pair in enumerate(pairs):
        if role in {"chosen", "both"}:
            rows.append(seed_row(pair=pair, pair_index=pair_index, sequence_key="chosen"))
        if role in {"rejected", "both"}:
            rows.append(seed_row(pair=pair, pair_index=pair_index, sequence_key="rejected"))
        if len(rows) >= max_rows:
            return rows[:max_rows]
    return rows


def seed_row(*, pair: dict[str, Any], pair_index: int, sequence_key: str) -> dict[str, Any]:
    candidate_id_key = "chosen_id" if sequence_key == "chosen" else "rejected_id"
    return {
        "sample_id": f"static-{sequence_key}-{pair_index:06d}",
        "prompt": str(pair["prompt"]),
        "sequence": str(pair[sequence_key]),
        "source": "phase8_dpo_static_seed",
        "source_pair_index": pair_index,
        "source_candidate_id": pair.get(candidate_id_key),
        "source_role": sequence_key,
        "preference_rule": pair.get("preference_rule"),
    }


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path


if __name__ == "__main__":
    main()
