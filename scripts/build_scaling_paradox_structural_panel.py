#!/usr/bin/env python3
"""Freeze a length-stratified prompt panel from the untouched real-failure challenge."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "experiments" / "scaling_paradox_structural_v1.json"
LENGTH_PATTERN = re.compile(r"(?:length (?:about|near)|around)\s+(\d+)\s*(?:aa|amino acids?)", re.IGNORECASE)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def target_length(row: dict[str, Any]) -> int:
    prompt = str(row["prompt"])
    match = LENGTH_PATTERN.search(prompt)
    if match:
        return int(match.group(1))
    return len(str(row["chosen"]))


def length_bin(length: int) -> str:
    if length < 240:
        return "short"
    if length <= 300:
        return "medium"
    return "long"


def stable_rank(seed: int, prompt: str) -> str:
    return sha256_bytes(f"{seed}\0{prompt}".encode("utf-8"))


def select_panel(rows: list[dict[str, Any]], *, count: int, seed: int) -> list[dict[str, Any]]:
    by_prompt: dict[str, dict[str, Any]] = {}
    for row in rows:
        prompt = str(row.get("prompt") or "").strip()
        if not prompt:
            continue
        current = by_prompt.get(prompt)
        candidate_key = (str(row.get("chosen_record_id") or ""), str(row.get("chosen_accession") or ""))
        current_key = (
            str(current.get("chosen_record_id") or ""),
            str(current.get("chosen_accession") or ""),
        ) if current else None
        if current is None or candidate_key < current_key:
            by_prompt[prompt] = row

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for prompt, row in by_prompt.items():
        length = target_length(row)
        buckets[length_bin(length)].append(
            {
                "prompt": prompt,
                "target_length": length,
                "length_bin": length_bin(length),
                "withheld_positive_group_sha256": sha256_bytes(
                    str(row.get("chosen_record_id") or row.get("chosen_accession") or "").encode("utf-8")
                ),
            }
        )
    if count % 3:
        raise ValueError("prompt_count must be divisible by the three preregistered length bins")
    per_bin = count // 3
    selected: list[dict[str, Any]] = []
    for name in ("short", "medium", "long"):
        ordered = sorted(buckets[name], key=lambda row: (stable_rank(seed, row["prompt"]), row["prompt"]))
        if len(ordered) < per_bin:
            raise ValueError(f"length bin {name!r} contains only {len(ordered)} unique prompts")
        selected.extend(ordered[:per_bin])
    selected.sort(key=lambda row: (row["length_bin"], row["target_length"], row["prompt"]))
    for index, row in enumerate(selected, start=1):
        row["prompt_id"] = f"spv1-p{index:02d}-{sha256_bytes(row['prompt'].encode('utf-8'))[:10]}"
    return selected


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(canonical_json(row) + "\n" for row in rows)
    path.write_text(payload, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()
    config_path = repo_path(args.config)
    config = load_json(config_path)
    manifest_path = repo_path(config["dataset_manifest"])
    manifest = load_json(manifest_path)
    source = manifest["partitions"][config["source_partition"]]
    source_path = repo_path(source["path"])
    if sha256_file(source_path) != source["sha256"]:
        raise RuntimeError("real-failure source partition hash does not match the frozen manifest")
    panel = select_panel(
        load_jsonl(source_path),
        count=int(config["prompt_count"]),
        seed=int(config["prompt_selection_seed"]),
    )
    panel_path = repo_path(config["prompt_panel"])
    write_jsonl(panel_path, panel)
    summary = {
        "contract": config["contract"],
        "dataset_manifest_sha256": manifest["manifest_sha256"],
        "source_partition_sha256": source["sha256"],
        "prompt_panel_sha256": sha256_file(panel_path),
        "prompt_count": len(panel),
        "length_bins": {name: sum(row["length_bin"] == name for row in panel) for name in ("short", "medium", "long")},
        "panel_path": str(panel_path),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
