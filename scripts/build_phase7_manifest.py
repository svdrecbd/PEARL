#!/usr/bin/env python3
import json
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from pearl.family import (
    load_reference_records, 
    compute_family_stats, 
    evaluate_candidate,
    levenshtein
)

TRUE_UNICORN = "MYKSLVFIALLLSFTVLSAQASPLQSVQKLDGVVKAVVVDGVEGHIFAPQSFVMNLLEHDSVVKQGDVVKVEMPQTGLTFSDVANVYDSLKLGVHRVQVVGDHSLFANVSNFSYVGVQDSKAILSVQGASVSSVGSITVVAQSFRGVKANQLPVFVDRLDSASPFLSHYFPDPSVLDQELVKGVSVGMTMHAELSPQERSAMFAAIRDEVGDSKVDQVFVVKNEQFESVPEKLDVTVPVASQDHVWSMTFAPQSFVMNLLEHDSVVKQGDVVKVEMPQTGLTFSDVANVYDSLKLGVHRVQVV"

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

def check_topology_masking(seq, family_stats, reference_records):
    repeats = find_all_repeats(seq, min_len=8)
    if not repeats:
        return True
        
    masked_seq = list(seq)
    for r in repeats:
        for k in range(r["pos2"], r["pos2"] + r["len"]):
            masked_seq[k] = "X"
            
    masked_eval = evaluate_candidate(sequence="".join(masked_seq).replace("X", "A"), family_stats=family_stats, reference_records=reference_records)
    return masked_eval.get("catalytic_geometry", {}).get("passes", False)

def get_mutations(parent, child):
    muts = []
    for i, (a, b) in enumerate(zip(parent, child)):
        if a != b:
            muts.append(f"{a}{i+1}{b}")
    if len(parent) != len(child):
        muts.append("length_diff")
    return ",".join(muts)

def main():
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    panel_file = Path("reports/analysis/phase7_local_library_v1/validation_panel.jsonl")
    candidates = []
    with open(panel_file) as f:
        for i, line in enumerate(f):
            data = json.loads(line)
            data["candidate_id"] = f"CAND_{i+1:03d}"
            candidates.append(data)
            
    # Simple greedy clustering (threshold dist 3)
    clusters = {}
    cluster_id_counter = 1
    
    for c in candidates:
        seq = c["sequence"]
        assigned = False
        for cid, center in clusters.items():
            if levenshtein(seq, center) <= 5:
                c["cluster_id"] = cid
                assigned = True
                break
        if not assigned:
            clusters[cluster_id_counter] = seq
            c["cluster_id"] = cluster_id_counter
            cluster_id_counter += 1
            
    out_path = Path("reports/analysis/phase7_local_library_v1/candidate_manifest.tsv")
    
    with open(out_path, "w") as out:
        header = [
            "candidate_id", "sequence", "mutations_from_v2.5_Hit2", "mutation_positions", 
            "ESM2_score", "topology_masking_pass", "family_core_pass", "motif_pass", 
            "geometry_pass", "cluster_id", "nearest_panel_neighbor", "nearest_natural_neighbor"
        ]
        out.write("\t".join(header) + "\n")
        
        for i, c in enumerate(candidates):
            seq = c["sequence"]
            
            eval_res = evaluate_candidate(sequence=seq, family_stats=family_stats, reference_records=reference_records)
            
            mut_pos = get_mutations(TRUE_UNICORN, seq)
            
            top_pass = check_topology_masking(seq, family_stats, reference_records)
            core_pass = eval_res.get("passes_core_screen", False)
            motif_pass = len(eval_res.get("serine_motifs", [])) == 1
            geom_pass = eval_res.get("catalytic_geometry", {}).get("passes", False)
            
            # nearest panel neighbor
            nearest_dist = 9999
            nearest_id = ""
            for other in candidates:
                if other["candidate_id"] != c["candidate_id"]:
                    dist = levenshtein(seq, other["sequence"])
                    if dist < nearest_dist:
                        nearest_dist = dist
                        nearest_id = other["candidate_id"]
            
            nearest_natural = eval_res.get("novelty", {}).get("closest_edit_identity", 0)
            
            row = [
                c["candidate_id"],
                seq,
                str(c["dist_to_unicorn"]),
                mut_pos,
                f"{c['esm']:.2f}",
                str(top_pass),
                str(core_pass),
                str(motif_pass),
                str(geom_pass),
                str(c["cluster_id"]),
                f"{nearest_id} (d={nearest_dist})",
                f"{nearest_natural:.4f}"
            ]
            out.write("\t".join(row) + "\n")
            
    print(f"Manifest saved to {out_path}")

if __name__ == "__main__":
    main()
