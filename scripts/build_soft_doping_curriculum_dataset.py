#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.open() if line.strip()]


def infer_canonical_motif(sequence: str, allowed_motifs: set[str]) -> str | None:
    for match in re.finditer(r"G.S.G", sequence):
        motif = match.group(0)
        if motif in allowed_motifs:
            return motif
    return None


def resolve_training_prompt(row: dict[str, Any]) -> str:
    prompt = str(row.get("prompt") or row.get("source_prompt") or "").strip()
    if prompt:
        return prompt

    length = int(row.get("length") or row.get("sequence_length") or len(str(row.get("sequence") or "")) or 300)
    motif = str(row.get("derived_motif") or "").strip()
    if not motif:
        family_eval = row.get("family_evaluation") or {}
        serine_motifs = family_eval.get("serine_motifs") or []
        if serine_motifs:
            motif = str(serine_motifs[0]).strip()

    motif_clause = f" with canonical serine motif {motif}" if motif else ""
    return (
        f"Generate a PETase-family esterase sequence around {length} aa"
        f"{motif_clause} while preserving catalytic bridge geometry."
    )


def normalize_training_row(row: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    prompt = resolve_training_prompt(enriched)
    enriched["prompt"] = prompt
    enriched["sequence_prompt"] = str(enriched.get("sequence_prompt") or prompt)
    return enriched


def build_dataset(
    *,
    purebred_rows: list[dict[str, Any]],
    loose_rows: list[dict[str, Any]],
    strict_rows: list[dict[str, Any]],
    allowed_motifs: set[str],
    strict_target_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    canonical_purebreds: list[dict[str, Any]] = []
    for row in purebred_rows:
        motif = infer_canonical_motif(row["sequence"], allowed_motifs)
        if motif is None:
            continue
        enriched = normalize_training_row(row)
        enriched["curriculum_role"] = "tier1_pull"
        enriched["curriculum_source"] = "purebred_canonical"
        enriched["derived_motif"] = motif
        canonical_purebreds.append(enriched)

    strict_repairs: list[dict[str, Any]] = []
    for row in strict_rows:
        enriched = normalize_training_row(row)
        enriched["curriculum_role"] = "tier1_pull"
        enriched["curriculum_source"] = "doping_strict"
        strict_repairs.append(enriched)

    selected_tier1: list[dict[str, Any]] = canonical_purebreds[:strict_target_count]
    remaining = max(0, strict_target_count - len(selected_tier1))
    if remaining:
        selected_tier1.extend(strict_repairs[:remaining])

    selected_tier2: list[dict[str, Any]] = []
    for row in loose_rows:
        enriched = normalize_training_row(row)
        enriched["curriculum_role"] = "tier2_anchor"
        enriched["curriculum_source"] = "doping_loose"
        selected_tier2.append(enriched)

    dataset = selected_tier2 + selected_tier1
    summary = {
        "tier2_anchor_count": len(selected_tier2),
        "tier1_pull_count": len(selected_tier1),
        "canonical_purebred_count": sum(1 for row in selected_tier1 if row["curriculum_source"] == "purebred_canonical"),
        "strict_repair_count": sum(1 for row in selected_tier1 if row["curriculum_source"] == "doping_strict"),
        "total_count": len(dataset),
        "allowed_motifs": sorted(allowed_motifs),
        "strict_target_count": strict_target_count,
    }
    return dataset, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a soft-doping curriculum dataset")
    parser.add_argument("--purebred-path", required=True)
    parser.add_argument("--loose-doping-path", required=True)
    parser.add_argument("--strict-doping-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path", required=True)
    parser.add_argument("--allowed-motifs", default="GYSLG,GYSQG")
    parser.add_argument("--strict-target-count", type=int, default=12)
    args = parser.parse_args()

    allowed_motifs = {motif.strip() for motif in args.allowed_motifs.split(",") if motif.strip()}
    dataset, summary = build_dataset(
        purebred_rows=load_jsonl(Path(args.purebred_path)),
        loose_rows=load_jsonl(Path(args.loose_doping_path)),
        strict_rows=load_jsonl(Path(args.strict_doping_path)),
        allowed_motifs=allowed_motifs,
        strict_target_count=args.strict_target_count,
    )

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as handle:
        for row in dataset:
            handle.write(json.dumps(row) + "\n")

    summary["output_path"] = str(output_path)
    Path(args.summary_path).write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
