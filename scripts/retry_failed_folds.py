#!/usr/bin/env python3
import json
import sys
import math
import urllib.request
import urllib.error
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

def fold_sequence(seq: str, name: str, out_dir: Path) -> Path:
    out_path = out_dir / f"{name}.pdb"
    
    url = "https://api.esmatlas.com/foldSequence/v1/pdb/"
    print(f"[{name}] Retrying folding sequence via ESMAtlas API...")
    try:
        req = urllib.request.Request(url, data=seq.encode("utf-8"), method="POST")
        with urllib.request.urlopen(req, timeout=180) as response:
            pdb_data = response.read().decode("utf-8")
            out_path.write_text(pdb_data)
            return out_path
    except urllib.error.URLError as e:
        print(f"Error folding {name}: {e}")
        return None

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
                b_factor = float(line[60:66].strip())
                
                coords[res_seq] = (x, y, z)
                plddts.append(b_factor)
                
    mean_plddt = sum(plddts) / len(plddts) if plddts else 0.0
    if mean_plddt > 0 and mean_plddt <= 1.0:
        mean_plddt *= 100.0
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
    report_path = ROOT / "reports" / "ablations" / "phase8-bio-dpo-eval-fast-p12-t0p8-s7" / "report.json"
    if not report_path.exists():
        print(f"Error: Missing report.json at {report_path}")
        sys.exit(1)
        
    report = json.loads(report_path.read_text(encoding="utf-8"))
    records = report.get("records", [])
    
    out_dir = ROOT / "reports" / "ablations" / "phase8-bio-dpo-eval-fast-p12-t0p8-s7" / "folds"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    records_path = ROOT / "data" / "petase_family_expanded" / "petase_records.jsonl"
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    # We want to fold Step 4, Step 9, Step 11
    target_steps = {4, 9, 11}
    results = []
    
    # First, load cached results for Step 0 and Step 2 if they exist
    cached_steps = {0, 2}
    for step in cached_steps:
        name = f"DPO_Candidate_Step{step}"
        pdb_path = out_dir / f"{name}.pdb"
        if pdb_path.exists():
            coords, mean_plddt = parse_pdb(pdb_path)
            # recalculate triad dist
            for record in records:
                if int(record["step"]) == step:
                    seq = record["extracted_sequence"]
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
                        "step": step,
                        "name": name,
                        "mean_plddt": round(mean_plddt, 2),
                        "ser_asp_dist": round(ser_dist, 2) if ser_dist else None,
                        "asp_his_dist": round(asp_dist, 2) if asp_dist else None,
                        "ser_his_dist": round(his_dist, 2) if his_dist else None,
                        "sequence_geometry_passes": bool(geom["passes"]),
                        "ca_triad_distance_passes": ca_triad_passes,
                    })

    for record in records:
        step = int(record["step"])
        if step not in target_steps:
            continue
            
        seq = record["extracted_sequence"]
        name = f"DPO_Candidate_Step{step}"
        pdb_path = fold_sequence(seq, name, out_dir)
        
        if pdb_path and pdb_path.exists():
            coords, mean_plddt = parse_pdb(pdb_path)
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
                "step": step,
                "name": name,
                "mean_plddt": round(mean_plddt, 2),
                "ser_asp_dist": round(ser_dist, 2) if ser_dist else None,
                "asp_his_dist": round(asp_dist, 2) if asp_dist else None,
                "ser_his_dist": round(his_dist, 2) if his_dist else None,
                "sequence_geometry_passes": bool(geom["passes"]),
                "ca_triad_distance_passes": ca_triad_passes,
            })
        else:
            results.append({
                "step": step,
                "name": name,
                "mean_plddt": 0.0,
                "ser_asp_dist": None,
                "asp_his_dist": None,
                "ser_his_dist": None,
                "sequence_geometry_passes": False,
                "ca_triad_distance_passes": False,
            })
            
    results.sort(key=lambda r: r["step"])
    
    print("\n--- Downstream Fold Verification Results (Retried) ---")
    print(f"{'Design Name':<25} | {'Mean pLDDT':<10} | {'S-D Dist (A)':<12} | {'D-H Dist (A)':<12} | {'S-H Dist (A)':<12} | {'Triad Pass'}")
    print("-" * 90)
    for r in results:
        s_d = f"{r['ser_asp_dist']:.2f}" if r['ser_asp_dist'] else "N/A"
        d_h = f"{r['asp_his_dist']:.2f}" if r['asp_his_dist'] else "N/A"
        s_h = f"{r['ser_his_dist']:.2f}" if r['ser_his_dist'] else "N/A"
        print(f"{r['name']:<25} | {r['mean_plddt']:<10.2f} | {s_d:<12} | {d_h:<12} | {s_h:<12} | {str(r['ca_triad_distance_passes'])}")

if __name__ == "__main__":
    main()
