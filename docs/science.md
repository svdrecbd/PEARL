# Science Status

## Current State (April 11, 2026)

Mining works. Retrain durability still does not. The newest evidence also says there is no passive “challenge-style” local-exploit lane already sitting in the saved finalized corpus.

Current canonical merged `stage-b-lite` mined pool:
- `1,597,184` raw candidates across the first `1.0M` tranche plus the `596,992` add-on tranche
- `179` exact-unique functional hits
- `54` exact-unique family-faithful hits
- `197` lineage clusters at `0.85`

Core references:
- [reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/bundle_summary.json](../reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/bundle_summary.json)
- [reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/retrain_readiness_selected_only.json](../reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/retrain_readiness_selected_only.json)

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
- [reports/robustness/pearl-topoff1m-a-strict-core-v6-stagea-smoke-p48-t08-s41s53s67/robustness_summary.json](../reports/robustness/pearl-topoff1m-a-strict-core-v6-stagea-smoke-p48-t08-s41s53s67/robustness_summary.json)
- [reports/robustness/pearl-topoff1m-a-strict-core-v6-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json](../reports/robustness/pearl-topoff1m-a-strict-core-v6-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json)

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

Candidate-audit local-repair pilot:
- native repair pilot:
  - `48` parent hits
  - `13,033` evaluated variants
  - `577` repair survivors
  - elapsed about `5.24h`
- validation:
  - `192` strict shortlist rows
  - `122` strict-bridge consensus rows
  - `192` strict-family rows
  - `13` unique parent runs represented in the strict shortlist
- readiness:
  - `ready_for_retrain: true`
  - `406` deduped tier-2 positives
  - `243` deduped tier-1 proxy positives
  - `228` clusters
  - `largest_cluster_share: 0.032`
  - `max_source_share: 0.1158`

References:
- [reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_summary.json](../reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_summary.json)
- [reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_validation_summary.json](../reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_validation_summary.json)
- [reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_readiness.json](../reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_readiness.json)

## Current Read

- mining/data engine: working
- eval/finalization engine: working
- constrained strict selection: implemented
- stricter smoke gate: implemented
- reranker lane: exists as a diagnostic track
- retrain recipe family: still not converting mined strict signal into enough cross-prompt coverage
- local-repair lane: scientifically real at the candidate-audit layer
- passive local-exploit lane in the finalized corpus: still absent

Current governing objective:

> We are no longer optimizing for existence of strict hits; we are optimizing for reproducible cross-prompt coverage.

Current negative result:

> There is no free lunch in the saved finalized corpus. If a PETase local-repair lane exists, we will have to build it from lower-level candidate surfaces or deliberate perturbation generation, not harvest it from finalized representatives.

Current positive result:

> The candidate-audit layer does contain enough local structure to manufacture a retrain-ready strict pool through same-length repair. The lane is real; the remaining question is scale discipline, not existence.

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
- treat local repair as the next gated experiment, not a side hypothesis
- do not buy another broad million-candidate mine until the repair lane either scales cleanly or collapses under concentration control
- keep strict promotion tied to the stricter `p48` smoke rule

Repair branch:
- source from candidate-audit / near-miss material, not finalized representatives
- keep same-length substitution-only repair as the core operator
- scale carefully because the pilot shortlist is still concentrated:
  - top parent run contributed `36 / 192`
  - second parent run contributed `24 / 192`
  - current strict set is entirely `1`- or `2`-mutation repairs
- treat concentration control as a first-class gating rule, not post-hoc cleanup

Mining branch:
- keep the coverage-aware adversarial-slice million plan as the fallback mainline if repair scale-up collapses
- do not discard the mining plan; defer it behind the next repair decision gate

Gemma branch:
- do not continue the current local Gemma path unchanged
- if revisited, it needs a corrected serving/prompting path and a small calibration tranche before another million-candidate run

Parallel branch:
- keep building the reranker lane from mined outputs
- treat it as a reranker-first measurement track, not a generator-training default
- only consider generator-side preference training if the reranker clearly beats scalar reward baselines on the harder held-out prompt / bucket / cluster splits

## Next Action Plan

1. Run a bounded repair scale-up, not a broad mining tranche.
- Target shape:
  - expand from `48` parents to a diversity-capped parent set
  - keep source caps per parent run and per source wave
  - prefer anchors from underrepresented successful parent runs before adding more variants from the top two parents
- Operational goal:
  - larger than the pilot, but still bounded enough to validate concentration behavior before paying for more mining

2. Add concentration-aware validation gates.
- Require the scaled repair set to preserve:
  - low largest-cluster share
  - low max-source share
  - broad parent-run representation
- Fail the branch if growth comes mostly from the same dominant parent families.

3. If the scaled repair lane still passes readiness, build one repair-augmented strict dataset.
- Use repair survivors as a new strict ingredient, not as a replacement for mined anchors.
- Then run one strict branch through:
  - stage A
  - stricter `p48` smoke
  - stage B only if smoke clears `2` seeds and `2` prompts

4. Only fall back to the next broad million if the scale-up fails.
- Failure conditions:
  - concentration gets ugly
  - repair survivors stop growing materially
  - retrain-readiness gains flatten
  - strict smoke does not improve after adding repair-derived stricts

## Repo / Engine State

- supported workflow control flow is now config-driven
- shared reusable logic now lives under [src/pearl](../src/pearl)
- historical PETase campaign wrappers now live under [archive/2026q1_topoff1m_a/scripts](../archive/2026q1_topoff1m_a/scripts) with compatibility symlinks left behind in `scripts/`
- the historical-analysis workflow now supports both:
  - finalized hit-universe scans
  - widened finalized-report near-miss scans

For full chronology and engineering incidents, use:
- [notes/LABNOTES.md](../notes/LABNOTES.md)
