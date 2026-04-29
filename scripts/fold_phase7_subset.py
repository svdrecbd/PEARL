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

from pearl.family import (
    load_reference_records, 
    compute_family_stats, 
    assess_catalytic_geometry
)

TRUE_UNICORN = "MYKSLVFIALLLSFTVLSAQASPLQSVQKLDGVVKAVVVDGVEGHIFAPQSFVMNLLEHDSVVKQGDVVKVEMPQTGLTFSDVANVYDSLKLGVHRVQVVGDHSLFANVSNFSYVGVQDSKAILSVQGASVSSVGSITVVAQSFRGVKANQLPVFVDRLDSASPFLSHYFPDPSVLDQELVKGVSVGMTMHAELSPQERSAMFAAIRDEVGDSKVDQVFVVKNEQFESVPEKLDVTVPVASQDHVWSMTFAPQSFVMNLLEHDSVVKQGDVVKVEMPQTGLTFSDVANVYDSLKLGVHRVQVV"
V2_UNICORN = "MGWSKRKMAAALAVVATLAAPAVAAPVAAVAPVAAASQGDAYVNGYTAGQWGPVYVLDSRFGRTFAVSGRNEFGDSGDPEIWVSDNGSALGQVSNHGANYSILLSNNSVLIEPGSVYAAVDSYNNYGNEYQIVYGDGDGDNGSPGDSEYFVAINAASNSQQTGSWADLVKDFGRQLAFAPLGLFCCSSSEYTVADGASAGLTPQSDQKVNFGWYAPAMYVDSRFGRTFGVAAANQYNGDAGDPEIWVQDYGSALGQVSNHGANYAILLSNNSVLIEPGSIYAAVDSYNNYGNE"
NATURAL_REF = "MAVMTPRRERSSLLSRALQVTAAAATALVTAVSLAAPAHAANPYERGPNPTDALLEASSGPFSVSEENVSRLSASGFGGGTIYYPRENNTYGAVAISPGYTGTEASIAWLGERIASHGFVVITIDTITTLDQPDSRAEQLNAALNHMINRASSTVRSRIDSSRLAVMGHSMGGGGTLRLASQRPDLKAAIPLTPWHLNKNWSSVTVPTLIIGADLDTIAPVATHAKPFYNSLPSSISKAYLELDGATHFAPNIPNKIIGKYSVAWLKRFVDNDTRYTQFLCPGPRDGLFGEVEEYRSTCPF"
STRUCTURAL_PLDDT_GATE = 70.0
CA_TRIAD_DISTANCE_LIMITS = {
    "ser_asp": (4.0, 20.0),
    "asp_his": (4.0, 20.0),
    "ser_his": (4.0, 20.0),
}

def fold_sequence(seq: str, name: str, out_dir: Path) -> Path:
    out_path = out_dir / f"{name}.pdb"
    if out_path.exists():
        return out_path
    
    url = "https://api.esmatlas.com/foldSequence/v1/pdb/"
    print(f"Folding {name} via ESMAtlas API...")
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
                b_factor = float(line[60:66].strip()) # ESMFold stores pLDDT here
                
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
    out_dir = Path("reports/analysis/phase7_local_library_v1/folds")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    # Get v2.3 artifact
    v23_audit_path = Path("reports/ablations/pearl-topoff1m-a-manifold-v23-lock-stagea-gate-p24-c128-p24-t0p8-s41/candidate_audit.json")
    v23_artifact = ""
    if v23_audit_path.exists():
        audit = json.loads(v23_audit_path.read_text())
        for r in audit["records"]:
            for c in r["candidates"]:
                if c.get("functional_bridge_passes"):
                    v23_artifact = c["extracted_sequence"]
                    break
            if v23_artifact: break
            
    # Get panel subset
    manifest_path = Path("reports/analysis/phase7_local_library_v1/candidate_manifest.tsv")
    panel_seqs = []
    with open(manifest_path) as f:
        next(f) # skip header
        for i, line in enumerate(f):
            if i >= 10: break
            parts = line.strip().split("\t")
            panel_seqs.append((parts[0], parts[1]))
            
    targets = [
        ("True_Unicorn_v1", TRUE_UNICORN),
        ("Old_v2_Unicorn_Artifact", V2_UNICORN),
        ("Natural_Cutinase_Ref", NATURAL_REF),
    ]
    if v23_artifact:
        targets.append(("v2.3_Repeat_Artifact", v23_artifact))
        
    targets.extend(panel_seqs)
    
    results = []
    for name, seq in targets:
        pdb_path = fold_sequence(seq, name, out_dir)
        coords, mean_plddt = parse_pdb(pdb_path)
        
        geom = assess_catalytic_geometry(seq, family_stats)
        
        ser_dist = asp_dist = his_dist = None
        s_idx, a_idx, h_idx = None, None, None
        
        if geom["serine_hits"] and geom["aspartate_hits"] and geom["histidine_hits"]:
            s_idx = geom["serine_hits"][0]
            a_idx = geom["aspartate_hits"][0]
            h_idx = geom["histidine_hits"][0]
            
            if s_idx in coords and a_idx in coords and h_idx in coords:
                ser_dist = dist(coords[s_idx], coords[a_idx])
                asp_dist = dist(coords[a_idx], coords[h_idx])
                his_dist = dist(coords[s_idx], coords[h_idx])
                
        sequence_geometry_passes = bool(geom["passes"])
        ca_triad_passes = ca_triad_distance_passes(ser_dist, asp_dist, his_dist)
        structure_confident = mean_plddt >= STRUCTURAL_PLDDT_GATE
        structural_gate_passes = structure_confident and ca_triad_passes

        results.append({
            "name": name,
            "mean_plddt": round(mean_plddt, 2),
            "ser_asp_dist": round(ser_dist, 2) if ser_dist else None,
            "asp_his_dist": round(asp_dist, 2) if asp_dist else None,
            "ser_his_dist": round(his_dist, 2) if his_dist else None,
            "sequence_geometry_passes": sequence_geometry_passes,
            "ca_triad_distance_passes": ca_triad_passes,
            "structure_confident": structure_confident,
            "structural_gate_passes": structural_gate_passes,
            "geometry_passes": structural_gate_passes,
        })
        
    out_json = out_dir / "fold_metrics.json"
    out_json.write_text(json.dumps(results, indent=2))
    
    print("\n--- Folding & Structural Metrics ---")
    for r in results:
        print(
            f"[{r['name']}] pLDDT: {r['mean_plddt']} | "
            f"S-A: {r['ser_asp_dist']}A, A-H: {r['asp_his_dist']}A | "
            f"Sequence geom: {r['sequence_geometry_passes']} | "
            f"Structural gate: {r['structural_gate_passes']}"
        )
        
    print(f"\nAll data saved to {out_dir}")

if __name__ == "__main__":
    main()
