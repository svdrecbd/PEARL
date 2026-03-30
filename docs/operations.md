# Operations

## Environment

Local/dev environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Runtime requirements:
- `TINKER_API_KEY`
- access to a Tinker backend
- local `mps` or CUDA hardware for ESM-heavy paths when not offloaded

Minimal validation suite:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Current library-backed test surface includes:
- strict curriculum selection and dataset building
- detached job and watcher plumbing
- checkpoint-map and JSON helpers
- report/resume validation
- smoke-gate evaluation

## Path Convention

The repo should resolve paths from repo root, not from one machine-specific absolute path.

Shell entrypoints should prefer:
- [scripts/repo_root.sh](../scripts/repo_root.sh)

Python code should prefer:
- [src/pearl/paths.py](../src/pearl/paths.py)
- [src/pearl/family.py](../src/pearl/family.py)
- [src/pearl/esm_proxy.py](../src/pearl/esm_proxy.py)

Detached job launch/stop plumbing should prefer:
- [src/pearl/detached_jobs.py](../src/pearl/detached_jobs.py)
- [src/pearl/watchers.py](../src/pearl/watchers.py)
- thin CLIs:
  - [scripts/launch_detached_job.py](../scripts/launch_detached_job.py)
  - [scripts/stop_detached_job.py](../scripts/stop_detached_job.py)

Checkpoint-map and atomic JSON helpers should prefer:
- [src/pearl/checkpoints.py](../src/pearl/checkpoints.py)
- [src/pearl/io_utils.py](../src/pearl/io_utils.py)

## Current Operator Rule

Use the supported workflow entrypoints from [docs/workflows.md](workflows.md).

Do not treat versioned campaign wrappers as the default operational surface unless you are explicitly replaying historical work.

## Config-Driven Strict Experiments

The supported strict experiment path is now:

```bash
bash scripts/launch_strict_experiment.sh \
  --config configs/experiments/strict/topoff1m_a_strict_core_v6.json \
  describe --pretty
```

```bash
bash scripts/launch_strict_experiment.sh \
  --config configs/experiments/strict/topoff1m_a_strict_core_v6.json \
  build-datasets
```

```bash
bash scripts/launch_strict_experiment.sh \
  --config configs/experiments/strict/topoff1m_a_strict_core_v6.json \
  launch-chain
```

Supported subcommands are:
- `describe`
- `build-datasets`
- `launch-stage`
- `launch-smoke`
- `launch-robustness`
- `watch-smoke-after-stage`
- `watch-stageb-after-smoke`
- `watch-robustness-after-stageb`
- `launch-chain`

## Config-Driven Mining

The supported mining path is now:

```bash
bash scripts/launch_mining_experiment.sh \
  --config configs/experiments/mining/topoff1m_a_targeted_raft.json \
  describe --pretty
```

```bash
bash scripts/launch_mining_experiment.sh \
  --config configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million.json \
  build-prompt-pack
```

```bash
bash scripts/launch_mining_experiment.sh \
  --config configs/experiments/mining/topoff1m_a_stageb_lite_even_million.json \
  launch-stage1
```

The generic runners now share the same repo-root and detached-job helpers:
- [scripts/strict_experiment.py](../scripts/strict_experiment.py)
- [scripts/mining_experiment.py](../scripts/mining_experiment.py)

## Historical Scripts

The historical wrapper inventory is tracked in:

- [archive/2026q1_topoff1m_a/manifest.json](../archive/2026q1_topoff1m_a/manifest.json)

Those files now live under the archive, and the old `scripts/` paths are compatibility symlinks for continuity with old notes and report links. They are not the supported surface.

The current `v6` wrapper family is now a compatibility layer:
- [scripts/build_topoff1m_a_strict_core_v6_datasets.sh](../scripts/build_topoff1m_a_strict_core_v6_datasets.sh)
- [scripts/launch_topoff1m_a_strict_core_v6.sh](../scripts/launch_topoff1m_a_strict_core_v6.sh)
- [scripts/launch_topoff1m_a_strict_core_v6_smoke.sh](../scripts/launch_topoff1m_a_strict_core_v6_smoke.sh)
- [scripts/launch_topoff1m_a_strict_core_v6_robustness.sh](../scripts/launch_topoff1m_a_strict_core_v6_robustness.sh)

Those names are preserved, but they now dispatch through the config-driven strict runner instead of carrying their own workflow logic.

The same is now true for the legacy `targeted_raft` and `strict_core_v2` through `strict_core_v6` launch/build wrappers: the old names are preserved, but the workflow logic is centralized in config-driven runners.
