#!/usr/bin/env python3
import json
import sys
from pathlib import Path

# Ensure src is in sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from pearl.family import evaluate_candidate, load_reference_records, compute_family_stats, levenshtein

def find_all_repeats(seq, min_len=8, threshold=0.85):
    n = len(seq)
    for i in range(0, n - min_len):
        for j in range(i + min_len, n - min_len):
            w1 = seq[i:i+min_len]
            w2 = seq[j:j+min_len]
            dist = levenshtein(w1, w2)
            if (1.0 - (dist / min_len)) >= threshold: return True
    return False

def is_topology_clean(seq, family_stats, reference_records, role):
    # Natural anchors novelty check bypass
    eval_res = evaluate_candidate(sequence=seq, family_stats=family_stats, reference_records=reference_records)
    core_ok = eval_res.get("passes_core_screen")
    if not core_ok and role == "natural_stability_anchor":
        core_ok = bool(eval_res.get("serine_motifs")) and eval_res.get("catalytic_geometry", {}).get("passes")
    
    if not core_ok or not eval_res.get("catalytic_geometry", {}).get("passes"): return False
    
    # Geometry survival after masking
    repeats = []
    n = len(seq)
    for i in range(0, n - 8):
        for j in range(i + 8, n - 8):
            if (1.0 - (levenshtein(seq[i:i+8], seq[j:j+8])/8.0)) >= 0.85:
                repeats.append((j, 8))
    
    if not repeats: return True
    masked = list(seq)
    for pos, l in repeats:
        for k in range(pos, pos+l): masked[k] = "X"
    
    masked_eval = evaluate_candidate(sequence="".join(masked).replace("X", "A"), family_stats=family_stats, reference_records=reference_records)
    return masked_eval.get("catalytic_geometry", {}).get("passes", False)

def main():
    curriculum_path = Path("reports/curriculum/manifold_v26_20260424/manifold_v26_true_clean_manifold_curriculum.jsonl")
    rows = [json.loads(l) for l in curriculum_path.open("r") if l.strip()]
    
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    passes = 0
    failures = []
    for r in rows:
        if is_topology_clean(r["sequence"], family_stats, reference_records, r.get("curriculum_role")):
            passes += 1
        else:
            failures.append(f"Row {r.get('curriculum_role')} failed topology-independence check")
            
    # Check Negatives REJECTED
    neg_path = Path("reports/analysis/topology_authentication/hard_negatives_final.jsonl")
    neg_rows = [json.loads(l) for l in neg_path.open("r") if l.strip()]
    rejected_negs = sum(1 for n in neg_rows if not is_topology_clean(n["sequence"], family_stats, reference_records, "negative"))
    
    packet = {
        "total_rows": len(rows),
        "strict_pass_count": passes,
        "negatives_rejected": rejected_negs,
        "total_negatives": len(neg_rows),
        "result": "PASS" if (passes == len(rows) and rejected_negs == len(neg_rows)) else "FAIL",
        "failures": failures[:5]
    }
    print(json.dumps(packet, indent=2))
    if packet["result"] == "PASS":
        print("\nDECISION: PASS - v2.6 clean-room curriculum verified.")
    else:
        print("\nDECISION: FAIL - check masking/repeat logic.")

if __name__ == "__main__":
    main()
