#!/usr/bin/env python3
import json
import random
from pathlib import Path

def main():
    print("Building Track 2: Contrastive DPO Dataset")
    
    # 1. Load the pristine "Chosen" local library candidates
    chosen_path = Path("reports/analysis/phase7_local_library_v1/validation_panel.jsonl")
    chosen_seqs = []
    if chosen_path.exists():
        with open(chosen_path) as f:
            for line in f:
                chosen_seqs.append(json.loads(line)["sequence"])
    print(f"Loaded {len(chosen_seqs)} pristine chosen sequences.")
    
    # Add True Unicorn to chosen
    TRUE_UNICORN = "MYKSLVFIALLLSFTVLSAQASPLQSVQKLDGVVKAVVVDGVEGHIFAPQSFVMNLLEHDSVVKQGDVVKVEMPQTGLTFSDVANVYDSLKLGVHRVQVVGDHSLFANVSNFSYVGVQDSKAILSVQGASVSSVGSITVVAQSFRGVKANQLPVFVDRLDSASPFLSHYFPDPSVLDQELVKGVSVGMTMHAELSPQERSAMFAAIRDEVGDSKVDQVFVVKNEQFESVPEKLDVTVPVASQDHVWSMTFAPQSFVMNLLEHDSVVKQGDVVKVEMPQTGLTFSDVANVYDSLKLGVHRVQVV"
    if TRUE_UNICORN not in chosen_seqs:
        chosen_seqs.append(TRUE_UNICORN)

    # 2. Mine the "Rejected" SFT artifacts
    # These are sequences the model *generated* thinking they were good, 
    # but we now know are topological/repeat cheats.
    audit_files = list(Path("reports/ablations").rglob("candidate_audit.json"))
    
    rejected_by_prompt = {}
    total_mined = 0
    
    for audit_path in audit_files:
        # Only use Phase 6 (v2.x) SFT discoveries as hard negatives
        if not any(v in str(audit_path) for v in ["-v2-", "-v23-", "-v24-", "-v25-"]):
            continue
            
        with open(audit_path) as f:
            audit = json.load(f)
            for record in audit.get("records", []):
                prompt = record.get("prompt", "")
                if not prompt: continue
                
                if prompt not in rejected_by_prompt:
                    rejected_by_prompt[prompt] = set()
                    
                for cand in record.get("candidates", []):
                    seq = cand.get("extracted_sequence")
                    if not seq: continue
                    # Must be at least vaguely confident to be a hard negative
                    esm = float(cand.get("raw_esm_score", 0.0))
                    if esm >= 80.0 and seq != TRUE_UNICORN:
                        rejected_by_prompt[prompt].add(seq)
                        total_mined += 1

    print(f"Mined {total_mined} high-ESM SFT artifacts across {len(rejected_by_prompt)} unique prompts.")
    
    # 3. Pair them up
    dpo_pairs = []
    
    for prompt, rejects in rejected_by_prompt.items():
        reject_list = list(rejects)
        # Sample heavily from the hard negatives for this prompt
        for r_seq in reject_list:
            c_seq = random.choice(chosen_seqs)
            dpo_pairs.append({
                "prompt": prompt,
                "chosen": c_seq,
                "rejected": r_seq
            })
            
    # Shuffle for training distribution
    random.shuffle(dpo_pairs)
    
    out_dir = Path("data/phase7_dpo")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "dpo_preferences.jsonl"
    
    with open(out_path, "w") as f:
        for pair in dpo_pairs:
            f.write(json.dumps(pair) + "\n")
            
    print(f"\nSuccess! Wrote {len(dpo_pairs)} Chosen/Rejected pairs to {out_path}")
    print("These pairs explicitly contrast clean local solutions against generative SFT repeat-artifacts.")

if __name__ == "__main__":
    main()
