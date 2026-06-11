# Active Repo Map

This workspace has been reduced to the components needed for the next PEARL pass.
Historical experiment material was moved to `archive/2026-04-28-labyrinth-cleanup/`.

## Active Components

- `main.py`: primary PEARL sampling/evaluation entrypoint.
- `src/pearl/`: supported library code for family scoring, reports, paths, watchers, and sampler utilities.
- `scripts/`: active operational scripts only.
  - Phase 8 DPO data/training: `build_hybrid_10k_dpo.py`, `preflight_phase8_dpo_dataset.py`, `run_tinker_dpo_smoke.py`. Chosen positives must be audited natural reference records; generated Phase 7 library rows are hard negatives only.
  - Phase 8 sparse OPD: `build_tinker_teacher_traces.py`, `build_sparse_opd_targets.py`, `run_tinker_sparse_opd_smoke.py`, `phase8_paid_run_preflight.py`.
  - Phase 7 evidence: `phase7_mcmc_library_builder.py`, `build_phase7_manifest.py`, `fold_phase7_subset.py`, plotting/PyMOL helpers.
  - Runtime/eval support: `run_sft_warmstart.py`, `run_robustness_two_phase.py`, `run_robustness_suite.py`, `run_ablation.py`, `strict_experiment.py`, detached job helpers.
- `data/phase8_dpo/`: current local length-controlled DPO dataset and manifests. This directory is ignored by Git because generated datasets are local artifacts.
- `reports/analysis/phase7_local_library_v1/`: distilled Phase 7 library, fold metrics, canonical PDBs, figures, and FASTA batches.
- `reports/analysis/postmortems/`: current scientific postmortems.
- `docs/` and `notes/`: human-readable project state and working log.
- `tests/`: supported tests for the active surface.

## Strategic Direction

The active pass is not another broad SFT replay. The current house shape is a small PLM plus preference/RL loop that uses natural PETase/cutinase records as the positive manifold and fold-failed generated sequences as hard negatives. The 3k DPO pilot completed and learned the training distribution strongly, but structural yield is unresolved because the only completed generation/fold slice is thin and weak. New work should strengthen that loop: shuffled/held-out DPO diagnostics, compact post-train candidate generation, structural fold validation, sparse OPD comparison, and only then any larger library expansion.

Treat Phase 7 generated/local-library rows as evidence, not trusted positives. They are useful because they expose structural mirages, repeat shortcuts, and score/structure mismatches.

## Archived Material

`archive/2026-04-28-labyrinth-cleanup/` contains historical paid-run outputs, old manifold/repair/mining configs, one-off experiment scripts, raw ColabFold batch dumps, stale tests, and scratch files. Nothing was intentionally deleted.

Use the archive for forensic lookup only. New work should add scripts and reports to the active layout above, or create a new dated archive bucket if an experiment becomes inactive.
