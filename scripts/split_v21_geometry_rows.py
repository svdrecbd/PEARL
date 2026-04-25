#!/usr/bin/env python3
import json
import glob
from pathlib import Path

def main():
    v21_pattern = "reports/ablations/pearl-topoff1m-a-manifold-v21-bridge-stagea-gate-p24-c128-p24-t0p8-s*/candidate_audit.json"
    
    bucket_1 = [] # Geometry + ESM pass + core pass
    bucket_2 = [] # Geometry + ESM 70-85
    bucket_3 = [] # Geometry + low ESM (<70) or core fail
    
    for path in glob.glob(v21_pattern):
        with open(path, 'r') as f:
            data = json.load(f)
            for record in data.get('records', []):
                prompt = record.get('prompt', '')
                for c in record.get('candidates', []):
                    if not c.get('geometry_passes'):
                        continue
                        
                    c['prompt'] = prompt
                    
                    if c.get('esm_gate_pass') and c.get('passes_core_screen'):
                        bucket_1.append(c)
                    elif c.get('passes_core_screen') and c.get('raw_esm_score') is not None and 70 <= c.get('raw_esm_score') < 85:
                        bucket_2.append(c)
                    else:
                        bucket_3.append(c)

    out_dir = Path("reports/analysis/manifold_v22_preparation")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(out_dir / "bucket1_v22_positives.jsonl", "w") as f:
        for c in bucket_1: f.write(json.dumps(c) + "\n")
        
    with open(out_dir / "bucket2_repair_targets.jsonl", "w") as f:
        for c in bucket_2: f.write(json.dumps(c) + "\n")
        
    with open(out_dir / "bucket3_hard_negatives.jsonl", "w") as f:
        for c in bucket_3: f.write(json.dumps(c) + "\n")
        
    print(f"Bucket 1 (v2.2 Positives): {len(bucket_1)}")
    print(f"Bucket 2 (Repair Targets): {len(bucket_2)}")
    print(f"Bucket 3 (Hard Negatives): {len(bucket_3)}")

if __name__ == "__main__":
    main()
