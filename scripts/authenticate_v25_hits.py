#!/usr/bin/env python3
import json
import sys
import os
import glob
from pathlib import Path

# Ensure src is in sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from pearl.family import evaluate_candidate, load_reference_records, compute_family_stats, levenshtein

V2_UNICORN = "MGWSKRKMAAALAVVATLAAPAVAAPVAAVAPVAAASQGDAYVNGYTAGQWGPVYVLDSRFGRTFAVSGRNEFGDSGDPEIWVSDNGSALGQVSNHGANYSILLSNNSVLIEPGSVYAAVDSYNNYGNEYQIVYGDGDGDNGSPGDSEYFVAINAASNSQQTGSWADLVKDFGRQLAFAPLGLFCCSSSEYTVADGASAGLTPQSDQKVNFGWYAPAMYVDSRFGRTFGVAAANQYNGDAGDPEIWVQDYGSALGQVSNHGANYAILLSNNSVLIEPGSIYAAVDSYNNYGNE"

def find_exact_repeats(seq, min_len=16):
    n = len(seq)
    for i in range(n - min_len):
        block = seq[i:i+min_len]
        if seq.find(block, i + 1) != -1:
            return block
    return None

def main():
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    path = "reports/ablations/pearl-topoff1m-a-manifold-v25-neighborhood-stagea-gate-p24-c128-p24-t0p8-s41/candidate_audit.json"
    data = json.load(open(path))
    
    hits = []
    for r in data["records"]:
        for c in r["candidates"]:
            if c.get("functional_bridge_passes"):
                seq = c["extracted_sequence"]
                esm = float(c.get("raw_esm_score") or c.get("esm_score") or 0.0)
                eval_res = evaluate_candidate(sequence=seq, family_stats=family_stats, reference_records=reference_records)
                
                hits.append({
                    "step": r["step"],
                    "esm": esm,
                    "dist_to_unicorn": levenshtein(seq, V2_UNICORN),
                    "repeat": find_exact_repeats(seq),
                    "core_pass": c.get("passes_core_screen"),
                    "geometry_pass": c.get("geometry_passes"),
                    "sequence": seq
                })
                
    print(json.dumps(hits, indent=2))

if __name__ == "__main__":
    main()
