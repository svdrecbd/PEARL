#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT_PATH = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT_PATH / "src"
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.family import find_serine_motifs, evaluate_candidate, AA_PATTERN

def find_repeats(seq, min_len=20):
    repeats = []
    n = len(seq)
    for i in range(n - min_len):
        block = seq[i:i+min_len]
        start_search = i + 1
        pos = seq.find(block, start_search)
        if pos != -1:
            l = min_len
            while i + l < n and pos + l < n and seq[i + l] == seq[pos + l]:
                l += 1
            full_block = seq[i:i+l]
            if not any(full_block in r["seq"] for r in repeats):
                repeats.append({"seq": full_block, "len": l})
    return repeats

def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists(): return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line: rows.append(json.loads(line))
    return rows

def pick_sequence(row: dict[str, Any]) -> str:
    sequence = row.get("sequence") or row.get("extracted_sequence") or row.get("sample_text")
    if sequence is None and isinstance(row.get("selected_candidate"), dict):
        sequence = row["selected_candidate"].get("sequence") or row["selected_candidate"].get("extracted_sequence")
    return str(sequence or "").strip().upper()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2-unicorn", default="reports/ablations/pearl-topoff1m-a-manifold-v2-stagea-gate-p24-c128-p24-t0p8-s53/candidate_audit.json")
    parser.add_argument("--v22-anchors", default="reports/curriculum/manifold_v22_20260424/manifold_v22_intersection_curriculum.jsonl")
    parser.add_argument("--v12-hits", default="reports/manifold/topoff1m-a-manifold-v12-20260423/v12_selected_repair_retargeted.jsonl")
    parser.add_argument("--purebred", default="data/petase_family_expanded/kimi_micro_sft_top9_unicorn_only.jsonl")
    parser.add_argument("--output", default="reports/curriculum/manifold_v24_20260424/manifold_v24_anti_repeat_curriculum.jsonl")
    args = parser.parse_args()

    # 1. Original v2 Unicorn (No-repeat verified)
    v2_audit = json.loads(Path(args.v2_unicorn).read_text())
    v2_hits = [c for r in v2_audit["records"] for c in r["candidates"] if c.get("functional_bridge_passes")]
    v2_unicorn = v2_hits[0]
    seq = pick_sequence(v2_unicorn)
    if find_repeats(seq, min_len=21):
         raise SystemExit("v2 Unicorn has repeats > 20!")
    v2_unicorn["curriculum_role"] = "v2_unicorn_lock"
    v2_unicorn["sequence"] = seq
    
    # 2. Natural Stability Anchors (Pull clean rows from records)
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    all_records = read_jsonl(records_path)
    natural_anchors = []
    for r in all_records:
        seq = r["sequence"].upper()
        if not find_repeats(seq, min_len=21):
            r["curriculum_role"] = "natural_stability_anchor"
            r["sequence"] = seq
            natural_anchors.append(r)
            if len(natural_anchors) >= 80: break
    
    print(f"Found {len(natural_anchors)} natural anchors passing anti-repeat gate.")

    # 3. v1.2/v2.2 Synthetic Anchors (Filter by anti-repeat)
    # Check both v1.2 hits and v2.2 anchors
    raw_syn = read_jsonl(Path(args.v12_hits)) + read_jsonl(Path(args.v22_anchors))
    synthetic_anchors = []
    for r in raw_syn:
        seq = pick_sequence(r)
        if not find_repeats(seq, min_len=21):
            r["curriculum_role"] = "synthetic_stability_anchor"
            r["sequence"] = seq
            synthetic_anchors.append(r)
            if len(synthetic_anchors) >= 16: break
    
    print(f"Found {len(synthetic_anchors)} synthetic anchors passing anti-repeat gate.")

    final_curriculum = [v2_unicorn] + natural_anchors + synthetic_anchors
    
    # Add prompts where missing
    for r in final_curriculum:
        if not r.get("prompt"):
            length = len(r["sequence"])
            r["prompt"] = f"Design a protein sequence inspired by Cutinase, length about {length} aa. Favor a PETase/cutinase-like GxSxG nucleophile motif and compatible catalytic residues. Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for r in final_curriculum:
            f.write(json.dumps(r) + "\n")
            
    summary = {
        "total_rows": len(final_curriculum),
        "roles": dict(Counter(r["curriculum_role"] for r in final_curriculum)),
        "anti_repeat_hard_gate": 20
    }
    with (out_path.parent / "summary.json").open("w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
