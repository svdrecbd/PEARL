# Science Status

## Current State (April 12, 2026)

Mining works. Repair is real. Retrain durability improved materially on the repair-augmented branch, but full robustness still fails on prompt coverage. The newest evidence still says there is no passive “challenge-style” local-exploit lane already sitting in the saved finalized corpus.

Current canonical merged `stage-b-lite` mined pool:
- `1,597,184` raw candidates across the first `1.0M` tranche plus the `596,992` add-on tranche
- `179` exact-unique functional hits
- `54` exact-unique family-faithful hits
- `197` lineage clusters at `0.85`

Core references:
- [reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/bundle_summary.json](../reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/bundle_summary.json)
- [reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/retrain_readiness_selected_only.json](../reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/retrain_readiness_selected_only.json)

Current candidate-audit local-repair lane:
- pilot:
  - `48` parents
  - `13,033` evaluated variants
  - `577` survivors
  - `192` strict shortlist rows
  - `122` strict-bridge consensus rows
  - readiness passed
- diversity-capped scale-up:
  - `96` parents
  - `28,030` evaluated variants
  - `1,071` survivors
  - `231` strict shortlist rows
  - `128` strict-bridge consensus rows
  - `18` unique parent runs represented in the strict shortlist
  - `ready_for_retrain: true`
  - `443` deduped tier-2 positives
  - `280` deduped tier-1 proxy positives
  - `228` clusters
  - `largest_cluster_share: 0.0293`
  - `max_source_share: 0.0655`

References:
- [reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_summary.json](../reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_summary.json)
- [reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_validation_summary.json](../reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_validation_summary.json)
- [reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_readiness.json](../reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_readiness.json)
- [reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_summary.json](../reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_summary.json)
- [reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_validation_summary.json](../reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_validation_summary.json)
- [reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_readiness.json](../reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_readiness.json)

Latest completed strict branch:
- `strict-core-v7-repair`
- stage-A dataset:
  - `160` pairs
  - `24` mined new strict uniques repeated `4x`
  - `18` repair strict uniques repeated `2x`
  - `10` old strict uniques repeated `2x`
  - `4` canonical purebreds repeated `2x`
- stage-A checkpoint:
  - `tinker://59c10b59-45ec-5ed4-92a9-7c06e4241d0b:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stagea-lr1e6-ep3`
- stage-A `p48` smoke passed the stricter promotion gate:
  - hits by seed `[0, 2, 1]`
  - prompt coverage `3 / 48`
  - pass thresholds were `2` seeds and `2` prompts
- stage-B-lite dataset:
  - `162` pairs
  - `2` bridge anchors added on top of the stage-A core
- stage-B-lite checkpoint:
  - `tinker://7bb7b832-45c0-5ac0-8cea-1c3bc3f1d7ea:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stageb-lite-lr5e7-ep1`
- full stage-B-lite robustness failed durability:
  - `p12`: `[0, 0, 0]`, coverage `0 / 12`
  - `p24`: `[0, 2, 0]`, coverage `2 / 24`
  - `p48`: `[0, 3, 1]`, coverage `4 / 48`

References:
- [reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_stage_a_summary.json](../reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_stage_a_summary.json)
- [reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_stage_b_lite_summary.json](../reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_stage_b_lite_summary.json)
- [reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stagea-lr1e6-ep3/summary.json](../reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stagea-lr1e6-ep3/summary.json)
- [reports/robustness/pearl-topoff1m-a-strict-core-v7-repair-stagea-smoke-p48-t08-s41s53s67/smoke_gate_decision.json](../reports/robustness/pearl-topoff1m-a-strict-core-v7-repair-stagea-smoke-p48-t08-s41s53s67/smoke_gate_decision.json)
- [reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stageb-lite-lr5e7-ep1/summary.json](../reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stageb-lite-lr5e7-ep1/summary.json)
- [reports/robustness/pearl-topoff1m-a-strict-core-v7-repair-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json](../reports/robustness/pearl-topoff1m-a-strict-core-v7-repair-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json)

Local Gemma stage1 trial:
- frozen half-wave:
  - `2053` prompts
  - `525,568` raw candidates
- finalized result:
  - `0` functional bridge steps
  - `0` family-faithful bridge steps
  - mean average reward `0.0`

Reference:
- [reports/raft/pearl-topoff1m-a-stageb-lite-gemma-local-raft-stage1-p3907-c256-20260403b-localgemma12/finalization_summary.json](../reports/raft/pearl-topoff1m-a-stageb-lite-gemma-local-raft-stage1-p3907-c256-20260403b-localgemma12/finalization_summary.json)

Interpretation:
- this was not a silent finalization failure
- the saved reports showed many motif and ESM-gate passes but essentially no catalytic geometry and zero retained bridge hits
- the most likely explanation is a bad local-search regime for this setup, especially `google/gemma-4-31b-it` served through the current raw completions path
- do not resume the Gemma path unchanged

Historical local-exploit audit:
- hit-only universe:
  - `249` exact-unique finalized hit steps
  - `66` exact-unique family-faithful
  - `248` clusters at `0.85`
  - largest cluster size `2`
- widened report universe:
  - `10,306` finalized report records
  - `9,090` exact-unique report records
  - `2,747` screened exact-unique near-miss candidates
- anchor-neighborhood result:
  - `24` strict anchors checked
  - `24` bridge-only anchors checked
  - all `48` anchors classified `red`
  - shortlist count `0`
  - in the widened pass, selected anchors had no neighbors even at `0.85` whole-sequence identity

References:
- [reports/analysis/petase_historical_local_exploit/universe/universe_summary.json](../reports/analysis/petase_historical_local_exploit/universe/universe_summary.json)
- [reports/analysis/petase_historical_local_exploit_wide/universe/report_universe_summary.json](../reports/analysis/petase_historical_local_exploit_wide/universe/report_universe_summary.json)
- [reports/analysis/petase_historical_local_exploit_wide/neighborhoods/anchor_neighborhood_summary.json](../reports/analysis/petase_historical_local_exploit_wide/neighborhoods/anchor_neighborhood_summary.json)
- [reports/analysis/petase_historical_local_exploit_wide/shortlist/local_exploit_shortlist_summary.json](../reports/analysis/petase_historical_local_exploit_wide/shortlist/local_exploit_shortlist_summary.json)

## Current Read

- mining/data engine: working
- eval/finalization engine: working
- constrained strict selection: implemented
- stricter smoke gate: implemented and now cleared by the repair-augmented `v7` branch
- reranker lane: exists as a diagnostic track
- retrain recipe family: improved materially with repair-derived strict data, but still not converting into enough cross-prompt coverage at `p12/p24/p48`
- local-repair lane: validated through both the candidate-audit scale-up and the repair-augmented retrain branch
- passive local-exploit lane in the finalized corpus: still absent

Current governing objective:

> We are no longer optimizing for existence of strict hits; we are optimizing for reproducible prompt coverage breadth across fixed held-out suites.

Current negative result:

> There is no free lunch in the saved finalized corpus. If a PETase local-repair lane exists, we will have to build it from lower-level candidate surfaces or deliberate perturbation generation, not harvest it from finalized representatives.

Current positive result:

> Repair-derived strict data transfers. It produced the first branch that cleared the stricter smoke gate and promoted cleanly to `stage-b-lite`. The remaining issue is coverage breadth, not whether the signal is real.

## External Lesson

An external constrained optimization exercise outside this repo changed the working hypothesis in one important way:

- a basin that looks exhausted can still have large remaining headroom if the search operator changes
- same-length substitution-only local repair, role-aware mutation maps, and closure scans can outperform another round of broad exploration

What transferred back to PEARL:
- a “dead” branch can mean dead search policy, not dead basin
- local repair remains worth thinking about
- but the PETase corpus audit now says we do not already have those local basins precomputed in the saved finalized surfaces

So the external lesson changed the question from:
- “should we try local exploit?”

to:
- “where do we source local neighborhoods from, if not the finalized corpus?”

## Current Research Direction

Primary branch:
- freeze `strict-core-v7-repair` as the current best retrain baseline
- analyze the `p12/p24/p48` prompt gaps before paying for another full durability sweep
- keep strict promotion tied to the stricter `p48` smoke rule, but do not confuse smoke success with full durability

Repair branch:
- keep sourcing from candidate-audit / near-miss material, not finalized representatives
- keep same-length substitution-only repair as the core operator
- preserve the scale-up caps that kept the lane healthy:
  - low largest-cluster share
  - low max-source share
  - broad parent-run representation
- use repair-derived strict rows to cover underrepresented prompt and bucket regimes, not just to add more near-duplicate positives

Mining branch:
- keep the coverage-aware adversarial-slice million plan as the fallback mainline if a coverage-targeted `v8` still collapses
- do not discard the mining plan; defer it behind the next coverage decision gate

Gemma branch:
- do not continue the current local Gemma path unchanged
- if revisited, it needs a corrected serving/prompting path and a small calibration tranche before another million-candidate run

Parallel branch:
- keep building the reranker lane from mined outputs
- treat it as a reranker-first measurement track, not a generator-training default
- only consider generator-side preference training if the reranker clearly beats scalar reward baselines on the harder held-out prompt / bucket / cluster splits

## Next Action Plan

1. Run prompt-gap analysis on the completed `v7` robustness outputs.
- Identify which prompt buckets collapse at `p12` and `p24`.
- Separate “signal exists at `p48`” from “coverage is actually broad enough to survive smaller prompt budgets.”

2. Build one coverage-focused `v8` strict dataset.
- Keep the repair-derived strict signal.
- Add more examples aimed at under-covered prompt / bucket / cluster regimes.
- Do not train directly on the held-out robustness prompts if evaluation integrity needs to stay clean.

3. Re-gate cheaper before another full nine-run durability sweep.
- Run stage A.
- Re-run the supported stricter `p48` smoke gate.
- If that improves, then pay for the full `p12/p24/p48` robustness suite again.

4. Only fall back to another broad mining tranche if `v8` repeats the same failure mode.
- Failure conditions:
  - `p12` remains dead
  - `p24` remains carried by a single seed
  - `p48` still lacks prompt breadth
  - repair additions stop broadening support across prompt regimes

## Repo / Engine State

- supported workflow control flow is now config-driven
- shared reusable logic now lives under [src/pearl](../src/pearl)
- historical PETase campaign wrappers now live under [archive/2026q1_topoff1m_a/scripts](../archive/2026q1_topoff1m_a/scripts) with compatibility symlinks left behind in `scripts/`
- the historical-analysis workflow now supports both:
  - finalized hit-universe scans
  - widened finalized-report near-miss scans

For full chronology and engineering incidents, use:
- [notes/LABNOTES.md](../notes/LABNOTES.md)
