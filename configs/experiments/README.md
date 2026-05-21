# Experiment Configs

Active Phase 8 work does not currently have a launch config checked into this directory.

Historical configs were moved to:

- `archive/2026-04-28-labyrinth-cleanup/configs/experiments/`

Current operational state:

- The active dataset is `data/phase8_dpo/dpo_preferences_hybrid_10k.jsonl`.
- The active preflight manifest is `data/phase8_dpo/dpo_preferences_hybrid_10k_preflight.json`.
- The active pair file has passed `scripts/run_tinker_dpo_smoke.py --shape-only`.
- The remaining paid blocker for the static preference path is a tiny Tinker custom-loss DPO smoke,
  not config selection.
- `physical_to_sequence_dpo_opd.yaml` is the offline artifact-build template for turning
  evaluated candidate rows into physical preference pairs and OPD distillation winners.
- The full dual-policy loop is not yet a one-command launch: post-DPO sampling, candidate folding,
  physical pair construction, and OPD/SFT winner distillation still need to be run as explicit stages.

No-cost Phase 8 pair shape check:

```bash
.venv/bin/python scripts/run_tinker_dpo_smoke.py \
  --name phase8-bio-dpo-shape \
  --pairs-path data/phase8_dpo/dpo_preferences_hybrid_10k.jsonl \
  --shape-only
```

Tiny Tinker DPO smoke once spend is intentional:

```bash
.venv/bin/python scripts/run_tinker_dpo_smoke.py \
  --name phase8-bio-dpo-smoke \
  --pairs-path data/phase8_dpo/dpo_preferences_hybrid_10k.jsonl \
  --max-pairs 8 \
  --batch-pairs 2
```

Full DPO + OPD loop shape after the smoke:

1. Train/update the policy with static natural-positive DPO.
2. Sample a compact candidate panel from that policy.
3. Evaluate/fold candidates into a PEARL `candidate_audit.json`.
4. Run `scripts/run_physical_to_sequence_loop.py` to build on-policy physical DPO pairs and OPD winners.
5. Train on physical pairs and distill the OPD winners, then run compact structural validation before scaling.

See `REPO_MAP.md` at the repository root for the active workspace map.
