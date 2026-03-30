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

## Current Default Next Move

- run another mining-backed loop
- use the constrained selector and stricter smoke gate on the next strict prototype
- keep the reranker lane as a diagnostic track until it clearly beats the scalar reward baseline on the harder held-out splits

For full chronology and engineering incidents, use:
- [/Users/svdr/tinker/notes/LABNOTES.md](/Users/svdr/tinker/notes/LABNOTES.md)
