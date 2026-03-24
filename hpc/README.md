# PEARL HPC Templates (Legacy Wynton / SGE)

These are starter templates for running PEARL workloads on Wynton with Apptainer + SGE.

Status note (March 24, 2026):

- these templates remain useful as historical reference and fallback tooling
- Wynton successfully validated the evaluator path
- Wynton is no longer the primary production runtime
- production scoring has moved to Nebius GPU VMs after the benchmark/tuning cycle made the runtime and cost picture clear
- see:
  - `/Users/svdr/tinker/notes/NEBIUS_BENCHMARK_PLAN.md`
  - `/Users/svdr/tinker/README.md`

## Files

- `Apptainer.def`: full PEARL container build recipe for Tinker-backed runs
- `Apptainer.prefilter_eval.def`: eval-only container for local shard scoring without `tinker`
- `submit_ablation.sge.sh`: single-run evaluation/ablation job
- `submit_raft_array.sge.sh`: array-job pattern for shard-based RAFT-style mining
- `submit_prefilter_eval_array.sge.sh`: array-job pattern for scoring prefiltered sequence shards (`hpc_ready_A/B`)

## Design assumptions

1. Intermediates and model caches go to `$TMPDIR` (node-local scratch).
2. Final outputs are synced to persistent storage under the repo `reports/` tree.
3. `TINKER_API_KEY` must be provided via environment, not committed to scripts.
4. `run_raft_wave.py` detached-process orchestration is intentionally bypassed on HPC; use scheduler arrays instead.

## Build container (example)

```bash
apptainer build pearl_env.sif hpc/Apptainer.def
```

For prefilter sequence-shard scoring only, use the lighter eval image:

```bash
apptainer build pearl_eval_env.sif hpc/Apptainer.prefilter_eval.def
```

## Submit ablation (example)

```bash
mkdir -p logs/sge
export TINKER_API_KEY=...
qsub \
  -v TINKER_API_KEY \
  -v INIT_STATE_PATH=tinker://... \
  -v RUN_NAME=wynton-ablation-smoke \
  hpc/submit_ablation.sge.sh
```

## Submit RAFT-style array (example)

```bash
mkdir -p logs/sge
export TINKER_API_KEY=...
qsub \
  -t 1-4 \
  -v TINKER_API_KEY \
  -v INIT_STATE_PATH=tinker://... \
  -v PROMPTS_DIR=/path/to/sharded-prompts \
  -v WAVE_NAME=wave01 \
  hpc/submit_raft_array.sge.sh
```

## Submit prefilter sequence-shard array (example)

Use this for the local-prefilter handoff shards (`hpc_ready_A_shard_*.jsonl`) where each row already contains a candidate sequence.

If the full `Apptainer.def` cannot build because `tinker` requires a newer Python than the base image provides, use `Apptainer.prefilter_eval.def` and set `SIF_PATH` to that eval-only image. The shard scorer does not import `tinker`.

If Apptainer is unavailable or the image build is blocked, `submit_prefilter_eval_array.sge.sh` also supports direct execution via a prebuilt Python environment by setting `PYTHON_BIN=/abs/path/to/python`.

```bash
mkdir -p logs/sge
qsub \
  -t 1-77 \
  -v SHARDS_DIR=/wynton/home/$USER/tinker/transfers/topoff_1m_run_20260307-232538/shards/A \
  -v SHARD_GLOB='hpc_ready_A_shard_*.jsonl' \
  -v WAVE_NAME=topoff1m-a \
  -v REFERENCE_RECORDS_PATH=/wynton/home/$USER/tinker/data/petase_family_expanded/petase_records.jsonl \
  hpc/submit_prefilter_eval_array.sge.sh
```

Optional smoke-run cap:

```bash
qsub \
  -t 1-2 \
  -v SHARDS_DIR=/wynton/home/$USER/tinker/transfers/topoff_1m_run_20260307-232538/shards/A \
  -v SHARD_GLOB='hpc_ready_A_shard_*.jsonl' \
  -v WAVE_NAME=topoff1m-a-smoke \
  -v LINE_LIMIT=250 \
  hpc/submit_prefilter_eval_array.sge.sh
```

## Notes

1. Create the correct shard type before launching array jobs (`prompt` shards for RAFT arrays, `hpc_ready_*` sequence shards for prefilter-eval arrays).
2. Ensure `logs/sge` exists before submit (`#$ -o` uses that path).
3. If your cluster uses additional GPU selectors, add them to `#$ -l ...`.

## March 2026 Wynton Execution Notes

The generic `gpu.q` path was not uniformly healthy in practice. The following cluster/runtime combinations were observed during bring-up:

- validated healthy:
  - `qb3-iogpu*` with A100-SXM4-40GB
  - `qb3-atgpu*` with A40
- validated unhealthy for this workload:
  - `qb3-idgpu*` (malformed `SGE_GPU` values, CUDA init failures, NVML failures)

The currently validated production path for prefilter shard scoring is:

1. Python env: `~/venvs/pearl-eval-cu121`
2. PyTorch: `2.5.1+cu121`
3. submission style:
   - direct Python via `PYTHON_BIN`
   - `SET_CUDA_VISIBLE_DEVICES=0`
   - `HF_HOME=$HOME/.cache/huggingface`
4. output handling:
   - write directly to persistent storage under `reports/hpc_sequence_eval/...`
   - do not rely on `/scratch` + `rsync` for final durability

Observed timing on validated runs:

- A100 A-shard smoke:
  - `250` records in `198.56s`
- A100 B-shard full run:
  - `958` records in `1157.435s`

Operational implication:

- full `10,000`-record A shards are likely in the `2.2h - 3.4h` range
- use at least `4h - 5h` walltime for the production `1-77` A-array

Postscript:

- those timings are now historical
- after Nebius-side evaluator tuning, the project moved to a much faster staged runtime with CPU parallelism
- treat the Wynton notes here as bring-up documentation, not the current production recommendation
