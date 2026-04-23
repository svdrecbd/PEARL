# Overview

PEARL is a research codebase for PETase-family sequence design. The repo currently contains three layers that need to stay conceptually separate:

1. The reusable engine:
   - generation, scoring, selection, reporting, and generic workflow runners
2. The active PETase campaign:
   - current mining, postprocess, training, robustness, and reranker work
3. The historical experiment surface:
   - one-off wrappers and queue chains preserved for continuity

The refactor now establishes that line explicitly.

Current repo state:
- supported strict and mining control flow is config-driven under:
  - [configs/experiments/README.md](../configs/experiments/README.md)
- reusable engine logic lives under:
  - [src/pearl/paths.py](../src/pearl/paths.py)
  - [src/pearl/detached_jobs.py](../src/pearl/detached_jobs.py)
  - [src/pearl/watchers.py](../src/pearl/watchers.py)
  - [src/pearl/checkpoints.py](../src/pearl/checkpoints.py)
  - [src/pearl/io_utils.py](../src/pearl/io_utils.py)
  - [src/pearl/reports.py](../src/pearl/reports.py)
  - [src/pearl/smoke_gate.py](../src/pearl/smoke_gate.py)
  - [src/pearl/strict_curricula.py](../src/pearl/strict_curricula.py)
  - [src/pearl/run_records.py](../src/pearl/run_records.py)
- supported runners now call those shared modules instead of reimplementing pathing, detached-job, watcher, and checkpoint logic per wrapper

## Supported Surface

The supported workflows are documented in:

- [workflows.md](workflows.md)
- [operations.md](operations.md)
- [science.md](science.md)
- [manifold_construction.md](manifold_construction.md)

For onboarding, treat these docs as authoritative before reading the white paper or the long-form labnotes. The white paper is useful background, but it is not the current-state operator document.

These docs describe the small set of workflows the repo should actively support:

- `mine`
- `postprocess`
- `analyze`
- `build-dataset`
- `repair`
- `train`
- `robustness`
- `reranker`
- `manifold-construction` (Phase 1 validator-first scaffold-bank implementation)

## Current Scientific Stance

As of April 22, 2026:

- `strict-core-v7-repair` is the best historical branch, but its robustness was narrow.
- `strict-core-v8-coverage` failed to broaden that branch; it regressed at `p12/p24` and lost family-faithful robustness.
- The `v8` stage-A p12/p24 diagnostic also failed, so `stage-b-lite` was not the sole problem.
- The `v9` p12/p24 repair rescue produced `79` high-ESM loose survivors but `0` strict-valid candidates and `0` retrain positives.
- The next serious strategy is scaffold-first manifold construction, not another small SFT tweak or blind paid mining tranche.
- Phase 1 has passed locally with `12,619` unique banked sequences, `4,893` family-manifold scaffolds, `3,769` strict-manifold scaffolds, `79` recovered `v9` negative rows, and `274` strict candidate positives.
- Phase 2 produced and ESM-scored `10,000` same-length strict-manifold candidates; all scored `>=95` on the L40S.
- Phase 2 selection passed readiness with `230` selected strict candidates across `79` parents, `8` lengths, `133` bridge-quality rows, and `100` two-mutants.
- Manifold curriculum v1 trained cleanly from the Phase 2 pool, but failed transfer at `p24`: `p12` passed with tier-2 hits `[1, 2, 0]`, while `p24` failed with `[0, 1, 0]`.
- Offline manifold v1.1 is built to patch the p24 prompt/length hole: `216` rows, including `48` exact p24 prompt-replay strict scaffold anchors.
- The active recommendation is to review v1.1 before any new paid branch.

## Historical Surface

Versioned `strict_core_*` and `strict_first_union` wrapper scripts are part of the project history, not the supported surface. They are tracked in:

- [archive/2026q1_topoff1m_a/README.md](../archive/2026q1_topoff1m_a/README.md)
- [archive/2026q1_topoff1m_a/manifest.json](../archive/2026q1_topoff1m_a/manifest.json)

They now live under the archive directly, and the old `scripts/` paths are compatibility symlinks so old report references and labnotes links do not break.

That means the repo should now be read as:
- `src/pearl`: reusable engine
- `configs/experiments`: supported workflow configuration
- `scripts`: active entrypoints plus compatibility symlinks
- `archive/.../scripts`: fossilized campaign wrappers

## Long-Form History

The full scientific and operational record remains in:

- [notes/LABNOTES.md](../notes/LABNOTES.md)

That file is the project fossil record, not the main operator entrypoint.
