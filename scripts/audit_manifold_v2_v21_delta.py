#!/usr/bin/env python3
import json
import glob
from pathlib import Path

def load_audits(pattern):
    candidates = []
    for path in glob.glob(pattern):
        with open(path, 'r') as f:
            data = json.load(f)
            for record in data.get('records', []):
                prompt = record.get('prompt', '')
                for c in record.get('candidates', []):
                    c['prompt'] = prompt
                    candidates.append(c)
    return candidates

def compute_metrics(candidates):
    total = len(candidates)
    if total == 0:
        return {}

    functional_bridge_hits = sum(1 for c in candidates if c.get('functional_bridge_passes'))
    family_faithful_hits = sum(1 for c in candidates if c.get('family_faithful_bridge_passes'))
    
    geom_passes = [c for c in candidates if c.get('geometry_passes')]
    geometry_pass_rate = len(geom_passes) / total
    
    esm_gate_rate = sum(1 for c in candidates if c.get('esm_gate_pass')) / total
    
    single_motif_geometry_esm_count = sum(
        1 for c in candidates
        if c.get('motif_count') == 1 and c.get('geometry_passes') and c.get('esm_gate_pass') and c.get('passes_core_screen')
    )
    
    esm_scores = [c.get('raw_esm_score', 0.0) for c in geom_passes if c.get('raw_esm_score', 0.0) > 0.0]
    mean_esm_given_geometry = sum(esm_scores) / len(esm_scores) if esm_scores else 0.0
    
    hit_prompts = len(set(c['prompt'] for c in candidates if c.get('functional_bridge_passes')))
    
    return {
        "functional_bridge_hits": functional_bridge_hits,
        "family_faithful_hits": family_faithful_hits,
        "geometry_pass_rate": geometry_pass_rate,
        "esm_gate_rate": esm_gate_rate,
        "single_motif_geometry_esm_count": single_motif_geometry_esm_count,
        "mean_esm_given_geometry": mean_esm_given_geometry,
        "prompt_hit_coverage": hit_prompts,
    }

def main():
    v2_pattern = "reports/ablations/pearl-topoff1m-a-manifold-v2-stagea-gate-p24-c128-p24-t0p8-s*/candidate_audit.json"
    v21_pattern = "reports/ablations/pearl-topoff1m-a-manifold-v21-bridge-stagea-gate-p24-c128-p24-t0p8-s*/candidate_audit.json"
    
    v2_candidates = load_audits(v2_pattern)
    v21_candidates = load_audits(v21_pattern)
    
    v2_metrics = compute_metrics(v2_candidates)
    v21_metrics = compute_metrics(v21_candidates)
    
    delta = {
        "geometry_gain": v21_metrics.get("geometry_pass_rate", 0) - v2_metrics.get("geometry_pass_rate", 0),
        "esm_loss_given_geometry": v2_metrics.get("mean_esm_given_geometry", 0) - v21_metrics.get("mean_esm_given_geometry", 0),
        "family_core_loss": sum(1 for c in v2_candidates if c.get("passes_core_screen")) / max(1, len(v2_candidates)) - sum(1 for c in v21_candidates if c.get("passes_core_screen")) / max(1, len(v21_candidates)),
        "bridge_loss": v2_metrics.get("functional_bridge_hits", 0) - v21_metrics.get("functional_bridge_hits", 0),
        "best_intersection_candidates": v21_metrics.get("single_motif_geometry_esm_count", 0)
    }
    
    output = {
        "v2": v2_metrics,
        "v2.1": v21_metrics,
        "delta": delta
    }
    
    print(json.dumps(output, indent=2))

if __name__ == "__main__":
    main()
