# PEARL

**PEARL** stands for **Protein Engineering Adapter via Reinforcement Learning**.

This repository explores de novo enzyme design with the [Tinker](https://tinker-docs.thinkingmachines.ai/) API by treating protein sequences as a generative language problem. The current focus is polyester-hydrolase / PETase-family sequence generation, combining:

- remote sequence generation and LoRA training through Tinker
- local protein plausibility scoring with an ESM-2 masked-language-model proxy
- family-aware candidate selection and geometry checks
- iterative ablation, warm-start, and zero-shot search workflows

The project is experimental and research-oriented. It is not a validated protein-design product and does not make biological or wet-lab claims.

## Current Direction

The most promising branch so far is a **zero-shot Kimi-K2.5 search** with blueprint-conditioned prompts and aggressive candidate sampling. Earlier Qwen-based branches established the evaluation stack and prompt/reward infrastructure, but the Kimi branch is the first one that produced rare candidates satisfying:

- a single active-site motif
- catalytic geometry checks
- high local ESM proxy score

These rare candidates are referred to in the codebase and experiments as **unicorns**.

## Repository Scope

This public repository is code-first.

Large generated assets are intentionally excluded from version control:

- downloaded UniProt-derived datasets
- experiment reports and candidate audits
- local checkpoints and logs
- ad hoc notes and scratch artifacts

That is why the included `.gitignore` is strict about `data/` and `reports/`.

## Core Components

- `main.py`: primary experiment loop for prompt construction, sampling, candidate filtering, ESM scoring, reward computation, and optional training
- `local_proxy.py`: local ESM-2 pseudo-pLDDT scorer and sequence extraction/validation utilities
- `petase_family.py`: PETase-family motif, geometry, and family-reward logic
- `scripts/run_ablation.py`: reproducible experiment runner for fixed prompt subsets
- `scripts/run_kimi_zero_shot_stratified_search.py`: Kimi zero-shot search runner across fixed prompt slices and temperature bands
- `scripts/run_sft_warmstart.py`: short supervised warm-start runner
- `scripts/build_uniprot_petase_dataset.py`: UniProt ingestion and prompt-building pipeline
- `scripts/build_geometry_sft_dataset.py`: geometry-positive SFT dataset construction
- `scripts/build_kimi_micro_sft_dataset.py`: tiny Kimi-native positive dataset construction from mined unicorns

## High-Level Workflow

### 1. Build or filter a prompt dataset

The project uses UniProt-derived prompt datasets for polyester-hydrolase-family proteins. Relevance filtering is used to exclude obviously off-target families.

### 2. Sample many candidate sequences

The main loop generates many candidates per prompt from a remote Tinker-served model, typically under blueprint-conditioned prompts.

### 3. Score and rerank candidates

Candidates are filtered and scored using:

- sequence-format and alphabet validation
- family motif checks
- catalytic geometry checks
- local ESM-2 pseudo-pLDDT scoring
- anti-template / diversity heuristics

### 4. Mine rare successful candidates

Rare candidates that satisfy:

- `motif_count == 1`
- `geometry_passes == true`
- `ESM >= threshold`

are treated as high-value positives for later warm-starts.

### 5. Warm-start before RL

Short supervised warm-starts are used before considering RL continuation, because sparse geometry rewards alone were not enough to reliably discover the right manifold from scratch.

## Installation

### Requirements

The repository currently pins:

```txt
tinker==0.14.0
torch==2.10.0
transformers==5.2.0
numpy==2.4.2
safetensors==0.7.0
sentencepiece==0.2.1
```

Install with:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### External Requirements

- a valid `TINKER_API_KEY`
- access to a Tinker backend that supports the target model
- Apple Silicon or another machine capable of local ESM proxy inference

Example environment setup:

```bash
export TINKER_API_KEY=...
export ESM2_DEVICE=mps
```

## Running Experiments

### Single experiment run

```bash
python main.py
```

The loop behavior is controlled heavily through environment variables, including:

- `TINKER_BASE_MODEL`
- `PROMPTS_PATH`
- `REFERENCE_RECORDS_PATH`
- `PROMPT_VARIANT`
- `TINKER_CANDIDATE_SAMPLE_COUNT`
- `TINKER_SECOND_STAGE_TOP_K`
- `TINKER_PLDDT_GATE_THRESHOLD`
- `TINKER_EVAL_ONLY`

### Reproducible ablations

```bash
python scripts/run_ablation.py \
  --name baseline-50 \
  --variant motif_prior_soft_v2 \
  --model moonshotai/Kimi-K2.5 \
  --prompts-path /path/to/prompts.jsonl \
  --reference-records-path /path/to/petase_records.jsonl \
  --prompt-count 50 \
  --candidate-sample-count 256 \
  --second-stage-top-k 16 \
  --eval-only \
  --capture-candidate-audit
```

### Stratified Kimi search

```bash
python scripts/run_kimi_zero_shot_stratified_search.py \
  --name-prefix kimi25-zero-shot \
  --model moonshotai/Kimi-K2.5 \
  --variant motif_prior_soft_v2 \
  --prompts-path /path/to/prompts.jsonl \
  --reference-records-path /path/to/petase_records.jsonl \
  --prompt-count 25 \
  --candidate-sample-count 256 \
  --second-stage-top-k 16 \
  --temperatures 0.85 \
  --esm2-device mps
```

### Warm-starting from mined positives

Use the dataset builders in `scripts/` to construct small positive-only or mixed SFT datasets, then run:

```bash
python scripts/run_sft_warmstart.py ...
```

## Local Scoring Notes

The ESM proxy in [local_proxy.py](/Users/svdr/tinker/local_proxy.py) is local and separate from the remote Tinker generation model.

- generator: remote, via Tinker
- scorer: local, via ESM-2 masked-LM pseudo-log-likelihood

Current fast local path:

- PyTorch
- `mps` on Apple Silicon
- exact in-process score cache

An MLX-native ESM scorer has been scoped, but the current repository does not yet include a production-ready MLX masked-ESM backend.

## Safety and Caveats

- This repository is for research and experimentation.
- Generated sequences are not experimentally validated.
- The ESM score used here is a lightweight local proxy, not a substitute for full structure prediction.
- Passing the local proxy and family heuristics does **not** imply wet-lab success.

## Project Status

The codebase is in active exploration. The current best practical direction is:

1. mine more Kimi-native high-quality positives
2. thicken the micro-SFT anchor set
3. re-audit on fixed holdout prompts
4. only then consider a short RL continuation

## License

This project is released under the Apache License 2.0. See `LICENSE`.
