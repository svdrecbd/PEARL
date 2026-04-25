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
            if line.strip(): rows.append(json.loads(line))
    return rows

def main():
    # 1. New True Unicorn (v2.5-Hit2)
    v25_audit = json.load(open("reports/ablations/pearl-topoff1m-a-manifold-v25-neighborhood-stagea-gate-p24-c128-p24-t0p8-s41/candidate_audit.json"))
    true_unicorn_row = next(c for r in v25_audit["records"] for c in r["candidates"] if c.get("functional_bridge_passes") and r["step"] == 11)
    true_unicorn_row["curriculum_role"] = "true_unicorn_v1"
    true_unicorn_row["sequence"] = true_unicorn_row["extracted_sequence"]

    # 2. Promoted survivors from artifacts (v2.3, v2.4)
    promoted_path = Path("reports/analysis/topology_authentication/true_positives_promoted.jsonl")
    promoted_rows = read_jsonl(promoted_path)
    for r in promoted_rows:
        r["curriculum_role"] = "true_clean_discovery"
        r["prompt"] = "Design a protein sequence inspired by Cutinase..."

    # 3. Clean Neighborhood Positives (50)
    neighborhood_path = Path("reports/analysis/manifold_v26_neighborhood_construction/clean_neighborhood_survivors.jsonl")
    neighborhood_rows = read_jsonl(neighborhood_path)
    random.shuffle(neighborhood_rows)
    positives = neighborhood_rows[:50]
    for r in positives:
        r["curriculum_role"] = "true_unicorn_neighborhood"
        r["prompt"] = "Design a protein sequence inspired by Cutinase..."

    # 4. Hardened Natural Anchors (30)
    v25_curriculum = read_jsonl(Path("reports/curriculum/manifold_v25_20260424/manifold_v25_clean_neighborhood_curriculum.jsonl"))
    naturals = [r for r in v25_curriculum if r["curriculum_role"] == "natural_stability_anchor"][:30]

    final_curriculum = [true_unicorn_row] + promoted_rows + positives + naturals
    
    out_path = Path("reports/curriculum/manifold_v26_20260424/manifold_v26_true_clean_manifold_curriculum.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for r in final_curriculum:
            f.write(json.dumps(r) + "\n")
            
    summary = {
        "total_rows": len(final_curriculum),
        "roles": dict(Counter(r["curriculum_role"] for r in final_curriculum)),
        "topology_hardened": True,
        "clean_anchor_count": 1 + len(promoted_rows)
    }
    with (out_path.parent / "summary.json").open("w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
