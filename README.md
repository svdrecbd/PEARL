# PEARL

PEARL stands for Protein Engineering Adapter via Reinforcement Learning.

This repository explores PETase-family sequence design through remote generation/training on Tinker plus local scoring, selection, mining, and evaluation logic. It is an experimental research codebase, not a validated product.

## Start Here

- Historical sponsor-facing summary: [`WHITEPAPER.md`](WHITEPAPER.md)
- Repo structure and supported surface: [`docs/overview.md`](docs/overview.md)
- Supported workflows: [`docs/workflows.md`](docs/workflows.md)
- Operator notes: [`docs/operations.md`](docs/operations.md)
- Current scientific status: [`docs/science.md`](docs/science.md)
- Proposed hard-route pivot: [`docs/manifold_construction.md`](docs/manifold_construction.md)
- Experiment configs: [`configs/experiments/README.md`](configs/experiments/README.md)
- Full experimental history: [`notes/LABNOTES.md`](notes/LABNOTES.md)
- Historical campaign wrapper inventory: [`archive/2026q1_topoff1m_a/README.md`](archive/2026q1_topoff1m_a/README.md)

## Current State

As of April 22, 2026:

- merged `stage-b-lite` mined pool:
  - `1,597,184` raw candidates
  - `179` exact-unique functional hits
  - `54` exact-unique family-faithful hits
  - `197` lineage clusters at `0.85`
- best historical strict branch:
  - `strict-core-v7-repair`
  - stage-A trained cleanly on `160` pairs and passed the stricter `p48` smoke gate with `2 / 3` seeds and `3 / 48` prompts
  - `stage-b-lite` trained cleanly on `162` pairs
  - full robustness still failed durability:
    - `p12`: `[0, 0, 0]`
    - `p24`: `[0, 2, 0]`
    - `p48`: `[0, 3, 1]`
    - the main miss was prompt coverage breadth, with only `4 / 48` prompts hit at `p48`
- latest strict branch:
  - `strict-core-v8-coverage`
  - stage-A checkpoint:
    - `tinker://0e007439-8486-58fd-8a5a-9769ced7e0b2:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v8-coverage-stagea-lr1e6-ep3`
  - stage-B-lite checkpoint:
    - `tinker://789989aa-dbe7-522b-a82a-1bccd9060a06:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v8-coverage-stageb-lite-lr5e7-ep1`
  - stage-A `p48` smoke showed hits but did not imply durability
  - full stage-B-lite robustness failed:
    - `p12`: `[0, 0, 0]`
    - `p24`: `[0, 0, 0]`
    - `p48`: `[0, 3, 3]`
    - all family-faithful counts were `0`
  - stage-A diagnostic at `p12/p24` also failed:
    - `p12`: `[0, 0, 0]`
    - `p24`: `[0, 0, 0]`
    - this means `stage-b-lite` was not the sole regression
- candidate-audit repair lane:
  - April 10/12 repair succeeded and made `v7` possible
  - April 21/22 p12/p24 `v9` repair failed as a rescue path:
    - `134` geometry-dominant near-misses
    - `47,489` local variants evaluated
    - `79` loose repaired survivors
    - `0` strict shortlist, `0` strict bridge, `0` strict family, `0` strict consensus
    - readiness failed with `0` retrain positives
- local Gemma mining trial:
  - half-wave `525,568`-candidate ESM check came back `0` functional / `0` family-faithful
  - treat the current local Gemma path as failed unless the serving/prompting path is corrected first
- historical local-exploit audit:
  - finalized-hit universe and widened finalized-report near-miss universe both came back with no usable anchor neighborhoods
  - current “no free lunch” read: there is no passive challenge-style local basin already sitting in the saved finalized corpus
- current direction:
  - stop treating broad paid sampling and small SFT tweaks as the primary next move
  - treat `strict-core-v7-repair` as the best historical baseline and a possible lucky narrow attractor
  - treat `v8` and the `v9` repair rescue as evidence that the current loop does not reliably learn the strict PETase/cutinase manifold
  - discuss or build a scaffold-first manifold-construction pipeline before spending on another large mining tranche
  - keep a `50k-75k` p12/p24 targeted mining sweep as an optional diagnostic, not the default next move
  - keep the reranker lane reranker-first and diagnostic-only until it clearly beats scalar reward baselines on harder held-out prompt / bucket / cluster splits

See [`docs/science.md`](docs/science.md) for the current research readout and primary artifact links.

## Supported Surface

The supported reusable workflows are:

1. `mine`
2. `postprocess`
3. `analyze`
4. `build-dataset`
5. `repair`
6. `train`
7. `robustness`
8. `reranker`
9. `manifold-construction` (planned / proposed)

The details and entrypoints for those workflows live in [`docs/workflows.md`](docs/workflows.md).

Versioned `strict_core_*` and `strict_first_union` wrappers now live under the archive and are exposed at their old `scripts/` paths through symlinks for continuity with the historical record. They are not the supported workflow surface anymore. The supported control flow is now config-driven and library-backed through `src/pearl`.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Pinned local/dev requirements are in [`requirements.txt`](requirements.txt):

- `tinker==0.16.1`
- `torch==2.10.0`
- `transformers==5.2.0`
- `tiktoken==0.12.0`
- `numpy==2.4.2`
- `safetensors==0.7.0`
- `sentencepiece==0.2.1`
- `rapidfuzz==3.14.5`

Production CUDA environments used on Nebius are separate from the local/dev baseline.

## Repo Landmarks

- `main.py`: current generation/eval engine with shared helpers now extracted into `src/pearl`
- `src/pearl/family.py`: family scoring and catalytic geometry checks
- `src/pearl/esm_proxy.py`: local ESM proxy scorer
- `src/pearl/`: reusable library surface for paths, detached jobs, reports, smoke gates, curricula, and run-record assembly
- `scripts/`: supported workflow entrypoints plus archived compatibility symlinks
- `reports/`: local run artifacts
- `data/`: prompts, records, and family datasets

The repo boundary is now explicit:

- reusable engine and shared helpers live under `src/pearl`
- supported workflow runners are config-driven entrypoints
- historical campaign wrappers are archived and kept only through compatibility symlinks

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
