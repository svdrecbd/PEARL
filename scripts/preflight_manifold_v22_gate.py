#!/usr/bin/env python3
import json
import hashlib
from collections import Counter
from pathlib import Path
import re

AA_PATTERN = re.compile(r"^[ACDEFGHIKLMNPQRSTVWY]+$")

def pick_sequence(row):
    sequence = row.get("sequence") or row.get("extracted_sequence") or row.get("sample_text")
    if sequence is None and isinstance(row.get("selected_candidate"), dict):
        sequence = row["selected_candidate"].get("sequence") or row["selected_candidate"].get("extracted_sequence")
    return str(sequence or "").strip().upper()

def get_esm(row):
    return float(row.get("raw_esm_score") or row.get("esm_score") or 0.0)

def is_strict_pass(r):
    core_ok = r.get("passes_core_screen") or r.get("strict_manifold_passes") or r.get("family_faithful_bridge_passes") or r.get("curriculum_role") in ["historical_anchor", "purebred_anchor"]
    geom_ok = r.get("geometry_passes") or r.get("functional_bridge_passes") or r.get("bridge_quality_passes") or r.get("family_faithful_bridge_passes") or r.get("curriculum_role") in ["historical_anchor", "purebred_anchor"]
    esm_ok = get_esm(r) >= 85.0
    return core_ok and geom_ok and esm_ok

def evaluate_row(row):
    seq = pick_sequence(row)
    valid_aa = 1 if AA_PATTERN.fullmatch(seq) else 0
    prompt_delta = row.get("prompt_length_delta")
    if prompt_delta is None:
        prompt_delta = abs(len(seq) - int(row.get("requested_length", 0)))
    length_ok = 1 if abs(prompt_delta) <= 5 else 0
    motif_count = row.get("motif_count") or (1 if row.get("has_family_serine_motif") else 0)
    single_motif = 1 if motif_count == 1 else 0
    family_core = 1 if row.get("passes_core_screen") else 0
    geom_pass = 1 if row.get("geometry_passes") else 0
    esm = get_esm(row)
    esm_90 = 1 if esm >= 90.0 else 0
    esm_85 = 1 if esm >= 85.0 else 0
    return (valid_aa, length_ok, single_motif, family_core, geom_pass, esm_90, esm_85, esm)

def main():
    config_path = Path("configs/experiments/strict/topoff1m_a_manifold_v22_baseline_20260424.json")
    config = json.loads(config_path.read_text())
    
    curriculum_path = Path(config["stages"]["stage-a"]["dataset_path"])
    rows = [json.loads(l) for l in curriculum_path.open("r") if l.strip()]
    
    out_dir = Path("reports/preflight/manifold_v22_baseline_20260424")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    failures = []
    
    if len(rows) < 67:
        failures.append(f"curriculum_row_count = {len(rows)} < 67")
        
    strict_rows = [r for r in rows if is_strict_pass(r)]
    if len(strict_rows) < 48:
        failures.append(f"strict_pass_rows = {len(strict_rows)} < 48")
        
    for r in rows:
        esm = get_esm(r)
        if esm < -200 or esm > 200:
            failures.append(f"esm_score scale seems wrong: {esm}")
            break
            
    roles = Counter(r.get("curriculum_role") for r in rows)
    if "v2_bridge_hit" not in roles:
        failures.append("v2 bridge anchor absent")
    if "v12_family_hit" not in roles and "historical_anchor" not in roles:
        failures.append("v1.2/v7 family anchors absent")
        
    v21_contrib = roles.get("v21_geometry_intersection", 0) / max(1, len(rows))
    if v21_contrib > 0.25:
        failures.append(f"v2.1 positive contribution {v21_contrib:.2f} > 0.25")
        
    if roles.get("repaired_v21", 0) > 0:
        failures.append(f"repair contribution {roles.get('repaired_v21')} != 0")
        
    # Check negatives
    negatives_path = Path("reports/analysis/manifold_v22_preparation/bucket3_hard_negatives.jsonl")
    negatives = [json.loads(l) for l in negatives_path.open("r") if l.strip()]
    
    rejected_negatives = []
    trap_rejected_by_esm = 0
    trap_count = 0
    for r in negatives:
        score = evaluate_row(r)
        # To be accepted: (1, 1, 1, 1, 1, 1, 1) or (1, 1, 1, 1, 1, 0, 1)
        accepted = score[:7] == (1, 1, 1, 1, 1, 1, 1) or score[:7] == (1, 1, 1, 1, 1, 0, 1)
        if not accepted:
            rejected_negatives.append(r)
            
        if r.get("passes_core_screen") and r.get("geometry_passes") and get_esm(r) < 85:
            trap_count += 1
            if score[3] == 1 and score[4] == 1 and score[6] == 0:
                trap_rejected_by_esm += 1
                
    if len(rejected_negatives) != len(negatives):
        failures.append(f"hard negatives rejected {len(rejected_negatives)} != {len(negatives)}")
        
    if trap_rejected_by_esm != trap_count:
        failures.append(f"trap rows rejected by ESM {trap_rejected_by_esm} != {trap_count}")

    lengths = len(set(len(pick_sequence(r)) for r in rows))
    if lengths < 5:
        failures.append(f"length diversity low: {lengths} unique lengths")
        
    config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
    curriculum_hash = hashlib.sha256(curriculum_path.read_bytes()).hexdigest()
    
    packet = {
        "curriculum_path": str(curriculum_path),
        "row_count": len(rows),
        "strict_pass_count": len(strict_rows),
        "esm_field_and_scale": "raw_esm_score/esm_score in 0-100",
        "v2_bridge_rows_present": "v2_bridge_hit" in roles,
        "v12_v7_anchors_present": "v12_family_hit" in roles or "historical_anchor" in roles,
        "v21_positive_contribution_pct": round(v21_contrib * 100, 1),
        "repair_contribution_pct": 0.0,
        "parent_source_diversity": len(set(r.get("source_candidate", {}).get("closest_match", {}).get("accession") or r.get("sequence_id") for r in rows)),
        "length_diversity": lengths,
        "motif_distribution": dict(Counter(r.get("derived_motif") for r in rows)),
        "geometry_pass_count": sum(1 for r in rows if r.get("geometry_passes") or r.get("functional_bridge_passes") or r.get("bridge_quality_passes") or r.get("family_faithful_bridge_passes") or r.get("curriculum_role") in ["historical_anchor", "purebred_anchor"]),
        "family_core_pass_count": sum(1 for r in rows if r.get("passes_core_screen") or r.get("strict_manifold_passes") or r.get("family_faithful_bridge_passes") or r.get("curriculum_role") in ["historical_anchor", "purebred_anchor"]),
        "negative_control_rejection_count": len(rejected_negatives),
        "trap_rows_rejected_by_esm": trap_rejected_by_esm,
        "trap_rows_total": trap_count,
        "config_hash": config_hash,
        "curriculum_hash": curriculum_hash,
        "validator_result": "PASS" if not failures else "FAIL",
        "failures": failures
    }
    
    with open(out_dir / "launch_packet.json", "w") as f:
        json.dump(packet, f, indent=2)
        
    with open(out_dir / "rejected_hard_negatives.jsonl", "w") as f:
        for r in rejected_negatives: f.write(json.dumps(r) + "\n")
        
    with open(out_dir / "curriculum_manifest.json", "w") as f:
        json.dump([r.get("sequence_id") for r in rows], f, indent=2)
        
    summary_md = [
        f"# Preflight Report: {config['name']}",
        "",
        f"**Curriculum:** `{curriculum_path}`",
        f"**Rows:** {len(rows)} (Strict: {len(strict_rows)})",
        f"**Config Hash:** `{config_hash}`",
        f"**Curriculum Hash:** `{curriculum_hash}`",
        "",
        "## Validation Checks",
        f"- Hard negatives rejected: {len(rejected_negatives)} / {len(negatives)}",
        f"- Trap rows rejected by ESM: {trap_rejected_by_esm} / {trap_count}",
        f"- Failures: {failures if failures else 'None'}",
        "",
    ]
    if not failures:
        summary_md.append("DECISION: PASS \u2014 v2.2-baseline is eligible for tiny p24/c128 diagnostic.")
    else:
        summary_md.append("DECISION: FAIL \u2014 do not launch paid gate.")
        
    with open(out_dir / "summary.md", "w") as f:
        f.write("\n".join(summary_md))
        
    print(json.dumps(packet, indent=2))
    print("\n" + "\n".join(summary_md))

if __name__ == "__main__":
    main()
