# Wynton HPC Pivot Checklist (UCSF)

Status date: March 24, 2026
Scope: historical planning and bring-up record

Superseded operationally:

- Wynton successfully validated the shard evaluator and durable output path.
- Wynton is no longer the primary production runtime because scheduler latency dominated execution.
- The production path has moved to Nebius GPU VMs, with preemptible `8x H100` as the current economic default.

## Execution Addendum (March 20-21, 2026)

Planning assumptions were later validated against real cluster behavior.

Observed outcome:

1. `qb3-idgpu*` was not a reliable production pool for this workload.
   - malformed `SGE_GPU` values were observed
   - CUDA and NVML initialization failures were reproduced with minimal PyTorch smoke jobs
2. `qb3-atgpu*` (A40) and `qb3-iogpu*` (A100) were validated as healthy pools for the same smoke jobs.
3. The effective production runtime became:
   - `torch 2.5.1+cu121`
   - direct Python execution
   - `SET_CUDA_VISIBLE_DEVICES=0`
   - direct writes to persistent output storage
4. End-to-end sequence-shard execution was validated on A100:
   - A-shard smoke (`250` records) succeeded on CUDA and wrote durable outputs
   - full B-shard run (`958` records) succeeded on CUDA and wrote durable outputs
5. A full `1-77` A-array run was submitted on `qb3-iogpu*` with `5h` walltime after the smoke phase completed.

Operational conclusion:

- Wynton is a usable production path for this project only when constrained to known-healthy pools.
- Array-style shard submission remains the correct strategy, but the main bottleneck is queue access, not code correctness.

## Preconditions

1. Confirm Wynton account, PI/group membership, and `gpu.q` access.
2. Validate SSH workflow and cluster login path for all operators.
3. Confirm current cluster health and any active limitations before launches.

## Critical Blocker First

1. Run a compute-node egress test to confirm whether jobs can reach the Tinker API endpoint.
2. Treat egress as a hard blocker until proven.
3. If blocked, pick one path before refactoring:
   - network exception/proxy/private endpoint
   - split workflow: remote generation elsewhere, Wynton for local scoring only

## Scheduler Migration Plan

1. Standardize all long runs on Wynton scheduler jobs (`qsub`, `gpu.q`).
2. Define a default resource policy:
   - walltime (`h_rt`)
   - memory (`h_vmem` or `mem_free`)
   - GPU count (`-l gpu=N`)
   - queue (`-q gpu.q`)
   - optional GPU type constraints
3. Replace local detached orchestration with scheduler-native submission/monitoring:
   - `/Users/svdr/tinker/scripts/run_raft_wave.py`
   - `/Users/svdr/tinker/scripts/launch_detached_job.py`
   - `/Users/svdr/tinker/scripts/stop_detached_job.py`

## Environment and Dependencies

1. Decide runtime packaging model (modules + venv/conda, or Apptainer).
2. Pre-stage Python dependencies and model assets used by ESM/HuggingFace paths.
3. Define cache/offline policy (`HF_HOME`, offline flags) to avoid runtime internet dependency.
4. Validate Python interpreter resolution strategy for all job entrypoints.

## Secrets and Configuration

1. Define secure injection for `TINKER_API_KEY` in job env (never commit, never log).
2. Document required env vars for runs:
   - `TINKER_API_KEY`
   - `TINKER_PYTHON_BIN`
   - `ESM2_DEVICE`
   - run-specific `TINKER_*` knobs used by scripts
3. Verify secrets are redacted in logs and metadata outputs.

## Data and Storage Layout

1. Place durable artifacts in group/home storage.
2. Use `/wynton/scratch` only for transient high-IO data.
3. Add retention handling for scratch purge behavior.
4. Use transfer nodes (`dt*`) for large inbound/outbound transfers.

## Workflow Mapping

1. Map PEARL entrypoints to scheduler jobs:
   - `/Users/svdr/tinker/scripts/run_ablation.py`
   - `/Users/svdr/tinker/scripts/run_robustness_suite.py`
   - `/Users/svdr/tinker/scripts/run_backward_lane.py`
2. Define job-array strategy for multi-seed and multi-shard workloads.
3. Define dependency strategy (submit-after-success chains where needed).

## Monitoring and Recovery

1. Standardize monitoring (`qstat`) and postmortem accounting (`qacct`).
2. Define retry policy for preemption/timeouts/transient failures.
3. Define resume strategy for interrupted long suites.

## Validation Sequence

1. Environment smoke test (imports, GPU visibility, path checks).
2. 1-prompt dry run.
3. 12-prompt ablation.
4. Frozen robustness suite.
5. Full wave after passing the above gates.

## Addendum: Budget + Migration + Templates (March 7, 2026)

### Budget-Capped Pre-Wynton Generation

1. Add a decoupled raw generator script (Tinker sampling only; no local ESM/geometry checks).
2. Enforce a hard pre-Wynton spend cap of `$500-$1,000` with an automatic stop condition.
3. Keep remaining budget (`~$3,500+`) reserved for remote LoRA micro-SFT/RAFT updates.
4. Use file rotation and compression for large raw JSONL output volumes.

### Linux Migration Notes

1. `local_proxy.py` already has dynamic device fallback (`cuda -> mps -> cpu`) when `ESM2_DEVICE` is unset.
2. Remove `mps` defaults from runner scripts:
   - `/Users/svdr/tinker/scripts/run_robustness_suite.py`
   - `/Users/svdr/tinker/scripts/run_raft_wave.py`
3. Remove hardcoded Mac paths in operational scripts:
   - `/Users/svdr/tinker/scripts/run_sft_warmstart.py`
   - `/Users/svdr/tinker/scripts/run_reseed3_batch.sh`
   - `/Users/svdr/tinker/scripts/launch_reseed3_batch_detached.sh`
4. Route intermediate artifacts and caches to `$TMPDIR`; sync final outputs to persistent storage.

### Dependency and Container Notes

1. Keep a single CUDA stack across host driver, container runtime, and Python environment.
2. Avoid reinstalling incompatible Torch wheels inside an NVIDIA PyTorch base image.
3. Treat `requirements.txt` as a local/dev baseline; maintain an HPC/container-specific install plan.

### Templates Added

1. `/Users/svdr/tinker/hpc/Apptainer.def`
2. `/Users/svdr/tinker/hpc/submit_ablation.sge.sh`
3. `/Users/svdr/tinker/hpc/submit_raft_array.sge.sh`
4. `/Users/svdr/tinker/hpc/README.md`

### Local Prefilter Spec Added (March 7, 2026)

1. `/Users/svdr/tinker/notes/LOCAL_PREFILTER_SCHEMA.md`
2. Defines canonical metadata schema for local pre-HPC filtering.
3. Defines reject codes, stage I/O contracts, and HPC handoff artifacts.
4. Keeps MLX explicitly optional and scoped to local ranking/embedding only.

## References

- https://wynton.ucsf.edu/hpc/get-started/access-cluster.html
- https://wynton.ucsf.edu/hpc/about/specs.html
- https://wynton.ucsf.edu/hpc/scheduler/submit-jobs.html
- https://wynton.ucsf.edu/hpc/scheduler/gpu.html
- https://wynton.ucsf.edu/hpc/scheduler/envvars.html
- https://wynton.ucsf.edu/hpc/scheduler/using-local-scratch.html
- https://wynton.ucsf.edu/hpc/transfers/files-and-directories.html
- https://wynton.ucsf.edu/hpc/howto/stage-conda.html
- https://wynton.ucsf.edu/hpc/status/index.html
