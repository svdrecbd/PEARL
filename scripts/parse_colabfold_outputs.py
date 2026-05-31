#!/usr/bin/env python3
import json
import sys
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from pearl.family import assess_catalytic_geometry, load_reference_records, compute_family_stats

CA_TRIAD_DISTANCE_LIMITS = {
    "ser_asp": (4.0, 20.0),
    "asp_his": (4.0, 20.0),
    "ser_his": (4.0, 20.0),
}

def parse_pdb(pdb_path: Path):
    coords = {}
    plddts = []
    
    if not pdb_path or not pdb_path.exists():
        return coords, 0.0
        
    with open(pdb_path) as f:
        for line in f:
            if line.startswith("ATOM  ") and line[12:16].strip() == "CA":
                res_seq = int(line[22:26].strip())
                x = float(line[30:38].strip())
                y = float(line[38:46].strip())
                z = float(line[46:54].strip())
                b_factor = float(line[60:66].strip()) # pLDDT score
                
                coords[res_seq] = (x, y, z)
                plddts.append(b_factor)
                
    mean_plddt = sum(plddts) / len(plddts) if plddts else 0.0
    if mean_plddt > 0 and mean_plddt <= 1.0:
        mean_plddt *= 100.0 # Convert 0-1 scale to 0-100 scale
    return coords, mean_plddt

def dist(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2)

def in_range(value, lower, upper):
    return value is not None and lower <= value <= upper

def ca_triad_distance_passes(ser_asp, asp_his, ser_his):
    return (
        in_range(ser_asp, *CA_TRIAD_DISTANCE_LIMITS["ser_asp"])
        and in_range(asp_his, *CA_TRIAD_DISTANCE_LIMITS["asp_his"])
        and in_range(ser_his, *CA_TRIAD_DISTANCE_LIMITS["ser_his"])
    )

def main():
    colab_dir = ROOT / "reports" / "ablations" / "phase8-bio-dpo-eval-fast-p12-t0p8-s7" / "colabfold_results"
    
    if not colab_dir.exists():
        colab_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created ColabFold results directory at {colab_dir}")
        print("Please extract your ColabFold ZIP or PDB files into this folder and run the script again.")
        sys.exit(0)
        
    pdb_files = list(colab_dir.glob("*.pdb"))
    if not pdb_files:
        print(f"No PDB files found in {colab_dir}")
        print("Please place your ColabFold PDB files there.")
        sys.exit(0)
        
    records_path = ROOT / "data" / "petase_family_expanded" / "petase_records.jsonl"
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    report_path = ROOT / "reports" / "ablations" / "phase8-bio-dpo-eval-fast-p12-t0p8-s7" / "report.json"
    target_sequences = {}
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        for record in report.get("records", []):
            step = int(record["step"])
            target_sequences[f"DPO_Candidate_Step{step}"] = record["extracted_sequence"]
            
    # Add natural control reference sequence
    target_sequences["Natural_Cutinase_Ref"] = "MAVMTPRRERSSLLSRALQVTAAAATALVTAVSLAAPAHAANPYERGPNPTDALLEASSGPFSVSEENVSRLSASGFGGGTIYYPRENNTYGAVAISPGYTGTEASIAWLGERIASHGFVVITIDTITTLDQPDSRAEQLNAALNHMINRASSTVRSRIDSSRLAVMGHSMGGGGTLRLASQRPDLKAAIPLTPWHLNKNWSSVTVPTLIIGADLDTIAPVATHAKPFYNSLPSSISKAYLELDGATHFAPNIPNKIIGKYSVAWLKRFVDNDTRYTQFLCPGPRDGLFGEVEEYRSTCPF"

    # We match PDBs to our target candidates
    target_names = ["Natural_Cutinase_Ref", "DPO_Candidate_Step0", "DPO_Candidate_Step2", "DPO_Candidate_Step4", "DPO_Candidate_Step9", "DPO_Candidate_Step11"]
    
    # We want to identify the best PDB for each target
    # Rank 1 is preferred. Relaxed is preferred over unrelaxed if available.
    best_pdbs = {}
    for name in target_names:
        matched = []
        for pdb in pdb_files:
            # Match by case-insensitive check
            if name.lower() in pdb.name.lower():
                matched.append(pdb)
                
        if not matched:
            continue
            
        # Sort matched PDBs so that:
        # 1. rank_1 or rank_001 is preferred
        # 2. relaxed is preferred over unrelaxed
        def sort_key(p: Path):
            rank_match = re.search(r"rank_0*([1-5])", p.name, re.IGNORECASE)
            rank = int(rank_match.group(1)) if rank_match else 99
            
            is_relaxed = 0 if "relaxed" in p.name.lower() and "unrelaxed" not in p.name.lower() else 1
            return (rank, is_relaxed)
            
        matched.sort(key=sort_key)
        best_pdbs[name] = matched[0]
        
    if not best_pdbs:
        print("Error: Found PDB files but none matched target candidate names:")
        print(f"Expected targets: {target_names}")
        print(f"Found files: {[p.name for p in pdb_files[:10]]}")
        sys.exit(1)
        
    results = []
    for name in target_names:
        if name not in best_pdbs:
            continue
            
        pdb_path = best_pdbs[name]
        print(f"Analyzing {name} using: {pdb_path.name}")
        coords, mean_plddt = parse_pdb(pdb_path)
        
        seq = target_sequences.get(name)
        if not seq:
            print(f"Warning: Sequence for {name} not found in ablation records. Skipping triad calculations.")
            results.append({
                "name": name,
                "pdb_file": pdb_path.name,
                "mean_plddt": round(mean_plddt, 2),
                "ser_asp_dist": None,
                "asp_his_dist": None,
                "ser_his_dist": None,
                "ca_triad_distance_passes": False
            })
            continue
            
        geom = assess_catalytic_geometry(seq, family_stats)
        
        ser_dist = asp_dist = his_dist = None
        if geom["serine_hits"] and geom["aspartate_hits"] and geom["histidine_hits"]:
            s_idx = geom["serine_hits"][0]
            a_idx = geom["aspartate_hits"][0]
            h_idx = geom["histidine_hits"][0]
            
            if s_idx in coords and a_idx in coords and h_idx in coords:
                ser_dist = dist(coords[s_idx], coords[a_idx])
                asp_dist = dist(coords[a_idx], coords[h_idx])
                his_dist = dist(coords[s_idx], coords[h_idx])
                
        ca_triad_passes = ca_triad_distance_passes(ser_dist, asp_dist, his_dist)
        
        results.append({
            "name": name,
            "pdb_file": pdb_path.name,
            "mean_plddt": round(mean_plddt, 2),
            "ser_asp_dist": round(ser_dist, 2) if ser_dist else None,
            "asp_his_dist": round(asp_dist, 2) if asp_dist else None,
            "ser_his_dist": round(his_dist, 2) if his_dist else None,
            "ca_triad_distance_passes": ca_triad_passes,
        })
        
    out_json = colab_dir / "colabfold_metrics.json"
    out_json.write_text(json.dumps(results, indent=2))
    
    print("\n" + "="*95)
    print(" "*25 + "HIGH-FIDELITY COLABFOLD VERIFICATION RESULTS")
    print("="*95)
    print(f"{'Design Name':<25} | {'Mean pLDDT':<10} | {'S-D Dist (A)':<12} | {'D-H Dist (A)':<12} | {'S-H Dist (A)':<12} | {'Triad Pass'}")
    print("-" * 95)
    for r in results:
        s_d = f"{r['ser_asp_dist']:.2f}" if r['ser_asp_dist'] else "N/A"
        d_h = f"{r['asp_his_dist']:.2f}" if r['asp_his_dist'] else "N/A"
        s_h = f"{r['ser_his_dist']:.2f}" if r['ser_his_dist'] else "N/A"
        print(f"{r['name']:<25} | {r['mean_plddt']:<10.2f} | {s_d:<12} | {d_h:<12} | {s_h:<12} | {str(r['ca_triad_distance_passes'])}")
    print("="*95)
    print(f"Metrics saved to: {out_json}\n")

if __name__ == "__main__":
    main()
