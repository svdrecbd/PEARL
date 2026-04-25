#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from collections import Counter

V2_UNICORN = "MGWSKRKMAAALAVVATLAAPAVAAPVAAVAPVAAASQGDAYVNGYTAGQWGPVYVLDSRFGRTFAVSGRNEFGDSGDPEIWVSDNGSALGQVSNHGANYSILLSNNSVLIEPGSVYAAVDSYNNYGNEYQIVYGDGDGDNGSPGDSEYFVAINAASNSQQTGSWADLVKDFGRQLAFAPLGLFCCSSSEYTVADGASAGLTPQSDQKVNFGWYAPAMYVDSRFGRTFGVAAANQYNGDAGDPEIWVQDYGSALGQVSNHGANYAILLSNNSVLIEPGSIYAAVDSYNNYGNE"
V2_UNICORN_PROMPT = "Design a protein sequence inspired by Cutinase from Clonostachys chloroleuca, length about 219 aa. Favor a PETase/cutinase-like GxSxG nucleophile motif and compatible catalytic residues. Output only uppercase amino acid letters ACDEFGHIKLMNPQRSTVWY."

def read_jsonl(path: Path):
    if not path.exists(): return []
    return [json.loads(l) for l in path.open("r") if l.strip()]

def pick_sequence(row):
    sequence = row.get("sequence") or row.get("extracted_sequence") or row.get("sample_text")
    if sequence is None and isinstance(row.get("selected_candidate"), dict):
        sequence = row["selected_candidate"].get("sequence") or row["selected_candidate"].get("extracted_sequence")
    return str(sequence or "").strip().upper()

def main():
    v22_path = Path("reports/curriculum/manifold_v22_20260424/manifold_v22_intersection_curriculum.jsonl")
    v12_path = Path("reports/manifold/topoff1m-a-manifold-v12-20260423/v12_selected_repair_retargeted.jsonl")
    purebred_path = Path("data/petase_family_expanded/kimi_micro_sft_top9_unicorn_only.jsonl")
    v21_survivor_path = Path("reports/analysis/manifold_v22_preparation/bucket1_v22_positives.jsonl")
    
    v22_rows = read_jsonl(v22_path)
    v12_rows = read_jsonl(v12_path)
    purebred_rows = read_jsonl(purebred_path)
    v21_rows = read_jsonl(v21_survivor_path)
    
    final_curriculum = []
    
    def add_rows(source_rows, role):
        for r in source_rows:
            seq = pick_sequence(r)
            r["sequence"] = seq
            r["curriculum_role"] = role
            final_curriculum.append(r)

    # 1. v2.2 Baseline rows
    v22_filtered = [r for r in v22_rows if r.get("curriculum_role") in ["v2_breadth_anchor", "v2_bridge_hit"]][:32]
    add_rows(v22_filtered, "v22_baseline_anchor")
    
    # 2. v2 Unicorn "Lock"
    prompts = [
        V2_UNICORN_PROMPT,
        "Generate a PETase/cutinase-family sequence around 293aa. Prefer GYSLG motif and valid catalytic triad.",
        "Design a stable polyester hydrolase similar to Clonostachys chloroleuca cutinase, length 293.",
        "SEQUENCE=MGWSKRKMAAALAVVATLAAPAVAAPVAAVAPVAAASQGDAYVNGYTAGQWGPVYVLDSRFGRTFAVSGRNEFGDSGDPEIWVSDNGSALGQVSNHGANYSILLSNNSVLIEPGSVYAAVDSYNNYGNEYQIVYGDGDGDNGSPGDSEYFVAINAASNSQQTGSWADLVKDFGRQLAFAPLGLFCCSSSEYTVADGASAGLTPQSDQKVNFGWYAPAMYVDSRFGRTFGVAAANQYNGDAGDPEIWVQDYGSALGQVSNHGANYAILLSNNSVLIEPGSIYAAVDSYNNYGNE",
        "Design a 293aa protein with a GASAG motif and high ESM stability.",
        "Inspired by Clonostachys chloroleuca cutinase: MGWSKRKMAAALAVVATLAAPAVAAPVAAVAPVAAASQGDAYVNGYTAGQWGPVYVLDSRFGRTFAVSGRNEFGDSGDPEIWVSDNGSALGQVSNHGANYSILLSNNSVLIEPGSVYAAVDSYNNYGNEYQIVYGDGDGDNGSPGDSEYFVAINAASNSQQTGSWADLVKDFGRQLAFAPLGLFCCSSSEYTVADGASAGLTPQSDQKVNFGWYAPAMYVDSRFGRTFGVAAANQYNGDAGDPEIWVQDYGSALGQVSNHGANYAILLSNNSVLIEPGSIYAAVDSYNNYGNE",
        "Generate a PETase sequence with the following signature: GASAG nucleophile, stable ESM backbone.",
        "Design a sequence matching the blueprint: Ser 198, Asp 206, His 260.",
        "Create a stable Clonostachys-inspired cutinase.",
        "Sequence discovery: high-stability bridge-hit variant MGWSKR..."
    ]
    for i, p in enumerate(prompts):
        final_curriculum.append({
            "sequence": V2_UNICORN,
            "prompt": p,
            "curriculum_role": "v2_unicorn_lock",
            "candidate_id": f"v2-unicorn-lock-{i}",
            "esm_score": 96.65,
            "length": 293
        })
        
    # 3. v1.2 Family-Faithful hits
    add_rows(v12_rows[:8], "v12_family_anchor")
        
    # 4. v2.1 Intersection survivor
    if v21_rows:
        survivor = v21_rows[0]
        for i in range(5):
            r = survivor.copy()
            seq = pick_sequence(r)
            r["sequence"] = seq
            r["curriculum_role"] = "v21_geometry_hint"
            r["candidate_id"] = f"v21-survivor-hint-{i}"
            final_curriculum.append(r)
            
    # 5. Purebred anchors
    add_rows(purebred_rows[:8], "purebred_anchor")
        
    out_dir = Path("reports/curriculum/manifold_v23_20260424")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "manifold_v23_unicorn_lock_curriculum.jsonl"
    
    with out_path.open("w") as f:
        for r in final_curriculum:
            f.write(json.dumps(r) + "\n")
            
    summary = {
        "total_rows": len(final_curriculum),
        "roles": dict(Counter(r["curriculum_role"] for r in final_curriculum)),
        "output_path": str(out_path)
    }
    with (out_dir / "summary.json").open("w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
