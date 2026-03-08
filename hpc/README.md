# PEARL HPC Templates (Wynton / SGE)

These are starter templates for running PEARL workloads on Wynton with Apptainer + SGE.

## Files

- `Apptainer.def`: container build recipe (NVIDIA PyTorch base image)
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
