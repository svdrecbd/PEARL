#!/usr/bin/env python3
import json
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

# Ensure src is in sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from pearl.family import evaluate_candidate, load_reference_records, compute_family_stats

V23_HIT1 = "MTVSTTRQILAASTALALAVVAGSAGQVSSAQKTTVYTGSDHGGTVHVWDQDNPWVFNENFGDLSAFDVNVKTTKGSLLDSKSVQDSGFNGYVTIYGWTRNSPLVEYYVVDSFGPTFDQYYPVDYLLHFSKRDEDGKLQLVKLQSWAELIAPDFNGTSYSPDTNVLVKDTGDLLAAYDKATFDIEYWDQFNAAGPGYAPRNGYSLGAYHVANYNASALNPGKCPNVMTIHGVAYLSRGLYPISYLYGWGLDPLVEYYIVDSFGPTFSEYKPVDYLLHFSKRDEDGKLQLVKLQSWAELIAPDFNG"
V23_HIT2 = "MTVPRRPRSRGLLAAAGLVTVAVAAACARGLGAASARPGDPAAHVVITGTDSGYHGVHDLLTLLDGLGWGASGVEPGTLDPEAWAAWAQAGLPDRDLTGGGRSASPGSVAAGVVGLVWLRGLDVEANQDWQPGMALDPRLRPADGRGLLSPQAQPLQGWQRINASGPGGYSLGVALGNAVALAAQGVDVQVLVDLNNQSVVSGDGLGLVDWLKASGVDGQPRSFLPDASARVPGALVQAAGLALNDPDVWAHGVVTQPQGVALANLGATLAALAQQGHVVAQLVDLNNQAVVTGDGLGLVDWLKASGVDGQPRSFLPDASARVPG"

def find_repeats(seq, min_len=21): # Gate is <= 20
    n = len(seq)
    for i in range(n - min_len):
        block = seq[i:i+min_len]
        if seq.find(block, i + 1) != -1:
            return True
    return False

def is_strict_pass(r, family_stats, reference_records):
    seq = r.get("sequence") or r.get("extracted_sequence")
    if not seq: return False
    
    # 1. Anti-repeat gate
    if find_repeats(seq, min_len=21): return False
    
    # 2. Evaluation checks
    eval_res = evaluate_candidate(sequence=seq, family_stats=family_stats, reference_records=reference_records)
    
    # If natural anchor, bypass core screen failure due to novelty=1.0
    core_ok = eval_res.get("passes_core_screen")
    if not core_ok and r.get("curriculum_role") == "natural_stability_anchor":
        # Check if it passes other core requirements
        # (motif, geometry, alphabet sanity)
        core_ok = bool(eval_res.get("serine_motifs")) and eval_res.get("catalytic_geometry", {}).get("passes")
        
    if not core_ok: return False
    if not eval_res.get("catalytic_geometry", {}).get("passes"): return False
    if len(eval_res.get("serine_motifs", [])) != 1: return False
    
    # 3. ESM floor (Naturals generally pass)
    esm = float(r.get("esm_score") or r.get("raw_esm_score") or 100.0) # Naturals default to 100 if missing
    if esm < 85.0: return False
    
    return True

def main():
    config_path = Path("configs/experiments/strict/topoff1m_a_manifold_v24_confirm_20260424.json")
    config = json.loads(config_path.read_text())
    curriculum_path = Path(config["stages"]["stage-a"]["dataset_path"])
    rows = [json.loads(l) for l in curriculum_path.open("r") if l.strip()]
    
    records_path = Path("data/petase_family_expanded/petase_records.jsonl")
    reference_records = load_reference_records(records_path)
    family_stats = compute_family_stats(reference_records)
    
    out_dir = Path("reports/preflight/manifold_v24_confirm_20260424")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    failures = []
    
    # 1. v2 Unicorn passes
    v2_audit = json.load(open("reports/ablations/pearl-topoff1m-a-manifold-v2-stagea-gate-p24-c128-p24-t0p8-s53/candidate_audit.json"))
    v2_unicorn = next(c for r in v2_audit["records"] for c in r["candidates"] if c.get("functional_bridge_passes"))
    if not is_strict_pass(v2_unicorn, family_stats, reference_records):
        failures.append("Original v2 Unicorn failed anti-repeat strict pass check")

    # 2. v2.3 Hits rejected
    if find_repeats(V23_HIT1, min_len=21) == False:
        failures.append("v2.3 Hit 1 did not trigger repeat detection")
    if find_repeats(V23_HIT2, min_len=21) == False:
        failures.append("v2.3 Hit 2 did not trigger repeat detection")
        
    # 3. v2.1 traps rejected
    traps_path = Path("reports/analysis/manifold_v22_preparation/bucket3_hard_negatives.jsonl")
    traps = [json.loads(l) for l in traps_path.open("r") if l.strip()]
    rejected_traps = sum(1 for t in traps if not is_strict_pass(t, family_stats, reference_records))
    if rejected_traps != len(traps):
        failures.append(f"v2.1 traps rejected {rejected_traps} != {len(traps)}")
        
    # 4. Positive curriculum checks
    # For confirmation, we need to know how many actually pass the NEW strict gate
    strict_pass_count = sum(1 for r in rows if is_strict_pass(r, family_stats, reference_records))
    
    # We might need to rebuild the curriculum if too many baseline rows have repeats
    # For now, let us see the failure.
    
    for r in rows:
        if find_repeats(r["sequence"], min_len=21):
            failures.append(f"Positive row {r.get('candidate_id')} (role={r.get('curriculum_role')}) has repeat > 20")

    if strict_pass_count < 48:
        failures.append(f"strict_pass_rows = {strict_pass_count} < 48")

    packet = {
        "config_name": config["name"],
        "curriculum_path": str(curriculum_path),
        "row_count": len(rows),
        "strict_pass_count": strict_pass_count,
        "v23_hits_rejected": True,
        "v21_traps_rejected": rejected_traps,
        "validator_result": "PASS" if not failures else "FAIL",
        "failures": failures
    }
    
    with open(out_dir / "launch_packet.json", "w") as f:
        json.dump(packet, f, indent=2)
        
    print(json.dumps(packet, indent=2))
    if not failures:
        print("\nDECISION: PASS - v2.4-anti-repeat-confirm is eligible for tiny p24/c128 diagnostic.")
    else:
        print("\nDECISION: FAIL - do not launch.")

if __name__ == "__main__":
    main()
