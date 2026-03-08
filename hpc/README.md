# PEARL HPC Templates (Wynton / SGE)

These are starter templates for running PEARL workloads on Wynton with Apptainer + SGE.

## Files

- `Apptainer.def`: container build recipe (NVIDIA PyTorch base image)
- `submit_ablation.sge.sh`: single-run evaluation/ablation job
- `submit_raft_array.sge.sh`: array-job pattern for shard-based RAFT-style mining

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

## Notes

1. Create prompt shards before launching the array job.
2. Ensure `logs/sge` exists before submit (`#$ -o` uses that path).
3. If your cluster uses additional GPU selectors, add them to `#$ -l ...`.
