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
    find_serine_motifs,
    levenshtein
)
from pearl.esm_proxy import get_esm2_plddt_scores

V2_UNICORN = "MGWSKRKMAAALAVVATLAAPAVAAPVAAVAPVAAASQGDAYVNGYTAGQWGPVYVLDSRFGRTFAVSGRNEFGDSGDPEIWVSDNGSALGQVSNHGANYSILLSNNSVLIEPGSVYAAVDSYNNYGNEYQIVYGDGDGDNGSPGDSEYFVAINAASNSQQTGSWADLVKDFGRQLAFAPLGLFCCSSSEYTVADGASAGLTPQSDQKVNFGWYAPAMYVDSRFGRTFGVAAANQYNGDAGDPEIWVQDYGSALGQVSNHGANYAILLSNNSVLIEPGSIYAAVDSYNNYGNE"

def find_exact_repeats(seq, min_len=21):
    n = len(seq)
    for i in range(n - min_len):
        block = seq[i:i+min_len]
        if seq.find(block, i + 1) != -1:
            return True
    return False

def find_near_repeats(seq, min_len=24, threshold=0.85):
    """Detects if any two blocks of min_len have high sequence identity."""
    n = len(seq)
    # Sampling for speed: check non-overlapping blocks
    blocks = []
    for i in range(0, n - min_len, min_len):
        blocks.append(seq[i:i+min_len])
    
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            dist = levenshtein(blocks[i], blocks[j])
            identity = 1.0 - (dist / min_len)
            if identity >= threshold:
                return True, identity
    return False, 0.0

def analyze_v24_results(audit_paths, family_stats, reference_records, natural_anchor_seqs, device="mps"):
    all_candidates = []
    for path in audit_paths:
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
        return {"error": "No candidates found."}

    # Sort and score top 500 for deep diagnostic
    all_candidates.sort(key=lambda x: x.get("stage2_score", 0), reverse=True)
    top_candidates = all_candidates[:500]
    
    print(f"Scoring ESM for top 500 candidates...")
    os.environ["ESM2_DEVICE"] = device
    sequences = [c["seq"] for c in top_candidates]
    esm_scores = get_esm2_plddt_scores(sequences)
    
    hits = []
    for c, score in zip(top_candidates, esm_scores):
        c["esm_score"] = score
        eval_res = evaluate_candidate(sequence=c["seq"], family_stats=family_stats, reference_records=reference_records)
        
        # Hard Gates
        exact_repeat = find_exact_repeats(c["seq"])
        near_repeat, near_identity = find_near_repeats(c["seq"])
        
        c["is_unicorn_replay"] = (c["seq"] == V2_UNICORN)
        c["dist_to_unicorn"] = levenshtein(c["seq"], V2_UNICORN)
        
        # Check proximity to natural anchors
        best_natural_dist = min([levenshtein(c["seq"], n) for n in natural_anchor_seqs])
        c["dist_to_nearest_natural"] = best_natural_dist
        c["is_natural_replay"] = (best_natural_dist == 0)
        
        if (score >= 85.0 and 
            eval_res.get("catalytic_geometry", {}).get("passes") and 
            eval_res.get("serine_motif_count") == 1 and
            not exact_repeat and 
            not near_repeat and
            not c["is_natural_replay"]):
            hits.append(c)

    report = {
        "metrics": {
            "mean_esm_top_500": mean([c["esm_score"] for c in top_candidates]),
            "functional_clean_hits": len(hits),
            "exact_repeat_found_count": sum(1 for c in top_candidates if find_exact_repeats(c["seq"])),
            "near_repeat_found_count": sum(1 for c in top_candidates if find_near_repeats(c["seq"])[0])
        },
        "clean_hits": [
            {
                "id": h.get("sequence_id", "unknown"),
                "esm": h["esm_score"],
                "dist_to_unicorn": h["dist_to_unicorn"],
                "dist_to_natural": h["dist_to_nearest_natural"],
                "step": h["step"]
            } for h in hits
        ]
    }
    return report

def main():
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    # Load Natural Anchors from v2.4 curriculum
    v24_path = Path("reports/curriculum/manifold_v24_20260424/manifold_v24_anti_repeat_curriculum.jsonl")
    v24_rows = [json.loads(l) for l in v24_path.open("r") if l.strip()]
    natural_anchor_seqs = [r["sequence"] for r in v24_rows if r["curriculum_role"] == "natural_stability_anchor"]

    run_name = "pearl-topoff1m-a-manifold-v24-confirm-stagea-gate-p24-c128"
    audit_pattern = f"reports/ablations/{run_name}-p24-t0p8-s*/candidate_audit.json"
    audit_paths = glob.glob(audit_pattern)
    
    if not audit_paths:
        print("Waiting for sampling to complete...")
        return

    report = analyze_v24_results(audit_paths, family_stats, reference_records, natural_anchor_seqs)
    
    output_dir = Path("reports/analysis/v24_final_authentication")
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "diagnostic_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
