#!/usr/bin/env python3
import json
import sys
import random
import os
import argparse
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from pearl.family import (
    load_reference_records, 
    compute_family_stats, 
    evaluate_candidate,
    levenshtein
)
from pearl.esm_proxy import get_esm2_plls

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
            if (1.0 - (dist / min_len)) >= threshold:
                found.append({"pos2": j, "len": min_len})
    return found

def is_topology_clean(seq, family_stats, reference_records):
    base_eval = evaluate_candidate(sequence=seq, family_stats=family_stats, reference_records=reference_records)
    if not base_eval.get("catalytic_geometry", {}).get("passes") or len(base_eval.get("serine_motifs", [])) != 1:
        return False
    if not base_eval.get("passes_core_screen"):
        return False
    
    repeats = find_all_repeats(seq, min_len=8)
    if not repeats:
        return True
        
    masked_seq = list(seq)
    for r in repeats:
        for k in range(r["pos2"], r["pos2"] + r["len"]):
            masked_seq[k] = "X"
            
    masked_eval = evaluate_candidate(sequence="".join(masked_seq).replace("X", "A"), family_stats=family_stats, reference_records=reference_records)
    return masked_eval.get("catalytic_geometry", {}).get("passes", False)

def mutate_sequence(seq, n_mutations=1):
    indices = random.sample(range(len(seq)), n_mutations)
    seq_list = list(seq)
    for idx in indices:
        seq_list[idx] = random.choice([aa for aa in AMINO_ACIDS if aa != seq_list[idx]])
    return "".join(seq_list)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generations", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--pool-size", type=int, default=20)
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()

    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    print("Starting Offline Local Library Design (Track 1)...")
    
    library = set()
    pool = [TRUE_UNICORN]
    
    total_evaluated = 0
    total_topology_passed = 0
    
    for gen in range(args.generations):
        print(f"\n--- Generation {gen+1}/{args.generations} ---")
        
        # Generate raw variants from the pool
        raw_variants = set()
        while len(raw_variants) < args.batch_size:
            parent = random.choice(pool)
            num_muts = random.choices([1, 2, 3], weights=[0.6, 0.3, 0.1])[0]
            child = mutate_sequence(parent, num_muts)
            raw_variants.add(child)
            
        # Filter by topology
        clean_variants = []
        for seq in raw_variants:
            total_evaluated += 1
            if is_topology_clean(seq, family_stats, reference_records):
                clean_variants.append(seq)
                total_topology_passed += 1
                
        print(f"Topology independent variants in this generation: {len(clean_variants)}")
        
        if not clean_variants:
            continue
            
        # Score ESM
        os.environ["ESM2_DEVICE"] = args.device
        esm_scores = get_esm2_plls(clean_variants)
        
        scored_candidates = []
        for seq, esm in zip(clean_variants, esm_scores):
            if esm >= 85.0:
                scored_candidates.append({"sequence": seq, "esm": esm})
                
        print(f"Survivors with ESM >= 85: {len(scored_candidates)}")
        
        for c in scored_candidates:
            # Add to library set
            library.add((c["sequence"], c["esm"]))
            
        # Update pool
        sorted_scored = sorted(scored_candidates, key=lambda x: x["esm"], reverse=True)
        for c in sorted_scored:
            if c["sequence"] not in pool:
                pool.append(c["sequence"])
                
        # Truncate pool to pool_size
        # Sort pool by ESM if possible, or just keep recent best
        pool = pool[:args.pool_size]
        
        print(f"Current library size: {len(library)}")
        
    print("\n--- Search Complete ---")
    print(f"Total sequences evaluated: {total_evaluated}")
    print(f"Total topology passed: {total_topology_passed}")
    
    # Cluster & Panel Selection
    final_panel = []
    sorted_library = sorted(list(library), key=lambda x: x[1], reverse=True)
    
    MIN_DISTANCE = 3
    for seq, esm in sorted_library:
        if all(levenshtein(seq, p["sequence"]) >= MIN_DISTANCE for p in final_panel):
            final_panel.append({"sequence": seq, "esm": esm, "dist_to_unicorn": levenshtein(seq, TRUE_UNICORN)})
            if len(final_panel) >= 96: # Max panel size
                break
                
    print(f"\nSelected final diverse panel of {len(final_panel)} candidates.")
    
    out_dir = Path("reports/analysis/phase7_local_library")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(out_dir / "full_library.jsonl", "w") as f:
        for seq, esm in sorted_library:
            f.write(json.dumps({"sequence": seq, "esm": esm, "dist_to_unicorn": levenshtein(seq, TRUE_UNICORN)}) + "\n")
            
    with open(out_dir / "validation_panel.jsonl", "w") as f:
        for c in final_panel:
            f.write(json.dumps(c) + "\n")
            
    with open(out_dir / "validation_panel.fasta", "w") as f:
        for i, c in enumerate(final_panel):
            f.write(f">candidate_{i+1:03d} | ESM={c['esm']:.2f} | Dist={c['dist_to_unicorn']}\n{c['sequence']}\n")
            
    summary = {
        "total_evaluated": total_evaluated,
        "total_topology_passed": total_topology_passed,
        "library_size": len(sorted_library),
        "panel_size": len(final_panel),
        "mean_panel_esm": mean([c["esm"] for c in final_panel]) if final_panel else 0.0,
        "mean_panel_dist": mean([c["dist_to_unicorn"] for c in final_panel]) if final_panel else 0.0
    }
    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
        
    print(f"Results saved to {out_dir}")

if __name__ == "__main__":
    main()
