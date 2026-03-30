# Science Status

## Current State (March 30, 2026)

Mining works. Retrain durability still does not.

Current merged `stage-b-lite` mined pool:
- `1,597,184` raw candidates across the first `1.0M` tranche plus the `596,992` add-on tranche
- `179` exact-unique functional hits
- `54` exact-unique family-faithful hits
- `197` lineage clusters at `0.85`

Core references:
- [/Users/svdr/tinker/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/bundle_summary.json](/Users/svdr/tinker/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/bundle_summary.json)
- [/Users/svdr/tinker/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/retrain_readiness_selected_only.json](/Users/svdr/tinker/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/retrain_readiness_selected_only.json)

Latest completed strict branch:
- `strict-core-v6`
- stage-A checkpoint:
  - `tinker://d8ec4eaf-9037-5a5e-854a-734c57f590af:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v6-stagea-lr1e6-ep3`
- stage-B-lite checkpoint:
  - `tinker://241de107-2843-5038-9584-4ffa8949f43c:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v6-stageb-lite-lr5e7-ep1`

Results:
- stage-A `p48` smoke passed narrowly:
  - hits by seed `[0, 1, 0]`
  - prompt coverage `1 / 48`
- full stage-B-lite robustness failed:
  - `p12`: `[1, 0, 0]`, coverage `1 / 12`
  - `p24`: `[0, 1, 0]`, coverage `1 / 24`
  - `p48`: `[0, 1, 1]`, coverage `2 / 48`

References:
- [/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-strict-core-v6-stagea-smoke-p48-t08-s41s53s67/robustness_summary.json](/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-strict-core-v6-stagea-smoke-p48-t08-s41s53s67/robustness_summary.json)
- [/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-strict-core-v6-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json](/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-strict-core-v6-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json)

## Current Read

- mining/data engine: working
- eval/finalization engine: working
- constrained strict selection: now implemented
- stricter smoke gate: now implemented
- reranker lane: now exists as a diagnostic track
- retrain recipe family: still not converting mined strict signal into enough cross-prompt coverage

Current governing objective:

> We are no longer optimizing for existence of strict hits; we are optimizing for reproducible cross-prompt coverage.

## Current Research Direction

Main branch:
- run another coverage-aware `~1.0M` mining tranche from the best current miner prior
- reserve part of that tranche for adversarial prompt buckets that repeatedly under-converted
- build one strict prototype with prompt-first, prompt-bucket, and `0.85` cluster constraints
- only promote to stage B if stage-A `p48` smoke reaches at least `2/3` seeds with hits and at least `2` prompts hit across seeds

Parallel branch:
- keep building the reranker lane from mined outputs
- treat it as a reranker-first measurement track, not a generator-training default
- only consider generator-side preference training if the reranker clearly beats scalar reward baselines on the harder held-out prompt / bucket / cluster splits

## Repo / Engine State

- supported workflow control flow is now config-driven
- shared reusable logic now lives under [/Users/svdr/tinker/src/pearl](/Users/svdr/tinker/src/pearl)
- historical PETase campaign wrappers now live under [/Users/svdr/tinker/archive/2026q1_topoff1m_a/scripts](/Users/svdr/tinker/archive/2026q1_topoff1m_a/scripts) with compatibility symlinks left behind in `scripts/`

For full chronology and engineering incidents, use:
- [/Users/svdr/tinker/notes/LABNOTES.md](/Users/svdr/tinker/notes/LABNOTES.md)
