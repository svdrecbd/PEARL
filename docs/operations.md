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
cd /Users/svdr/tinker
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
- [/Users/svdr/tinker/scripts/repo_root.sh](/Users/svdr/tinker/scripts/repo_root.sh)

Python code should prefer:
- [/Users/svdr/tinker/src/pearl/paths.py](/Users/svdr/tinker/src/pearl/paths.py)

Detached job launch/stop plumbing should prefer:
- [/Users/svdr/tinker/src/pearl/detached_jobs.py](/Users/svdr/tinker/src/pearl/detached_jobs.py)
- [/Users/svdr/tinker/src/pearl/watchers.py](/Users/svdr/tinker/src/pearl/watchers.py)
- thin CLIs:
  - [/Users/svdr/tinker/scripts/launch_detached_job.py](/Users/svdr/tinker/scripts/launch_detached_job.py)
  - [/Users/svdr/tinker/scripts/stop_detached_job.py](/Users/svdr/tinker/scripts/stop_detached_job.py)

Checkpoint-map and atomic JSON helpers should prefer:
- [/Users/svdr/tinker/src/pearl/checkpoints.py](/Users/svdr/tinker/src/pearl/checkpoints.py)
- [/Users/svdr/tinker/src/pearl/io_utils.py](/Users/svdr/tinker/src/pearl/io_utils.py)

## Current Operator Rule

Use the supported workflow entrypoints from [/Users/svdr/tinker/docs/workflows.md](/Users/svdr/tinker/docs/workflows.md).

Do not treat versioned campaign wrappers as the default operational surface unless you are explicitly replaying historical work.

## Config-Driven Strict Experiments

The supported strict experiment path is now:

```bash
bash /Users/svdr/tinker/scripts/launch_strict_experiment.sh \
  --config /Users/svdr/tinker/configs/experiments/strict/topoff1m_a_strict_core_v6.json \
  describe --pretty
```

```bash
bash /Users/svdr/tinker/scripts/launch_strict_experiment.sh \
  --config /Users/svdr/tinker/configs/experiments/strict/topoff1m_a_strict_core_v6.json \
  build-datasets
```

```bash
bash /Users/svdr/tinker/scripts/launch_strict_experiment.sh \
  --config /Users/svdr/tinker/configs/experiments/strict/topoff1m_a_strict_core_v6.json \
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
bash /Users/svdr/tinker/scripts/launch_mining_experiment.sh \
  --config /Users/svdr/tinker/configs/experiments/mining/topoff1m_a_targeted_raft.json \
  describe --pretty
```

```bash
bash /Users/svdr/tinker/scripts/launch_mining_experiment.sh \
  --config /Users/svdr/tinker/configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million.json \
  build-prompt-pack
```

```bash
bash /Users/svdr/tinker/scripts/launch_mining_experiment.sh \
  --config /Users/svdr/tinker/configs/experiments/mining/topoff1m_a_stageb_lite_even_million.json \
  launch-stage1
```

The generic runners now share the same repo-root and detached-job helpers:
- [/Users/svdr/tinker/scripts/strict_experiment.py](/Users/svdr/tinker/scripts/strict_experiment.py)
- [/Users/svdr/tinker/scripts/mining_experiment.py](/Users/svdr/tinker/scripts/mining_experiment.py)

## Historical Scripts

The historical wrapper inventory is tracked in:

- [/Users/svdr/tinker/archive/2026q1_topoff1m_a/manifest.json](/Users/svdr/tinker/archive/2026q1_topoff1m_a/manifest.json)

Those files now live under the archive, and the old `scripts/` paths are compatibility symlinks for continuity with old notes and report links. They are not the supported surface.

The current `v6` wrapper family is now a compatibility layer:
- [/Users/svdr/tinker/scripts/build_topoff1m_a_strict_core_v6_datasets.sh](/Users/svdr/tinker/scripts/build_topoff1m_a_strict_core_v6_datasets.sh)
- [/Users/svdr/tinker/scripts/launch_topoff1m_a_strict_core_v6.sh](/Users/svdr/tinker/scripts/launch_topoff1m_a_strict_core_v6.sh)
- [/Users/svdr/tinker/scripts/launch_topoff1m_a_strict_core_v6_smoke.sh](/Users/svdr/tinker/scripts/launch_topoff1m_a_strict_core_v6_smoke.sh)
- [/Users/svdr/tinker/scripts/launch_topoff1m_a_strict_core_v6_robustness.sh](/Users/svdr/tinker/scripts/launch_topoff1m_a_strict_core_v6_robustness.sh)

Those names are preserved, but they now dispatch through the config-driven strict runner instead of carrying their own workflow logic.

The same is now true for the legacy `targeted_raft` and `strict_core_v2` through `strict_core_v6` launch/build wrappers: the old names are preserved, but the workflow logic is centralized in config-driven runners.
