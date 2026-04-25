#!/usr/bin/env python3
import json
import sys
import random
import os
from pathlib import Path
from statistics import mean

# Ensure src is in sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from pearl.family import (
    load_reference_records, 
    compute_family_stats, 
    evaluate_candidate,
    levenshtein,
    find_serine_motifs
)
from pearl.esm_proxy import get_esm2_plddt_scores

# v2.5-Hit2 (True Unicorn v1)
TRUE_UNICORN = "MYKSLVFIALLLSFTVLSAQASPLQSVQKLDGVVKAVVVDGVEGHIFAPQSFVMNLLEHDSVVKQGDVVKVEMPQTGLTFSDVANVYDSLKLGVHRVQVVGDHSLFANVSNFSYVGVQDSKAILSVQGASVSSVGSITVVAQSFRGVKANQLPVFVDRLDSASPFLSHYFPDPSVLDQELVKGVSVGMTMHAELSPQERSAMFAAIRDEVGDSKVDQVFVVKNEQFESVPEKLDVTVPVASQDHVWSMTFAPQSFVMNLLEHDSVVKQGDVVKVEMPQTGLTFSDVANVYDSLKLGVHRVQVV"
AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"

def find_all_repeats(seq, min_len=8, threshold=0.85):
    n = len(seq)
    found = []
    for i in range(0, n - min_len):
        for j in range(i + min_len, n - min_len):
            w1 = seq[i:i+min_len]
            w2 = seq[j:j+min_len]
            dist = levenshtein(w1, w2)
            identity = 1.0 - (dist / min_len)
            if identity >= threshold:
                found.append({"pos2": j, "len": min_len})
    return found

def is_topology_clean(seq, family_stats, reference_records):
    # Base check
    base_eval = evaluate_candidate(sequence=seq, family_stats=family_stats, reference_records=reference_records)
    if not base_eval.get("catalytic_geometry", {}).get("passes") or len(base_eval.get("serine_motifs", [])) != 1:
        return False
    
    # Repeat dependency check
    repeats = find_all_repeats(seq, min_len=8)
    if not repeats:
        return True
        
    masked_seq = list(seq)
    for r in repeats:
        for k in range(r["pos2"], r["pos2"] + r["len"]):
            masked_seq[k] = "X"
    
    masked_eval = evaluate_candidate(sequence="".join(masked_seq).replace("X", "A"), family_stats=family_stats, reference_records=reference_records)
    return masked_eval.get("catalytic_geometry", {}).get("passes", False)

def mutate_sequence(seq, n_mutations=2):
    indices = random.sample(range(len(seq)), n_mutations)
    seq_list = list(seq)
    for idx in indices:
        seq_list[idx] = random.choice([aa for aa in AMINO_ACIDS if aa != seq_list[idx]])
    return "".join(seq_list)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-variants", type=int, default=1000)
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()

    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    print(f"Generating local variants around True Unicorn v1...")
    variants = set()
    while len(variants) < args.num_variants:
        n = random.choices([1, 2, 3], weights=[0.5, 0.4, 0.1])[0]
        variants.add(mutate_sequence(TRUE_UNICORN, n))
    
    variant_list = list(variants)
    candidates = []
    print("Pre-filtering for topology independence...")
    for seq in variant_list:
        if is_topology_clean(seq, family_stats, reference_records):
            candidates.append(seq)
            
    print(f"{len(candidates)} candidates passed topology pre-filter.")
    
    if not candidates:
        print("No candidates passed topology filter. Try more variants.")
        return

    # Batch ESM scoring
    print(f"Scoring ESM for {len(candidates)} candidates on {args.device}...")
    os.environ["ESM2_DEVICE"] = args.device
    esm_scores = get_esm2_plddt_scores(candidates)
    
    survivors = []
    for seq, esm in zip(candidates, esm_scores):
        if esm >= 85.0:
            survivors.append({
                "sequence": seq,
                "esm_score": esm,
                "dist_to_hit2": levenshtein(seq, TRUE_UNICORN)
            })
            
    print(f"Found {len(survivors)} clean topology-independent survivors!")
    
    out_dir = Path("reports/analysis/manifold_v26_neighborhood_construction")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "clean_neighborhood_survivors.jsonl", "w") as f:
        for s in survivors:
            f.write(json.dumps(s) + "\n")
            
    summary = {
        "num_searched": args.num_variants,
        "num_survivors": len(survivors),
        "mean_esm_survivors": mean([s["esm_score"] for s in survivors]) if survivors else 0.0,
        "output_path": str(out_dir / "clean_neighborhood_survivors.jsonl")
    }
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
