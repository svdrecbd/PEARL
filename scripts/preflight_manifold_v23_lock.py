#!/usr/bin/env python3
import json
import hashlib
from collections import Counter
from pathlib import Path

def main():
    config_path = Path("configs/experiments/strict/topoff1m_a_manifold_v23_unicorn_lock_20260424.json")
    config = json.loads(config_path.read_text())
    
    curriculum_path = Path(config["stages"]["stage-a"]["dataset_path"])
    rows = [json.loads(l) for l in curriculum_path.open("r") if l.strip()]
    
    out_dir = Path("reports/preflight/manifold_v23_lock_20260424")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    failures = []
    roles = Counter(r.get("curriculum_role") for r in rows)
    
    if "v2_unicorn_lock" not in roles or roles["v2_unicorn_lock"] < 10:
        failures.append("v2 unicorn lock rows missing or insufficient (<10)")
        
    if config["stages"]["stage-a"]["learning_rate"] != "1.25e-7":
        failures.append(f"Learning rate mismatch: {config['stages']['stage-a']['learning_rate']} != 1.25e-7")

    if "v22-baseline" not in config["base_init_state_path"]:
        failures.append("Init state does not point to v2.2-baseline")
        
    packet = {
        "config_name": config["name"],
        "curriculum_path": str(curriculum_path),
        "row_count": len(rows),
        "roles": dict(roles),
        "lr": config["stages"]["stage-a"]["learning_rate"],
        "validator_result": "PASS" if not failures else "FAIL",
        "failures": failures
    }
    
    with open(out_dir / "launch_packet.json", "w") as f:
        json.dump(packet, f, indent=2)
        
    print(json.dumps(packet, indent=2))
    if not failures:
        print("\nDECISION: PASS - v2.3-unicorn-lock is eligible for tiny p24/c128 diagnostic.")
    else:
        print("\nDECISION: FAIL - do not launch.")

if __name__ == "__main__":
    main()
