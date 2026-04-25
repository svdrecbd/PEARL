#!/usr/bin/env python3
import json
import sys
import os
import glob
import math
from pathlib import Path
from statistics import mean
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
    find_serine_motifs
)
from pearl.esm_proxy import get_esm2_plddt_scores

V2_UNICORN = "MGWSKRKMAAALAVVATLAAPAVAAPVAAVAPVAAASQGDAYVNGYTAGQWGPVYVLDSRFGRTFAVSGRNEFGDSGDPEIWVSDNGSALGQVSNHGANYSILLSNNSVLIEPGSVYAAVDSYNNYGNEYQIVYGDGDGDNGSPGDSEYFVAINAASNSQQTGSWADLVKDFGRQLAFAPLGLFCCSSSEYTVADGASAGLTPQSDQKVNFGWYAPAMYVDSRFGRTFGVAAANQYNGDAGDPEIWVQDYGSALGQVSNHGANYAILLSNNSVLIEPGSIYAAVDSYNNYGNE"

def levenshtein(s1, s2):
    if len(s1) < len(s2): return levenshtein(s2, s1)
    if len(s2) == 0: return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def analyze_v23_results(audit_paths, family_stats, reference_records, device="mps"):
    all_candidates = []
    
    for path in audit_paths:
        path = Path(path)
        if not path.exists(): continue
        with open(path, "r") as f:
            data = json.load(f)
        for record in data.get("records", []):
            prompt = record.get("prompt")
            step = record.get("step")
            for c in record.get("candidates", []):
                seq = c.get("extracted_sequence") or c.get("sample_text")
                if not seq: continue
                c["seq"] = seq
                c["prompt"] = prompt
                c["step"] = step
                all_candidates.append(c)

    if not all_candidates:
        return "No candidates found to analyze."

    print(f"Analyzing {len(all_candidates)} candidates...")
    
    # Layer 1 & 2: Stability and Geometry Pre-score
    geometry_passes = []
    stability_dominant = 0
    total = len(all_candidates)
    
    # We need to score ESM for a subset at least to get distribution
    # For triage, we will score top candidates by stage1/stage2 scores
    all_candidates.sort(key=lambda x: x.get("stage2_score", 0), reverse=True)
    top_candidates = all_candidates[:500] # Score top 500 for detailed triage
    
    print(f"Scoring ESM for top 500 candidates...")
    os.environ["ESM2_DEVICE"] = device
    sequences = [c["seq"] for c in top_candidates]
    esm_scores = get_esm2_plddt_scores(sequences)
    
    for c, score in zip(top_candidates, esm_scores):
        c["esm_score"] = score
        
        # Evaluate family and geometry
        eval_res = evaluate_candidate(
            sequence=c["seq"],
            family_stats=family_stats,
            reference_records=reference_records
        )
        c["eval"] = eval_res
        
        if eval_res.get("catalytic_geometry", {}).get("passes"):
            c["geometry_pass"] = True
        else:
            c["geometry_pass"] = False
            
        if score >= 85.0:
            c["stability_pass"] = True
        else:
            c["stability_pass"] = False

    # Layer 3: Unicorn Basin Check
    hits = []
    for c in top_candidates:
        if c.get("geometry_pass") and c.get("stability_pass") and c["eval"].get("serine_motif_count") == 1:
            c["dist_to_unicorn"] = levenshtein(c["seq"], V2_UNICORN)
            hits.append(c)

    # Summary Generation
    mean_esm = mean([c["esm_score"] for c in top_candidates])
    geom_rate = sum(1 for c in top_candidates if c.get("geometry_pass")) / len(top_candidates)
    stab_rate = sum(1 for c in top_candidates if c.get("stability_pass")) / len(top_candidates)
    
    report = {
        "metrics": {
            "mean_esm_top_500": mean_esm,
            "geometry_pass_rate_top_500": geom_rate,
            "stability_pass_rate_top_500": stab_rate,
            "functional_bridge_hits": len(hits)
        },
        "hits": [
            {
                "candidate_id": h.get("sequence_id", "unknown"),
                "esm": h["esm_score"],
                "dist_to_unicorn": h["dist_to_unicorn"],
                "step": h["step"],
                "prompt_match": "exact" if h["prompt"].strip() == V2_UNICORN.strip() else "neighbor"
            } for h in hits
        ]
    }
    
    return report

def main():
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    run_name = "pearl-topoff1m-a-manifold-v23-lock-stagea-gate-p24-c128"
    audit_pattern = f"reports/ablations/{run_name}-p24-t0p8-s*/candidate_audit.json"
    audit_paths = glob.glob(audit_pattern)
    
    output_dir = Path("reports/analysis/v23_post_run_diagnostic")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if not audit_paths:
        print("Waiting for audits to be generated...")
        return

    report = analyze_v23_results(audit_paths, family_stats, reference_records)
    
    with open(output_dir / "diagnostic_report.json", "w") as f:
        json.dump(report, f, indent=2)
    
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
