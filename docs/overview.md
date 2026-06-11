# Overview

PEARL is a research codebase for PETase-family sequence design. The repo currently contains three layers that need to stay conceptually separate:

1. The reusable engine:
   - generation, scoring, selection, reporting, and generic workflow runners
2. The active PETase campaign:
   - current Phase 8 preference-learning, DPO characterization, sparse OPD, and structural readout work
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
  - [src/pearl/tinker_dpo.py](../src/pearl/tinker_dpo.py)
  - [src/pearl/opd_lite.py](../src/pearl/opd_lite.py)
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
- `manifold-construction` (validator-first scaffold bank, repair-frontier lanes, and offline curriculum builders)
- `preference-dpo-opd` (Phase 8 DPO baseline, sparse OPD target build, and matched structural readouts)

## Current Scientific Stance

As of June 11, 2026:

- The SFT/mining/manifold campaign is historical context. It produced useful signal and failures, but did not deliver durable prompt/seed robustness or folded structural confidence.
- Phase 7 structural validation exposed the central failure mode: local sequence proxies can pass while global structure remains weak.
- Phase 8 is the active path: natural PETase/cutinase records are chosen positives, fold-failed generated rows are hard negatives, and DPO is the first preference-learning baseline.
- The 3k DPO pilot completed and learned the training distribution strongly. W&B/local batch metrics moved from first-100 mean DPO loss `0.6775` and reward margin `0.0419` to last-100 loss `0.3655` and reward margin `2.7476`.
- The biological readout is unresolved. The only completed DPO generation slice is `p12`, temperature `0.8`, seed `7`, with `0` bridge hits and `0 / 5` folded CA-triad passes.
- DPO is therefore a live baseline/control, not a solved design result and not a failed path.
- Sparse OPD/multi-teacher feedback is the prepared comparison branch while full-vocabulary logits remain unavailable.
- The next scientific work is DPO characterization plus matched DPO versus DPO+OPD structural readouts.

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
