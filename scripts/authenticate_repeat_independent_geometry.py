#!/usr/bin/env python3
import json
import sys
import os
from pathlib import Path

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

def find_all_repeats(seq, min_len=8, threshold=0.85):
    """Finds exact and near repeats of at least min_len."""
    n = len(seq)
    found = []
    # Check all pairs of non-overlapping windows for identity
    for i in range(0, n - min_len):
        for j in range(i + min_len, n - min_len):
            w1 = seq[i:i+min_len]
            w2 = seq[j:j+min_len]
            dist = levenshtein(w1, w2)
            identity = 1.0 - (dist / min_len)
            if identity >= threshold:
                found.append({
                    "pos1": i,
                    "pos2": j,
                    "len": min_len,
                    "identity": identity,
                    "seq1": w1,
                    "seq2": w2
                })
    return found

def authenticate_repeat_independence(seq, family_stats, reference_records, min_repeat_len=8):
    # 1. Base evaluation
    base_eval = evaluate_candidate(sequence=seq, family_stats=family_stats, reference_records=reference_records)
    if not base_eval.get("catalytic_geometry", {}).get("passes"):
        return {"status": "FAIL_BASE_GEOMETRY"}
        
    # 2. Detect repeats (using a lower floor of 8aa to catch even small duplications)
    repeats = find_all_repeats(seq, min_len=min_repeat_len)
    
    if not repeats:
        return {"status": "CLEAN_INDEPENDENT_HIT", "base_eval": base_eval}

    # 3. Repeat-Dependent Geometry Check
    # We mask the *second* occurrence of every detected repeat block
    masked_seq = list(seq)
    for r in repeats:
        for k in range(r["pos2"], r["pos2"] + r["len"]):
            masked_seq[k] = "X"
            
    masked_seq_str = "".join(masked_seq).replace("X", "A") # Use A for alphabet sanity
    masked_eval = evaluate_candidate(sequence=masked_seq_str, family_stats=family_stats, reference_records=reference_records)
    
    geometry_survives = masked_eval.get("catalytic_geometry", {}).get("passes", False)
    
    if geometry_survives:
        return {
            "status": "CLEAN_INDEPENDENT_HIT", # Even with repeats, they aren't needed for geometry
            "repeat_info": f"Found {len(repeats)} repeat blocks, but geometry survives masking.",
            "base_eval": base_eval
        }
    else:
        return {
            "status": "REPEAT_DEPENDENT_ARTIFACT",
            "repeat_info": f"Found {len(repeats)} repeat blocks. Masking them breaks catalytic geometry.",
            "repeats": repeats[:5] # Sample
        }

def main():
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    # 1. Re-verify v2 Unicorn
    v2_audit = json.load(open("reports/ablations/pearl-topoff1m-a-manifold-v2-stagea-gate-p24-c128-p24-t0p8-s53/candidate_audit.json"))
    v2_unicorn = next(c["extracted_sequence"] for r in v2_audit["records"] for c in r["candidates"] if c.get("functional_bridge_passes"))
    
    print("Authenticating v2 Unicorn...")
    unicorn_auth = authenticate_repeat_independence(v2_unicorn, family_stats, reference_records)
    print(f"Result: {unicorn_auth['status']}")

    # 2. Verify v2.5 Hits
    v25_hits = [
        "MFNVTVLAAGLLAAVAAPAAAQVTVSFGDSITHGLWPTNGLSLDLAGQAVLDDYNGDLQFWSGNNGGSRENYVNASGGSNLGSGFNSDSQTLAKWLKAQGPASNAKLTTYSVQDNGGVHSDALQQAVDAAAAQILGVLGVTYDVFGNSNTGYFASQLAGHAPAVDFAANNDLVYMTSSTYGSNGSGHGSLSIGSIGGSKGDSLSLDGGGNTYASQDIQKAVDAAVAQILGVLGVTYDVFGNSNTGYFASQLAGHAPAVDFAANNDLVYMTSSTYGSNGSGHGSLSIGSIGG",
        "MYKSLVFIALLLSFTVLSAQASPLQSVQKLDGVVKAVVVDGVEGHIFAPQSFVMNLLEHDSVVKQGDVVKVEMPQTGLTFSDVANVYDSLKLGVHRVQVVGDHSLFANVSNFSYVGVQDSKAILSVQGASVSSVGSITVVAQSFRGVKANQLPVFVDRLDSASPFLSHYFPDPSVLDQELVKGVSVGMTMHAELSPQERSAMFAAIRDEVGDSKVDQVFVVKNEQFESVPEKLDVTVPVASQDHVWSMTFAPQSFVMNLLEHDSVVKQGDVVKVEMPQTGLTFSDVANVYDSLKLGVHRVQVV"
    ]
    
    for i, seq in enumerate(v25_hits):
        print(f"\nAuthenticating v2.5 Hit {i+1}...")
        res = authenticate_repeat_independence(seq, family_stats, reference_records)
        print(f"Result: {res['status']}")
        if "repeat_info" in res: print(f"Info: {res['repeat_info']}")

if __name__ == "__main__":
    main()
