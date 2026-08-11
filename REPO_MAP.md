# Active PEARL Repository Map

This public repository contains the PEARL scientific methods campaign and its reusable scientific
runtime. California Synthetic, Concord, IMS/Relief, company assets, and the MirageBench benchmark
package were moved to the separate private `svdrecbd/california-synthetic` repository without
merging Git histories.

Historical PEARL experiment material remains under `archive/2026-04-28-labyrinth-cleanup/` or in
Git-ignored local report/data directories.

## Active components

- `main.py`: primary PEARL sampling and evaluation entrypoint.
- `src/pearl/`: supported scientific library code for family scoring, preference training,
  structure gating, reports, paths, watchers, and sampler utilities.
- `scripts/`: PEARL data-building, training, evaluation, and analysis utilities.
  - Phase 8 preference data/training: `build_hybrid_10k_dpo.py`,
    `preflight_phase8_dpo_dataset.py`, and `run_tinker_dpo_smoke.py`.
  - Phase 8 sparse OPD: `build_tinker_teacher_traces.py`, `build_sparse_opd_targets.py`,
    `run_tinker_sparse_opd_smoke.py`, and `phase8_paid_run_preflight.py`.
  - Phase 7 evidence: `phase7_mcmc_library_builder.py`, `build_phase7_manifest.py`,
    `fold_phase7_subset.py`, and plotting/structure helpers.
  - Runtime/evaluation: matched sampling, robustness, ablation, strict-experiment, and detached-job
    helpers.
- `docs/`: supported scientific and operator documentation.
- `notes/LABNOTES.md`: long-form scientific record. Company/product strategy does not belong here.
- `tests/`: supported PEARL test surface.
- `infra/`: PEARL external-compute packaging, pending portability and secret review before commit.

## Local scientific artifacts

The following paths are intentionally ignored because they contain generated datasets, experiment
outputs, provider state, or large scientific artifacts:

- `data/`
- `reports/` except explicitly allowlisted publication assets
- `archive/`
- W&B state, logs, checkpoints, caches, and local environments

MirageBench reports derived from PEARL may remain locally as scientific evidence, but the benchmark
implementation and California Synthetic release machinery live in the private company repository.
Any future bridge must identify the released PEARL artifact, version/hash, license, and attribution.

## Current scientific priority

The twelve-model three-arm screen shows broad proxy-to-structure transfer failure under the current
PETase/cutinase contract. The raw artifacts are useful, but the pooled statistics and figures remain
provisional because the original analysis mixed cohorts, missed an aliased randomized arm, and did
not implement the declared model/seed/prompt hierarchy.

Immediate work should:

1. stop or canonicalize accidental duplicate paid runs;
2. rebuild the contaminated on-policy preference dataset before any replay;
3. freeze exactly twelve complete three-arm models and correct the hierarchical analysis;
4. regenerate figures with fail-closed loaders and source hashes;
5. write the PEARL methods paper within its scientific and institutional publication boundary.

Do not treat generated Phase 7 rows as trusted positives. Do not cite the random-substitution
"LigandMPNN" output, the non-ESM3 rescoring summary, or the current on-policy dataset as valid
scientific controls.
