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

As of April 22, 2026, do not launch another strict-core train branch from the failed `v9` repair output. The repair run completed, but readiness failed with `0` retrain positives. The current active path is scaffold-first manifold construction, documented in [manifold_construction.md](manifold_construction.md).

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

Phase 1 now has a validator-first local runner for scaffold-bank construction, blueprint extraction, immutable/mutable mask construction, and strict-positive round-trip checks.

Operational starting point:

```bash
python scripts/manifold_construction_experiment.py \
  --config configs/experiments/manifold/topoff1m_a_phase1_constructor_20260422.json \
  launch-pad
```

Current local Phase 1 result:
- `ready: true`
- `12,619` unique sequences
- `4,893` family-manifold scaffolds
- `3,769` strict-manifold scaffolds
- `274` strict candidate positives
- `0` strict-positive round-trip rejects
- recovered `79` `v9` negative rows with `0` negative family-manifold passes

Phase 2 pre-ESM frontier:

```bash
python scripts/manifold_construction_experiment.py \
  --config configs/experiments/manifold/topoff1m_a_phase1_constructor_20260422.json \
  build-phase2-frontier
```

Current local Phase 2 result:
- `10,000` same-length strict-manifold candidates
- `4,067` one-mutants
- `5,933` two-mutants
- `79` contributing parent scaffolds before the frontier cap was reached
- L40S ESM scoring completed for all `10,000` rows
- min `99.73`, mean `99.9121`, max `99.98`
- all `10,000` scored `>=95`

Phase 2 selection:

```bash
python scripts/manifold_construction_experiment.py \
  --config configs/experiments/manifold/topoff1m_a_phase1_constructor_20260422.json \
  select-phase2
```

Current selection result:
- `ready_for_curriculum_build: true`
- `230` selected strict candidates
- `79` parent scaffolds
- `8` unique lengths
- `130` one-mutants and `100` two-mutants
- `133` bridge-quality rows across `48` parent scaffolds
- max parent share `0.013043`
- max length share `0.165217`
- selected ESM min `99.8`, mean `99.9225`, max `99.98`

Manifold curriculum v1 transfer test:
- config: [../configs/experiments/strict/topoff1m_a_manifold_curriculum_v1_20260422.json](../configs/experiments/strict/topoff1m_a_manifold_curriculum_v1_20260422.json)
- dataset: `reports/raft/topoff1m-a-manifold-curriculum-v1-20260422/manifold_v1_stage_a.jsonl`
- summary: `reports/raft/topoff1m-a-manifold-curriculum-v1-20260422/manifold_v1_stage_a_summary.json`
- stage-A run: `pearl-micro-sft-topoff1m-a-manifold-v1-stagea-lr8e7-ep2`
- p12/p24 gate: `pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128`
- result: failed overall
- `p12`: passed, tier-2 hits by seed `[1, 2, 0]`, `2 / 3` seeds hit, `3` prompts covered
- `p24`: failed, tier-2 hits by seed `[0, 1, 0]`, `1 / 3` seeds hit, `1` prompt covered
- GPU drained after completion; no compute process remained

Next operational step:
- do not launch retries, stage-B, p48, or paid mining from this branch
- run an offline audit of p12 hits versus p24 misses
- build a balanced `v1.1` curriculum candidate set before any new Tinker spend

Manifold curriculum v1.1 offline repair:
- audit script: [../scripts/audit_manifold_v1_gate.py](../scripts/audit_manifold_v1_gate.py)
- builder: [../scripts/build_manifold_v11_curriculum.py](../scripts/build_manifold_v11_curriculum.py)
- config: [../configs/experiments/strict/topoff1m_a_manifold_curriculum_v11_20260422.json](../configs/experiments/strict/topoff1m_a_manifold_curriculum_v11_20260422.json)
- audit report: `reports/analysis/manifold_v1_gate_audit_20260422/audit.md`
- dataset: `reports/raft/topoff1m-a-manifold-curriculum-v11-20260422/manifold_v11_stage_a.jsonl`
- summary: `reports/raft/topoff1m-a-manifold-curriculum-v11-20260422/manifold_v11_stage_a_summary.json`
- result: `216` rows, `160` balanced Phase 2 anchors, `48` p24 prompt-replay strict scaffold anchors, `8` purebred anchors
- p24 replay anchor length delta: mean absolute `0.042`, max absolute `1`
- launch policy: review first; do not train automatically

Manifold curriculum v1.1 p24 gate:
- stage-A gate: `pearl-topoff1m-a-manifold-v11-stagea-gate-p24-t08-s41s53s67-c128`
- postmortem script: [../scripts/audit_manifold_v11_gate.py](../scripts/audit_manifold_v11_gate.py)
- postmortem report: `reports/analysis/manifold_v11_gate_postmortem_20260423/audit.md`
- robustness summary: `reports/robustness/pearl-topoff1m-a-manifold-v11-stagea-gate-p24-t08-s41s53s67-c128/robustness_summary.json`
- result: failed cleanly with completed runs `3`, missing runs `0`, tier-2 hits `[0, 0, 0]`, and prompt coverage `[0, 0, 0]`
- failure mode: raw pool had `9,216` candidates but `0` single-motif plus geometry plus ESM tier-2 proxy candidates
- launch policy: do not launch p48, stage-B, retry, or broad mining from v1.1

Next supported operational path:
- build v1.2 offline first
- lane builder: [../scripts/build_manifold_v12_offline_lanes.py](../scripts/build_manifold_v12_offline_lanes.py)
- lane summary: `reports/analysis/manifold_v12_offline_lanes_20260423/v12_offline_lanes_summary.json`
- current lane inventory: `43` geometry-valid/ESM-failing rows, `41` ESM-valid/geometry-failing rows, `2,946` single-motif background negatives, `6,186` motif-failure negatives, `55` selected length-offtarget failures
- repair-frontier builder: [../scripts/build_manifold_v12_repair_frontier.py](../scripts/build_manifold_v12_repair_frontier.py)
- repair-frontier scorer: [../scripts/score_manifold_v12_repair_frontier.py](../scripts/score_manifold_v12_repair_frontier.py)
- repair selector: [../scripts/select_manifold_v12_repair_candidates.py](../scripts/select_manifold_v12_repair_candidates.py)
- repair-frontier summary: `reports/analysis/manifold_v12_repair_frontier_20260423/repair_frontier_summary.json`
- first ESM-positive smoke: `24 / 24` ESM-valid/geometry-repair candidates passed ESM, but all from one source row
- one-per-source breadth diagnostic: `40 / 41` repaired ESM-lane representatives passed ESM, showing breadth in family space
- breadth-selected offline set: `39` strict/core/ESM candidates across `38` sources and `29` lengths
- stage-A dataset: `reports/raft/topoff1m-a-manifold-curriculum-v12-20260423/manifold_v12_stage_a.jsonl`
- experiment config: `configs/experiments/strict/topoff1m_a_manifold_curriculum_v12_20260423.json`
- require nonzero strict-conjunction density in offline replay before any paid Tinker gate
- additionally require source breadth and length-retargeted prompt obedience before any paid Tinker gate
- keep any future paid proof to a tiny p24-only gate until the offline constructor separates positives from v9/v1.1 negatives
- v1.2 paid p24 result: `3 / 3` seeds with one post-ESM hit each, but only `3 / 24` prompts covered
- v1.2 gate audit: `reports/analysis/manifold_v12_gate_audit_20260423/audit.json`
- v1.3 builder: `scripts/build_manifold_v13_curriculum.py`
- v1.3 config: `configs/experiments/strict/topoff1m_a_manifold_curriculum_v13_20260423.json`
- v1.3 stage-A dataset: `reports/raft/topoff1m-a-manifold-curriculum-v13-20260423/manifold_v13_stage_a.jsonl`
- v1.3 composition: `39` breadth anchors, `8` support scaffolds, `9` gate-hit replays, `8` purebred anchors
- v1.3 paid p24 result: tier-2 hits by seed `[0, 0, 1]`, prompt coverage `1 / 24`, family-faithful hits `0`
- v1.3 robustness summary: `reports/robustness/pearl-topoff1m-a-manifold-v13-stagea-gate-p24-t08-s41s53s67-c128/robustness_summary.json`
- only recovered tier-2 event: seed `67`, prompt step `11`, bridge-only
- do not launch a v1.4-style replay from this branch shape
- the next approved work should be offline manifold redesign using v1.2 positives and v1.3 negatives, not stage-B, p48, or mining

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
