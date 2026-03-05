# PEARL

PEARL stands for Protein Engineering Adapter via Reinforcement Learning.

This repository explores computational sequence design for PETase-family proteins using remote generation/training through Tinker and local scoring/ranking logic. It is an experimental research codebase, not a validated protein-design product.

## Start Here

- Sponsor-facing summary: [`PROJECTBRIEF.md`](PROJECTBRIEF.md)
- Full experimental history and decisions: [`notes/LABNOTES.md`](notes/LABNOTES.md)

## Current State (March 2026)

- The project has clear existence proof of the target bridge:
  - single catalytic motif
  - geometry pass
  - high ESM proxy (`ESM >= 85`)
- The bridge is still sparse and seed-fragile at larger prompt scales.
- Current work is robustness and repair, gated by fixed-suite durability checks (`12/24/48`, fixed seeds), not broad RL scaling.
- RL pilot was an explicit negative result on this landscape and is not the active path.

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
- `scripts/check_retrain_readiness.py`: automatic retrain-go/no-go checks on mined pools
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

## Runtime Requirements

- Valid `TINKER_API_KEY`
- Access to a Tinker backend with the target model
- Local hardware for ESM scoring (Apple Silicon `mps` or CUDA/CPU fallback)

Example:

```bash
export TINKER_API_KEY=...
export ESM2_DEVICE=mps
```

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
