# PEARL

PEARL stands for Protein Engineering Adapter via Reinforcement Learning.

This repository explores computational sequence design for PETase-family proteins using remote generation/training through Tinker and local scoring/ranking logic. It is an experimental research codebase, not a validated protein-design product.

## Start Here

- Sponsor-facing summary: [`WHITEPAPER.md`](WHITEPAPER.md)
- Full experimental history and decisions: [`notes/LABNOTES.md`](notes/LABNOTES.md)

## Current State (March 28, 2026)

- The full Tier-A Nebius A-stockpile is complete and local:
  - `761,029` records evaluated
  - `15,583` geometry passes
  - `141` functional bridges
  - `10` family-faithful bridges
- The postprocess bundle for that run lives under:
  - `reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/`
- The repair lane is no longer hypothetical:
  - H100 repair wave: `32` seeds -> `8,908` variants -> `446` raw survivors
  - capped survivor set: `61`
  - strict shortlist: `8`
  - strict family-clean repairs: `2`
- The retrain gate opened on repaired tier-1 proxies:
  - see `reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_survivor_readiness_wave1_h100_lineage_capped.json`
- Two post-topoff warmstart branches were trained:
  - `pearl-micro-sft-topoff1m-a-ultra-conservative-lr5e7-ep1`
  - `pearl-micro-sft-topoff1m-a-balanced-strict-lr5e7-ep1`
- `ultra` robustness is complete and failed durability:
  - `reports/robustness/pearl-topoff1m-a-ultra-robustness-2phase-h100-p12p24p48-t08-s41s53s67/robustness_summary.json`
- The new `balanced + motif_prior_soft_v2` mining lane is now the active positive result:
  - `300,032` raw candidates -> `27` functional bridge steps -> `4` family-faithful bridge steps
  - `200,192` raw candidates -> `23` functional bridge steps -> `8` family-faithful bridge steps
  - combined `500,224` raw candidates -> `50` functional bridge steps -> `12` family-faithful bridge steps
  - exact dedup on finalized hits remains `50` functional + `12` family-faithful
- The first mined-pool retrain branch (`softmotif-lineage-conservative`) also failed durability:
  - `reports/robustness/pearl-topoff1m-a-softmotif-lineage-conservative-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json`
- A stricter follow-up branch was then trained:
  - stage A strict union:
    - `reports/warmstart/pearl-micro-sft-topoff1m-a-strict-first-union-stagea-lr1e6-ep2/summary.json`
  - stage B strict union + small-anchor mix:
    - `reports/warmstart/pearl-micro-sft-topoff1m-a-strict-first-union-stageb-lr5e7-ep1/summary.json`
- The `strict-first-union` stage-B checkpoint still failed durability, but it failed better:
  - `reports/robustness/pearl-topoff1m-a-strict-first-union-stageb-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json`
  - `p12`: one seed hit tier-2 once
  - `p24`: zero tier-2 hits
  - `p48`: hits by seed `[1, 0, 2]`, including one family-faithful hit
- Current execution focus is no longer “find any strict hits”.
  - It is now recipe work on top of the validated `500k` mined pool.
- Wynton served as the bring-up path and validated the evaluator, but it is no longer the preferred production environment because scheduler latency dominated wall time.
- The validated production runtime for the sequence-stockpile scorer is:
  - `torch 2.5.1+cu121`
  - `PREFILTER_EVAL_MODE=staged`
  - `PREFILTER_CPU_WORKERS=8`
  - `ESM2_BATCH_SIZE=256`
  - `ESM2_SEQUENCE_BATCH_SIZE=1`
  - `ESM2_PIPELINE_CHUNK_SIZE=128`
- Final Nebius benchmark ladder:
  - L40S baseline: `0.364412 s/record`
  - tuned H100: `0.108953 s/record`
  - tuned H200: `0.104376 s/record`
- H200 is only `~4.4%` faster than H100 after tuning, so the current economic default is preemptible `8x H100`, not H200.
- The current decision gate is:
  - treat the `balanced + motif_prior_soft_v2` half-million mining lane as the live data engine
  - treat strict-heavy retraining as directionally correct, but assume the current `12`-anchor stage-B mix still blurs the basin
  - next recipe candidate is `strict-core-v2`:
    - strict-only union of old A-run family-faithful hits + new half-million family-faithful hits + canonical purebreds
    - stronger strict oversampling
    - `2-3` epochs at roughly `1e-6` to `1.5e-6`
  - only if that looks better, try `stage-b-lite`:
    - add just `4-8` bridge-only anchors for `1` low-LR epoch
  - do not spend on another large mining tranche until the stricter recipe space is exhausted

## What The System Does

1. Sample candidate sequences from a remote model.
2. Evaluate local sequence quality, family plausibility, motif structure, novelty, and catalytic geometry.
3. Run second-stage ranking with ESM proxy and selector weights.
4. Mine positives and near-misses.
5. Build compact repair/retrain datasets and rerun fixed robustness suites.
6. When robustness fails but mining improves, pivot toward a stockpile-first mining flywheel instead of forcing more branches through the old durability path.

## Core Files

- `main.py`: generation/eval loop, scoring, selection, resume-safe report writing
- `petase_family.py`: family scoring, motif/geometry checks, novelty logic
- `local_proxy.py`: ESM-2 pseudo-pLDDT scorer (torch backend)
- `scripts/run_ablation.py`: reproducible single-run launcher over prompt subsets
- `scripts/run_robustness_suite.py`: frozen `12/24/48` suite + durability gate summary
- `scripts/run_robustness_two_phase.py`: stockpile-first robustness runner for H100 (`stage1` Tinker sampling in parallel, then batched ESM finalization)
- `scripts/finalize_ablation_from_candidate_audit.py`: H100 second-stage rescoring/finalization from a `candidate_audit.json`
- `scripts/finalize_raft_wave.py`: finalize a stage1-only mining wave on CUDA/MPS after the stockpile is complete
- `scripts/run_backward_lane.py`: precompute miss-bank + repair-pool + retrain-readiness while other shards are still running
- `scripts/check_retrain_readiness.py`: automatic retrain-go/no-go checks on mined pools
- `scripts/check_repair_survivor_readiness.py`: retrain-go/no-go checks after adding repair survivors to a base run pool
- `scripts/build_diversity_capped_repair_pool.py`: caps repair pools by source run + sequence identity cluster before repair generation
- `scripts/build_strict_first_union_curricula.py`: builds strict-first union stage-A/stage-B curricula from old and new family-faithful pools plus a small anchor set
- `scripts/run_raft_wave.py`: detached mining waves with stage1-only stockpiling, prompt offsets, and a safety cap on parallel workers
- `scripts/rebalance_stage1_wave.py`: stop/relaunch unfinished stage1 prompt subsets as more shards when a wave is too coarse
- `scripts/launch_detached_job.py`: robust detached process launcher with metadata/logs
- `scripts/launch_topoff1m_a_warmstart.sh`: detached warmstart launcher for the `ultra` and `balanced` A-run curricula
- `scripts/launch_topoff1m_a_strict_first_union.sh`: detached warmstart launcher for the strict-first union stage-A / stage-B recipe
- `scripts/launch_topoff1m_a_strict_first_union_robustness.sh`: detached two-phase robustness launcher for the strict-first union checkpoints
- `scripts/sync_topoff1m_a_eval_bundle.sh`: pushes the H100 eval bundle to a Nebius VM
- `scripts/launch_topoff1m_a_robustness_h100.sh`: detached H100 launcher for the two-phase `ultra`/`balanced` robustness suites

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requirements are pinned in [`requirements.txt`](requirements.txt) and include:

- `tinker==0.16.1`
- `torch==2.10.0`
- `transformers==5.2.0`
- `numpy==2.4.2`

Note: the production shard-scoring runtime used on Nebius/Wynton is a separate CUDA environment (`torch 2.5.1+cu121`) rather than the local/dev `requirements.txt` baseline.

## Runtime Requirements

- Valid `TINKER_API_KEY`
- Access to a Tinker backend with the target model
- Local hardware for ESM scoring (Apple Silicon `mps` or CUDA/CPU fallback)

Example:

```bash
export TINKER_API_KEY=...
export ESM2_DEVICE=mps
```

## Current Validated Nebius Path

For production stockpile scoring, the repository now has a validated Nebius execution path that differs from the local/dev defaults:

- Python env: `~/venvs/pearl-eval-cu121`
- PyTorch: `2.5.1+cu121`
- evaluator mode:
  - `PREFILTER_EVAL_MODE=staged`
  - `PREFILTER_CPU_WORKERS=8`
  - `ESM2_BATCH_SIZE=256`
  - `ESM2_SEQUENCE_BATCH_SIZE=1`
  - `ESM2_PIPELINE_CHUNK_SIZE=128`
- outputs should be written directly to persistent storage under `reports/nebius_benchmarks/...` during benchmarking and under the production output root during full stockpile runs
- current benchmark artifacts live under:
  - `reports/nebius_benchmarks/`

Current validated benchmark outcomes:

- L40S tuned baseline:
  - `0.364412 s/record`
  - `9878.93 records/hour`
- H100 tuned rerun:
  - `0.108953 s/record`
  - `33041.77 records/hour`
- H200 tuned best:
  - `0.104376 s/record`
  - `34490.69 records/hour`

Operational implication:

- a `10,000`-record shard is now about `17-18 minutes` on the final tuned path
- the full `761,029` Tier-A pool is about `22.1 GPU-hours`
- an `8x H100` node can clear the full Tier-A pool in roughly `2.9 hours`, before additional overhead
- at current Nebius pricing, preemptible H100 is the economic default because H200 does not outperform it by enough to justify the price premium

## Legacy Wynton Bring-Up

Wynton is now a historical bring-up and fallback path, not the primary production target.

What Wynton proved:

- the shard evaluator ran correctly on real UCSF GPUs
- durable direct-to-storage outputs worked
- healthy pools were:
  - `qb3-iogpu*` (A100)
  - `qb3-atgpu*` (A40)
- unhealthy pool:
  - `qb3-idgpu*`

Legacy validated artifacts:

- A-shard smoke on A100 (`250` records, CUDA path, durable output):
  - [`reports/hpc_sequence_eval/topoff1m-a-smoke-a100-cu121-20260321b/runs/topoff1m-a-smoke-a100-cu121-20260321b-hpc_ready_A_shard_0001/summary.json`](reports/hpc_sequence_eval/topoff1m-a-smoke-a100-cu121-20260321b/runs/topoff1m-a-smoke-a100-cu121-20260321b-hpc_ready_A_shard_0001/summary.json)
- B-shard full run on A100 (`958` records, CUDA path, durable output):
  - [`reports/hpc_sequence_eval/topoff1m-b-a100-cu121-20260321/runs/topoff1m-b-a100-cu121-20260321-hpc_ready_B_shard_0001/summary.json`](reports/hpc_sequence_eval/topoff1m-b-a100-cu121-20260321/runs/topoff1m-b-a100-cu121-20260321-hpc_ready_B_shard_0001/summary.json)

## Data And Artifacts

The repository is intentionally code-first. Large datasets and run artifacts are mostly excluded from version control.

Common local paths:

- prompts and family records: `data/petase_family_expanded/`
- run outputs: `reports/ablations/`, `reports/robustness/`, `reports/raft/`
- detached logs and metadata: `reports/logs/`

## Typical Workflows

### 1. Reproducible eval run

```bash
python scripts/run_ablation.py \
  --name my-eval-run \
  --model moonshotai/Kimi-K2.5 \
  --variant baseline \
  --prompts-path /abs/path/prompts.jsonl \
  --reference-records-path /abs/path/petase_records.jsonl \
  --prompt-count 24 \
  --candidate-sample-count 128 \
  --second-stage-top-k 16 \
  --second-stage-esm-weight 0.4 \
  --second-stage-motif-weight 0.3 \
  --second-stage-geometry-weight 0.3 \
  --second-stage-template-weight 0.05 \
  --init-state-path tinker://.../weights/... \
  --eval-only \
  --resume \
  --capture-candidate-audit \
  --seed 41
```

### 2. Durability suite (`12/24/48`)

```bash
python scripts/run_robustness_suite.py \
  --name my-robustness \
  --init-state-path tinker://.../weights/... \
  --model moonshotai/Kimi-K2.5 \
  --variant baseline \
  --suite-sizes 12,24,48 \
  --temperatures 0.8 \
  --seeds 41,53,67 \
  --candidate-sample-count 128 \
  --second-stage-top-k 16 \
  --second-stage-esm-weight 0.4 \
  --second-stage-motif-weight 0.3 \
  --second-stage-geometry-weight 0.3 \
  --second-stage-template-weight 0.05
```

### 2b. Two-phase H100 durability suite

Use this path when remote Tinker sampling dominates wall clock and you want to decouple:

1. stockpile candidate pools first
2. then run H100 ESM rescoring/finalization only on completed pools

Sync the bundle to a Nebius H100 VM from your Mac:

```bash
bash scripts/sync_topoff1m_a_eval_bundle.sh <VM_IP>
```

Set up the VM once:

```bash
ssh -i ~/.ssh/nebius_h200 svdr@<VM_IP>
bash ~/work/tinker/scripts/setup_nebius_h100_eval_env.sh
export TINKER_API_KEY=...
```

Launch `ultra` on the VM:

```bash
export STOCKPILE_JOBS=4
export STOCKPILE_RETRIES=2
bash ~/work/tinker/scripts/launch_topoff1m_a_robustness_h100.sh ultra
```

Queue `balanced` only after `ultra` is actually complete:

```bash
python3 ~/work/tinker/scripts/launch_detached_job.py \
  --job-name pearl-topoff1m-a-balanced-robustness-2phase-h100-queue \
  --cwd ~/work/tinker \
  --metadata-path ~/work/tinker/reports/logs/pearl-topoff1m-a-balanced-robustness-2phase-h100-queue.json \
  --log-path ~/work/tinker/reports/logs/pearl-topoff1m-a-balanced-robustness-2phase-h100-queue.log \
  --env "TINKER_API_KEY=$TINKER_API_KEY" \
  --env "STOCKPILE_JOBS=$STOCKPILE_JOBS" \
  --env "STOCKPILE_RETRIES=$STOCKPILE_RETRIES" \
  -- bash -lc 'while [ ! -f "$HOME/work/tinker/reports/robustness/pearl-topoff1m-a-ultra-robustness-2phase-h100-p12p24p48-t08-s41s53s67/robustness_summary.json" ]; do sleep 60; done; bash ~/work/tinker/scripts/launch_topoff1m_a_robustness_h100.sh balanced'
```

Operational notes:

- The queue gate should watch for `robustness_summary.json`, not the parent PID.
- The VM venv needs `sentencepiece`, `protobuf`, and `tiktoken` installed or some stockpile lanes can fail during tokenizer init.
- `run_robustness_two_phase.py` now supports:
  - `--stockpile-jobs`
  - `--stockpile-retries`
- Kill the VM only after both of these files exist:
  - `reports/robustness/pearl-topoff1m-a-ultra-robustness-2phase-h100-p12p24p48-t08-s41s53s67/robustness_summary.json`
  - `reports/robustness/pearl-topoff1m-a-balanced-robustness-2phase-h100-p12p24p48-t08-s41s53s67/robustness_summary.json`

### 3. Retrain readiness check

```bash
python scripts/check_retrain_readiness.py \
  reports/ablations/.../candidate_audit.json \
  --selected-only
```

### 4. Detached mining wave

```bash
python scripts/run_raft_wave.py \
  --name wave1 \
  --init-state-path tinker://.../weights/... \
  --total-prompt-count 200 \
  --shard-count 4 \
  --candidate-sample-count 256 \
  --second-stage-top-k 16 \
  --temperature 0.8
```

## Outputs You Should Expect

Most runs produce:

- `report.json`: step-level selected output records
- `summary.json`: aggregate run metrics
- `candidate_audit.json`: full per-candidate pool (if enabled)

Robustness suites additionally produce:

- `runs_manifest.json`
- `robustness_summary.json` with durability-gate pass/fail and seed vectors

## Safety And Scientific Scope

- Sequences from this repo are computational outputs only.
- ESM proxy is a lightweight stability proxy, not a structural truth model.
- Passing local gates does not imply biochemical activity or wet-lab success.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
