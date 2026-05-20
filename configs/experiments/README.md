# Experiment Configs

Active Phase 8 work does not currently have a launch config checked into this directory.

Historical configs were moved to:

- `archive/2026-04-28-labyrinth-cleanup/configs/experiments/`

Current operational state:

- The active dataset is `data/phase8_dpo/dpo_preferences_hybrid_10k.jsonl`.
- The active preflight manifest is `data/phase8_dpo/dpo_preferences_hybrid_10k_preflight.json`.
- The next local check is `scripts/run_tinker_dpo_smoke.py --shape-only` against the active
  pair file; the remaining blocker is a tiny paid Tinker custom-loss smoke, not config selection.
- `physical_to_sequence_dpo_opd.yaml` is the offline artifact-build template for turning
  evaluated candidate rows into physical preference pairs and OPD distillation winners.

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

See `REPO_MAP.md` at the repository root for the active workspace map.
