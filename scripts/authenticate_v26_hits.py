#!/usr/bin/env python3
import json
import sys
import glob
from pathlib import Path

# Ensure src is in sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from pearl.family import evaluate_candidate, load_reference_records, compute_family_stats, levenshtein

def find_all_repeats(seq, min_len=8, threshold=0.85):
    n = len(seq)
    found = []
    for i in range(0, n - min_len):
        for j in range(i + min_len, n - min_len):
            w1 = seq[i:i+min_len]
            w2 = seq[j:j+min_len]
            dist = levenshtein(w1, w2)
            if (1.0 - (dist / min_len)) >= threshold:
                found.append((j, min_len))
    return found

def authenticate_hit(seq, family_stats, reference_records):
    eval_res = evaluate_candidate(sequence=seq, family_stats=family_stats, reference_records=reference_records)
    if not eval_res.get("catalytic_geometry", {}).get("passes"):
        return False, "FAIL_BASE_GEOMETRY"
    if not eval_res.get("passes_core_screen"):
        return False, "FAIL_CORE_SCREEN"
    if len(eval_res.get("serine_motifs", [])) != 1:
        return False, "FAIL_MOTIF"
    
    repeats = find_all_repeats(seq, min_len=8)
    if not repeats:
        return True, "CLEAN"
        
    masked = list(seq)
    for pos, l in repeats:
        for k in range(pos, pos+l): masked[k] = "X"
    
    masked_eval = evaluate_candidate(sequence="".join(masked).replace("X", "A"), family_stats=family_stats, reference_records=reference_records)
    
    if masked_eval.get("catalytic_geometry", {}).get("passes", False):
        return True, "CLEAN_SURVIVES_MASKING"
    else:
        return False, "REPEAT_DEPENDENT"

def main():
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    # Load training rows to compute nearest neighbor distances
    curriculum_path = Path("reports/curriculum/manifold_v26_20260424/manifold_v26_true_clean_manifold_curriculum.jsonl")
    train_rows = [json.loads(l) for l in curriculum_path.open("r") if l.strip()]
    positive_train_seqs = [r["sequence"] for r in train_rows if r["curriculum_role"] != "repeat_artifact_negative"]
    
    run_name = "pearl-topoff1m-a-manifold-v26-clean-stagea-gate-p24-c128"
    audit_paths = glob.glob(f"reports/ablations/{run_name}-p24-t0p8-s*/candidate_audit.json")
    
    clean_hits = []
    artifacts = []
    
    for path in audit_paths:
        seed = path.split("-s")[-1].split("/")[0]
        data = json.load(open(path))
        for r in data.get("records", []):
            for c in r.get("candidates", []):
                esm = float(c.get("raw_esm_score") or c.get("esm_score") or 0.0)
                if esm < 85.0:
                    continue
                
                seq = c.get("extracted_sequence")
                if not seq: continue
                
                # Pre-screen: check if it even passes geometry
                if not c.get("geometry_passes"):
                    continue
                    
                is_clean, reason = authenticate_hit(seq, family_stats, reference_records)
                
                # compute nearest training positive
                dists = [levenshtein(seq, t_seq) for t_seq in positive_train_seqs]
                min_dist = min(dists) if dists else -1
                
                info = {
                    "seed": seed,
                    "step": r["step"],
                    "esm": esm,
                    "reason": reason,
                    "min_train_dist": min_dist,
                    "sequence": seq
                }
                
                if is_clean:
                    clean_hits.append(info)
                elif reason == "REPEAT_DEPENDENT":
                    artifacts.append(info)
                    
    print(f"Total Clean Hits: {len(clean_hits)}")
    print(f"Total Artifacts (ESM >= 85, Geom Pass, Repeat Dependent): {len(artifacts)}")
    
    print("\n--- CLEAN HITS ---")
    for h in clean_hits:
        print(f"Seed {h['seed']} Step {h['step']}: ESM={h['esm']}, TrainDist={h['min_train_dist']}, Reason={h['reason']}")
        
    print("\n--- ARTIFACTS SAMPLE (first 5) ---")
    for a in artifacts[:5]:
        print(f"Seed {a['seed']} Step {a['step']}: ESM={a['esm']}, TrainDist={a['min_train_dist']}, Reason={a['reason']}")

if __name__ == "__main__":
    main()
