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

For onboarding, treat those three docs as authoritative before reading the white paper or the long-form labnotes. The white paper is useful background, but it is not the current-state operator document.

These docs describe the small set of workflows the repo should actively support:

- `mine`
- `postprocess`
- `analyze`
- `build-dataset`
- `repair`
- `train`
- `robustness`
- `reranker`

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
