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
  - [/Users/svdr/tinker/configs/experiments/README.md](/Users/svdr/tinker/configs/experiments/README.md)
- reusable engine logic lives under:
  - [/Users/svdr/tinker/src/pearl/paths.py](/Users/svdr/tinker/src/pearl/paths.py)
  - [/Users/svdr/tinker/src/pearl/detached_jobs.py](/Users/svdr/tinker/src/pearl/detached_jobs.py)
  - [/Users/svdr/tinker/src/pearl/watchers.py](/Users/svdr/tinker/src/pearl/watchers.py)
  - [/Users/svdr/tinker/src/pearl/checkpoints.py](/Users/svdr/tinker/src/pearl/checkpoints.py)
  - [/Users/svdr/tinker/src/pearl/io_utils.py](/Users/svdr/tinker/src/pearl/io_utils.py)
  - [/Users/svdr/tinker/src/pearl/reports.py](/Users/svdr/tinker/src/pearl/reports.py)
  - [/Users/svdr/tinker/src/pearl/smoke_gate.py](/Users/svdr/tinker/src/pearl/smoke_gate.py)
  - [/Users/svdr/tinker/src/pearl/strict_curricula.py](/Users/svdr/tinker/src/pearl/strict_curricula.py)
  - [/Users/svdr/tinker/src/pearl/run_records.py](/Users/svdr/tinker/src/pearl/run_records.py)
- supported runners now call those shared modules instead of reimplementing pathing, detached-job, watcher, and checkpoint logic per wrapper

## Supported Surface

The supported workflows are documented in:

- [/Users/svdr/tinker/docs/workflows.md](/Users/svdr/tinker/docs/workflows.md)
- [/Users/svdr/tinker/docs/operations.md](/Users/svdr/tinker/docs/operations.md)
- [/Users/svdr/tinker/docs/science.md](/Users/svdr/tinker/docs/science.md)

These docs describe the small set of workflows the repo should actively support:

- `mine`
- `postprocess`
- `build-dataset`
- `train`
- `robustness`
- `reranker`

## Historical Surface

Versioned `strict_core_*` and `strict_first_union` wrapper scripts are part of the project history, not the supported surface. They are tracked in:

- [/Users/svdr/tinker/archive/2026q1_topoff1m_a/README.md](/Users/svdr/tinker/archive/2026q1_topoff1m_a/README.md)
- [/Users/svdr/tinker/archive/2026q1_topoff1m_a/manifest.json](/Users/svdr/tinker/archive/2026q1_topoff1m_a/manifest.json)

They now live under the archive directly, and the old `scripts/` paths are compatibility symlinks so old report references and labnotes links do not break.

That means the repo should now be read as:
- `src/pearl`: reusable engine
- `configs/experiments`: supported workflow configuration
- `scripts`: active entrypoints plus compatibility symlinks
- `archive/.../scripts`: fossilized campaign wrappers

## Long-Form History

The full scientific and operational record remains in:

- [/Users/svdr/tinker/notes/LABNOTES.md](/Users/svdr/tinker/notes/LABNOTES.md)

That file is the project fossil record, not the main operator entrypoint.
