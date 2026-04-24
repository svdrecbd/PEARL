import json
import os
from pathlib import Path

ROBUSTNESS_DIR = Path("reports/robustness/pearl-topoff1m-a-manifold-v21-bridge-stagea-gate-p24-c128")
ABLATIONS_DIR = Path("reports/ablations")
SEEDS = [41, 53, 67]
RUN_NAME_BASE = "pearl-topoff1m-a-manifold-v21-bridge-stagea-gate-p24-c128-p24-t0p8-s"

def main():
    runs = []
    for seed in SEEDS:
        summary_path = ABLATIONS_DIR / f"{RUN_NAME_BASE}{seed}" / "summary.json"
        if summary_path.exists():
            with summary_path.open("r") as f:
                runs.append(json.loads(f.read()))
    
    if not runs:
        print("No ablation summaries found.")
        return

    summary = {
        "suite_name": "pearl-topoff1m-a-manifold-v2-stagea-gate-p24-c128",
        "completed_run_count": len(runs),
        "run_count": 3,
        "runs": runs,
        "overall_functional_bridge_hits": sum(len(r.get("functional_bridge_steps", [])) for r in runs),
        "overall_family_faithful_bridge_hits": sum(len(r.get("family_faithful_bridge_steps", [])) for r in runs)
    }
    
    output_path = ROBUSTNESS_DIR / "robustness_summary.json"
    with output_path.open("w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"Manually aggregated summary written to {output_path}")
    print(json.dumps({
        "functional_hits": summary["overall_functional_bridge_hits"],
        "seeds_completed": summary["completed_run_count"]
    }, indent=2))

if __name__ == "__main__":
    main()
