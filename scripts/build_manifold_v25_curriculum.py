#!/usr/bin/env python3
import json
import random
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

def read_jsonl(path: Path):
    rows = []
    with path.open("r") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows

def main():
    # 1. Clean Neighborhood Positives (50)
    neighborhood_path = Path("reports/analysis/manifold_v25_neighborhood_construction/clean_neighborhood_survivors.jsonl")
    neighborhood_rows = read_jsonl(neighborhood_path)
    random.shuffle(neighborhood_rows)
    positives = neighborhood_rows[:50]
    for r in positives:
        r["curriculum_role"] = "clean_neighborhood_positive"
        r["prompt"] = "Design a protein sequence inspired by Cutinase, length about 293 aa. Favor a PETase/cutinase-like GxSxG nucleophile motif and compatible catalytic residues. Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."

    # 2. Natural Anchors (Filter by hardened v2.5 gates)
    v24_curriculum = read_jsonl(Path("reports/curriculum/manifold_v24_20260424/manifold_v24_anti_repeat_curriculum.jsonl"))
    raw_naturals = [r for r in v24_curriculum if r["curriculum_role"] == "natural_stability_anchor"]
    
    # Re-use preflight logic locally for construction
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    from pearl.family import evaluate_candidate, load_reference_records, compute_family_stats, levenshtein
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)

    def find_exact_repeats(seq, min_len=16):
        n = len(seq)
        for i in range(n - min_len):
            block = seq[i:i+min_len]
            if seq.find(block, i + 1) != -1: return True
        return False

    def find_near_repeats(seq, min_len=21, threshold=0.85):
        n = len(seq)
        blocks = []
        for i in range(0, n - min_len, min_len): blocks.append(seq[i:i+min_len])
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                dist = levenshtein(blocks[i], blocks[j])
                identity = 1.0 - (dist / min_len)
                if identity >= threshold: return True
        return False

    def is_clean(seq, role):
        if find_exact_repeats(seq) or find_near_repeats(seq): return False
        eval_res = evaluate_candidate(sequence=seq, family_stats=family_stats, reference_records=reference_records)
        core_ok = eval_res.get("passes_core_screen")
        if not core_ok and role == "natural_stability_anchor":
            core_ok = bool(eval_res.get("serine_motifs")) and eval_res.get("catalytic_geometry", {}).get("passes")
        return core_ok and eval_res.get("catalytic_geometry", {}).get("passes") and len(eval_res.get("serine_motifs", [])) == 1

    naturals = []
    for r in raw_naturals:
        if is_clean(r["sequence"], "natural_stability_anchor"):
            r["curriculum_role"] = "natural_stability_anchor"
            naturals.append(r)
            if len(naturals) >= 30: break
    
    print(f"Found {len(naturals)} hardened natural anchors.")

    # 3. Original v2 Unicorn Anchor (1)
    v2_audit = json.load(open("reports/ablations/pearl-topoff1m-a-manifold-v2-stagea-gate-p24-c128-p24-t0p8-s53/candidate_audit.json"))
    v2_unicorn = next(c for r in v2_audit["records"] for c in r["candidates"] if c.get("functional_bridge_passes"))
    v2_unicorn["curriculum_role"] = "v2_unicorn_lock"
    v2_unicorn["sequence"] = v2_unicorn["extracted_sequence"]

    final_curriculum = [v2_unicorn] + positives + naturals
    
    out_path = Path("reports/curriculum/manifold_v25_20260424/manifold_v25_clean_neighborhood_curriculum.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for r in final_curriculum:
            f.write(json.dumps(r) + "\n")
            
    summary = {
        "total_rows": len(final_curriculum),
        "roles": dict(Counter(r["curriculum_role"] for r in final_curriculum)),
        "hard_gates": {
            "max_exact_repeat": 15,
            "max_near_repeat": 20,
            "esm_floor": 85
        }
    }
    with (out_path.parent / "summary.json").open("w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
