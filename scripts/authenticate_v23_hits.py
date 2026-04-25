#!/usr/bin/env python3
import json
import os
import sys
import re
from pathlib import Path
from collections import Counter

# Ensure src is in sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from pearl.family import (
    load_reference_records, 
    compute_family_stats, 
    evaluate_candidate,
    levenshtein
)

def find_repeats(seq, min_len=20):
    repeats = []
    n = len(seq)
    for i in range(n - min_len):
        block = seq[i:i+min_len]
        # Look for this block elsewhere in the sequence
        start_search = i + 1
        pos = seq.find(block, start_search)
        if pos != -1:
            # Found a repeat! Expand it
            l = min_len
            while i + l < n and pos + l < n and seq[i + l] == seq[pos + l]:
                l += 1
            full_block = seq[i:i+l]
            # Avoid redundant overlapping repeats
            if not any(full_block in r["seq"] for r in repeats):
                repeats.append({
                    "seq": full_block,
                    "pos1": i,
                    "pos2": pos,
                    "len": l
                })
    return repeats

def authenticate_candidate(c, family_stats, reference_records, v2_unicorn_seq, v22_anchors, v21_survivor):
    seq = c.get("extracted_sequence") or c.get("sample_text")
    
    # 1-5: Basic and Evaluation checks
    eval_res = evaluate_candidate(
        sequence=seq,
        family_stats=family_stats,
        reference_records=reference_records
    )
    
    esm = float(c.get("raw_esm_score") or c.get("esm_score") or 0.0)
    
    # 6-7: Repeat Detection
    repeats = find_repeats(seq)
    
    # 8-10: Distances
    dist_v2 = levenshtein(seq, v2_unicorn_seq)
    dist_v22 = min([levenshtein(seq, a) for a in v22_anchors]) if v22_anchors else None
    dist_v21 = levenshtein(seq, v21_survivor) if v21_survivor else None
    
    # 12: Masking check
    # Mask repeats and check if geometry still passes
    masked_seq = list(seq)
    for r in repeats:
        for i in range(r["pos2"], r["pos2"] + r["len"]):
            masked_seq[i] = "X"
    masked_seq_str = "".join(masked_seq)
    
    # We re-evaluate the masked version (replace X with A for family logic to avoid crashes, but check site impact)
    eval_masked = evaluate_candidate(
        sequence=masked_seq_str.replace("X", "A"),
        family_stats=family_stats,
        reference_records=reference_records
    )
    
    auth = {
        "candidate_id": c.get("sequence_id") or "unknown",
        "length": len(seq),
        "motif_count": eval_res.get("serine_motif_count"),
        "geometry_pass": eval_res.get("catalytic_geometry", {}).get("passes"),
        "core_pass": eval_res.get("passes_core_screen"),
        "esm_score": esm,
        "repeats": repeats,
        "repeat_count": len(repeats),
        "dist_to_v2_unicorn": dist_v2,
        "dist_to_nearest_v22": dist_v22,
        "dist_to_v21_survivor": dist_v21,
        "masked_geometry_pass": eval_masked.get("catalytic_geometry", {}).get("passes"),
        "masked_core_pass": eval_masked.get("passes_core_screen")
    }
    return auth

def main():
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    # Load v2 Unicorn
    v2_audit = json.load(open("reports/ablations/pearl-topoff1m-a-manifold-v2-stagea-gate-p24-c128-p24-t0p8-s53/candidate_audit.json"))
    v2_unicorn_seq = next(c["extracted_sequence"] for r in v2_audit["records"] for c in r["candidates"] if c.get("functional_bridge_passes"))
    
    # Load v2.2 Anchors
    v22_rows = [json.loads(l) for l in open("reports/curriculum/manifold_v22_20260424/manifold_v22_intersection_curriculum.jsonl")]
    v22_anchors = [r["sequence"] for r in v22_rows if r.get("curriculum_role") == "v22_baseline_anchor"]
    
    # Load v2.1 Survivor
    v21_rows = [json.loads(l) for l in open("reports/analysis/manifold_v22_preparation/bucket1_v22_positives.jsonl")]
    v21_survivor = v21_rows[0]["extracted_sequence"] if v21_rows else None
    
    # Identify v2.3 hits
    v23_hits = []
    run_name = "pearl-topoff1m-a-manifold-v23-lock-stagea-gate-p24-c128"
    for path in Path("reports/ablations").glob(f"{run_name}-p24-t0p8-s*/candidate_audit.json"):
        data = json.load(open(path))
        for r in data["records"]:
            for c in r["candidates"]:
                if c.get("functional_bridge_passes"):
                    v23_hits.append(c)
                    
    auth_results = []
    for c in v23_hits:
        auth_results.append(authenticate_candidate(c, family_stats, reference_records, v2_unicorn_seq, v22_anchors, v21_survivor))
        
    out_dir = Path("reports/analysis/manifold_v23_hit_authentication")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(out_dir / "hit_authentication.json", "w") as f:
        json.dump(auth_results, f, indent=2)
        
    md = "# v2.3 Hit Authentication Report\n\n"
    for a in auth_results:
        md += f"## Candidate {a['candidate_id']}\n"
        md += f"- **Status:** {'VALID' if a['repeat_count'] == 0 else 'REPEAT-DETECTED'}\n"
        md += f"- **ESM:** {a['esm_score']}\n"
        md += f"- **Geometry Pass:** {a['geometry_pass']}\n"
        md += f"- **Masked Geometry Pass:** {a['masked_geometry_pass']}\n"
        md += f"- **Repeat Count:** {a['repeat_count']}\n"
        for r in a['repeats']:
            md += f"  - Block: `{r['seq']}` (Len: {r['len']})\n"
        md += "\n"
        
    (out_dir / "hit_authentication.md").write_text(md)
    print(md)

if __name__ == "__main__":
    main()
