#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def upload_training_runs():
    try:
        import wandb
    except ImportError:
        print("Error: 'wandb' package is not installed.")
        return

    # 1. Upload the main 3k DPO Pilot Final run
    pilot_report_path = ROOT / "reports" / "tinker_dpo_smoke" / "phase8-bio-dpo-pilot-3k-final" / "report.json"
    if pilot_report_path.exists():
        print(f"Uploading historical DPO training: {pilot_report_path.name}...")
        try:
            report = json.loads(pilot_report_path.read_text(encoding="utf-8"))
            
            # Start a run for the training trajectory
            run = wandb.init(
                project="pearl-dpo",
                name=report["name"],
                config={
                    "model": report["base_model"],
                    "pairs_path": report["pairs_path"],
                    "pair_count": report["pair_count"],
                    "epochs": report["epochs"],
                    "batch_pairs": report["batch_pairs"],
                    "beta": report["beta"],
                    "learning_rate": report["learning_rate"],
                    "rank": report["rank"],
                    "init_state_path": report["init_state_path"],
                    "reference_state_path": report["reference_state_path"],
                    "checkpoint_path": report["checkpoint_path"],
                    "historical_import": True
                }
            )
            
            # Replay each batch step-by-step
            batches = report.get("batches", [])
            for batch in batches:
                epoch = batch["epoch"]
                batch_index = batch["batch_index"]
                
                log_data = {
                    "epoch": epoch,
                    "batch_index": batch_index,
                    "global_step": epoch * (report["pair_count"] // report["batch_pairs"]) + batch_index,
                }
                
                # Extract forward/backward metrics
                fb_metrics = batch.get("forward_backward_metrics") or {}
                for k, v in fb_metrics.items():
                    log_data[f"train/{k}"] = v
                    
                # Extract optimizer metrics
                opt_metrics = batch.get("optim_step_metrics") or {}
                for k, v in opt_metrics.items():
                    log_data[f"train/optim_{k}"] = v
                    
                wandb.log(log_data)
                
            run.finish()
            print("Successfully uploaded DPO Pilot Training history.")
        except Exception as e:
            print(f"Error uploading training run: {e}")
    else:
        print("Historical pilot report not found.")

def upload_eval_suites():
    try:
        import wandb
    except ImportError:
        return

    # 2. Upload consolidated robustness summaries
    robustness_dir = ROOT / "reports" / "robustness"
    if robustness_dir.exists():
        for suite_dir in robustness_dir.iterdir():
            if not suite_dir.is_dir():
                continue
            summary_path = suite_dir / "robustness_summary.json"
            if summary_path.exists():
                print(f"Uploading historical evaluation suite: {suite_dir.name}...")
                try:
                    summary = json.loads(summary_path.read_text(encoding="utf-8"))
                    
                    run = wandb.init(
                        project="pearl-eval",
                        name=f"robustness-{suite_dir.name}",
                        config={
                            "suite_name": summary["suite_name"],
                            "init_state_path": summary["init_state_path"],
                            "model": summary["model"],
                            "variant": summary["variant"],
                            "suite_sizes": summary["suite_sizes"],
                            "temperatures": summary["temperatures"],
                            "seeds": summary["seeds"],
                            "durability_config": summary["durability_config"],
                            "historical_import": True
                        }
                    )
                    
                    # Log global durability gate status
                    gate = summary.get("durability_gate") or {}
                    wandb.log({
                        "durability/gate_passed": int(gate.get("passed", False)),
                        "durability/baseline_locked": int(gate.get("baseline_locked", False)),
                    })
                    
                    # Log group-level metrics
                    for group in summary.get("groups", []):
                        p_count = group["prompt_count"]
                        temp = group["temperature"]
                        prefix = f"group_p{p_count}_t{temp}"
                        
                        group_data = {
                            f"{prefix}/run_count": group["run_count"],
                            f"{prefix}/bridge_hits_rate_mean": group["bridge_hits_per_prompt"]["mean"],
                            f"{prefix}/bridge_hits_rate_min": group["bridge_hits_per_prompt"]["min"],
                            f"{prefix}/bridge_hits_rate_max": group["bridge_hits_per_prompt"]["max"],
                            f"{prefix}/stability_dominant_rate_mean": group["stability_dominant_rate"]["mean"],
                            f"{prefix}/geometry_dominant_rate_mean": group["geometry_dominant_rate"]["mean"],
                            f"{prefix}/prompts_with_hits": group["prompts_with_any_tier2_across_seeds"],
                        }
                        wandb.log(group_data)
                        
                    run.finish()
                    print(f"Successfully uploaded {suite_dir.name} evaluation summary.")
                except Exception as e:
                    print(f"Error uploading eval suite {suite_dir.name}: {e}")

if __name__ == "__main__":
    upload_training_runs()
    upload_eval_suites()
