#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT_PATH = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT_PATH / "src"
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

AA_PATTERN = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")

def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

def sequence_id(sequence: str, *, prefix: str = "v22") -> str:
    return f"{prefix}-{hashlib.sha1(sequence.encode('utf-8')).hexdigest()[:16]}"

def pick_sequence(row: dict[str, Any]) -> str:
    sequence = row.get("sequence") or row.get("extracted_sequence") or row.get("sample_text")
    if sequence is None and isinstance(row.get("selected_candidate"), dict):
        sequence = row["selected_candidate"].get("sequence") or row["selected_candidate"].get("extracted_sequence")
    return str(sequence or "").strip().upper()

def evaluate_row(row: dict[str, Any]) -> tuple[int, ...]:
    """
    Selection should be hard-ordered:
    valid amino acids
    length obedience (delta <= 5)
    exactly one acceptable serine motif
    family core screen
    catalytic geometry pass
    ESM/stability floor (>= 85, prefer >= 90)
    """
    seq = pick_sequence(row)
    valid_aa = 1 if AA_PATTERN.fullmatch(seq) else 0
    
    prompt_delta = row.get("prompt_length_delta")
    if prompt_delta is None:
        prompt_delta = abs(len(seq) - int(row.get("requested_length", 0)))
    length_ok = 1 if abs(prompt_delta) <= 5 else 0
    
    motif_count = row.get("motif_count") or (1 if row.get("has_family_serine_motif") else 0)
    single_motif = 1 if motif_count == 1 else 0
    
    family_core = 1 if row.get("passes_core_screen") else 0
    geom_pass = 1 if row.get("geometry_passes") else 0
    
    esm = float(row.get("raw_esm_score") or row.get("esm_score") or 0.0)
    esm_90 = 1 if esm >= 90.0 else 0
    esm_85 = 1 if esm >= 85.0 else 0
    
    # rank is a tuple where higher is better
    return (valid_aa, length_ok, single_motif, family_core, geom_pass, esm_90, esm_85, esm)

def select_top(rows: list[dict[str, Any]], max_count: int) -> list[dict[str, Any]]:
    valid_rows = [r for r in rows if evaluate_row(r)[:7] == (1, 1, 1, 1, 1, 1, 1) or evaluate_row(r)[:7] == (1, 1, 1, 1, 1, 0, 1)]
    return sorted(valid_rows, key=evaluate_row, reverse=True)[:max_count]

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2-bridge-hits", default="reports/curriculum/manifold_v21_20260424/manifold_v21_bridge_curriculum.jsonl")
    parser.add_argument("--v12-family-hits", default="reports/manifold/topoff1m-a-manifold-v12-20260423/v12_selected_repair_retargeted.jsonl")
    parser.add_argument("--v2-breadth", default="reports/analysis/manifold_v2_offline_constructor_20260424_batch2/v2_constructor_final_reselected.jsonl")
    parser.add_argument("--v21-geometry-intersection", default="reports/analysis/manifold_v22_preparation/bucket1_v22_positives.jsonl")
    parser.add_argument("--historical-anchors", default="reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/family_faithful_bridges.jsonl")
    parser.add_argument("--purebred", default="data/petase_family_expanded/kimi_micro_sft_top9_unicorn_only.jsonl")
    parser.add_argument("--repaired-v21", default="reports/repair/topoff1m-a-v21-geometry-repair-20260424/repair_survivors_strict.jsonl")
    parser.add_argument("--output", default="reports/curriculum/manifold_v22_20260424/manifold_v22_intersection_curriculum.jsonl")
    args = parser.parse_args()

    v2_bridge_rows = [r for r in read_jsonl(Path(args.v2_bridge_hits)) if r.get("functional_bridge_passes")][:12]
    v12_family_rows = read_jsonl(Path(args.v12_family_hits))[:12]
    v2_breadth_rows = read_jsonl(Path(args.v2_breadth))[:24]
    v21_geom_rows = read_jsonl(Path(args.v21_geometry_intersection))[:20]
    hist_rows = read_jsonl(Path(args.historical_anchors))[:16]
    purebred_rows = read_jsonl(Path(args.purebred))[:8]
    repaired_rows = read_jsonl(Path(args.repaired_v21))[:12]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    final_curriculum = []
    
    def add_rows(source_rows, role):
        for r in source_rows:
            r["curriculum_role"] = role
            final_curriculum.append(r)

    add_rows(v2_bridge_rows, "v2_bridge_hit")
    add_rows(v12_family_rows, "v12_family_hit")
    add_rows(v2_breadth_rows, "v2_breadth_anchor")
    add_rows(v21_geom_rows, "v21_geometry_intersection")
    add_rows(hist_rows, "historical_anchor")
    add_rows(purebred_rows, "purebred_anchor")
    add_rows(repaired_rows, "repaired_v21")

    # Add dummy prompt to rows lacking it
    for r in final_curriculum:
        seq = pick_sequence(r)
        if "sequence" not in r:
            r["sequence"] = seq
        if not r.get("prompt"):
            r["prompt"] = f"Design a protein sequence inspired by Cutinase, length about {len(seq)} aa. Favor a PETase/cutinase-like GxSxG nucleophile motif and compatible catalytic residues. Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."

    with out_path.open("w", encoding="utf-8") as f:
        for r in final_curriculum:
            f.write(json.dumps(r) + "\n")
            
    summary = {
        "total_rows": len(final_curriculum),
        "roles": dict(Counter(r["curriculum_role"] for r in final_curriculum))
    }
    
    with (out_path.parent / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
