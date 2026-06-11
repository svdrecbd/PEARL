# Experiment Configs

Active Phase 8 work does not currently have a one-command launch config checked into this directory.

Historical configs were moved to:

- `archive/2026-04-28-labyrinth-cleanup/configs/experiments/`

Current operational state:

- The active dataset is `data/phase8_dpo/dpo_preferences_hybrid_10k.jsonl`.
- The active preflight manifest is `data/phase8_dpo/dpo_preferences_hybrid_10k_preflight.json`.
- The active pair file passed `scripts/run_tinker_dpo_smoke.py --shape-only`.
- The tiny paid DPO smoke completed:
  - `reports/tinker_dpo_smoke/phase8-bio-dpo-smoke/report.json`
- A `3,000`-pair DPO pilot completed:
  - `reports/tinker_dpo_smoke/phase8-bio-dpo-pilot-3k-final/report.json`
  - checkpoint: `tinker://68b86c30-7c34-5c97-bb55-01e139610267:train:0/weights/phase8-bio-dpo-pilot-3k-final`
- W&B/local batch metrics strengthen the DPO training read:
  - first-100 mean DPO loss `0.6775`; last-100 `0.3655`
  - first-100 mean reward margin `0.0419`; last-100 `2.7476`
  - positive-min-margin batches rose from `6%` to `87%`
- DPO runner telemetry status:
  - W&B logging is additive
  - local per-batch `report.json` persistence is restored
  - fake-Tinker CLI regression covers non-empty train-mode batch reports
- The only completed post-DPO evaluation slice is still preliminary:
  - `p12`, temperature `0.8`, seed `7`
  - `0` functional bridge hits
  - `0` family-faithful bridge hits
  - folded subset: `0 / 5` CA-triad passes, mean pLDDT `25.61-36.27`
  - interpretation: underpowered warning slice, not a DPO-only verdict
- Canonical readout:
  - `docs/phase8_dpo_pilot_readout.md`
- `physical_to_sequence_dpo_opd.yaml` is the offline artifact-build template for turning
  evaluated candidate rows into physical preference pairs and OPD distillation winners.
- `docs/phase8_no_logits_opd.md` is the no-logits execution packet. It defines the sparse
  top-K OPD path that can run with current Tinker APIs while full-vocabulary logits access is pending.
- The sparse OPD lane is scaffolded by `scripts/build_sparse_opd_targets.py` and
  `scripts/run_tinker_sparse_opd_smoke.py`.
- `scripts/build_sparse_opd_rollout_seed.py` creates a static smoke seed panel from the DPO chosen
  sequences; this is only for trace/target/training readiness, not the final on-policy readout.
- `scripts/build_tinker_teacher_traces.py` collects the teacher-forced top-K traces needed by sparse OPD.
- `scripts/phase8_paid_run_preflight.py` writes the combined readiness and cost report.
- The full dual-policy loop is not yet a one-command launch: post-DPO sampling, candidate folding,
  physical pair construction, and OPD/SFT winner distillation still need to be run as explicit stages.
- Exact ProteinOPD remains blocked on full-vocabulary student and teacher logits; sparse OPD is the
  available approximation, not a claim of exact JSD distillation.

No-cost Phase 8 pair shape check:

```bash
.venv/bin/python scripts/run_tinker_dpo_smoke.py \
  --name phase8-bio-dpo-shape \
  --pairs-path data/phase8_dpo/dpo_preferences_hybrid_10k.jsonl \
  --shape-only
```

Tiny Tinker DPO smoke command, already completed for the current dataset:

```bash
.venv/bin/python scripts/run_tinker_dpo_smoke.py \
  --name phase8-bio-dpo-smoke \
  --pairs-path data/phase8_dpo/dpo_preferences_hybrid_10k.jsonl \
  --max-pairs 8 \
  --batch-pairs 2
```

No-cost sparse OPD target shape check after teacher top-K traces exist:

```bash
.venv/bin/python scripts/build_sparse_opd_rollout_seed.py \
  --max-rows 256

.venv/bin/python scripts/build_sparse_opd_targets.py \
  --name phase8-sparse-opd-targets \
  --teacher-trace-path reports/opd_lite/phase8-teacher-traces/teacher_traces.jsonl \
  --top-k 20

.venv/bin/python scripts/run_tinker_sparse_opd_smoke.py \
  --name phase8-sparse-opd-shape \
  --targets-path reports/opd_lite/phase8-sparse-opd-targets/sparse_opd_targets.jsonl \
  --shape-only
```

Combined readiness/cost preflight:

```bash
.venv/bin/python scripts/phase8_paid_run_preflight.py \
  --name phase8-paid-readiness
```

Full DPO characterization + OPD comparison shape after the May 30 DPO pilot and June W&B review:

1. Keep the 3k DPO checkpoint as the active DPO-only baseline/control.
2. Run shuffled and/or held-out DPO diagnostics when budget permits.
3. Run additional DPO-only generation slices across prompts, temperatures, and seeds.
4. Use May 30 and follow-up folded failures or low-pLDDT selected candidates as on-policy negatives.
5. Build sparse OPD teacher traces and sparse targets.
6. Train a tiny DPO + sparse OPD update.
7. Sample compact candidate panels from the base, SFT, DPO, sparse OPD, and DPO+OPD policies.
8. Evaluate/fold strict subsets into PEARL `candidate_audit.json` files.
9. Compare pLDDT/pTM, active-site geometry, repeat/domain artifacts, novelty distance,
   family score, diversity, solubility/aggregation proxies, expression likelihood,
   manufacturability, biosafety, and functional proxy score.
10. Run `scripts/run_physical_to_sequence_loop.py` to build on-policy physical DPO pairs and OPD winners.

The next research milestone is: can DPO + OPD reduce structural hallucination while preserving novelty?
The key comparison is not raw proxy-score improvement; it is whether DPO + OPD produces fewer
confident-looking structural mirages than a sufficiently characterized DPO-only baseline.

See `REPO_MAP.md` at the repository root for the active workspace map.
