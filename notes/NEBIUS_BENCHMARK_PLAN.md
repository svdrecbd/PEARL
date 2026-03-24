# Nebius Benchmark Plan and Outcome

Goal: compare real shard-eval throughput and cost efficiency across Nebius GPU classes, then lock the production runtime.

Validated benchmark target:
- `transfers/topoff_1m_run_20260307-232538/shards/A/hpc_ready_A_shard_0001.jsonl`
- `line_limit = 1000`
- env default: `~/venvs/pearl-eval-cu121/bin/python`

Prepared launchers:
- `/Users/svdr/tinker/scripts/run_nebius_l40s_benchmark.sh`
- `/Users/svdr/tinker/scripts/run_nebius_h100_benchmark.sh`
- `/Users/svdr/tinker/scripts/run_nebius_h200_benchmark.sh`
- `/Users/svdr/tinker/scripts/run_nebius_b200_benchmark.sh`

Each launcher:
- logs `hostname`, `nvidia-smi -L`, and runtime config
- runs `scripts/run_sequence_shard_eval.py`
- writes outputs under `reports/nebius_benchmarks/<wave>/runs/`
- prints a compact benchmark summary with:
  - `records_evaluated`
  - `duration_seconds`
  - `seconds_per_record`
  - `records_per_hour`
  - `esm_device`

Default benchmark tuning:
- `ESM2_ENABLE_TF32=1`
- `ESM2_DTYPE=bf16`
- `ESM2_USE_TORCH_COMPILE=0`

Rationale:
- TF32 and BF16 are cheap wins on Ampere/Hopper/Blackwell-class GPUs.
- `torch.compile` is exposed but left off by default because the scorer uses a small ESM2 model and compile overhead may not pay back cleanly. If needed, test it explicitly with `ESM2_USE_TORCH_COMPILE=1`.

Metrics to compare:
1. `seconds_per_record`
2. `records_per_hour`
3. `$/1M records`
4. stability / zero runtime surprises

## Outcome (March 24, 2026)

Single-GPU benchmark ladder:

- L40S tuned baseline:
  - `0.364412 s/record`
  - `9878.93 records/hour`
- H100 untuned rerun:
  - `0.25474 s/record`
  - `14132.06 records/hour`
- H200 untuned:
  - essentially tied with H100

Critical finding:

- the naive GPU ladder understated premium-GPU value because the evaluator was CPU-bound
- the real bottleneck was the family / novelty evaluator, not ESM itself

Winning runtime after CPU-side tuning:

- `PREFILTER_EVAL_MODE=staged`
- `PREFILTER_CPU_WORKERS=8`
- `ESM2_BATCH_SIZE=256`
- `ESM2_SEQUENCE_BATCH_SIZE=1`
- `ESM2_PIPELINE_CHUNK_SIZE=128`

Final tuned results:

- H100:
  - `0.108953 s/record`
  - `33041.77 records/hour`
- H200:
  - `0.104376 s/record`
  - `34490.69 records/hour`

Economic conclusion:

- H200 is only about `4.4%` faster than H100 after tuning
- at observed Nebius prices, that gap is too small to justify the H200 premium
- the current production default is preemptible `8x H100`

Operational implication:

- full Tier-A pool (`761,029` records) is about `22.1 GPU-hours` on the tuned path
- an `8x H100` node should clear Tier-A in roughly `2.9 hours` before overhead
