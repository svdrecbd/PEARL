#!/usr/bin/env python3
import json
import sys
import random
import os
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
    AA_PATTERN,
    find_serine_motifs,
    levenshtein
)
from pearl.esm_proxy import get_esm2_plddt_scores

V2_UNICORN = "MGWSKRKMAAALAVVATLAAPAVAAPVAAVAPVAAASQGDAYVNGYTAGQWGPVYVLDSRFGRTFAVSGRNEFGDSGDPEIWVSDNGSALGQVSNHGANYSILLSNNSVLIEPGSVYAAVDSYNNYGNEYQIVYGDGDGDNGSPGDSEYFVAINAASNSQQTGSWADLVKDFGRQLAFAPLGLFCCSSSEYTVADGASAGLTPQSDQKVNFGWYAPAMYVDSRFGRTFGVAAANQYNGDAGDPEIWVQDYGSALGQVSNHGANYAILLSNNSVLIEPGSIYAAVDSYNNYGNE"
AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"

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

def mutate_sequence(seq, n_mutations=2):
    mutable_indices = list(range(len(seq)))
    # Exclude catalytic triad regions if known (simplified: exclude around known serine 198 etc)
    # For now, just random to see if we can find any.
    indices = random.sample(mutable_indices, n_mutations)
    seq_list = list(seq)
    for idx in indices:
        current_aa = seq_list[idx]
        new_aa = random.choice([aa for aa in AMINO_ACIDS if aa != current_aa])
        seq_list[idx] = new_aa
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
    
    print(f"Generating {args.num_variants} local variants around v2 Unicorn...")
    
    variants = set()
    # Mix of 1, 2, and 3 mutations
    while len(variants) < args.num_variants:
        n = random.choices([1, 2, 3], weights=[0.5, 0.4, 0.1])[0]
        variants.add(mutate_sequence(V2_UNICORN, n))
    
    variant_list = list(variants)
    
    # Pre-filter for repeats and motifs
    candidates = []
    print("Pre-filtering for repeats and motifs...")
    for seq in variant_list:
        if find_exact_repeats(seq) or find_near_repeats(seq):
            continue
        motifs = find_serine_motifs(seq)
        if len(motifs) != 1:
            continue
        candidates.append(seq)
        
    print(f"{len(candidates)} candidates passed pre-filter.")
    
    # Score ESM in batches
    print(f"Scoring ESM for {len(candidates)} candidates on {args.device}...")
    os.environ["ESM2_DEVICE"] = args.device
    esm_scores = get_esm2_plddt_scores(candidates)
    
    # Final Hard Gate Validation
    survivors = []
    for seq, esm in zip(candidates, esm_scores):
        if esm < 85.0:
            continue
            
        eval_res = evaluate_candidate(sequence=seq, family_stats=family_stats, reference_records=reference_records)
        if eval_res.get("passes_core_screen") and eval_res.get("catalytic_geometry", {}).get("passes"):
            survivors.append({
                "sequence": seq,
                "esm_score": esm,
                "dist_to_unicorn": levenshtein(seq, V2_UNICORN),
                "family_assessment": eval_res
            })
            
    print(f"Found {len(survivors)} clean survivors!")
    
    out_dir = Path("reports/analysis/manifold_v25_neighborhood_construction")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(out_dir / "clean_neighborhood_survivors.jsonl", "w") as f:
        for s in survivors:
            f.write(json.dumps(s) + "\n")
            
    summary = {
        "num_searched": args.num_variants,
        "num_prefiltered": len(candidates),
        "num_survivors": len(survivors),
        "mean_esm_survivors": mean([s["esm_score"] for s in survivors]) if survivors else 0.0,
        "output_path": str(out_dir / "clean_neighborhood_survivors.jsonl")
    }
    
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    from statistics import mean
    main()
