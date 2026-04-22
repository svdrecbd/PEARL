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

Local-hosted mining trials additionally need:
- a CUDA box large enough to serve the local sampler model
- an OpenAI-compatible inference server such as `vllm`
- a tokenizer id resolvable through Hugging Face for the served model

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

As of April 22, 2026, do not launch another strict-core train branch from the failed `v9` repair output. The repair run completed, but readiness failed with `0` retrain positives. The current discussion path is scaffold-first manifold construction, documented in [manifold_construction.md](manifold_construction.md).

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

Current branch caveat:
- `strict-core-v7-repair` is the best historical baseline.
- `strict-core-v8-coverage` trained and evaluated, but failed short-context robustness.
- `strict-core-v9-p12p24-repair` was prepared as a possible branch but should not be trained from the failed repair pool.
- Do not run `launch-chain` on `v9` unless a replacement strict pool passes readiness.

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

Local OpenAI-compatible stage1 trial:

```bash
bash scripts/sync_local_stage1_bundle.sh <vm-host-or-ip>
bash scripts/setup_nebius_h200_local_stage1_env.sh
export MODEL=google/gemma-4-31b-it
export SAMPLER_TOKENIZER=google/gemma-4-31b-it
bash scripts/launch_local_vllm_server.sh
$HOME/venvs/pearl-local-stage1-cu124/bin/python scripts/check_local_openai_sampler.py \
  --base-url http://127.0.0.1:8000 \
  --model gemma-local \
  --tokenizer "$SAMPLER_TOKENIZER"
bash scripts/launch_topoff1m_a_stageb_lite_coverage_million_local.sh
```

Notes:
- the local-hosted path is stage1 / eval-only only
- it reuses the existing coverage-aware prompt pack under `reports/raft_prompt_packs/...`
- training and robustness stay on the existing Tinker-backed path
- the current recommendation is not to launch a blind `1M` mining run by default
- if paid mining is chosen, start with a `50k-75k` p12/p24 exact-hole sweep, then decide whether a `250k-300k` targeted tranche is justified

The generic runners now share the same repo-root and detached-job helpers:
- [scripts/strict_experiment.py](../scripts/strict_experiment.py)
- [scripts/mining_experiment.py](../scripts/mining_experiment.py)
- [scripts/analysis_experiment.py](../scripts/analysis_experiment.py)
- [scripts/repair_experiment.py](../scripts/repair_experiment.py)

## Config-Driven Historical Analysis

The supported historical-analysis staging path is now:

```bash
bash scripts/launch_analysis_experiment.sh \
  --config configs/experiments/analysis/petase_historical_local_exploit.json \
  describe --pretty
```

```bash
bash scripts/launch_analysis_experiment.sh \
  --config configs/experiments/analysis/petase_historical_local_exploit.json \
  launch-pad --dry-run
```

Supported subcommands are:
- `describe`
- `build-universe`
- `build-neighborhoods`
- `build-shortlist`
- `launch-pad`

Operator rule:
- the dry-run launch pad is the staging surface
- do not actually process the historical corpus until you explicitly launch it

## Config-Driven Repair / Local Exploit

The supported repair pilot path is now:

```bash
bash scripts/launch_repair_experiment.sh \
  --config configs/experiments/repair/topoff1m_a_local_repair_pilot_20260410.json \
  describe --pretty
```

```bash
bash scripts/launch_repair_experiment.sh \
  --config configs/experiments/repair/topoff1m_a_local_repair_pilot_20260410.json \
  launch-pad --dry-run
```

Bounded scale-up path:

```bash
bash scripts/launch_repair_experiment.sh \
  --config configs/experiments/repair/topoff1m_a_local_repair_scaleup_20260412.json \
  launch-pad --dry-run
```

Failed p12/p24 rescue path:

```bash
bash scripts/launch_repair_experiment.sh \
  --config configs/experiments/repair/topoff1m_a_v9_p12p24_repair_20260421.json \
  describe --pretty
```

Supported subcommands are:
- `describe`
- `build-pool`
- `cap-pool`
- `run-native-repair`
- `validate`
- `check-readiness`
- `launch-pad`

Operator rule:
- repair is a supported workflow, but the April 21/22 p12/p24 rescue failed as a v9 data source
- the pilot and April 12 scale-up succeeded; the p12/p24 rescue did not
- use `cap-pool` when the config carries a `repair_pool.diversity_cap` block
- do not use high-ESM repair survivors for training unless they also pass strict family validation and readiness
- future repair work should enforce family-manifold constraints before optimizing ESM or geometry

## Manifold Construction

There is not yet a production runner for the manifold-construction route.

Operational starting point:

1. Build a scaffold bank from natural references, canonical purebreds, old strict hits, mined family-faithful reps, and April 12 strict repairs.
2. Verify all unedited scaffolds round-trip through strict validation.
3. Extract active-site blueprints and immutable masks.
4. Run same-length edit search only inside allowed mutable positions.
5. Reject any sequence that leaves the family length band, motif identity, active-site blueprint, catalytic gap limits, or family core screen.

Reference:
- [manifold_construction.md](manifold_construction.md)

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
