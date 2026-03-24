# PEARL

PEARL stands for Protein Engineering Adapter via Reinforcement Learning.

This repository explores computational sequence design for PETase-family proteins using remote generation/training through Tinker and local scoring/ranking logic. It is an experimental research codebase, not a validated protein-design product.

## Start Here

- Sponsor-facing summary: [`WHITEPAPER.md`](WHITEPAPER.md)
- Full experimental history and decisions: [`notes/LABNOTES.md`](notes/LABNOTES.md)

## Current State (March 24, 2026)

- The project has clear existence proof of the target bridge:
  - single catalytic motif
  - geometry pass
  - high ESM proxy (`ESM >= 85`)
- `repair20` did not clear durability and should not be advanced as the active scientific branch.
- Current execution focus is Nebius-side production scoring for the `761,029` Tier-A handoff records and `958` Tier-B records, not additional exploratory RL scaling.
- Wynton served as the bring-up path and validated the evaluator, but it is no longer the preferred production environment because scheduler latency dominated wall time.
- The validated production runtime is now:
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
- The path to a clean dataset is now straightforward:
  - run the full A/B stockpile on Nebius
  - aggregate scored candidates, rejects, and near-miss records
  - build the shortlist/repair/retrain dataset from those mined outputs

## What The System Does

1. Sample candidate sequences from a remote model.
2. Evaluate local sequence quality, family plausibility, motif structure, novelty, and catalytic geometry.
3. Run second-stage ranking with ESM proxy and selector weights.
4. Mine positives and near-misses.
5. Build compact repair/retrain datasets and rerun fixed robustness suites.

## Core Files

- `main.py`: generation/eval loop, scoring, selection, resume-safe report writing
- `petase_family.py`: family scoring, motif/geometry checks, novelty logic
- `local_proxy.py`: ESM-2 pseudo-pLDDT scorer (torch backend)
- `scripts/run_ablation.py`: reproducible single-run launcher over prompt subsets
- `scripts/run_robustness_suite.py`: frozen `12/24/48` suite + durability gate summary
- `scripts/run_backward_lane.py`: precompute miss-bank + repair-pool + retrain-readiness while other shards are still running
- `scripts/check_retrain_readiness.py`: automatic retrain-go/no-go checks on mined pools
- `scripts/check_repair_survivor_readiness.py`: retrain-go/no-go checks after adding repair survivors to a base run pool
- `scripts/build_diversity_capped_repair_pool.py`: caps repair pools by source run + sequence identity cluster before repair generation
- `scripts/run_raft_wave.py`: detached mining waves with a safety cap on parallel workers
- `scripts/launch_detached_job.py`: robust detached process launcher with metadata/logs

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requirements are pinned in [`requirements.txt`](requirements.txt) and include:

- `tinker==0.14.0`
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
