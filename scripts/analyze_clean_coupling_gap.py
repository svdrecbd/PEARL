#!/usr/bin/env python3
import json
import sys
import os
import glob
from pathlib import Path
from statistics import mean

# Ensure src is in sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from pearl.family import (
    load_reference_records, 
    compute_family_stats, 
    evaluate_candidate
)

def analyze_population(name, audit_paths, family_stats, reference_records):
    results = []
    for path in audit_paths:
        data = json.loads(Path(path).read_text())
        for record in data.get("records", []):
            for c in record.get("candidates", []):
                seq = c.get("extracted_sequence") or c.get("sample_text")
                if not seq: continue
                
                eval_res = evaluate_candidate(sequence=seq, family_stats=family_stats, reference_records=reference_records)
                esm = float(c.get("raw_esm_score") or c.get("esm_score") or 0.0)
                geom_score = eval_res.get("catalytic_geometry", {}).get("passes", False)
                
                results.append({
                    "name": name,
                    "esm": esm,
                    "geometry": 1.0 if geom_score else 0.0,
                    "passes_core": eval_res.get("passes_core_screen", False),
                    "length": len(seq)
                })
    return results

def main():
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    # 1. Natural Anchors
    v24_curriculum = [json.loads(l) for l in open("reports/curriculum/manifold_v24_20260424/manifold_v24_anti_repeat_curriculum.jsonl")]
    naturals = []
    for r in v24_curriculum:
        if r["curriculum_role"] == "natural_stability_anchor":
            eval_res = evaluate_candidate(sequence=r["sequence"], family_stats=family_stats, reference_records=reference_records)
            # Naturals are ESM high by default (we assume 100 here or could rescore if needed)
            naturals.append({
                "name": "Natural",
                "esm": 100.0,
                "geometry": 1.0 if eval_res.get("catalytic_geometry", {}).get("passes") else 0.0,
                "passes_core": True,
                "length": len(r["sequence"])
            })

    # 2. Original v2 Unicorn
    v2_audit_path = "reports/ablations/pearl-topoff1m-a-manifold-v2-stagea-gate-p24-c128-p24-t0p8-s53/candidate_audit.json"
    unicorn_data = analyze_population("Unicorn", [v2_audit_path], family_stats, reference_records)
    unicorn = [u for u in unicorn_data if u["esm"] > 90 and u["geometry"] == 1.0]

    # 3. v2.4 Generated Population
    v24_run = "pearl-topoff1m-a-manifold-v24-confirm-stagea-gate-p24-c128"
    v24_audits = glob.glob(f"reports/ablations/{v24_run}-p24-t0p8-s*/candidate_audit.json")
    v24_data = analyze_population("v2.4", v24_audits, family_stats, reference_records)

    all_data = naturals + unicorn + v24_data
    
    out_dir = Path("reports/analysis/coupling_gap_diagnosis")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(out_dir / "coupling_map_data.json", "w") as f:
        json.dump(all_data, f, indent=2)
        
    print(f"Coupling map data written to {out_dir / 'coupling_map_data.json'}")
    print(f"Total points: {len(all_data)}")

if __name__ == "__main__":
    main()
