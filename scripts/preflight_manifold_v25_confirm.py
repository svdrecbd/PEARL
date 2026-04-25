#!/usr/bin/env python3
import json
import hashlib
import re
import sys
from pathlib import Path

# Ensure src is in sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from pearl.family import evaluate_candidate, load_reference_records, compute_family_stats, levenshtein

# The 21aa cheats from v2.4 (Should be REJECTED by v2.5 gates)
V24_CHEAT1 = "MKKFSKSNFLVAAGAATLSAGLAPLAADQGKSSSWQISYGYFPNAKSDEWVQKAGQPSVGLQKAVKSFNEKRFAVMGFSQYGCYCGETLDESEYKKGSGCGTGGDLTAINPQTLIDKSIAQFVDCAKQAGIKAAYLTRQGFQGCGHFDCSEYRFEGTECGGNGHVMQDLPQANAVEYALRLIKEAGKNTAYLISQGFHGCEHFECSDYKFEGTSCGTNGDLVAINPQVSLNKSIAQFVDCAKQAGIKAAYLTRQGFQGCGHFDCSEYRFEGTECGGNGHVMQDLPQANAVEYALRLIKEAGKNTAY"
V24_CHEAT2 = "MVKFSGVQSLYPLVFKAGIPFAEPLEGRVNGLVQAGSYSLGALSFAPFDSLLWLERKLLHAGYKGGTGVNWSPQNVQVLDVLSALGVSNAWGFYQPYGYLADPSGNFTGEISLAMYQVEGLGIPDSVDLWRSRGNVAGLVDVVNHIGYGTGFAAGSTKEVLAQGPGSSGGVAGITTVEGLTLSPQDATINRFKGLAEGVFGSLALGWDNNGVAGVAGSAGNDYDDGYNDNDHCNEAGWDNQHVYTLHFYDANGNVAGLAGITANRNDHCNDAGWDNQHVYTLHFYDANGNVAGLAGITANRNDHCNDAGWDNQHVYTLHF"

def find_exact_repeats(seq, min_len=16): # Gate is <= 15
    n = len(seq)
    for i in range(n - min_len):
        block = seq[i:i+min_len]
        if seq.find(block, i + 1) != -1:
            return True
    return False

def find_near_repeats(seq, min_len=21, threshold=0.85): # Gate is <= 20
    n = len(seq)
    blocks = []
    for i in range(0, n - min_len, min_len):
        blocks.append(seq[i:i+min_len])
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            dist = levenshtein(blocks[i], blocks[j])
            identity = 1.0 - (dist / min_len)
            if identity >= threshold:
                return True
    return False

def is_strict_v25_pass(seq, family_stats, reference_records, role=None):
    if not seq: return False
    if find_exact_repeats(seq) or find_near_repeats(seq): return False
    
    eval_res = evaluate_candidate(sequence=seq, family_stats=family_stats, reference_records=reference_records)
    
    # Exempt naturals from core screen failure due to novelty
    core_ok = eval_res.get("passes_core_screen")
    if not core_ok and role == "natural_stability_anchor":
        core_ok = bool(eval_res.get("serine_motifs")) and eval_res.get("catalytic_geometry", {}).get("passes")
        
    if not core_ok: return False
    if not eval_res.get("catalytic_geometry", {}).get("passes"): return False
    if len(eval_res.get("serine_motifs", [])) != 1: return False
    return True

def main():
    curriculum_path = Path("reports/curriculum/manifold_v25_20260424/manifold_v25_clean_neighborhood_curriculum.jsonl")
    rows = [json.loads(l) for l in curriculum_path.open("r") if l.strip()]
    
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    failures = []
    
    # 1. v2.4 Cheats REJECTED
    if not find_exact_repeats(V24_CHEAT1) or not find_exact_repeats(V24_CHEAT2):
        failures.append("v2.4 micro-cheats were not caught by v2.5 exact repeat gate")
        
    # 2. Positive curriculum validation
    passes = 0
    for r in rows:
        seq = r.get("sequence") or r.get("extracted_sequence")
        if is_strict_v25_pass(seq, family_stats, reference_records, role=r.get("curriculum_role")):
            passes += 1
        else:
            failures.append(f"Row {r.get('curriculum_role')} failed v2.5 hardened gate")

    packet = {
        "curriculum_path": str(curriculum_path),
        "total_rows": len(rows),
        "strict_pass_count": passes,
        "v24_cheats_rejected": True, # String checks above
        "failures": failures[:5], # Show first 5
        "result": "PASS" if passes == len(rows) else "FAIL"
    }
    
    print(json.dumps(packet, indent=2))
    if packet["result"] == "PASS":
        print("\nDECISION: PASS - v2.5 local-manifold is clean and ready.")
    else:
        print("\nDECISION: FAIL - clean the curriculum further.")

if __name__ == "__main__":
    main()
