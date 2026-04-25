#!/usr/bin/env python3
import json
import sys
import os
import glob
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

def triage_seed(ablation_dir, family_stats, reference_records, device="mps"):
    ablation_dir = Path(ablation_dir)
    audit_path = ablation_dir / "candidate_audit.json"
    if not audit_path.exists():
        print(f"Audit not found: {audit_path}")
        return None
        
    with open(audit_path, "r") as f:
        data = json.load(f)
        
    records = data.get("records", [])
    all_triage_results = []
    
    # Trackers
    functional_bridge_hits = []
    geometry_pass_count = 0
    stability_pass_count = 0
    intersection_pass_count = 0
    
    print(f"Processing {len(records)} records in {ablation_dir.name}...")
    
    for record in records:
        step = record.get("step")
        prompt = record.get("prompt")
        req_len = record.get("requested_length") or 0
        
        candidates = record.get("candidates", [])
        for c in candidates:
            seq = c.get("extracted_sequence") or c.get("sample_text")
            if not seq: continue
            
            # Stage 0: Basic Filters
            valid_aa = bool(AA_PATTERN.fullmatch(seq))
            len_delta = abs(len(seq) - req_len) if req_len > 0 else 0
            motifs = find_serine_motifs(seq)
            motif_count = len(motifs)
            
            if not valid_aa or len_delta > 5 or motif_count != 1:
                continue
                
            # Stage 1: Family Core & Geometry (Combined in evaluate_candidate)
            eval_res = evaluate_candidate(
                sequence=seq,
                family_stats=family_stats,
                reference_records=reference_records
            )
            
            if not eval_res.get("passes_core_screen") or not eval_res.get("catalytic_geometry", {}).get("passes"):
                continue
            
            geometry_pass_count += 1
            
            # Stage 3: ESM (Delayed Scoring)
            # We will batch these at the end for efficiency if needed, 
            # but for triage we can do them one by one or in small batches.
            # For simplicity in this triage script, we collect them.
            
            c["triage_eval"] = eval_res
            c["step"] = step
            c["prompt"] = prompt
            all_triage_results.append(c)

    # Batch score ESM for survivors
    if all_triage_results:
        print(f"Scoring ESM for {len(all_triage_results)} survivors...")
        sequences = [c.get("extracted_sequence") or c.get("sample_text") for c in all_triage_results]
        # Set device
        os.environ["ESM2_DEVICE"] = device
        esm_scores = get_esm2_plddt_scores(sequences)
        
        for c, score in zip(all_triage_results, esm_scores):
            c["esm_score"] = score
            if score >= 85.0:
                stability_pass_count += 1
                intersection_pass_count += 1
                functional_bridge_hits.append(c)
                
    triage_summary = {
        "seed": ablation_dir.name.split("-s")[-1],
        "geometry_pass_count": geometry_pass_count,
        "stability_pass_count": stability_pass_count,
        "functional_bridge_hits_count": len(functional_bridge_hits),
        "hits": functional_bridge_hits
    }
    
    return triage_summary

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()

    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    seeds = ["41", "53", "67"]
    base_dir = "reports/ablations"
    run_prefix = "pearl-topoff1m-a-manifold-v22-baseline-stagea-gate-p24-c128-p24-t0p8-s"
    
    output_dir = Path("reports/analysis/v22_seed_triage")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    all_summaries = []
    
    for seed in seeds:
        ablation_dir = Path(f"{base_dir}/{run_prefix}{seed}")
        summary = triage_seed(ablation_dir, family_stats, reference_records, device=args.device)
        if summary:
            all_summaries.append(summary)
            with open(output_dir / f"seed{seed}_triage.json", "w") as f:
                json.dump(summary, f, indent=2)
                
    # Cross-seed summary
    summary_md = "# Cross-Seed Triage Summary (v2.2-baseline)\n\n"
    summary_md += "| Seed | Geometry Pass | Stability Pass (ESM >= 85) | Bridge Hits |\n"
    summary_md += "| :--- | :--- | :--- | :--- |\n"
    
    for s in all_summaries:
        summary_md += f"| {s['seed']} | {s['geometry_pass_count']} | {s['stability_pass_count']} | {s['functional_bridge_hits_count']} |\n"
        
    (output_dir / "cross_seed_summary.md").write_text(summary_md)
    print("\n" + summary_md)

if __name__ == "__main__":
    main()
