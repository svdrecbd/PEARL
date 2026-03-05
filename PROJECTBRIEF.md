# PROJECTBRIEF

## PEARL: PETase-Family Sequence Design

### Executive Summary

PEARL is an applied AI protein-design project focused on generating PETase/cutinase-like sequences that satisfy three constraints at the same time:

1. single catalytic motif
2. catalytic geometry pass
3. high foldability proxy (`ESM >= 85`)

The project has reached a clear technical signal:

- the target manifold exists
- the model can hit it
- hits are still sparse and not yet durable across broader prompt suites

This is not a dead project. It is in a narrow-manifold optimization phase.

## What Has Been Built

Core system:

- remote generation and training loop via Tinker
- local evaluator stack (motif, geometry, family plausibility, novelty)
- local ESM-2 proxy scorer
- reproducible ablation, robustness, and repair data pipelines
- retrain-readiness checks and durability-gate logic
- resume-safe run persistence and detached process tooling

Repository entry points:

- `main.py` for generation/eval loop
- `petase_family.py` for family and geometry scoring
- `local_proxy.py` for ESM proxy scoring
- `scripts/run_ablation.py` and `scripts/run_robustness_suite.py` for reproducible benchmarking

## Evidence To Date

Historical signal:

- zero-shot Kimi mining produced real Tier-2 hits
- micro-SFT branches transferred that signal intermittently
- strict and soft doping curricula that over-constrained the manifold collapsed the bridge

Recent robustness state (March 2026):

- p12 robustness has shown non-zero Tier-2 but seed fragility
- latest completed p24 3-seed pass produced `1/72` Tier-2 prompt hits (`[0,0,1]`)
- p48 is still incomplete in the current cycle

Interpretation:

- progress exists (not dead-zero)
- production is intermittent, not yet durable
- current objective is to raise floor and prompt coverage, not chase single outliers

## Why This Is Worth Funding

1. The core scientific risk has been partially retired.
   We already have existence proof of the target intersection.
2. The remaining problem is optimization and robustness, not blind discovery.
3. Tooling maturity is high enough for disciplined iteration.
   Failures now return actionable diagnostics, not ambiguity.
4. The work product is transferable.
   Even before wet-lab readiness, this yields reusable infrastructure for constrained protein sequence search.

## Current Bottleneck

The bottleneck is not model access. It is reliable bridge density:

- too many stability-only outputs
- too many geometry-only outputs
- too few intersection outputs across prompt/seed permutations

That is exactly what the durability gate is designed to measure and prevent over-claiming.

## 90-Day Plan

1. Complete full `12/24/48` durability suite for the active branch with fixed seeds.
2. Freeze a reference branch only if all gate conditions pass.
3. Build and dedupe a clean success pool from confirmed Tier-2 outputs and near-misses.
4. Run targeted repair/mining cycles against that frozen baseline.
5. Perform computational structural triage on the top shortlist.

Primary success criterion:

- convert rare existence proof into controlled low-rate production across seeds and prompt sizes.

## Budget Envelope (Low 4 Digits / Month)

This budget assumes generation/training remains on Tinker and cloud spend is for offloading local compute, scoring, orchestration, and validation bursts.

### Lean (`~$1.0k-$1.2k/month`)

- 1 small always-on control node
- 1 CPU worker
- burst GPU hours for scoring/triage
- modest storage and egress

Use case:

- single active experiment track with weekly robustness cycles

### Standard (`~$2.3k-$2.7k/month`)

- stronger always-on worker capacity
- parallel burst GPUs for faster turnaround
- larger storage buffer

Use case:

- multiple parallel ablation/repair tracks with faster decision cadence

### Extended (`~$3.2k-$3.9k/month`)

- standard footprint plus periodic high-end validation bursts

Use case:

- deeper computational triage on shortlisted candidates

Important boundary:

- full 24/7 self-hosted frontier training/serving is not a low-4-digit budget problem.

## Sponsor Decision Framework

A sponsor should back this if they want:

1. a high-upside, milestone-driven computational discovery program
2. transparent evidence gates instead of vague progress claims
3. reusable protein-design infrastructure as a parallel asset

A sponsor should not back this if they require:

1. guaranteed wet-lab-ready candidates in the immediate term
2. deterministic month-one production rates
3. zero scientific risk

## Sponsor Ask

Requested support:

1. low-4-digit monthly operating budget for 3-6 months
2. continued model-platform access for generation/training
3. checkpointed milestone reviews tied to durability-gate outcomes

Milestone review cadence:

- every 2 weeks for run health and throughput
- every 4 weeks for gate-level scientific progress

---

For full technical history and raw experiment records, see:

- `README.md`
- `notes/LABNOTES.md`
