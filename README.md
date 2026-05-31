# PEARL

PEARL stands for Protein Engineering Adapter via Reinforcement Learning.

This repository explores PETase-family sequence design through remote generation/training on Tinker plus local scoring, selection, mining, and evaluation logic. It is an experimental research codebase, not a validated product.

## Start Here

- Active workspace map after the April 28 cleanup: [`REPO_MAP.md`](REPO_MAP.md)
- Historical sponsor-facing summary: [`WHITEPAPER.md`](WHITEPAPER.md)
- Repo structure and supported surface: [`docs/overview.md`](docs/overview.md)
- Supported workflows: [`docs/workflows.md`](docs/workflows.md)
- Operator notes: [`docs/operations.md`](docs/operations.md)
- Current scientific status: [`docs/science.md`](docs/science.md)
- Manifold-construction pivot: [`docs/manifold_construction.md`](docs/manifold_construction.md)
- Phase 8 DPO pilot readout: [`docs/phase8_dpo_pilot_readout.md`](docs/phase8_dpo_pilot_readout.md)
- Phase 8 no-logits OPD packet: [`docs/phase8_no_logits_opd.md`](docs/phase8_no_logits_opd.md)
- Experiment configs: [`configs/experiments/README.md`](configs/experiments/README.md)
- Full experimental history: [`notes/LABNOTES.md`](notes/LABNOTES.md)

## Current State

May 30, 2026 Phase 8 update: the Tinker custom-loss DPO path has now run beyond smoke scale. A 3k-pair natural-positive DPO pilot completed and the training objective moved in the expected direction, but the only completed post-DPO evaluation slice so far was `p12`, temperature `0.8`, seed `7`. That slice produced local proxy movement but no functional or family-faithful bridge hits, and a five-candidate folded subset had low pLDDT (`25.61-36.27`) with `0 / 5` CA-triad passes. Treat that as an underpowered warning, not a falsification of DPO-only: DPO remains a live baseline/control that needs higher-resolution eval before its failure modes or yield can be estimated.

May 2026 heat check: the project has enough working components to continue the preference-learning path, but not enough evidence to claim the protein-design thesis is solved. The strongest direction is to keep characterizing DPO while preparing sparse OPD/multi-teacher feedback as the comparison branch: natural PETase/cutinase records as positives, generated/fold-failed artifacts and new low-confidence generated candidates as hard negatives, then compact post-train generation and structural validation before any larger library expansion.

April 29, 2026 DPO correction: Phase 7 generated/local-library sequences are no longer allowed on the chosen side of the paid-run DPO dataset. The current local Phase 8 build uses reviewed natural PETase/cutinase records as chosen positives and demotes the fold-failed Phase 7 generated panel to hard negatives.

April 28, 2026 cleanup note: the active workspace is now focused on Phase 8 DPO readiness. The current 10k DPO dataset lives locally in `data/phase8_dpo/`, its structural evidence lives in `reports/analysis/phase7_local_library_v1/`, and old run outputs/scripts/configs were moved to the local ignored archive at `archive/2026-04-28-labyrinth-cleanup/`. See `REPO_MAP.md` and `notes/LABNOTES.md` for the current map and latest scientific status.

As of April 23, 2026:

- merged `stage-b-lite` mined pool:
  - `1,597,184` raw candidates
  - `179` exact-unique functional hits
  - `54` exact-unique family-faithful hits
  - `197` lineage clusters at `0.85`
- best historical strict branch:
  - `strict-core-v7-repair`
  - stage-A and stage-B-lite trained cleanly
  - full robustness stayed narrow:
    - `p12`: `[0, 0, 0]`
    - `p24`: `[0, 2, 0]`
    - `p48`: `[0, 3, 1]`
    - the main miss was prompt coverage breadth, with only `4 / 48` prompts hit at `p48`
- negative strict/repair evidence:
  - `strict-core-v8-coverage` failed to broaden `v7`, regressed at `p12/p24`, and lost family-faithful robustness
  - the April 21/22 `v9` p12/p24 repair rescue found `79` loose high-ESM survivors but `0` strict shortlist rows and `0` retrain positives
  - local Gemma mining and historical local-exploit scans did not expose a usable passive basin
- scaffold-first manifold pivot:
  - Phase 1 built a local scaffold bank with `12,619` unique sequences, `4,893` family-manifold scaffolds, `3,769` strict-manifold scaffolds, `79` recovered `v9` negatives, and `274` strict candidate positives
  - Phase 2 built and ESM-scored a `10,000`-candidate same-length strict-manifold frontier; all candidates scored `>=95`
  - Phase 2 selection passed readiness with `230` selected strict candidates across `79` parent scaffolds, `8` lengths, and `100` two-mutants
- manifold curriculum outcomes:
  - `v1`: nonzero transfer but failed breadth; `p12` passed with tier-2 hits `[1, 2, 0]`, while `p24` failed with `[0, 1, 0]`
  - `v1.1`: p24-only gate failed cleanly with `0` tier-2 hits and `0` raw single-motif plus geometry plus ESM candidates
  - `v1.2`: length-retargeted repair distillation recovered real but narrow signal: `3` functional hits, `2` family-faithful hits, and `3 / 24` prompt coverage
  - `v1.3`: support-prompt widening regressed to `[0, 0, 1]` tier-2 hits, `1 / 24` prompt coverage, and `0` family-faithful hits
- current rule:
  - do not launch another paid manifold `v1.x` replay, stage-B, p48, or broad mining tranche from this branch line
  - the manifold `v2` objective panel is now built at `reports/analysis/manifold_v2_objective_panel_20260424/`
  - use its `2` `v1.2` family-faithful hits as positive anchors and `45` `v1.3` stable-only / geometry-only finalists as hard negatives
  - use its `305` v9/v1.1 drift negatives and `190` historical support positives to shape the next offline constructor
  - the first v2 offline constructor selected `64` hard-gated pre-ESM candidates across `38` parents and `8` exact lengths
  - the expanded v2 constructor scored `192 / 192` candidates above ESM `85`
  - final reselection produced `34` strict/core/ESM candidates across `18` parent source keys and `14` exact lengths
  - the finalized v2 curriculum has `42` rows: `34` selected candidates plus `8` purebred anchors
  - the v2 p24/c128 diagnostic completed but failed durability with tier-2 hits `[0, 1, 0]`, prompt coverage `1 / 24`, and `0` family-faithful hits
  - active next branch is v2.1 bridge-weighted replay at `reports/curriculum/manifold_v21_20260424/manifold_v21_bridge_curriculum.jsonl`
  - v2.1 has `71` rows: `28` v2 strict-breadth anchors, `15` measured bridge replay rows, `12` support prompt anchors, `12` historical family-faithful anchors, and `4` purebred anchors
  - current paid scope is a tiny v2.1 stage-A train plus p24-only diagnostic gate; no stage-B, p48, or broad mining from this artifact
  - keep paid mining as a small diagnostic only if the offline v2 redesign stalls

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
9. `manifold-construction` (Phase 1 and Phase 2 selection implemented)

The details and entrypoints for those workflows live in [`docs/workflows.md`](docs/workflows.md).

Versioned `strict_core_*` and `strict_first_union` wrappers now live under the archive and are exposed at their old `scripts/` paths through symlinks for continuity with the historical record. They are not the supported workflow surface anymore. The supported control flow is now config-driven and library-backed through `src/pearl`.

## Installation

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Pinned local/dev requirements are in [`requirements.txt`](requirements.txt). The local baseline
uses Python 3.13 because the current Tinker SDK requires Python >=3.11:

- `tinker==0.21.0`
- `torch==2.12.0`
- `transformers==5.8.1`
- `tiktoken==0.13.0`
- `numpy==2.4.6`
- `safetensors==0.7.0`
- `sentencepiece==0.2.1`
- `rapidfuzz==3.14.5`
- `charset-normalizer==3.4.6`

Production CUDA environments used on Nebius are separate from the local/dev baseline.

## Repo Landmarks

- `main.py`: current generation/eval engine with shared helpers now extracted into `src/pearl`
- `src/pearl/family.py`: family scoring and catalytic geometry checks
- `src/pearl/esm_proxy.py`: local ESM proxy scorer
- `src/pearl/`: reusable library surface for paths, detached jobs, reports, smoke gates, curricula, and run-record assembly
- `scripts/`: supported workflow entrypoints plus archived compatibility symlinks, including `scripts/manifold_construction_experiment.py`
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
