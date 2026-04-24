# LABNOTES

Internal working notes for **PEARL**: Protein Engineering Adapter via Reinforcement Learning.

This document is meant to do three jobs:

1. Preserve the experimental story from start to finish.
2. Record the engineering failures and fixes that materially changed results.
3. Onboard a new collaborator without forcing them to reconstruct the project from terminal history.

This is a living document. It should be updated whenever we change the search regime, reward/eval definition, or operational workflow.

Supported operator docs now live under:

- [docs/overview.md](../docs/overview.md)
- [docs/workflows.md](../docs/workflows.md)
- [docs/operations.md](../docs/operations.md)
- [docs/science.md](../docs/science.md)
- [docs/manifold_construction.md](../docs/manifold_construction.md)

This file remains the long-form experimental and engineering fossil record.

## Latest Canonical Status (as of April 23, 2026)

- best historical retrain branch:
  - `strict-core-v7-repair`
  - stage-A checkpoint:
    - `tinker://59c10b59-45ec-5ed4-92a9-7c06e4241d0b:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stagea-lr1e6-ep3`
  - stage-B-lite checkpoint:
    - `tinker://7bb7b832-45c0-5ac0-8cea-1c3bc3f1d7ea:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stageb-lite-lr5e7-ep1`
  - stage-A `p48` smoke passed the stricter gate:
    - hits by seed `[0, 2, 1]`
    - prompt coverage `3 / 48`
  - full stage-B-lite robustness still failed durability:
    - `p12`: hits by seed `[0, 0, 0]`, prompt coverage `0 / 12`
    - `p24`: hits by seed `[0, 2, 0]`, prompt coverage `2 / 24`
    - `p48`: hits by seed `[0, 3, 1]`, prompt coverage `4 / 48`
  - interpretation:
    - `v7` remains the best empirical branch
    - it may have found a narrow, fragile attractor rather than a robust learned PETase/cutinase manifold
- latest completed strict branch:
  - `strict-core-v8-coverage`
  - config:
    - [configs/experiments/strict/topoff1m_a_strict_core_v8_coverage_20260413.json](../configs/experiments/strict/topoff1m_a_strict_core_v8_coverage_20260413.json)
  - stage-A checkpoint:
    - `tinker://0e007439-8486-58fd-8a5a-9769ced7e0b2:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v8-coverage-stagea-lr1e6-ep3`
  - stage-B-lite checkpoint:
    - `tinker://789989aa-dbe7-522b-a82a-1bccd9060a06:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v8-coverage-stageb-lite-lr5e7-ep1`
  - stage-A `p48` smoke result:
    - seed `41`: `3` functional, `2` family-faithful
    - seed `53`: `1` functional, `0` family-faithful
    - seed `67`: `0` functional, `0` family-faithful
    - smoke gate passed, but this was not enough to predict durability
  - full stage-B-lite robustness:
    - `p12`: functional hits by seed `[0, 0, 0]`, family-faithful `[0, 0, 0]`
    - `p24`: functional hits by seed `[0, 0, 0]`, family-faithful `[0, 0, 0]`
    - `p48`: functional hits by seed `[0, 3, 3]`, family-faithful `[0, 0, 0]`
  - stage-A diagnostic after the failure:
    - run name: `pearl-topoff1m-a-strict-core-v8-stagea-diagnostic-p12p24-t08-s41s53s67`
    - checkpoint: `v8` stage-A checkpoint above
    - `p12`: functional `[0, 0, 0]`, family-faithful `[0, 0, 0]`
    - `p24`: functional `[0, 0, 0]`, family-faithful `[0, 0, 0]`
  - interpretation:
    - `stage-b-lite` was not the sole regression
    - the `v8` stage-A policy itself failed the short-context `p12/p24` manifold test
    - raw `p48` functional hits are not sufficient because the family-faithful signal collapsed
- latest local repair rescue attempt:
  - config:
    - [configs/experiments/repair/topoff1m_a_v9_p12p24_repair_20260421.json](../configs/experiments/repair/topoff1m_a_v9_p12p24_repair_20260421.json)
  - intended strict config if repair had passed:
    - [configs/experiments/strict/topoff1m_a_strict_core_v9_p12p24_repair_20260421.json](../configs/experiments/strict/topoff1m_a_strict_core_v9_p12p24_repair_20260421.json)
  - source audits:
    - `v8` stage-A diagnostic `p12/p24`
    - `v8` stage-B-lite robustness `p12/p24`
  - repair pool:
    - `12` source audits
    - `134` geometry-dominant near-misses
    - `0` tier-2 hits
    - mean ESM score `31.6049`
    - mean geometry score `0.5971`
  - native repair:
    - `134` hits processed
    - `47,489` local variants evaluated
    - `79` loose repair survivors
    - max survivor ESM `99.08`
    - mean survivor ESM `95.943`
    - elapsed time `8,081.93` seconds on the L40S
  - strict validation:
    - `0` strict shortlist
    - `0` strict bridge
    - `0` strict family
    - `0` strict consensus
    - `79 / 79` rejected
  - reject histogram:
    - `esm_below_strict_floor`: `25`
    - `fails_family_core_screen`: `79`
    - `gap_error_above_strict_bridge_limit`: `61`
    - `missing_family_serine_motif`: `79`
    - `mutation_count_too_high`: `18`
    - `outside_family_length_band`: `79`
  - readiness:
    - `ready_for_retrain: false`
    - base positives: `0`
    - survivor positives: `0`
    - no `v9` dataset should be built from this repair output
  - interpretation:
    - local repair found stable, geometry-ish sequences
    - those sequences were not strict PETase/cutinase-family candidates
    - the failure mode is family-manifold drift, not GPU/runtime failure
- current spend/cost read:
  - user-observed Tinker spend through the `v8` eval path was about `$53.33`
  - sampled eval candidates in that spend:
    - smoke: `18,432`
    - full robustness: `32,256`
    - total: `50,688`
  - observed blended cost:
    - roughly `$1.05 / 1k` candidates
    - roughly `$105 / 100k`
    - roughly `$315 / 300k`
    - roughly `$1,052 / 1M`
  - the April 21/22 local repair rescue did not add Tinker sampling spend
- current scientific read:
  - the original broad mining/data engine worked as a discovery engine
  - April 10/12 repair was real and made `v7` possible
  - `v7` may still have been a lucky narrow attractor
  - `v8` failed to broaden the attractor
  - the `v9` p12/p24 repair rescue failed because stable repaired outputs left the strict family manifold
  - manifold curriculum v1 produced nonzero strict transfer but failed to broaden it to `p24`
  - the next serious phase should not be another small SFT tweak
- current manifold-construction status:
  - Phase 1 validator-first constructor is implemented:
    - [scripts/manifold_construction_experiment.py](../scripts/manifold_construction_experiment.py)
    - [configs/experiments/manifold/topoff1m_a_phase1_constructor_20260422.json](../configs/experiments/manifold/topoff1m_a_phase1_constructor_20260422.json)
  - local output:
    - [reports/manifold/topoff1m-a-manifold-phase1-20260422/summary.json](../reports/manifold/topoff1m-a-manifold-phase1-20260422/summary.json)
    - [reports/manifold/topoff1m-a-manifold-phase1-20260422/roundtrip_report.json](../reports/manifold/topoff1m-a-manifold-phase1-20260422/roundtrip_report.json)
  - scaffold bank:
    - `12,619` unique sequences
    - `4,893` family-manifold scaffolds
    - `3,769` strict-manifold scaffolds
    - `274` strict candidate positives
  - round-trip:
    - `272` strict-positive rows
    - `272` strict-positive passes
    - `0` strict-positive rejects
  - negative gate:
    - recovered `79` `v9` reject rows from the L40S box
    - `0` negative family-manifold passes
- current Phase 2 ESM-scored status:
  - local output:
    - [reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_pre_esm_frontier.jsonl](../reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_pre_esm_frontier.jsonl)
    - [reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_pre_esm_summary.json](../reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_pre_esm_summary.json)
    - [reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_esm_scored.jsonl](../reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_esm_scored.jsonl)
    - [reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_esm_score_summary.json](../reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_esm_score_summary.json)
    - [reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_selected_strict.jsonl](../reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_selected_strict.jsonl)
    - [reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_selection_summary.json](../reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_selection_summary.json)
  - frontier:
    - `10,000` strict-manifold same-length candidates
    - `4,067` one-mutants
    - `5,933` two-mutants
    - `96` selected parent scaffolds
    - `79` contributing parent scaffolds before the `10,000` cap was reached
    - `8` unique lengths
  - ESM scoring:
    - scored on the L40S with `ESM2_DEVICE=cuda`
    - duration `763.589` seconds
    - `10,000 / 10,000` scored
    - min `99.73`, mean `99.9121`, max `99.98`
    - all `10,000` scored `>=95`
  - diversity/readiness selection:
    - run on the L40S box after scoring
    - `ready_for_curriculum_build: true`
    - `230` selected strict candidates
    - `79` parent scaffolds
    - `8` unique lengths
    - mutation histogram: `130` one-mutants and `100` two-mutants
    - `133` bridge-quality rows across `48` parent scaffolds
    - max parent share `0.013043`
    - max length share `0.165217`
    - selected ESM min `99.8`, mean `99.9225`, max `99.98`
  - manifold curriculum v1:
    - config:
      - [configs/experiments/strict/topoff1m_a_manifold_curriculum_v1_20260422.json](../configs/experiments/strict/topoff1m_a_manifold_curriculum_v1_20260422.json)
    - builder:
      - [scripts/build_manifold_curriculum.py](../scripts/build_manifold_curriculum.py)
    - dataset:
      - [reports/raft/topoff1m-a-manifold-curriculum-v1-20260422/manifold_v1_stage_a.jsonl](../reports/raft/topoff1m-a-manifold-curriculum-v1-20260422/manifold_v1_stage_a.jsonl)
      - [reports/raft/topoff1m-a-manifold-curriculum-v1-20260422/manifold_v1_stage_a_summary.json](../reports/raft/topoff1m-a-manifold-curriculum-v1-20260422/manifold_v1_stage_a_summary.json)
    - `238` dataset rows
    - `230` selected Phase 2 rows
    - `8` canonical purebred rows
    - `234` unique sequences
    - `133` bridge-quality selected rows
    - stage-A train:
      - `pearl-micro-sft-topoff1m-a-manifold-v1-stagea-lr8e7-ep2`
      - base checkpoint: `strict-core-v7-repair-stageb-lite`
      - epochs `2`, learning rate `8e-7`, batch size `8`
      - training report: [reports/warmstart/pearl-micro-sft-topoff1m-a-manifold-v1-stagea-lr8e7-ep2/report.json](../reports/warmstart/pearl-micro-sft-topoff1m-a-manifold-v1-stagea-lr8e7-ep2/report.json)
    - capped gate:
      - `pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128`
      - [reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/robustness_summary.json](../reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/robustness_summary.json)
      - [reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/p12_gate_decision.json](../reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/p12_gate_decision.json)
      - [reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/p24_gate_decision.json](../reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/p24_gate_decision.json)
    - gate outcome:
      - overall: failed
      - `p12`: passed, tier-2 hits by seed `[1, 2, 0]`, `2 / 3` seeds with hits, `3` prompts covered
      - `p24`: failed, tier-2 hits by seed `[0, 1, 0]`, `1 / 3` seeds with hits, `1` prompt covered
    - operational guard:
      - branch stayed inside the agreed stage-A plus p12/p24-only scope
      - no retries, stage-B, p48, or paid mining were launched
      - the L40S GPU drained after completion
    - interpretation:
      - the Phase 2 manifold pool is not inert; it can induce strict hits
      - the learned behavior is still narrow and fails broader `p24` prompt coverage
      - manifold v1 should stop here
  - manifold curriculum v1.1 offline repair:
    - audit:
      - [scripts/audit_manifold_v1_gate.py](../scripts/audit_manifold_v1_gate.py)
      - [reports/analysis/manifold_v1_gate_audit_20260422/audit.md](../reports/analysis/manifold_v1_gate_audit_20260422/audit.md)
      - [reports/analysis/manifold_v1_gate_audit_20260422/audit.json](../reports/analysis/manifold_v1_gate_audit_20260422/audit.json)
    - builder:
      - [scripts/build_manifold_v11_curriculum.py](../scripts/build_manifold_v11_curriculum.py)
    - config:
      - [configs/experiments/strict/topoff1m_a_manifold_curriculum_v11_20260422.json](../configs/experiments/strict/topoff1m_a_manifold_curriculum_v11_20260422.json)
    - dataset:
      - [reports/raft/topoff1m-a-manifold-curriculum-v11-20260422/manifold_v11_stage_a.jsonl](../reports/raft/topoff1m-a-manifold-curriculum-v11-20260422/manifold_v11_stage_a.jsonl)
      - [reports/raft/topoff1m-a-manifold-curriculum-v11-20260422/manifold_v11_stage_a_summary.json](../reports/raft/topoff1m-a-manifold-curriculum-v11-20260422/manifold_v11_stage_a_summary.json)
    - audit result:
      - `23` p24 prompt holes
      - `1` p24 weak-hit prompt
      - `20 / 20` unique p24 requested lengths absent from the Phase 2 selected pool
      - actual v1 functional hits were strict but length-mismatched, so direct hit replay is not used by default
    - dataset result:
      - `216` rows
      - `212` unique sequences
      - `160` balanced Phase 2 anchors
      - `46` p24-hole strict scaffold anchors
      - `2` p24 weak-hit strict scaffold anchors
      - `8` canonical purebred anchors
      - `33` length buckets
      - p24 replay anchor length delta: min `-1`, max `1`, mean absolute `0.042`
      - max sequence repeat `2`
      - max parent/candidate share `0.013889`
    - interpretation:
      - v1.1 patches the exact p24 prompt/length hole exposed by v1
      - the later p24-only gate failed cleanly with `0` tier-2 hits and no hidden strict-conjunction reservoir
  - manifold curriculum v1.2:
    - selected `39` strict/core/ESM repair candidates across `38` sources and `29` exact lengths
    - stage-A dataset had `47` rows: `39` selected repairs plus `8` purebred anchors
    - paid p24 gate recovered `3` functional hits and `2` family-faithful hits
    - prompt coverage stayed narrow at `3 / 24`, so durability failed
  - manifold curriculum v1.3:
    - dataset had `64` rows: `39` v1.2 breadth anchors, `8` support scaffolds, `9` gate-hit replays, and `8` purebred anchors
    - paid p24 gate regressed to tier-2 hits `[0, 0, 1]`, prompt coverage `1 / 24`, and `0` family-faithful hits
    - the only recovered tier-2 event was bridge-only at seed `67`, prompt step `11`
- current decision point:
  - do not launch a blind `1M` candidate run as the default next step
  - do not retry manifold v1 unchanged
  - do not launch another paid manifold `v1.x` replay, stage-B, p48, or broad mining from this branch line
  - build a manifold `v2` offline constructor/objective branch before spending again
  - freeze v1.2 family-faithful hits as positive anchors
  - treat v1.3 stable-only and geometry-only finalists as hard negatives
  - a `50k-75k` p12/p24 exact-hole sweep remains available only as a diagnostic if the offline redesign stalls

## Previous Canonical Status (superseded; as of April 20, 2026)

- active mined-data engine:
  - merged `stage-b-lite` `1.6M` pool
  - `1,597,184` raw candidates across the `1,000,192` first tranche plus the `596,992` add-on tranche
  - merged postprocess bundle:
    - `179` exact-unique functional hits
    - `54` exact-unique family-faithful hits
    - `197` lineage clusters at `0.85`, largest cluster size `2`
- candidate-audit local-repair lane:
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
    - `18` unique parent runs in the strict shortlist
    - readiness passed with `443` deduped tier-2 positives, `280` tier-1 proxy positives, `228` clusters, `largest_cluster_share = 0.0293`, and `max_source_share = 0.0655`
- latest completed strict branch:
  - `strict-core-v7-repair`
  - stage-A checkpoint:
    - `tinker://59c10b59-45ec-5ed4-92a9-7c06e4241d0b:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stagea-lr1e6-ep3`
  - stage-A smoke custom gate passed on `p48`:
    - hits by seed `[0, 2, 1]`
    - prompt coverage `3 / 48`
    - pass thresholds were `2` seeds and `2` prompts
  - stage-B-lite checkpoint:
    - `tinker://7bb7b832-45c0-5ac0-8cea-1c3bc3f1d7ea:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stageb-lite-lr5e7-ep1`
  - full robustness still failed:
    - `p12`: hits by seed `[0, 0, 0]`, prompt coverage `0 / 12`
    - `p24`: hits by seed `[0, 2, 0]`, prompt coverage `2 / 24`
    - `p48`: hits by seed `[0, 3, 1]`, prompt coverage `4 / 48`
  - interpretation:
    - this is the first repair-augmented branch that actually cleared the stricter smoke gate and promoted cleanly to `stage-b-lite`
    - the project has turned a corner
    - but the full durability problem is still prompt coverage breadth, not hit existence
- next built strict branch:
  - `strict-core-v8-coverage`
  - config:
    - [configs/experiments/strict/topoff1m_a_strict_core_v8_coverage_20260413.json](../configs/experiments/strict/topoff1m_a_strict_core_v8_coverage_20260413.json)
  - base/init checkpoint:
    - `tinker://7bb7b832-45c0-5ac0-8cea-1c3bc3f1d7ea:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stageb-lite-lr5e7-ep1`
  - stage-A dataset:
    - `184` pairs
    - `63` unique sequences
    - selected new stricts: `32` rows from `54` raw, across `19` prompt buckets
    - selected repair stricts: `20` rows from `231` raw, across all `5` repair prompt buckets
  - stage-B-lite dataset:
    - `192` pairs
    - `71` unique sequences
    - bridge anchors: `8` rows from `143` raw, across `8` prompt buckets
  - engineering change:
    - added bucket-capped selection for mined strict and repair strict rows
    - kept bridge-anchor selection prompt-cluster-diverse
  - status:
    - built locally and tests pass
    - not yet launched
- local Gemma H200 trial:
  - half-wave frozen at `2053` prompts / `525,568` raw candidates
  - ESM finalization retained:
    - `0` functional bridge steps
    - `0` family-faithful bridge steps
  - this was not a silent finalization failure
  - saved reports showed motif and ESM-gate activity but essentially no catalytic geometry and zero retained bridge hits
  - current interpretation:
    - the local Gemma path as run (`google/gemma-4-31b-it` through the raw completions path) is not a valid production miner
    - do not continue it unchanged
- historical local-exploit audit:
  - initial finalized-hit universe:
    - `249` exact-unique finalized hit steps
    - `66` exact-unique family-faithful
    - `248` clusters at `0.85`
    - largest cluster size `2`
  - widened finalized-report universe:
    - `10,306` finalized report records
    - `9,090` exact-unique report records
    - `2,747` screened exact-unique near-miss candidates
  - anchor-neighborhood result:
    - `24` strict anchors checked
    - `24` bridge-only anchors checked
    - all `48` anchors classified `red`
    - shortlist `0`
    - no neighbors even at `0.85` whole-sequence identity in the widened pass
- then-current phase:
  - governing objective: reproducible cross-prompt coverage, not existence of isolated strict hits
  - freeze `strict-core-v7-repair` as the best current retrain baseline
  - treat the enlarged strict pool as validated mining output, not as a failed data engine
  - next gated branch: run coverage-focused `v8`, informed by the `p12/p24/p48` prompt gaps
  - clean `v8` Tinker eval budget:
    - smoke decision: `18,432` sampled candidates
    - smoke plus full robustness, if promoted: `50,688` sampled candidates
    - using the current pasted rates, clean end-to-end branch cost is roughly `$133-142`
  - passive local exploit is not available in the saved finalized corpus
  - candidate-audit local repair is validated as a real lane and remains part of the next strict mix
  - broad mining is now fallback only if coverage-targeted retrain still stalls
  - parallel branch: keep the reranker lane reranker-first and diagnostic until it clearly beats scalar reward baselines on harder held-out prompt / bucket / cluster splits
- then-ruled-out paths:
  - resumed PPO
  - another loose-heavy SFT mix
  - another tiny strict-core variant before buying more data
  - treating the `1.6M` merged mine as a failure
  - treating the external local-optimization lesson as proof that the current finalized corpus already contains a free local-exploit lane
  - using Wynton as the primary production runtime
  - AlphaFold-scale downstream triage

Supported engine state:

- reusable engine logic now lives under [src/pearl](../src/pearl)
- supported workflow identity now lives under [configs/experiments](../configs/experiments)
- historical PETase wrapper families now live under [archive/2026q1_topoff1m_a/scripts](../archive/2026q1_topoff1m_a/scripts) with compatibility symlinks left behind in `scripts/`

## April 21-22, 2026: `v8` robustness failure, failed p12/p24 repair rescue, and manifold-construction pivot

Artifacts and configs:

- [configs/experiments/strict/topoff1m_a_strict_core_v8_coverage_20260413.json](../configs/experiments/strict/topoff1m_a_strict_core_v8_coverage_20260413.json)
- [configs/experiments/repair/topoff1m_a_v9_p12p24_repair_20260421.json](../configs/experiments/repair/topoff1m_a_v9_p12p24_repair_20260421.json)
- [configs/experiments/strict/topoff1m_a_strict_core_v9_p12p24_repair_20260421.json](../configs/experiments/strict/topoff1m_a_strict_core_v9_p12p24_repair_20260421.json)
- remote repair artifacts on the L40S box:
  - `/home/svdr/work/tinker/reports/repair/topoff1m-a-v9-p12p24-repair-20260421/repair_pool_selected_raw_summary.json`
  - `/home/svdr/work/tinker/reports/repair/topoff1m-a-v9-p12p24-repair-20260421/repair_summary.json`
  - `/home/svdr/work/tinker/reports/repair/topoff1m-a-v9-p12p24-repair-20260421/repair_validation_summary.json`
  - `/home/svdr/work/tinker/reports/repair/topoff1m-a-v9-p12p24-repair-20260421/repair_readiness.json`

### `v8` final readout

`strict-core-v8-coverage` was designed to test whether the `v7` repair-derived signal could be broadened with bucket-capped strict selection and more bridge-anchor diversity.

The result was negative:

- stage-A checkpoint:
  - `tinker://0e007439-8486-58fd-8a5a-9769ced7e0b2:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v8-coverage-stagea-lr1e6-ep3`
- stage-B-lite checkpoint:
  - `tinker://789989aa-dbe7-522b-a82a-1bccd9060a06:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v8-coverage-stageb-lite-lr5e7-ep1`
- stage-A `p48` smoke:
  - seed `41`: `3` functional, `2` family-faithful
  - seed `53`: `1` functional, `0` family-faithful
  - seed `67`: `0` functional, `0` family-faithful
  - smoke passed, but the signal was not durable
- full stage-B-lite robustness:
  - `p12`: functional `[0, 0, 0]`, family-faithful `[0, 0, 0]`
  - `p24`: functional `[0, 0, 0]`, family-faithful `[0, 0, 0]`
  - `p48`: functional `[0, 3, 3]`, family-faithful `[0, 0, 0]`

This was worse than `v7` on the most important short-context suites. `v7` had at least shown `p24` signal `[0, 2, 0]` and `p48` signal `[0, 3, 1]`; `v8` lost `p24` entirely and lost all family-faithful robustness signal.

### Stage-A diagnostic

To separate `stage-b-lite` damage from stage-A damage, we ran:

- run name:
  - `pearl-topoff1m-a-strict-core-v8-stagea-diagnostic-p12p24-t08-s41s53s67`
- checkpoint:
  - `v8` stage-A checkpoint above
- suite:
  - `p12,p24`
  - seeds `41,53,67`
  - temperature `0.8`
  - `128` candidates per prompt
  - `second_stage_top_k = 8`

Final stage-A diagnostic:

- `p12`:
  - seed `41`: `0` functional, `0` family-faithful, average reward `6.5425`
  - seed `53`: `0` functional, `0` family-faithful, average reward `4.3792`
  - seed `67`: `0` functional, `0` family-faithful, average reward `7.215`
- `p24`:
  - seed `41`: `0` functional, `0` family-faithful, average reward `5.5204`
  - seed `53`: `0` functional, `0` family-faithful, average reward `5.5646`
  - seed `67`: `0` functional, `0` family-faithful, average reward `6.4796`

Interpretation:

- `stage-b-lite` was not the sole failure
- the `v8` stage-A generator was already dead at `p12/p24`
- a simple “skip stage B” branch is not a v9 strategy

### p12/p24 repair rescue

After the diagnostic, we tried a local repair rescue aimed only at `p12/p24` surfaces.

Config:

- [configs/experiments/repair/topoff1m_a_v9_p12p24_repair_20260421.json](../configs/experiments/repair/topoff1m_a_v9_p12p24_repair_20260421.json)

Inputs:

- `v8` stage-A diagnostic `p12/p24` candidate audits
- `v8` stage-B-lite robustness `p12/p24` candidate audits
- selected and unselected geometry-dominant near-misses

Important operator fix:

- the first repair driver was stopped because `native_repair.selected_only` was still `true`
- that contradicted the rescue plan, because the useful near-misses were in the unselected candidate surface
- the corrected driver used `--include-unselected`

Repair pool:

- `12` source audits
- `134` total rows
- `0` tier-2 hits
- `134` geometry-dominant near-misses
- mean ESM score `31.6049`
- mean geometry score `0.5971`

Native repair:

- `134` hits processed
- `47,489` local variants evaluated
- `79` loose repair survivors
- max survivor ESM `99.08`
- mean survivor ESM `95.943`
- proposal device: CUDA
- elapsed time: `8,081.93` seconds

This looked superficially promising until strict validation.

Strict validation:

- input count: `79`
- strict shortlist: `0`
- strict bridge: `0`
- strict family: `0`
- strict consensus: `0`
- review: `0`
- reject: `79`

Reject histogram:

- `esm_below_strict_floor`: `25`
- `fails_family_core_screen`: `79`
- `gap_error_above_strict_bridge_limit`: `61`
- `missing_family_serine_motif`: `79`
- `mutation_count_too_high`: `18`
- `outside_family_length_band`: `79`

Readiness:

- `ready_for_retrain: false`
- base positive count: `0`
- survivor positive count: `0`
- all minimum-positive and cluster-count checks failed

Conclusion:

> The repair pass recovered stable geometry-ish sequences, but not strict PETase/cutinase-family sequences.

This is not an infrastructure failure. The run finished, the GPU drained, and the validator worked. The failure is scientific: high ESM plus local geometry repair is not enough when the candidate has already drifted out of the family manifold.

### Cost read

Observed user-side Tinker spend through the `v8` eval path was about `$53.33`.

Candidate count behind that spend:

- stage-A smoke: `48 * 3 * 128 = 18,432`
- full robustness: `(12 + 24 + 48) * 3 * 128 = 32,256`
- total sampled eval candidates: `50,688`

Observed blended candidate cost:

- about `$1.05 / 1k` candidates
- about `$105 / 100k`
- about `$315 / 300k`
- about `$1,052 / 1M`

The p12/p24 repair rescue did not add Tinker candidate spend; it was local L40S compute.

### Strategic update

The old read after `v7` was:

> Repair-derived strict data transfers; the remaining issue is coverage breadth.

The updated read after `v8` plus the failed `v9` repair rescue is:

> Repair-derived strict data can transfer, but the current Kimi sampling plus strict-SFT plus repair loop does not reliably learn or preserve the strict PETase/cutinase manifold.

The chance that `v7` was partly a lucky narrow attractor is now material.

Current options:

1. Run a cheap diagnostic mining sweep:
   - `50k-75k` exact p12/p24 hole sweep
   - stop unless strict or near-strict density is nonzero
2. Run a targeted p12/p24 mining tranche:
   - `250k-300k` candidates
   - expected cost around `$315` at observed rates
   - kill if strict density and cluster breadth are absent
3. Skip paid sampling for now and construct the manifold directly:
   - build a scaffold bank from natural references and validated strict rows
   - infer and lock active-site blueprints
   - permit only same-length edits that preserve family membership, motif identity, length band, and catalytic spacing
   - optimize ESM and novelty only after strict family validity is guaranteed

Recommended next research direction:

> Stop asking Kimi to discover the joint constraint. Build a scaffold-first manifold constructor and use paid mining only as a diagnostic or later distillation source.

The draft operator plan for this hard route is documented in [docs/manifold_construction.md](../docs/manifold_construction.md).

## April 13-20, 2026: Coverage-focused `strict-core-v8` built and costed

Artifacts:

- [configs/experiments/strict/topoff1m_a_strict_core_v8_coverage_20260413.json](../configs/experiments/strict/topoff1m_a_strict_core_v8_coverage_20260413.json)
- [reports/raft/topoff1m-a-strict-core-v8-coverage-20260413/strict_core_v8_stage_a_summary.json](../reports/raft/topoff1m-a-strict-core-v8-coverage-20260413/strict_core_v8_stage_a_summary.json)
- [reports/raft/topoff1m-a-strict-core-v8-coverage-20260413/strict_core_v8_stage_b_lite_summary.json](../reports/raft/topoff1m-a-strict-core-v8-coverage-20260413/strict_core_v8_stage_b_lite_summary.json)
- [reports/raft/topoff1m-a-strict-core-v8-coverage-20260413/strict_core_v8_selected_new_family_faithful.jsonl](../reports/raft/topoff1m-a-strict-core-v8-coverage-20260413/strict_core_v8_selected_new_family_faithful.jsonl)
- [reports/raft/topoff1m-a-strict-core-v8-coverage-20260413/strict_core_v8_selected_repair_family_faithful.jsonl](../reports/raft/topoff1m-a-strict-core-v8-coverage-20260413/strict_core_v8_selected_repair_family_faithful.jsonl)
- [reports/raft/topoff1m-a-strict-core-v8-coverage-20260413/strict_core_v8_selected_bridge_anchors.jsonl](../reports/raft/topoff1m-a-strict-core-v8-coverage-20260413/strict_core_v8_selected_bridge_anchors.jsonl)

What changed:

- the `v7` result separated two questions:
  - the repair signal transfers
  - coverage breadth is still too weak
- `v8` therefore changes the data shape rather than the optimizer first
- mined strict rows now use a bucket-capped selector:
  - target: `32` rows
  - cap: `7` rows per prompt bucket
  - selected coverage: `32` prompts, `19` prompt buckets, `32` sequence clusters
- repair strict rows also use a bucket-capped selector with source and cluster controls:
  - target: `20` rows
  - cap: `9` rows per prompt bucket
  - max `2` rows per source run
  - max `1` row per sequence cluster
  - selected coverage: `20` prompts, all `5` repair prompt buckets, `20` sequence clusters
- bridge anchors now pull more of the unused diversity reserve:
  - target: `8` anchors
  - selected from `143` bridge-anchor candidates
  - selected coverage: `8` prompts, `8` prompt buckets, `8` sequence clusters

Built datasets:

- stage A:
  - `184` pairs
  - `63` unique sequences
  - source mix:
    - `20` old family-faithful rows
    - `96` mined new family-faithful rows
    - `60` repair family-faithful rows
    - `8` canonical purebred rows
- stage B-lite:
  - `192` pairs
  - `71` unique sequences
  - source mix:
    - the full stage-A set
    - `8` bridge-anchor rows

Why this matters:

- `v7` was the first branch to prove transfer but failed on prompt breadth
- `v8` is the first branch that directly targets that failure mode
- this makes another million-candidate tranche a fallback, not the immediate next move
- if `v8` fails the same way as `v7`, the next mining tranche should be coverage-aware and aimed at underrepresented prompt families rather than broad generic generation

Expected Tinker candidate budget:

- smoke only:
  - `48` prompts
  - `3` seeds
  - `128` candidates per prompt
  - `18,432` sampled candidates
- full robustness after `stage-b-lite`:
  - `12 + 24 + 48` prompts
  - `3` seeds
  - `128` candidates per prompt
  - `32,256` sampled candidates
- full branch eval path:
  - `50,688` sampled candidates

Using the pasted rates:

- prefill: `$5.15 / 1M tokens`
- sample: `$12.81 / 1M tokens`
- train: `$15.40 / 1M tokens`

Estimated clean-run spend:

- smoke only: roughly `$47-50`
- full robustness after promotion: roughly `$83-89`
- full `v8` branch, including small warmstart training cost: roughly `$133-142`

Caveats:

- this is a clean-run estimate
- stockpile retries can increase sampling spend if Tinker flakes
- the training cost is small relative to remote sampling

Current decision rule:

- run `v8` stage A
- run the stricter `p48` smoke gate
- promote to `stage-b-lite` only if smoke clears
- pay for full `p12/p24/p48` robustness only if the branch earns it
- defer another huge mine unless `v8` repeats the `p12/p24` collapse or remains narrow at `p48`

## April 12, 2026: Repair scale-up, `strict-core-v7-repair`, and the first real turn

Artifacts:

- [reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_summary.json](../reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_summary.json)
- [reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_validation_summary.json](../reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_validation_summary.json)
- [reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_readiness.json](../reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_readiness.json)
- [reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_stage_a_summary.json](../reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_stage_a_summary.json)
- [reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_stage_b_lite_summary.json](../reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_stage_b_lite_summary.json)
- [reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stagea-lr1e6-ep3/summary.json](../reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stagea-lr1e6-ep3/summary.json)
- [reports/robustness/pearl-topoff1m-a-strict-core-v7-repair-stagea-smoke-p48-t08-s41s53s67/smoke_gate_decision.json](../reports/robustness/pearl-topoff1m-a-strict-core-v7-repair-stagea-smoke-p48-t08-s41s53s67/smoke_gate_decision.json)
- [reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stageb-lite-lr5e7-ep1/summary.json](../reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stageb-lite-lr5e7-ep1/summary.json)
- [reports/robustness/pearl-topoff1m-a-strict-core-v7-repair-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json](../reports/robustness/pearl-topoff1m-a-strict-core-v7-repair-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json)

What happened:

- the bounded repair scale-up worked
  - `96` parents
  - `28,030` evaluated variants
  - `1,071` survivors
  - `231` strict shortlist rows
  - `128` strict-bridge consensus rows
  - readiness passed with low concentration and broad parent-run support
- that made it possible to build `strict-core-v7-repair`
  - stage A used `160` pairs
  - repair stricts were included as a real training ingredient, not as a side audit
- stage A then passed the stricter `p48` smoke gate
  - hits by seed `[0, 2, 1]`
  - `3 / 48` prompts hit across seeds
  - this was the first branch in the current recipe family to clear the newer `2 seeds / 2 prompts` rule
- `stage-b-lite` then trained cleanly on `162` pairs

Why this mattered:

- this was the first end-to-end sign that repair-derived strict signal transfers into model behavior
- the old question was “is the repair lane real at all?”
- after this run, that question is settled enough to move on

What full robustness then said:

- `p12` died completely: `[0, 0, 0]`
- `p24` stayed narrow: `[0, 2, 0]`
- `p48` kept seed support but still lacked prompt breadth: `[0, 3, 1]` with only `4 / 48` prompts hit
- so the branch turned the corner, but it did not finish the job

Updated read after the full suite:

> Repair-derived strict data is now proven as a real retrain ingredient. The remaining failure mode is prompt coverage breadth, especially at smaller prompt budgets.

This is why the next branch should be coverage-focused `v8`, not another blind broad mining purchase and not another no-op micro-variant of the old strict recipe.

## April 2026: External Local-Optimization Lesson

An external constrained optimization exercise outside this repo materially changed the project read.

What that exercise showed:

- broad exploration can stop being the right move once a real basin exists
- a basin that looks exhausted can still have real headroom if the operator changes
- same-length substitution-only repair, role-aware mutation maps, and closure scans can outperform another broad search loop

What transferred back to PEARL:

- a “dead” branch can mean dead search policy, not dead basin
- local repair is a real lane worth considering
- but the PETase question is now different:
  - not “does local exploit matter?”
  - but “where do we source local neighborhoods from?”

The historical-corpus audit answered that question negatively for the current saved finalized surfaces:

- not from finalized hit representatives
- not from widened finalized-report winners

This is the current no-free-lunch result:

> There is no passive challenge-style local basin already sitting in the saved finalized corpus.

If a PETase local-repair lane exists, we will have to build it ourselves from:

- candidate-audit / lower-level near-miss material
- or deliberate perturbation generation around anchors

not harvest it from the already finalized surfaces.

## April 10-11, 2026: Candidate-Audit Local-Repair Pilot

After the negative finalized-corpus audit, we ran the first deliberate local-repair pilot against candidate-audit surfaces instead of finalized representatives.

Artifacts:

- [reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_summary.json](../reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_summary.json)
- [reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_validation_summary.json](../reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_validation_summary.json)
- [reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_readiness.json](../reports/repair/topoff1m-a-local-repair-pilot-20260410/repair_readiness.json)

What the pilot actually did:

- native repair on `48` parent hits
- `13,033` evaluated variants
- `577` repair survivors
- validation retained:
  - `192` strict shortlist rows
  - `122` strict-bridge consensus rows
  - `192` strict-family rows
  - `13` unique parent runs in the strict shortlist
- readiness passed:
  - `406` deduped tier-2 positives
  - `243` deduped tier-1 proxy positives
  - `228` clusters
  - `largest_cluster_share = 0.032`
  - `max_source_share = 0.1158`

What it means:

- the pessimistic read was too strong
- there is no passive local basin in the finalized representative surfaces
- but there is enough local structure in the candidate-audit layer to manufacture a retrain-ready strict pool

Important caveat:

- the pilot is promising, but not yet broad
- the retained strict set is concentrated:
  - top parent run contributed `36 / 192`
  - second parent run contributed `24 / 192`
- the whole validated strict set is still only `1`- or `2`-mutation repairs

So the lesson is:

> the lane exists, but the next question is concentration control, not whether local repair is real at all.

Updated action plan after the pilot:

1. run one bounded repair scale-up with explicit caps per parent run and source wave
2. require the scaled set to preserve low cluster share and low source concentration
3. if that passes, build one repair-augmented strict dataset and run one strict branch
4. only fall back to another broad million-candidate mining tranche if repair scale-up flattens or collapses into a few parent families

## April 2026: Historical Locality Audit

To test whether the broader historical mined universe already contained exploitable local neighborhoods, we added a config-driven analysis workflow and ran two passes.

Pass 1: finalized hit universe

- config:
  - [configs/experiments/analysis/petase_historical_local_exploit.json](../configs/experiments/analysis/petase_historical_local_exploit.json)
- result:
  - [reports/analysis/petase_historical_local_exploit/universe/universe_summary.json](../reports/analysis/petase_historical_local_exploit/universe/universe_summary.json)
  - [reports/analysis/petase_historical_local_exploit/neighborhoods/anchor_neighborhood_summary.json](../reports/analysis/petase_historical_local_exploit/neighborhoods/anchor_neighborhood_summary.json)
  - [reports/analysis/petase_historical_local_exploit/shortlist/local_exploit_shortlist_summary.json](../reports/analysis/petase_historical_local_exploit/shortlist/local_exploit_shortlist_summary.json)
- interpretation:
  - current canonical hit surfaces are too sparse for passive local exploitation

Pass 2: widened finalized-report near-miss universe

- config:
  - [configs/experiments/analysis/petase_historical_local_exploit_wide.json](../configs/experiments/analysis/petase_historical_local_exploit_wide.json)
- result:
  - [reports/analysis/petase_historical_local_exploit_wide/universe/report_universe_summary.json](../reports/analysis/petase_historical_local_exploit_wide/universe/report_universe_summary.json)
  - [reports/analysis/petase_historical_local_exploit_wide/neighborhoods/anchor_neighborhood_summary.json](../reports/analysis/petase_historical_local_exploit_wide/neighborhoods/anchor_neighborhood_summary.json)
  - [reports/analysis/petase_historical_local_exploit_wide/shortlist/local_exploit_shortlist_summary.json](../reports/analysis/petase_historical_local_exploit_wide/shortlist/local_exploit_shortlist_summary.json)
- interpretation:
  - widening the saved surface to screened finalized-report winners still did not produce local anchor families
  - the selected anchors had no whole-sequence neighbors even at `0.85`

This audit did reveal one real thing operationally:

- if we keep the analysis lane, the neighborhood builder needs a cheap prefilter before full Levenshtein so it does not waste time on impossible comparisons

More importantly, it gave a clear scientific bearing:

- the right next widening step is not “more finalization summaries”
- it is either:
  - lower-level candidate-audit material
  - or new deliberate perturbation generation

## March 24, 2026: Post-Wynton Nebius Pivot

Wynton mattered, but it is no longer the operational center of gravity.

What Wynton proved:

- the shard evaluator ran correctly on real CUDA hardware
- durable direct-to-storage outputs worked
- `qb3-iogpu*` and `qb3-atgpu*` were healthy pools
- `qb3-idgpu*` was not a healthy pool

Why the project moved on:

- Wynton queue latency became the main bottleneck once evaluator correctness was established
- Nebius made it possible to benchmark hardware classes directly and then buy the correct runtime instead of waiting for scheduler access

Nebius benchmark ladder summary:

- L40S baseline:
  - `0.364412 s/record`
  - `9878.93 records/hour`
- untuned H100:
  - `0.25474 s/record`
  - `14132.06 records/hour`
- untuned H200:
  - effectively tied with H100

Important engineering lesson:

- the GPU was not the real bottleneck
- the CPU-side family / novelty evaluator was
- once the evaluator was staged and parallelized, premium GPUs started to separate again

Final tuned runtime:

- `PREFILTER_EVAL_MODE=staged`
- `PREFILTER_CPU_WORKERS=8`
- `ESM2_BATCH_SIZE=256`
- `ESM2_SEQUENCE_BATCH_SIZE=1`
- `ESM2_PIPELINE_CHUNK_SIZE=128`

Final tuned benchmark results:

- H100 rerun:
  - `108.953s` for `1000` records
  - `33041.77 records/hour`
- H200 best:
  - `104.376s` for `1000` records
  - `34490.69 records/hour`

Operational conclusion:

- H200 is only about `4.4%` faster than H100 after tuning
- at the observed Nebius prices, preemptible H100 is the economic winner
- the project now has a clear path to a clean mined dataset without further architectural uncertainty

## Project Goal

Generate PETase/cutinase-like protein candidates that satisfy all of the following:

- single catalytic serine motif
- plausible catalytic geometry under the sequence-level evaluator
- high local ESM proxy score (`ESM >= 85`)
- strong family plausibility
- enough diversity to avoid trivial motif-spam collapse

The current workflow is:

1. sample candidates from a remote frontier model via Tinker
2. filter/rerank locally with a sequence-level family/geometry evaluator
3. score stability locally with an ESM-2 masked-LM proxy
4. use mined positives for short supervised warm-starts
5. only turn on RL after the bridge manifold is stable enough

## Core Terms

### Unicorn

A candidate is treated as a **unicorn** when it satisfies the practical bridge condition:

- `motif_count == 1`
- `geometry_passes == true`
- `esm_gate_pass == true`

In practice we also expect:

- `hard_gate_pass == true`

### Bridge

The **bridge** is the narrow intersection between:

- stable single-site protein-like generations
- and geometry-correct catalytic generations

Most failure modes in this project are different ways of missing that intersection.

### Catalytic Doping

**Catalytic Doping** is the current repair regime:

- start from high-ESM, single-motif, non-geometry candidates
- keep most of the backbone fixed
- relocate or repair catalytic windows only
- rescore for geometry + ESM

This is the current post-mining direction after broad sampling saturated.

## Repo Landmarks

- Public-facing project doc: [README.md](../README.md)
- Main loop: [main.py](../main.py)
- Family evaluator: [src/pearl/family.py](/Users/svdr/tinker/src/pearl/family.py)
- Local ESM proxy: [src/pearl/esm_proxy.py](/Users/svdr/tinker/src/pearl/esm_proxy.py)
- Ablation runner: [scripts/run_ablation.py](../scripts/run_ablation.py)
- Stratified mining runner: [scripts/run_kimi_zero_shot_stratified_search.py](../scripts/run_kimi_zero_shot_stratified_search.py)
- SFT warm-start runner: [scripts/run_sft_warmstart.py](../scripts/run_sft_warmstart.py)
- Detached launcher: [scripts/launch_detached_job.py](../scripts/launch_detached_job.py)
- Detached reseed launcher: [scripts/launch_reseed3_batch_detached.sh](../scripts/launch_reseed3_batch_detached.sh)
- Catalytic Doping builder: [scripts/build_catalytic_doping_candidates.py](../scripts/build_catalytic_doping_candidates.py)

## Chronology

### Phase 0: Bootstrap

Initial state:

- toy prompt loop
- missing `tinker` and `local_proxy` modules
- no real backend validation

Temporary compatibility shims were used only to prove the loop shape, then removed.

### Phase 1: Real Tinker Integration

We replaced the shim path with the real Tinker API flow and verified:

- remote sampling
- `forward_backward`
- `optim_step`
- remote checkpoint save

The early dry run proved the infrastructure, not the biology.

### Phase 2: Data Expansion

We built a real UniProt-derived dataset under [data/petase_family_expanded](../data/petase_family_expanded).

Important point:

- broad family data became abundant
- true high-value positives did not

This distinction remained central for the rest of the project.

### Phase 3: Evaluation Layer

We built a real evaluator around:

- validity
- entropy/diversity
- family serine motifs
- sequence-level catalytic geometry
- novelty
- ESM proxy gating

This let us stop guessing and start measuring exact failure modes.

### Phase 4: Qwen Branch

Key finding:

- Qwen could generate protein-like sequences
- but it struggled to produce the PETase-family bridge reliably

Observed failure modes:

- generic stable proteins with weak family signal
- motif-forced collapse into brittle low-trainability outputs
- repetitive scaffold spam
- geometry washout under RL continuation

Important positive result:

- short SFT warm-starts could restore full-length geometry-capable generation

Important negative result:

- reward shaping alone did not solve the missing grammar problem

Conclusion:

- Qwen validated the experimental stack
- but it was not the right long-term inner-loop model for this problem

### Phase 5: Kimi Pivot

We moved to `moonshotai/Kimi-K2.5` as a clean architecture branch.

Key reason:

- the bottleneck had become global positional planning under blueprint constraints
- that is where a stronger frontier MoE model had a chance to help

Zero-shot Kimi result:

- first branch to show raw `single_motif + geometry` mass

That was the decisive proof that the architecture pivot was justified.

### Phase 6: Kimi Mining

We ran aggressive zero-shot mining around `t = 0.85`.

Original successful sweep:

- Batch 1: `2` unicorns
- Batch 2: `0`
- Batch 3: `3`
- Batch 4: `0`
- total original: `5`

Reseed 3:

- Batch 1: `+1`
- Batch 2: `+2` by evidence, but full raw sequences later lost to an overwrite incident
- Batch 3: `+3`
- Batch 4: `+0`

Total unicorn evidence:

- `11`

Recoverable unicorn sequences on disk:

- `9`

Perfect wildtypes:

- `3`

Usable positives at the end of the main mining phase:

- `9 recoverable unicorns + 3 wildtypes = 12`

### Phase 7: Kimi Micro-SFT Experiments

#### Top-5 branch

Dataset:

- `3` perfect wildtypes
- `2` Kimi-native unicorns

Checkpoint:

- `tinker://587cd86e-7adb-54d3-b931-bca85c8ac57f:train:0/weights/kimi25-micro-sft-top5-lr1e6-ep2`

Key result:

- produced a real holdout bridge hit on the 12-prompt audit

This became the initial gold branch.

#### Top-12 direct from base

Dataset:

- `3` wildtypes
- `9` recoverable unicorns

Checkpoint:

- `tinker://ee1fed04-67bb-5965-99e1-7493f6e432f5:train:0/weights/kimi25-micro-sft-top12-lr1e6-ep2`

Result:

- more stable
- but lost the holdout bridge

#### Top-12 continuation from top-5

Checkpoint:

- `tinker://0ca0c340-2a8e-5c42-b316-fe8e075e36e0:train:0/weights/kimi25-micro-sft-top12-cont-from-top5-lr5e7-ep1`

Result:

- also lost the bridge
- even more conservative than the top-5 branch

Interpretation:

- adding more positives did not help by default
- the extra examples likely blurred the narrow Kimi-native bridge manifold

#### Top-9 unicorn-only

Dataset:

- `9` recoverable unicorns
- no wildtypes

Checkpoint:

- `tinker://e2872501-ad4f-5d06-bbab-9b8255839cc1:train:0/weights/kimi25-micro-sft-top9-unicorn-only-lr1e6-ep2`

12-prompt result:

- recovered a real bridge hit again
- selected hit:
  - `motif_count = 1`
  - `geometry_passes = true`
  - `esm_gate_pass = true`
  - `raw_esm_score = 99.56`

Important nuance:

- that hit had `has_family_serine_motif = false`

Interpretation:

- removing wildtypes likely helped preserve the bridge
- but the branch still needed larger-scale validation

### Phase 8: 48-Prompt Validation of Unicorn-Only Branch

We scaled the unicorn-only branch to a `48`-prompt eval-only sweep using 4 parallel 12-prompt shards.

Aggregate result:

- `6144` candidates
- `2048` single-motif candidates
- `68` single-motif + ESM-pass candidates
- `57` single-motif + geometry candidates
- `0` single-motif + geometry + ESM candidates

Interpretation:

- the bridge manifold is still present
- but it is too fragile at larger evaluation scale
- broad validation on this branch did not support immediate RL

This was the point where broad mining stopped looking attractive.

## What We Learned

### 1. The bridge is real

We have repeatedly seen:

- zero-shot Kimi unicorns
- a small Kimi-native micro-SFT transferring the bridge at least once

So the bridge is not imaginary.

### 2. The bridge is fragile

Repeated `12`-prompt audits and the `48`-prompt validation showed:

- the intersection is real
- but sparse and unstable

### 3. Broad “better data” can be worse

More positives did not automatically help.

The likely failure mode:

- extra positives pulled the model toward a safer stable/family manifold
- but away from the narrow bridge manifold

### 4. Wildtypes are not automatically helpful

The unicorn-only branch strongly suggests the wildtypes were at least partly washing out the Kimi-native bridge.

### 5. Broad mining has diminishing returns

By the end of the 48-prompt eval, we had many:

- stable single-site candidates
- geometry-positive candidates

But still failed to close the intersection robustly.

That is why the project is pivoting toward constrained repair.

## Bugs, Failures, and Fixes

### Missing modules bootstrap

Problem:

- initial script did not run due to missing `tinker` / `local_proxy`

Resolution:

- temporary shim for loop validation only
- later replaced with real backend integration

### Validation leak

Problem:

- an early “validation” path was still performing training steps

Resolution:

- explicit `eval_only` support added
- holdout interpretation corrected

### API / SDK drift

Problem:

- old Tinker SDK version stopped being accepted by the backend

Resolution:

- active environment updated to supported SDK

### Duplicate batch overwrite incident

Problem:

- a stale Batch 2 relaunch reused the same output path
- final `candidate_audit.json` got overwritten

What survived:

- counts and step-level evidence

What was lost:

- exact full sequences of the two Batch 2 unicorns

Fixes:

- duplicate-run guards added to [run_reseed3_batch.sh](/Users/svdr/tinker/scripts/run_reseed3_batch.sh)
- relaunch blocked if `summary.json` exists
- relaunch blocked if matching run name is already active

### Partial-run data loss

Problem:

- interrupted runs used to lose everything if they had not finished

Fix:

- [main.py](/Users/svdr/tinker/main.py) now writes partial `report.json` and `candidate_audit.json` after every completed prompt using atomic replace

### Flaky background jobs

Problem:

- shell-backgrounded jobs often died before `main.py` actually entered the loop

Root cause:

- inherited fragile session/stdin/stdout state from short-lived parent shells

Fix:

- added [launch_detached_job.py](/Users/svdr/tinker/scripts/launch_detached_job.py)
- added [launch_reseed3_batch_detached.sh](/Users/svdr/tinker/scripts/launch_reseed3_batch_detached.sh)
- detached jobs now get:
  - new session
  - closed stdin
  - direct log files
  - metadata files with PID/command/cwd

### MLX investigation

Question:

- can the local ESM masked-LM proxy be ported to MLX?

Result:

- MLX is installed
- no ready MLX-native masked ESM path was found
- current safe production path remains torch + MPS

Artifacts:

- [probe_mlx_esm_backend.py](/Users/svdr/tinker/scripts/probe_mlx_esm_backend.py)

## State Snapshot (after Phase 8, before March 3, 2026)

Best checkpoint for bridge preservation at this snapshot:

- `tinker://e2872501-ad4f-5d06-bbab-9b8255839cc1:train:0/weights/kimi25-micro-sft-top9-unicorn-only-lr1e6-ep2`

But:

- the `48`-prompt eval said it is not robust enough for RL yet

So the project was **not RL-ready** at this snapshot.

However:

- the bridge exists
- the model can produce high-ESM stable candidates in volume
- and we now have a cleaner understanding of the failure mode

New state after the first Catalytic Doping pilot:

- the relocation-aware repair pass succeeded
- it produced `220` repaired `geometry + ESM` survivors from `55` stable parents
- those survivors are not `220` independent scaffolds, but they are strong enough to justify a repair-derived SFT branch

Primary artifacts:

- analysis note:
  - [kimi_catalytic_doping_val48_reloc_v1_analysis.md](/Users/svdr/tinker/reports/analysis/kimi_catalytic_doping_val48_reloc_v1_analysis.md)
- survivor pool:
  - [kimi_catalytic_doping_survivors_val48_reloc_v1.jsonl](/Users/svdr/tinker/data/petase_family_expanded/kimi_catalytic_doping_survivors_val48_reloc_v1.jsonl)
- run summary:
  - [kimi_catalytic_doping_val48_reloc_v1_summary.json](/Users/svdr/tinker/data/petase_family_expanded/kimi_catalytic_doping_val48_reloc_v1_summary.json)

## Why Catalytic Doping Exists

The `48`-prompt eval gave the clearest diagnosis yet:

- many high-ESM single-motif candidates
- many geometry-positive candidates
- zero candidates in the intersection

That means the next search problem is no longer:

- “sample more from scratch”

It is:

- “take the stable side and graft/repair the catalytic geometry into it”

Catalytic Doping is our name for that regime.

## Catalytic Doping: Definition

Current intended regime:

1. harvest stable backbones:
   - `motif_count == 1`
   - high `ESM`
   - preferably family-positive
   - not already geometry-positive
2. infer or use a blueprint
3. if needed, neutralize the existing serine motif
4. relocate a family-like serine motif toward the catalytic window
5. place D/H around blueprint and gap anchors
6. rescore for:
   - `motif_count == 1`
   - geometry
   - `ESM >= 85`
7. use surviving repaired candidates as cleaner positives

Current implementation path:

- [build_catalytic_doping_candidates.py](/Users/svdr/tinker/scripts/build_catalytic_doping_candidates.py)

## Short-Term Next Steps

1. Downselect the `220` Catalytic Doping survivors to a compact, diverse training set.
2. Keep at most `1-2` repaired variants per parent prompt-step and prefer scaffold diversity over raw count.
3. Run a small repair-derived SFT branch from the current best Kimi checkpoint.
4. Re-evaluate on the `12`-prompt holdout first, then scale to `24` prompts if the bridge survives.
5. Only revisit RL when the repaired branch holds up at larger eval scale.

### Strict Tier-1 Doping Failure

We explicitly tried the hard-canonical version next:

- only canonical graft motifs: `GYSLG`, `GYSQG`
- only parent backbones with `has_family_serine_motif = true`
- low-LR continuation from the best `top9` checkpoint

Result:

- [summary.json](/Users/svdr/tinker/reports/ablations/kimi25-micro-sft-top9-plus-doping24strict-cont-lr5e7-ep1-val12-t08-c128/summary.json)
- `functional_bridge_rate = 0.0`
- `family_faithful_bridge_rate = 0.0`

Interpretation:

- strict biology pressure successfully increased family-looking stable outputs
- but it over-constrained the model and killed the bridge entirely
- the best geometry attempts under this branch were unstable or multi-motif

This is an important negative result:

- **hard Tier 1 supervision collapses the physics**

### Soft Doping Pivot

The next repair-derived curriculum should be softer:

- majority Tier 2 anchors from the loose doping shortlist
- minority Tier 1 pull from canonical purebreds and strict repaired examples

This keeps the spatial/ESM manifold alive while applying a gentler family-faithful pull instead of a hard wall.

### Soft Doping Failure

We ran the soft-doping curriculum from:

- `tinker://fc8cb9c3-0d7f-518d-9668-977fcafef21f:train:0/weights/kimi25-micro-sft-top9-soft-doping41-cont-lr5e7-ep1`

on the standard `12`-prompt holdout, sharded into four `3`-prompt runs for speed.

Final result:

- Tier 2 functional bridge: `0 / 12`
- Tier 1 family-faithful bridge: `0 / 12`

Pattern:

- some shards produced geometry without enough ESM
- other shards produced strong stable single-site outputs without geometry
- the soft curriculum did not preserve the Tier 2 bridge

Interpretation:

- SFT appears exhausted for this problem family
- the model treats our synthetic repairs as conflicting local optima rather than a clean path to the intersection
- further SFT-only mixing is more likely to confuse the latent backbone grammar than to recover Tier 1

### RL Pivot

The current reference policy for RL is:

- `tinker://7a5aeb3f-0652-52d1-849d-9916dfb43c7c:train:0/weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1`

Reason:

- it is the only branch that held a Tier 2 functional bridge at larger (`24`-prompt) holdout scale
- it still does not produce Tier 1 family-faithful bridges
- but it gives us a real, non-zero gradient to optimize

Planned PPO pilot reward ladder:

- `0` if `ESM < 85` or no catalytic geometry
- `1` for Tier 2 (`motif_count == 1` + geometry + `ESM >= 85`)
- `6` for Tier 1 (Tier 2 + `has_family_serine_motif = true`)

Operational stance:

- short pilot only (`20-30` steps)
- very low learning rate
- large rollout batch
- no full RL campaign until the pilot shows the bridge can be strengthened without collapsing the policy

### PPO Pilot Outcome

The PPO pilot was operationally stable but scientifically starved.

Artifacts:

- [/Users/svdr/tinker/reports/rl_pilot/kimi25-ppo-tier-bridge-pilot20-c2048-lr1e6/report.json](/Users/svdr/tinker/reports/rl_pilot/kimi25-ppo-tier-bridge-pilot20-c2048-lr1e6/report.json)
- [/Users/svdr/tinker/reports/rl_pilot/kimi25-ppo-tier-bridge-pilot20-c2048-lr1e6/candidate_audit.json](/Users/svdr/tinker/reports/rl_pilot/kimi25-ppo-tier-bridge-pilot20-c2048-lr1e6/candidate_audit.json)

Observed:

- `3 / 20` steps completed before termination
- `0` Tier 2 hits
- `0` Tier 1 hits
- each step produced `31-41` geometry-positive candidates out of `2048`
- selected samples repeatedly hit geometry, and one even hit family-faithful geometry, but all had `ESM` in the `20s-30s`

Interpretation:

- PPO was not failing because of infrastructure
- PPO was failing because the reward landscape was too sparse
- the model had learned a "spaghetti" regime: satisfy geometry cheaply without producing a foldable backbone

Decision:

- terminate PPO
- keep the hard `ESM >= 85` floor
- pivot to RAFT / Expert Iteration

## RAFT Pivot

Reference policy:

- `tinker://7a5aeb3f-0652-52d1-849d-9916dfb43c7c:train:0/weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1`

Phase 1 plan:

1. generate `30k-50k` candidates offline from the reference policy
2. score locally with the existing geometry and ESM filters
3. keep only Tier 2 / Tier 1 successes
4. run a tiny success-only SFT to ratchet the generator forward

Operational note:

- detached launches now use [/Users/svdr/tinker/scripts/launch_detached_job.py](/Users/svdr/tinker/scripts/launch_detached_job.py)
- job metadata redacts API-like secrets

## Longer-Term Validation Path

If the bridge becomes robust enough:

1. short RL pilot
2. larger eval-only sweep
3. shortlist generation
4. AlphaFold / structural triage on shortlist
5. possibly wet-lab work if the computational stack justifies it

## Notes for New Collaborators

If you are new to this repo, do not start by changing RL.

Do this first:

1. read [README.md](/Users/svdr/tinker/README.md)
2. read this file
3. inspect:
   - [main.py](/Users/svdr/tinker/main.py)
   - [src/pearl/family.py](/Users/svdr/tinker/src/pearl/family.py)
   - [src/pearl/esm_proxy.py](/Users/svdr/tinker/src/pearl/esm_proxy.py)
4. understand the unicorn definition
5. understand the bridge failure mode
6. do not reuse output paths for new experiments
7. prefer detached launcher or foreground execution over shell backgrounding

## Bottom Line

PEARL is not in a failure state. It is in a narrow-manifold state.

The project has already answered several major questions:

- does the bridge exist? yes
- can Kimi hit it? yes
- does naive scaling of the positive set solve it? no
- is the broad eval robust enough yet? no
- is constrained catalytic repair the right next move? yes

That is where we are.

## Funding And Platform Constraint

This project is currently being developed under a `USD 5,000` grant / credit from Thinking Machines.

That funding is constrained to the Thinking Machines platform, so the core generation / training work is forced onto Tinker rather than being freely portable to another provider or local training stack.

Practical implication:

- remote model generation and training flow happen through Tinker
- local work is mainly evaluation, scoring, filtering, and experiment orchestration
- when iteration speed becomes poor, part of that bottleneck is simply the platform constraint rather than a mistake in the local code

This matters for interpreting the project timeline and engineering decisions. Several choices that might be simpler off-platform are currently not available because the grant has to be spent inside Tinker.

## Status Snapshot (March 3, 2026)

As of March 3, 2026:

- all active PEARL processes are stopped
- best current reference policy is still:
  - `tinker://7a5aeb3f-0652-52d1-849d-9916dfb43c7c:train:0/weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1`
- Tier 2 functional bridge exists, but only weakly
- Tier 1 family-faithful bridge is still absent

Recovered positive data:

- `11` unicorns by evidence
- only `9` recoverable unicorn sequences on disk
- `3` wildtypes
- effective reusable positive pool for SFT was therefore `12`, not `14`

Branch results:

- `top5` micro-SFT:
  - weak but real Tier 2 bridge
- `top12` and continuation:
  - worse than `top5`
- `top9 unicorn-only`:
  - recovered the weak bridge
- loose mixed doping:
  - best practical branch
  - held Tier 2 at `24`-prompt scale, but still no Tier 1
- strict canonical-only doping:
  - killed the bridge
- soft-doping curriculum:
  - killed the bridge

Current interpretation:

- SFT has mostly exhausted its useful easy wins
- adding more synthetic positives without extreme care tends to blur or kill the bridge
- the model repeatedly finds:
  - geometry without enough fold stability
  - or strong fold stability without the right geometry

## PPO Outcome

The PPO pilot is now a closed negative result.

Summary:

- operationally stable
- scientifically starved
- geometry appeared repeatedly
- one selected sample even hit family-faithful geometry
- but all selected geometry-positive samples had very poor `ESM` and received reward `0`

Interpretation:

- PPO was not failing because of crashes or wrapper bugs
- PPO was failing because the reward was too sparse for online optimization on this landscape
- the model entered a "spaghetti" regime: easy geometry, no foldable backbone

Decision:

- PPO is not the current path forward
- do not resume it without a fundamentally different reward regime or much denser success rate

## RAFT / Expert Iteration Snapshot (March 3, 2026)

RAFT remains the correct conceptual direction, but the first implementation pass exposed a throughput problem.

What happened:

- broad detached RAFT wave launched successfully
- detached process supervision worked
- but the current `run_ablation.py -> main.py` path was too slow in the first-prompt stage to be operationally useful at the intended scale
- even after reducing concurrency and shrinking to a `10`-prompt proof run, the first prompt still took too long to make this shape of mining practical

Interpretation:

- RAFT as an idea is still alive
- current RAFT execution path is too slow
- before more large-scale RAFT mining, the mining implementation needs to be reshaped so we can get through prompt `0` in sane time

## Practical Assessment

The project is:

- not hopeless
- not solved
- not RL-ready
- not ready for AlphaFold-scale downstream validation
- still worth pursuing

The most accurate one-line summary is:

- the bridge is real, but fragile

The current bottleneck is not whether Kimi can ever hit the right manifold.
The bottleneck is whether we can make the search / optimization loop reach that manifold reliably and cheaply enough to iterate.

## March 4, 2026 Engineering Update

This section records the engineering cleanup and throughput investigation done after the March 3 snapshot.

### Repo / code hygiene

Before more experiments, the repo was cleaned up enough to reduce operational confusion:

- `LABNOTES.md` moved under `notes/`
- scratch timing scripts moved under `benchmarks/`
- stray local report artifacts moved under `reports/legacy/`
- hot-path code had a cleanup pass:
  - named constants replaced scattered magic numbers
  - duplicated reward / bridge bookkeeping was factored into shared helpers
  - local proxy parsing was simplified

This did not change the scientific state, but it made the runtime path easier to inspect and modify.

### Local evaluator optimizations

The local PETase-family evaluator got several real optimizations:

- cached reference k-mers in memory instead of rebuilding them on every candidate evaluation
- removed wasteful set-union allocation in Jaccard scoring
- switched novelty shortlist selection from full sort to a bounded top-k path
- skipped full novelty scoring for obvious cheap rejects
- kept the tandem-repeat micro-optimization, but confirmed it is minor

Interpretation:

- these changes were worth keeping
- they reduced local stage-1 cost materially
- they did not solve the full prompt-level throughput problem by themselves

### Prompt-0 timing instrumentation

`main.py` was instrumented with explicit timing markers around:

- service client startup
- base model resolution
- training client creation
- tokenizer loading
- prompt loading
- reference loading / family stats
- sampler preparation
- remote sampling
- stage-1 local evaluation
- stage-2 ESM scoring

The first full measured one-prompt eval-only benchmark at `256` candidates showed:

- startup total: `34.8s`
- `create_training_client`: `32.2s`
- `save_weights_and_get_sampling_client`: `6.2s`
- remote sampling: `32.7s`
- stage-1 local evaluation: `11.9s`
- stage-2 ESM scoring: `22.6s`
- total wall clock: `112.8s`

Main conclusion:

- the dominant bottleneck was no longer the old Python novelty path
- the real cost center was remote Tinker startup / sampling, with local ESM second and local stage-1 third

### Reuse / prewarm pass

Two immediate runtime changes were added:

- explicit ESM prewarm so model-load cost is visible at startup
- sampling-client reuse across prompts when weights have not changed

On a `2`-prompt, `64`-candidate eval-only timing run:

- step `1` reused the sampling client with effectively `0s` client-prep cost
- startup included explicit `ESM` prewarm
- this cleaned up repeated per-step overhead, but the main remaining cost was still remote sampling

Conclusion:

- reuse is worth keeping
- prewarm is worth keeping
- neither changes the fundamental fact that remote generation dominates end-to-end time once local scoring is no longer pathological

### Tinker SDK investigation

The SDK was read directly to answer whether the training startup cost was avoidable.

Important findings:

- `ServiceClient()` creates a fresh Tinker session with heartbeat
- `create_training_client_from_state(...)` is expensive by design:
  - fetch weights info
  - create a new LoRA training run
  - load the checkpoint into that run
- `save_weights_and_get_sampling_client()` is also expensive by design, but it is still the natural training-loop path
- there is no clean public API to reattach to an old training client across separate program runs
- there is a clean public direct sampling path for sampler checkpoints:
  - `create_sampling_client(model_path=...)`

That created a clear split:

- eval-only should avoid the training client whenever possible
- actual training runs still need the existing training-client path

### Eval-only sampler resolution

An eval-only fast path was then added:

- if `INIT_STATE_PATH` is already a sampler checkpoint, use it directly
- if a known derived sampler checkpoint exists locally, use it directly
- if the input is only a training checkpoint, resolve or create a matching sampler checkpoint once, then reuse it on future evals

Important SDK caveat discovered during this work:

- Tinker does not let `create_sampling_client(model_path=...)` load a normal `weights` checkpoint
- it requires a `sampler_weights` checkpoint
- also, saving sampler weights from a loaded training checkpoint creates a new sampler checkpoint under a new training run id, not under the original run id

That means naive string replacement from:

- `/weights/...`

to:

- `/sampler_weights/...`

is not enough.

To close that loop, a local mapping file was introduced:

- `.tinker_sampler_checkpoint_map.json`

This stores:

- source training checkpoint path
- resolved derived sampler checkpoint path

and future eval-only runs validate and reuse that sampler path directly.

### Concrete result

For the current reference policy:

- source training checkpoint:
  - `tinker://7a5aeb3f-0652-52d1-849d-9916dfb43c7c:train:0/weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1`
- derived sampler checkpoint:
  - `tinker://29d6d1c5-cf40-5404-9af1-3755d95bd6ed:train:0/sampler_weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1`

Once that mapping existed, a follow-up eval-only benchmark using the mapped sampler path showed:

- startup total: `3.6s`
- no training-client creation
- no sampler-refresh step
- total wall clock on a small `1`-prompt, `8`-candidate run: `31.8s`

Interpretation:

- the eval-only loose end is now actually closed
- future eval / ablation / detached mining runs should reuse sampler checkpoints rather than repeatedly paying the training-client startup tax

### Operational Recommendation Snapshot (March 4, 2026)

At this point the engineering recommendation is:

- for eval-only:
  - use resolved sampler checkpoints and keep the local sampler mapping
- for real training:
  - keep `save_weights_and_get_sampling_client()` as the prompt-loop path
- do not spend more time trying to replace the training-loop sampler refresh with `save_weights_for_sampler(...) + create_sampling_client(...)` unless there is a specific need to verify it experimentally

Reason:

- for training mode, both approaches still pay the save-for-sampler cost
- the named-checkpoint path likely adds extra session creation overhead rather than removing it
- the high-value win was in eval-only reuse, and that win has now been captured

## March 5, 2026 Robustness Cycle Update (Repair17)

This section captures the full `repair16 -> repair17` durability cycle and the final outcome.

### Script and workflow changes

1. Robustness summary ingestion hardening:
   - [run_robustness_suite.py](/Users/svdr/tinker/scripts/run_robustness_suite.py) now resolves existing ablation runs by metadata (`prompt_count`, `seed`, `init_state_path`, `model`, `variant`) instead of relying only on exact run-name directory matches.
   - It now tolerates equivalent temperature naming tokens (`t08` vs `t0p8`) when mapping completed runs.
   - This removed the manual-summary fallback needed in the previous cycle.
2. Repair-pool export cleanup:
   - [build_repair_pool_dataset.py](/Users/svdr/tinker/scripts/build_repair_pool_dataset.py) now supports `--output-audit-path`.
   - It can emit a merged `candidate_audit.json` directly from selected repair-pool rows, making repair waves reproducible from one command.
3. Existing native-repair script remained in active use:
   - [build_kimi_native_repair_dataset.py](/Users/svdr/tinker/scripts/build_kimi_native_repair_dataset.py)

### Repair17 cycle artifacts

Repair pool build (selected candidates only, deduped):

- output pool:
  - [/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_pool_selected.jsonl](/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_pool_selected.jsonl)
- merged audit for repair script input:
  - [/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_pool_selected_audit.json](/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_pool_selected_audit.json)
- summary:
  - [/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_pool_selected_summary.json](/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_pool_selected_summary.json)

Pool composition:

- `37` total rows
- `5` `tier2_hit`
- `32` `geometry_dominant_near_miss`
- sourced from `12` prior repair15/repair16 robustness audits

### Repair wave outcome

Bounded repair wave (`max_hits=16`, `rounds=1`, `radius=2`, `top_residues_per_position=2`, `beam_size=3`):

- survivors:
  - [/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_survivors_wave1.jsonl](/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_survivors_wave1.jsonl)
- best attempts:
  - [/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_best_attempts_wave1.jsonl](/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_best_attempts_wave1.jsonl)
- summary:
  - [/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_summary_wave1.json](/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_summary_wave1.json)

Result:

- `evaluated_variant_count = 186`
- `survivor_count = 15`

### Repair17 warm-start

Trained a one-epoch micro-SFT continuation from repair16 using the `15` repaired survivors.

- checkpoint:
  - `tinker://a3a29303-c696-574b-adbc-a9180c43aaa4:train:0/weights/pearl-micro-sft-repair17-from-repair16-wave1-lr5e7-ep1`
- summary:
  - [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-repair17-from-repair16-wave1-lr5e7-ep1/summary.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-repair17-from-repair16-wave1-lr5e7-ep1/summary.json)

### Repair17 durability check (`12` prompts, `t=0.8`, seeds `41/53/67`)

Run outputs:

- [/Users/svdr/tinker/reports/ablations/pearl-repair17-robustness-p12-t08-r1-p12-t0p8-s41/summary.json](/Users/svdr/tinker/reports/ablations/pearl-repair17-robustness-p12-t08-r1-p12-t0p8-s41/summary.json)
- [/Users/svdr/tinker/reports/ablations/pearl-repair17-robustness-p12-t08-r1-p12-t0p8-s53/summary.json](/Users/svdr/tinker/reports/ablations/pearl-repair17-robustness-p12-t08-r1-p12-t0p8-s53/summary.json)
- [/Users/svdr/tinker/reports/ablations/pearl-repair17-robustness-p12-t08-r1-p12-t0p8-s67/summary.json](/Users/svdr/tinker/reports/ablations/pearl-repair17-robustness-p12-t08-r1-p12-t0p8-s67/summary.json)

Robustness suite summary:

- [/Users/svdr/tinker/reports/robustness/pearl-repair17-robustness-p12-t08-r1/robustness_summary.json](/Users/svdr/tinker/reports/robustness/pearl-repair17-robustness-p12-t08-r1/robustness_summary.json)

Final vector and gate:

- `tier2_hits_by_seed = [0, 1, 0]`
- `prompt_coverage_by_seed = [0, 1, 0]`
- `bridge_hits_per_prompt.mean = 0.027778`
- `prompts_with_any_tier2_across_seeds = 1`
- durability gate: `FAILED`

Failed gate conditions:

- `seed_support`
- `prompt_coverage`
- `basin_pressure_vs_baseline`

### Comparison vs repair16

Repair17 did not increase durable bridge production:

- bridge vector remained `repair16: [0,1,0] -> repair17: [0,1,0]`
- bridge mean unchanged (`0.027778`)
- basin mix shifted:
  - stability-dominant mean worsened (`0.25 -> 0.277778`)
  - geometry-dominant mean improved (`0.25 -> 0.222222`)

Interpretation:

- this was a sideways move on the core target
- the branch remains in **search/repair mode**
- it is still not freeze-worthy as the canonical reference policy

## March 5, 2026 Wave3 Diversity + Repair20 Update

This section records the readiness hardening pass and the resulting `repair20` warm-start.

### What changed in code/workflow

1. Diversity-capped repair pool builder:
   - added [build_diversity_capped_repair_pool.py](/Users/svdr/tinker/scripts/build_diversity_capped_repair_pool.py)
   - supports caps by source run and identity cluster to avoid gradient domination by near-duplicates.
2. Repair lineage propagation:
   - updated [build_kimi_native_repair_dataset.py](/Users/svdr/tinker/scripts/build_kimi_native_repair_dataset.py)
   - survivors now carry parent-source lineage fields (`source_parent_run`, `source_parent_audit_path`).
3. Readiness attribution fix:
   - added [check_repair_survivor_readiness.py](/Users/svdr/tinker/scripts/check_repair_survivor_readiness.py)
   - source-share can now be computed from embedded lineage (or parent pool mapping) instead of collapsing survivors into one synthetic source.

### Wave3 repair pool and repair run

Built a multirun pool from `12` repair18 robustness audits:

- merged pool:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_multirun.jsonl](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_multirun.jsonl)
- merged summary:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_multirun_summary.json](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_multirun_summary.json)

Pool composition:

- `59` total (`8` tier2 + `51` geometry-dominant)

Diversity capping output:

- capped pool:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_diversity_capped.jsonl](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_diversity_capped.jsonl)
- capped audit:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_diversity_capped_audit.json](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_diversity_capped_audit.json)
- selected after capping: `34`

Repair wave output:

- summary:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_summary_wave3_diversity.json](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_summary_wave3_diversity.json)
- survivors:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_survivors_wave3_diversity.jsonl](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_survivors_wave3_diversity.jsonl)
- lineage-enriched survivors:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_survivors_wave3_diversity_lineage.jsonl](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_survivors_wave3_diversity_lineage.jsonl)

Wave3 repair result:

- `evaluated_variant_count = 1370`
- `survivor_count = 32`

### Retrain readiness (lineage-aware)

Readiness artifacts:

- [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_wave3_diversity_readiness_lineage_embedded.json](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_wave3_diversity_readiness_lineage_embedded.json)

Gate result:

- `ready_for_retrain = true`
- checks: `7 / 7 passed`

Key counts:

- `deduped_tier2_count = 40`
- `deduped_tier1_proxy_count = 34`
- `cluster_count = 8`
- `largest_cluster_share = 0.125`
- `max_source_share = 0.25`
- `train_tier2_count = 32`
- `train_tier1_proxy_count = 26`

### Repair20 warm-start

Started one-epoch micro-SFT from repair18 using the `32` lineage-enriched wave3 survivors.

- summary:
  - [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-repair20-from-wave3-lineage-lr5e7-ep1/summary.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-repair20-from-wave3-lineage-lr5e7-ep1/summary.json)
- full report:
  - [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-repair20-from-wave3-lineage-lr5e7-ep1/report.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-repair20-from-wave3-lineage-lr5e7-ep1/report.json)

Checkpoint produced:

- `tinker://6c7881f9-0330-5a3b-8acf-f2a44a7cbf70:train:0/weights/pearl-micro-sft-repair20-from-wave3-lineage-lr5e7-ep1`

Interpretation:

- readiness hardline is now actually met (not just near-miss),
- lineage/source-share accounting is fixed,
- branch is ready for post-retrain durability confirmation (`12 -> 24 -> 48`, fixed seeds).

## March 7-8, 2026 Pivot Update: Wynton + Budget Burn + Local Prefilter

This section captures the major operational pivot away from local full-eval loops and into:

1. budget-capped raw generation now,
2. heavy scoring/optimization on Wynton GPU later,
3. new local prefiltering so HPC time is not wasted on obvious junk.

### Strategic pivot and budget policy

- Wynton HPC was designated as the target runtime for heavy ESM/geometry and training loops.
- Local machine was repurposed for high-volume Tinker raw generation and preprocessing only.
- Spend policy changed to:
  - burn approximately `USD 1,000` for raw candidate stockpile,
  - allow controlled overrun to hit practical round-number data targets,
  - keep the majority of remaining grant for cluster-side LoRA/RAFT work.

Planning artifact:

- [/Users/svdr/tinker/notes/WYNTON_PIVOT_CHECKLIST.md](/Users/svdr/tinker/notes/WYNTON_PIVOT_CHECKLIST.md)

### Raw-generation campaign summary

Main cohorts launched:

1. `kimi25-raw-10x100-20260307-002408-r01..r10`
2. `kimi25-raw-plus10x50-20260307-012712-r11..r20`
3. top-off cohort for 1M push:
   - `kimi25-topoff1m-20260308-010724-r01..r20`
   - per-run cap `USD 21`, `samples_per_request=64`, `compress=false`

As of `2026-03-08T05:01:36Z`:

- top-off cohort (`20` runs):
  - spend: `USD 281.177182`
  - raw candidates: `229,696`
  - output tokens: `61,721,314`
  - requests: `3,589`
  - runner health snapshot: `20 active`, `0 stalled`, `0 capped`
- all raw-generation progress files combined (`44` runs):
  - spend: `USD 1,292.923572`
  - raw candidates: `1,053,033`
  - output tokens: `283,933,432`

### Data-integrity incident and recovery

A corruption/recovery pass was run on the initial 20-run campaign outputs.

Artifact:

- [/Users/svdr/tinker/reports/raw_generation/recovery_audit_20260307/damage_report.json](/Users/svdr/tinker/reports/raw_generation/recovery_audit_20260307/damage_report.json)

Reported totals (`generated_at_utc = 2026-03-07T17:17:37Z`):

- `expected_candidates = 498,944`
- `recovered_candidates = 494,190`
- `damage_candidates = 4,754`
- `recovery_rate = 0.99047188`
- `aggregate_json_parse_or_schema_errors_seen = 30`

Interpretation:

- the majority of data survived,
- corruption pressure was real enough to justify hardened supervision and salvage-aware ingest.

### Supervision hardening for long local runs

The watchdog path was hardened to reduce bad restarts and preserve run semantics:

- [/Users/svdr/tinker/reports/raw_generation/watchdog_supervisor.py](/Users/svdr/tinker/reports/raw_generation/watchdog_supervisor.py)

Key operational hardening points:

1. run-pattern override via `WATCHDOG_RUN_PATTERNS`.
2. dynamic stale thresholds tied to observed request latency (`STALE_LATENCY_MULTIPLIER`) with minimum floors.
3. restart command preserves key run config flags (`compress`, max-* limits, budget flags).
4. avoids unnecessary restart behavior when runs are already complete/capped.
5. integrated with local `caffeinate` use during overnight generation.

### Local prefilter suite implemented (pre-HPC triage)

To avoid burning Wynton cycles on obvious failures, a local staged prefilter pipeline was implemented:

- core pipeline:
  - [/Users/svdr/tinker/scripts/prefilter_local.py](/Users/svdr/tinker/scripts/prefilter_local.py)
- rules config:
  - [/Users/svdr/tinker/configs/prefilter/local_prefilter_v1.yaml](/Users/svdr/tinker/configs/prefilter/local_prefilter_v1.yaml)
- run-to-run uniqueness comparator:
  - [/Users/svdr/tinker/scripts/snapshot_prefilter_uniqueness.py](/Users/svdr/tinker/scripts/snapshot_prefilter_uniqueness.py)
- fixture + regression smoke:
  - [/Users/svdr/tinker/benchmarks/prefilter_smoke_fixture/raw_samples_fixture.jsonl](/Users/svdr/tinker/benchmarks/prefilter_smoke_fixture/raw_samples_fixture.jsonl)
  - [/Users/svdr/tinker/scripts/check_prefilter_smoke.py](/Users/svdr/tinker/scripts/check_prefilter_smoke.py)

Pipeline stages:

1. `ingest` (parse + salvage),
2. `canonicalize`,
3. `hard-filter`,
4. `exact-dedup`,
5. `near-dedup`,
6. `priority`,
7. `handoff`.

Validation status:

- `check_prefilter_smoke.py` passed.
- production sanity run on `5,000` real records passed end-to-end:
  - hard-filter pass/reject: `4520 / 480`
  - exact dedup unique/dup: `3766 / 754`
  - near-dedup selected/members: `3762 / 4`
  - handoff ready counts: `A=3757`, `B=5`

Important nuance:

- with no novelty reference set, priority naturally collapses toward mostly `A` tier.
- meaningful `A/B/C` stratification requires providing historical reference inputs to `--reference-jsonl`.

### Trigger command at 1M milestone

When the raw-generation target is reached and writes are stable/paused, run:

```bash
python /Users/svdr/tinker/scripts/prefilter_local.py all \
  --inputs /Users/svdr/tinker/reports/raw_generation \
  --out-root /Users/svdr/tinker/reports/prefilter/topoff_1m_run
```

This produces staged outputs plus `summary.json` and scheduler-ready handoff JSONLs for HPC.

### Prefilter execution snapshot (March 8, 2026)

The full local prefilter pipeline was executed against the assembled raw-generation corpus:

- command:
  - `python /Users/svdr/tinker/scripts/prefilter_local.py all --inputs /Users/svdr/tinker/reports/raw_generation --out-root /Users/svdr/tinker/reports/prefilter/topoff_1m_run`
- output root:
  - [/Users/svdr/tinker/reports/prefilter/topoff_1m_run](/Users/svdr/tinker/reports/prefilter/topoff_1m_run)
- summary artifact:
  - [/Users/svdr/tinker/reports/prefilter/topoff_1m_run/summary.json](/Users/svdr/tinker/reports/prefilter/topoff_1m_run/summary.json)
- handoff manifest:
  - [/Users/svdr/tinker/reports/prefilter/topoff_1m_run/handoff/manifest.json](/Users/svdr/tinker/reports/prefilter/topoff_1m_run/handoff/manifest.json)

Observed stage counts:

- ingest:
  - `raw_file_count = 92`
  - `lines_seen = 1,010,348`
  - `records_written = 1,010,346`
  - `json_parse_success = 1,010,213`
  - `json_parse_fail = 135`
  - `salvaged = 133`
  - `source_read_errors = 30` (truncated/corrupt gzip read failures)
- hard-filter:
  - `pass_count = 947,551`
  - `reject_count = 62,795`
- exact dedup:
  - `unique_count = 763,343`
  - `dup_count = 184,208`
- near dedup:
  - `selected_count = 761,987`
  - `cluster_members_count = 1,356`
- priority:
  - `tier_a_count = 761,029`
  - `tier_b_count = 958`
  - `tier_c_count = 0`
- handoff:
  - `hpc_ready_A = 761,029`
  - `hpc_ready_B = 958`
  - `hpc_explore_C_sample = 0`

Operational note:

- `prefilter_local.py` ingest was hardened to tolerate compressed-stream failures (`EOFError`, `zlib.error`, decode errors) on a per-file basis, record them in ingest stats/rejects, and continue rather than aborting the full run.

### HPC handoff sharding + transfer package snapshot (March 8, 2026)

To make SGE-array submission deterministic, the handoff outputs were split into fixed-size shards and bundled with integrity metadata.

- sharded package root:
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538)
- transfer bundle:
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538_bundle.tar.gz](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538_bundle.tar.gz)
- bundle checksum:
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538_bundle.tar.gz.sha256](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538_bundle.tar.gz.sha256)
- shard manifest + checksums:
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/shard_manifest.json](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/shard_manifest.json)
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/SHA256SUMS.txt](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/SHA256SUMS.txt)
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/SHA256_VERIFY.txt](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/SHA256_VERIFY.txt)
- SGE hint file:
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/sge_array_hint.env](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/sge_array_hint.env)

Sharding policy and counts:

- `A`: `10,000` records per shard -> `77` shards (`761,029` total lines)
- `B`: `1,000` records per shard -> `1` shard (`958` total lines)
- recommended array range for `A`: `1-77`

### Sequence-shard HPC scorer path added (March 8, 2026)

The prior SGE templates were prompt-driven (`run_ablation.py`) and did not directly consume `hpc_ready_A/B` sequence records.  
To support prefilter handoff scoring directly on Wynton, a sequence-shard evaluator path was added.

- sequence scorer:
  - [/Users/svdr/tinker/scripts/run_sequence_shard_eval.py](/Users/svdr/tinker/scripts/run_sequence_shard_eval.py)
- SGE array submit template:
  - [/Users/svdr/tinker/hpc/submit_prefilter_eval_array.sge.sh](/Users/svdr/tinker/hpc/submit_prefilter_eval_array.sge.sh)
- docs:
  - [/Users/svdr/tinker/hpc/README.md](/Users/svdr/tinker/hpc/README.md)

Capabilities:

1. Reads one `hpc_ready_*.jsonl` shard,
2. runs ESM proxy + PETase family/geometry evaluation per sequence,
3. writes:
   - `scored_candidates.jsonl`
   - `functional_bridges.jsonl`
   - `rejects.jsonl`
   - `summary.json`

Smoke validation on real shard data:

- command used:
  - `ESM2_DEVICE=cpu python /Users/svdr/tinker/scripts/run_sequence_shard_eval.py --input-jsonl /Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/shards/A/hpc_ready_A_shard_0001.jsonl --output-dir /Users/svdr/tinker/reports/hpc_sequence_eval_smoke --reference-records-path /Users/svdr/tinker/data/petase_family_expanded/petase_records.jsonl --name smoke-a0001 --limit 3`
- result:
  - evaluated `3/3` records
  - output artifacts written under:
    - [/Users/svdr/tinker/reports/hpc_sequence_eval_smoke/smoke-a0001](/Users/svdr/tinker/reports/hpc_sequence_eval_smoke/smoke-a0001)

## March 20-21, 2026 Wynton bring-up outcome: validated production path

The Wynton execution path moved from planning into real scheduler/runtime validation.

### Initial failure mode characterization

Cluster bring-up exposed a real distinction between queue availability and runtime health.

- `qb3-idgpu*` nodes were schedulable, but not reliable for this workload:
  - malformed `SGE_GPU` values were observed in some jobs (`SGE_GPU=to`)
  - even with `CUDA_VISIBLE_DEVICES` unset, PyTorch reported `cuda_available=false` or CUDA/NVML initialization errors
  - this was reproduced with both:
    - `torch 2.10.0+cu128`
    - `torch 2.5.1+cu121`

Minimal repro artifacts added:

- [/Users/svdr/tinker/hpc/submit_cuda_smoke.sge.sh](/Users/svdr/tinker/hpc/submit_cuda_smoke.sge.sh)
- [/Users/svdr/tinker/scripts/check_torch_cuda_env.py](/Users/svdr/tinker/scripts/check_torch_cuda_env.py)

Operational implication:

- `qb3-idgpu*` should not be treated as the default production target for PEARL shard scoring.

### Healthy pool discovery

Two healthy pools were confirmed with the minimal CUDA smoke:

1. `qb3-atgpu*`
   - example success: `qb3-atgpu31`
   - GPU class: `NVIDIA A40`
2. `qb3-iogpu*`
   - example success: `qb3-iogpu4`
   - GPU class: `NVIDIA A100-SXM4-40GB`

The validated runtime on healthy pools became:

- Python env: `~/venvs/pearl-eval-cu121`
- PyTorch: `2.5.1+cu121`
- direct Python execution
- `SET_CUDA_VISIBLE_DEVICES=0`
- `ESM2_DEVICE=auto`

### Submit template hardening from real cluster behavior

The sequence-shard submit template was hardened accordingly:

- [/Users/svdr/tinker/hpc/submit_prefilter_eval_array.sge.sh](/Users/svdr/tinker/hpc/submit_prefilter_eval_array.sge.sh)

Key changes:

1. no longer force `ESM2_DEVICE=cuda`; use `auto`
2. make `CUDA_VISIBLE_DEVICES` masking optional and default it to off
3. stop relying on `/scratch` + `rsync` for durable outputs
4. write shard results directly to persistent storage under `reports/hpc_sequence_eval/...`
5. log `host`, `SGE_GPU`, masking mode, and selected runtime details

### Validated shard-scoring execution results

#### A-shard smoke on A100

- host:
  - `qb3-iogpu4.wynton.ucsf.edu`
- run:
  - `topoff1m-a-smoke-a100-cu121-20260321b-hpc_ready_A_shard_0001`
- artifact:
  - [/Users/svdr/tinker/reports/hpc_sequence_eval/topoff1m-a-smoke-a100-cu121-20260321b/runs/topoff1m-a-smoke-a100-cu121-20260321b-hpc_ready_A_shard_0001/summary.json](/Users/svdr/tinker/reports/hpc_sequence_eval/topoff1m-a-smoke-a100-cu121-20260321b/runs/topoff1m-a-smoke-a100-cu121-20260321b-hpc_ready_A_shard_0001/summary.json)

Observed outcome:

- `250` records seen / parsed / evaluated
- `esm_info.device = cuda`
- `esm_gate_pass_count = 132`
- `geometry_pass_count = 8`
- `functional_bridge_count = 0`
- `duration_seconds = 198.56`
- outputs written directly to persistent storage

Interpretation:

- the PEARL shard scorer now has a real, durable, GPU-backed Wynton execution path on A100.

#### B-shard full run on A100

- host:
  - `qb3-iogpu4.wynton.ucsf.edu`
- run:
  - `topoff1m-b-a100-cu121-20260321-hpc_ready_B_shard_0001`
- artifact:
  - [/Users/svdr/tinker/reports/hpc_sequence_eval/topoff1m-b-a100-cu121-20260321/runs/topoff1m-b-a100-cu121-20260321-hpc_ready_B_shard_0001/summary.json](/Users/svdr/tinker/reports/hpc_sequence_eval/topoff1m-b-a100-cu121-20260321/runs/topoff1m-b-a100-cu121-20260321-hpc_ready_B_shard_0001/summary.json)

Observed outcome:

- `958` records seen / parsed / evaluated
- `esm_gate_pass_count = 732`
- `geometry_pass_count = 0`
- `functional_bridge_count = 0`
- `duration_seconds = 1157.435`
- outputs written directly to persistent storage

Interpretation:

- the production path is not just smoke-valid; it has already produced durable real-run outputs on the B shard.

### Runtime and array-planning implications

Based on the validated A100 runs:

- `250` records in `198.56s` implies roughly `0.79s / record`
- `958` records in `1157.435s` implies roughly `1.21s / record`

Operational estimate:

- a `10,000`-record A shard is likely on the order of `2.2h - 3.4h`
- the full `761,029` A-record pool would take roughly `10` days on one GPU if run fully sequentially
- the correct execution model is therefore an SGE array (`1-77`) over independent shards, letting the scheduler accumulate completions over time

### Production launch status

After validating the A100 path, the full A-array production run was submitted:

- run family:
  - `topoff1m-a-a100-cu121-20260321`
- scheduler shape:
  - `1-77` array
  - `hostname=qb3-iogpu*`
  - `compute_cap=80`
  - `h_rt=05:00:00`

As of the time of this note:

- B production output is complete (`1/1`)
- A smoke is complete (`1/1`)
- A full `1-77` production array is submitted and waiting on scheduler availability

### Support escalation

A Wynton support report was prepared and sent summarizing:

- malformed `SGE_GPU`
- `idgpu` CUDA/NVML failures
- successful A40 and A100 minimal smoke jobs
- exact minimal repro scripts and job IDs

Operational implication:

- current bottleneck is scheduler access to known-healthy GPU pools, not code correctness.

## March 27, 2026 topoff1m A-run closeout + postprocess + robustness handoff

### A-run production closeout

The full `topoff1m` Tier-A Nebius run is now complete and fully local.

Primary bundle:

- [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/bundle_summary.json](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/bundle_summary.json)
- [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/all_functional_bridges.jsonl](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/all_functional_bridges.jsonl)
- [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/family_faithful_bridges.jsonl](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/family_faithful_bridges.jsonl)
- [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/family_faithful_bridges.fasta](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/family_faithful_bridges.fasta)

Bundle totals:

- `77` shard summaries
- `761,029` records evaluated
- `15,583` geometry passes
- `141` functional bridges
- `10` family-faithful bridges

Interpretation:

- the run was not a washout
- strict tier-1 density was still too thin for a clean retrain gate on mined hits alone
- the next rational step became repair/doping rather than immediate “mine more”

### H100 repair wave

Repair outputs:

- [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_summary_wave1_h100.json](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_summary_wave1_h100.json)
- [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_survivors_wave1_h100.jsonl](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_survivors_wave1_h100.jsonl)
- [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_best_attempts_wave1_h100.jsonl](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_best_attempts_wave1_h100.jsonl)

Observed result:

- `32` seed hits processed
- `8,908` variants evaluated
- `446` raw survivors

Raw survivors were too loose to trust directly, so the survivor pool was capped and validated.

Key files:

- lineage-capped survivor pool:
  - [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_survivors_wave1_h100_lineage_capped.jsonl](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_survivors_wave1_h100_lineage_capped.jsonl)
- readiness result:
  - [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_survivor_readiness_wave1_h100_lineage_capped.json](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_survivor_readiness_wave1_h100_lineage_capped.json)
- strict family repairs:
  - [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_survivors_wave1_h100_strict_family.jsonl](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_survivors_wave1_h100_strict_family.jsonl)
- strict shortlist:
  - [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_survivors_wave1_h100_strict_shortlist.jsonl](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/repair_survivors_wave1_h100_strict_shortlist.jsonl)

Validated outcome:

- `61` capped survivors considered
- only `8` survived strict validation
- only `2` were strict family-clean repairs
- `53` were rejected from conservative training use

Repair-readiness outcome:

- `ready_for_retrain = true`
- `182` deduped tier-2 positives
- `70` deduped tier-1 proxies
- `145` train tier-2 after holdout
- `40` train tier-1 proxies after holdout

Interpretation:

- repair solved the gate problem
- strict-family density is still narrow, so training should remain conservative
- this was enough to justify a limited warmstart branch pair

### Warmstart branches

Recommended curricula:

- ultra-conservative:
  - [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/soft_doping_curriculum_ultra_conservative.jsonl](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/soft_doping_curriculum_ultra_conservative.jsonl)
  - [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/soft_doping_curriculum_ultra_conservative_summary.json](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/soft_doping_curriculum_ultra_conservative_summary.json)
- balanced-strict:
  - [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/soft_doping_curriculum_balanced_strict.jsonl](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/soft_doping_curriculum_balanced_strict.jsonl)
  - [/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/soft_doping_curriculum_balanced_strict_summary.json](/Users/svdr/tinker/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/soft_doping_curriculum_balanced_strict_summary.json)

Warmstart outputs:

- ultra:
  - [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-ultra-conservative-lr5e7-ep1/summary.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-ultra-conservative-lr5e7-ep1/summary.json)
- balanced:
  - [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-balanced-strict-lr5e7-ep1/summary.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-balanced-strict-lr5e7-ep1/summary.json)

Warmstart stats:

- ultra:
  - `47` pairs
  - mean sequence length `475.3`
  - mean ESM `93.04`
- balanced:
  - `53` pairs
  - mean sequence length `482.81`
  - mean ESM `93.78`

Interpretation:

- two post-topoff checkpoints now exist
- the project is no longer in “can we ever hit bridge?” territory
- the immediate question is whether either branch shows durable uplift on the frozen suite

### Two-phase H100 robustness path

The original one-process H100 robustness path was the wrong architecture for this workload.

Observed problem:

- remote Tinker sampling dominated wall clock
- the H100 only helped during local ESM bursts
- GPU utilization looked flat or bursty even when the suite was technically alive

The replacement path is now:

1. stockpile stage-1 candidate pools first
2. defer local ESM rescoring/finalization to a separate H100 step
3. summarize the suite only after finalized ablation dirs exist

Files added for this:

- [/Users/svdr/tinker/scripts/run_robustness_two_phase.py](/Users/svdr/tinker/scripts/run_robustness_two_phase.py)
- [/Users/svdr/tinker/scripts/finalize_ablation_from_candidate_audit.py](/Users/svdr/tinker/scripts/finalize_ablation_from_candidate_audit.py)
- [/Users/svdr/tinker/scripts/run_nebius_h100_robustness.sh](/Users/svdr/tinker/scripts/run_nebius_h100_robustness.sh)
- [/Users/svdr/tinker/scripts/launch_topoff1m_a_robustness_h100.sh](/Users/svdr/tinker/scripts/launch_topoff1m_a_robustness_h100.sh)
- [/Users/svdr/tinker/scripts/sync_topoff1m_a_eval_bundle.sh](/Users/svdr/tinker/scripts/sync_topoff1m_a_eval_bundle.sh)

Operational lessons from the March 27 bring-up:

1. the queue for `balanced` must wait on `ultra`’s `robustness_summary.json`, not the `ultra` parent PID
2. the Nebius eval venv must include:
   - `sentencepiece`
   - `protobuf`
   - `tiktoken`
3. stockpile lanes can fail transiently, so `run_robustness_two_phase.py` now supports:
   - `--stockpile-jobs`
   - `--stockpile-retries`
4. completed stage-1 ablation logs are written per lane under:
   - `reports/ablations/<run_name>/stage1.log`

Recommended VM settings for the current branch:

- `STOCKPILE_JOBS=4`
- `STOCKPILE_RETRIES=2`
- one H100 per active suite
- run `ultra` first, `balanced` second on the same VM unless a second H100 is available

### Current live branch state during the March 27 robustness run

The active live run family is:

- ultra suite:
  - `pearl-topoff1m-a-ultra-robustness-2phase-h100-p12p24p48-t08-s41s53s67`
- balanced suite:
  - `pearl-topoff1m-a-balanced-robustness-2phase-h100-p12p24p48-t08-s41s53s67`

Partial ultra accomplishments already observed during the live run:

- finalized:
  - `p12/s41`
  - `p12/s53`
  - `p12/s67`
  - `p24/s41`
- partial signal:
  - `p12/s53` already produced `1` functional bridge step
  - `p24/s41` already produced `1` functional bridge step
  - no family-faithful steps observed yet in the completed `ultra` subset

Interpretation:

- `ultra` is not dead
- the suite has already shown nonzero tier-2 signal
- the correct decision on more mining still depends on the final `ultra` and `balanced` robustness summaries

Kill condition for the current robustness VM:

- do not stop the VM until both of these files exist:
  - `/home/svdr/work/tinker/reports/robustness/pearl-topoff1m-a-ultra-robustness-2phase-h100-p12p24p48-t08-s41s53s67/robustness_summary.json`
  - `/home/svdr/work/tinker/reports/robustness/pearl-topoff1m-a-balanced-robustness-2phase-h100-p12p24p48-t08-s41s53s67/robustness_summary.json`

At that point:

1. rsync the `reports/robustness/` and `reports/ablations/` outputs back locally
2. archive the launcher logs
3. then kill the VM

## March 27, 2026 robustness failure + softmotif half-million mining pivot

### Robustness outcome

The post-topoff `ultra` branch finished its two-phase H100 robustness suite and failed the durability gate.

Primary summary:

- [/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-ultra-robustness-2phase-h100-p12p24p48-t08-s41s53s67/robustness_summary.json](/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-ultra-robustness-2phase-h100-p12p24p48-t08-s41s53s67/robustness_summary.json)

Interpretation:

- the repair-derived checkpoint was not durable enough to become the new default branch
- the failure did **not** invalidate the data signal; it invalidated the branch as a stable model endpoint
- the right pivot was to stop spending H100 time on robustness and move into stockpile-first remine

The `balanced` robustness branch was intentionally stopped once the architecture decision was clear.

### Stockpile-first mining architecture

The active mining lane became:

- checkpoint:
  - `tinker://6c592489-8afb-558c-a9b3-7331cf4d62ed:train:0/weights/pearl-micro-sft-topoff1m-a-balanced-strict-lr5e7-ep1`
- prompt variant:
  - `motif_prior_soft_v2`
- workflow:
  1. run `stage1-only` remote sampling locally
  2. capture `candidate_audit.json` per shard
  3. defer H100 ESM rescoring/finalization until the stockpile is complete

Relevant scripts used in this pivot:

- [/Users/svdr/tinker/scripts/run_raft_wave.py](/Users/svdr/tinker/scripts/run_raft_wave.py)
- [/Users/svdr/tinker/scripts/finalize_raft_wave.py](/Users/svdr/tinker/scripts/finalize_raft_wave.py)
- [/Users/svdr/tinker/scripts/rebalance_stage1_wave.py](/Users/svdr/tinker/scripts/rebalance_stage1_wave.py)

Operational notes:

- `run_raft_wave.py` now supports `--prompt-offset`, which made the second non-overlapping wave possible
- stage1-only mode skips local ESM prewarm and keeps the remote generation loop cheap enough to parallelize harder
- `rebalance_stage1_wave.py` helped on the coarse wave, but a final edge-case bug remained in mixed stopped/rebalanced states; the last `300k` prompts were completed via a manual tail fix rather than trusting another rebalance

### Completed mining waves

#### `300k` wave

Wave directory:

- [/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-balanced-softmotif-raft-stage1-p1172-c256-20260327c](/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-balanced-softmotif-raft-stage1-p1172-c256-20260327c)

Finalization summary:

- [/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-balanced-softmotif-raft-stage1-p1172-c256-20260327c/finalization_summary.json](/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-balanced-softmotif-raft-stage1-p1172-c256-20260327c/finalization_summary.json)

Outcome:

- `1,172` prompts
- `300,032` raw candidates
- `27` functional bridge steps
- `4` family-faithful bridge steps
- exact dedup on finalized hits:
  - `27` functional exact-unique sequences
  - `4` family-faithful exact-unique sequences

#### `200k` wave

Wave directory:

- [/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-balanced-softmotif-raft-stage1-p782-c256-next782-20260327d](/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-balanced-softmotif-raft-stage1-p782-c256-next782-20260327d)

Finalization summary:

- [/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-balanced-softmotif-raft-stage1-p782-c256-next782-20260327d/finalization_summary.json](/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-balanced-softmotif-raft-stage1-p782-c256-next782-20260327d/finalization_summary.json)

Outcome:

- `782` prompts
- `200,192` raw candidates
- `23` functional bridge steps
- `8` family-faithful bridge steps
- exact dedup on finalized hits:
  - `23` functional exact-unique sequences
  - `8` family-faithful exact-unique sequences

### Combined half-million result

All-in mining totals for the new lane:

- `1,954` prompts finalized
- `500,224` raw candidates generated
- `50` functional bridge steps
- `12` family-faithful bridge steps
- exact dedup on finalized hits:
  - `50` functional exact-unique sequences
  - `12` family-faithful exact-unique sequences

Interpretation:

- the new lane is a real positive result, not just a pilot artifact
- the `200k` tranche actually improved strict-hit density relative to the `300k` tranche
- the project now has a working data engine even though the previous retrain branch failed durability

The bottleneck has shifted:

- no longer “can we find real hits?”
- now “can we cluster, validate, and retrain on the cleaner mined pool without collapsing diversity?”

### New project state after the half-million run

Current posture:

- model branch:
  - still unresolved after `ultra` durability failure
- mining/data branch:
  - materially improved and now productive
- next work:
  1. lineage-aware clustering of the `50 / 12` finalized hit set
  2. conservative curriculum construction from that clustered pool
  3. the next retrain/eval loop using the cleaner mined positives

Operational implication:

- do not spend on another large mining tranche until the `50 / 12` pool has been clustered and tried in the next conservative retrain cycle
- if the next conservative cycle still fails durability, the mining lane remains valuable, but the flywheel needs better diversity control rather than more blind volume

## March 28, 2026 strict-first union cycle + next recipe

### Why the softmotif lineage-conservative branch was not enough

The first mined-pool retrain branch used the new half-million positives, but it still failed durability.

Primary summary:

- [/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-softmotif-lineage-conservative-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json](/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-softmotif-lineage-conservative-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json)

Observed pattern:

- `p12`: `0 / 3` seeds with any tier-2 hit
- `p24`: `0 / 3`
- `p48`: `1 / 3`, with only `1` total tier-2 hit

Diagnosis:

- the mined pool itself was not the main problem
- the curriculum was still too loose-heavy relative to the scarce strict positives
- it taught bridge-adjacent basin behavior better than it taught the narrow strict-family bridge manifold

### Strict-first union datasets

To test that diagnosis, a stricter recipe was built from:

- old A-run family-faithful hits
- new half-million family-faithful hits
- canonical purebreds
- then a very limited bridge-only mix-in

Builder and outputs:

- builder:
  - [/Users/svdr/tinker/scripts/build_strict_first_union_curricula.py](/Users/svdr/tinker/scripts/build_strict_first_union_curricula.py)
- stage A dataset:
  - [/Users/svdr/tinker/reports/raft/topoff1m-a-strict-first-union-postprocess-20260327/strict_first_union_stage_a.jsonl](/Users/svdr/tinker/reports/raft/topoff1m-a-strict-first-union-postprocess-20260327/strict_first_union_stage_a.jsonl)
  - [/Users/svdr/tinker/reports/raft/topoff1m-a-strict-first-union-postprocess-20260327/strict_first_union_stage_a_summary.json](/Users/svdr/tinker/reports/raft/topoff1m-a-strict-first-union-postprocess-20260327/strict_first_union_stage_a_summary.json)
- stage B dataset:
  - [/Users/svdr/tinker/reports/raft/topoff1m-a-strict-first-union-postprocess-20260327/strict_first_union_stage_b.jsonl](/Users/svdr/tinker/reports/raft/topoff1m-a-strict-first-union-postprocess-20260327/strict_first_union_stage_b.jsonl)
  - [/Users/svdr/tinker/reports/raft/topoff1m-a-strict-first-union-postprocess-20260327/strict_first_union_stage_b_summary.json](/Users/svdr/tinker/reports/raft/topoff1m-a-strict-first-union-postprocess-20260327/strict_first_union_stage_b_summary.json)

Stage A contents:

- `48` rows
- `26` unique strict sequences
- `10` old A-run family-faithful uniques, each repeated `2x`
- `12` new half-million family-faithful uniques, each repeated `2x`
- `4` canonical purebred uniques, each repeated `1x`

Stage B contents:

- `60` rows
- `38` unique sequences
- same `48` strict rows from stage A
- plus only `12` bridge-only anchors

Interpretation:

- this was a much cleaner recipe than the earlier loose-heavy branch
- but the anchor mix was still nontrivial enough that it could blur the basin again if the strict core had not already consolidated

### Stage A and stage B training

Launchers:

- [/Users/svdr/tinker/scripts/launch_topoff1m_a_strict_first_union.sh](/Users/svdr/tinker/scripts/launch_topoff1m_a_strict_first_union.sh)
- [/Users/svdr/tinker/scripts/launch_topoff1m_a_strict_first_union_robustness.sh](/Users/svdr/tinker/scripts/launch_topoff1m_a_strict_first_union_robustness.sh)

Stage A checkpoint:

- [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-first-union-stagea-lr1e6-ep2/summary.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-first-union-stagea-lr1e6-ep2/summary.json)

Stage A stats:

- `48` pairs
- `2` epochs
- LR `1e-6`
- mean sequence length `384.04`

Stage B checkpoint:

- [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-first-union-stageb-lr5e7-ep1/summary.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-first-union-stageb-lr5e7-ep1/summary.json)

Stage B stats:

- `60` pairs
- `1` epoch
- LR `5e-7`
- mean sequence length `366.82`

### Strict-first stage-B robustness outcome

Primary summary:

- [/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-strict-first-union-stageb-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json](/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-strict-first-union-stageb-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json)

Outcome:

- `completed_run_count: 9`
- `durability_gate.passed: false`

Per prompt-size result:

- `p12`:
  - tier-2 hits by seed `[0, 0, 1]`
  - prompt coverage `1 / 12`
- `p24`:
  - tier-2 hits by seed `[0, 0, 0]`
  - prompt coverage `0 / 24`
- `p48`:
  - tier-2 hits by seed `[1, 0, 2]`
  - prompt coverage `3 / 48`
  - one family-faithful hit in `p48 / s67`

Interpretation:

- this branch still failed, but it failed better than the previous mined-pool conservative branch
- the strict-first idea is probably directionally correct
- the useful signal all appeared where the prompt budget was largest
- the bridge manifold did not collapse to absolute zero, which is materially different from the prior failure pattern

Why it still failed:

- `12` bridge-only anchors was likely still enough to widen the basin before the strict core fully stabilized
- the strict core itself may still be under-consolidated at `2` epochs / `1e-6`
- the evidence points to a recipe problem, not a “need another half-million immediately” problem

### Next recipe: strict-core-v2, then stage-b-lite only if needed

The next recipe should be stricter, not broader.

Recommended stage A (`strict-core-v2`):

- strict-only union of:
  - old A-run family-faithful hits
  - new half-million family-faithful hits
  - canonical purebreds
- stronger oversampling than the current stage A:
  - new family-faithful rows: about `3x`
  - old family-faithful rows: about `2x`
  - purebreds: about `2x`
- target size: around `64` rows
- `2-3` epochs
- LR roughly `1e-6` to `1.5e-6`

Reasoning:

- the branch improved once strict positives dominated
- the next question is whether removing anchors entirely and pushing strict consolidation harder improves prompt coverage at `p48` and wakes up `p24`

Recommended stage B (`stage-b-lite`), only if the stricter stage A looks better:

- start from the `strict-core-v2` checkpoint
- add only `4-8` bridge-only anchors
- pick anchors by:
  - strongest geometry
  - best reward / ESM
  - family-like length band
  - non-overlapping lineage
- train `1` epoch
- LR roughly `2e-7` to `5e-7`

Decision rule:

- if strict-only stage A outperforms the current stage-B branch, keep the core strict and add fewer anchors
- if strict-only stage A also fails flatly, continue recipe work before buying another large mining tranche

Operational implication:

- do not jump straight to another half-million run
- the mined pool is already strong enough to justify at least one more strict-only recipe cycle
- the next spend should be on recipe sharpening, not more blind data volume

## March 29, 2026 1M stage-b-lite tranche + strict-core-v4 failure

### 1M mining tranche outcome

The next mining tranche used the strongest available miner prior at the time, `stage-b-lite`, and pushed to roughly one million raw candidates.

Wave:

- [/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-stageb-lite-raft-stage1-p3907-c256-20260329a](/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-stageb-lite-raft-stage1-p3907-c256-20260329a)

Finalization summary:

- [/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-stageb-lite-raft-stage1-p3907-c256-20260329a/finalization_summary.json](/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-stageb-lite-raft-stage1-p3907-c256-20260329a/finalization_summary.json)

Outcome:

- `3,907` prompts
- `1,000,192` raw candidates
- `134` functional bridge steps
- `37` family-faithful bridge steps

Interpretation:

- the 1M tranche clearly validated the mining lane again
- this was not a marginal extension of the half-million result
- the bottleneck after this point was no longer positive discovery, but how to turn a much larger strict pool into a durable checkpoint

### 1M postprocess bundle and retrain readiness

Bundle and readiness outputs:

- [/Users/svdr/tinker/reports/raft/topoff1m-a-stageb-lite-1m-postprocess-20260329/bundle_summary.json](/Users/svdr/tinker/reports/raft/topoff1m-a-stageb-lite-1m-postprocess-20260329/bundle_summary.json)
- [/Users/svdr/tinker/reports/raft/topoff1m-a-stageb-lite-1m-postprocess-20260329/retrain_readiness_selected_only.json](/Users/svdr/tinker/reports/raft/topoff1m-a-stageb-lite-1m-postprocess-20260329/retrain_readiness_selected_only.json)

Key counts:

- `134` exact-unique functional hits
- `37` exact-unique family-faithful hits
- `133` lineage clusters at `0.85`
- largest cluster size `2`
- `ready_for_retrain: true`
- after holdout:
  - `107` train tier-2
  - `12` train tier-1-proxy

Interpretation:

- the 1M bundle is genuinely diverse
- the strict pool is not being faked by cluster collapse
- the project had, by any reasonable gate, enough mined strict material to justify another retrain cycle

### strict-core-v4 datasets

To exploit the 1M bundle, a broader strict-core recipe was built.

Stage A summary:

- [/Users/svdr/tinker/reports/raft/topoff1m-a-strict-core-v4-postprocess-20260329/strict_core_v4_stage_a_summary.json](/Users/svdr/tinker/reports/raft/topoff1m-a-strict-core-v4-postprocess-20260329/strict_core_v4_stage_a_summary.json)

Stage B-lite summary:

- [/Users/svdr/tinker/reports/raft/topoff1m-a-strict-core-v4-postprocess-20260329/strict_core_v4_stage_b_lite_summary.json](/Users/svdr/tinker/reports/raft/topoff1m-a-strict-core-v4-postprocess-20260329/strict_core_v4_stage_b_lite_summary.json)

Stage A contents:

- `102` rows
- `51` unique strict sequences
- `10` old A-run family-faithful uniques, repeated `2x`
- `37` new 1M family-faithful uniques, repeated `2x`
- `4` canonical purebreds, repeated `2x`

Stage B-lite contents:

- `106` rows
- `55` unique sequences
- same `102` strict rows
- plus only `4` anchors

Interpretation:

- on paper this looked like the right scale-up
- in practice it changed two variables at once:
  - it widened the strict pool dramatically
  - it reduced per-sequence consolidation compared with the earlier stronger recipe

### strict-core-v4 training

Stage A summary:

- [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v4-stagea-lr1e6-ep2/summary.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v4-stagea-lr1e6-ep2/summary.json)

Stage B-lite summary:

- [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v4-stageb-lite-lr5e7-ep1/summary.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v4-stageb-lite-lr5e7-ep1/summary.json)

Stage A stats:

- `102` pairs
- `2` epochs
- LR `1e-6`
- mean sequence length `341.98`
- mean ESM score `7.71`

Stage B-lite stats:

- `106` pairs
- `1` epoch
- LR `5e-7`
- mean sequence length `340.42`
- mean ESM score `7.42`

### strict-core-v4 stage-B-lite robustness outcome

Primary summary:

- [/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-strict-core-v4-stageb-lite-robustness-2phase-l40-p12p24p48-t08-s41s53s67/robustness_summary.json](/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-strict-core-v4-stageb-lite-robustness-2phase-l40-p12p24p48-t08-s41s53s67/robustness_summary.json)

Outcome:

- `completed_run_count: 9`
- `durability_gate.passed: false`

Per prompt-size result:

- `p12`:
  - tier-2 hits by seed `[0, 0, 0]`
  - prompt coverage `0 / 12`
- `p24`:
  - tier-2 hits by seed `[1, 0, 0]`
  - prompt coverage `1 / 24`
  - exactly one family-faithful hit in `p24 / s41`
- `p48`:
  - tier-2 hits by seed `[0, 0, 0]`
  - prompt coverage `0 / 48`

Retained totals:

- `1` functional hit
- `1` family-faithful hit

Interpretation:

- this was not a narrow miss
- the branch collapsed at the exact place where the better recipes had previously shown life: `p48`
- the 1M data did not rescue the recipe because the recipe itself had become too diffuse

### Why v4 regressed despite much better data

This is the important diagnosis.

Compared with `strict-core-v2` stage A:

- `v2` stage A:
  - `64` rows
  - `26` unique strict sequences
  - new family-faithful rows repeated `3x`
  - trained for `3` epochs
- `v4` stage A:
  - `102` rows
  - `51` unique strict sequences
  - all strict buckets repeated only `2x`
  - trained for `2` epochs

So `v4` did two weakening things at once:

- it almost doubled the strict target surface area
- it reduced how hard each strict sequence was reinforced

That likely explains the observed failure pattern:

- the 1M pool itself was strong
- the retrain gate was easily satisfied
- but the model never consolidated enough on the bridge manifold to survive the `p48` block

In other words:

- this was a dilution failure, not a data failure

### Next recipe direction after v4

The next recipe should not discard the 1M mine. It should use a tighter top slice of it.

Proposed direction (`strict-core-v5`):

- do not feed all `37` new family-faithful hits back into stage A
- take a narrower top slice of the 1M family-faithful set
- keep the old A-run family-faithful hits and canonical purebreds
- restore heavier repetition on the strongest strict rows
- return to `3` stage-A epochs
- only add a tiny anchor mix, if any, after the strict core shows `p48` recovery

Decision rule after that:

- if the tighter top-slice recipe still fails, stop spending on micro-variants and go back to the mines
- the next mining escalation should then be about `1.5M` raw candidates with the best available miner prior

## March 30, 2026 600k add-on tranche, 1.6M merge, strict-core-v6, and checkpoint cleanup

### 600k add-on tranche outcome

The follow-up mining tranche was stopped early for budget protection after the clean valid wave reached `596,992` raw candidates.

Wave:

- [/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-stageb-lite-raft-stage1-p3906-c256-20260329b-next3907](/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-stageb-lite-raft-stage1-p3906-c256-20260329b-next3907)

Finalization summary:

- [/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-stageb-lite-raft-stage1-p3906-c256-20260329b-next3907/finalization_summary.json](/Users/svdr/tinker/reports/raft/pearl-topoff1m-a-stageb-lite-raft-stage1-p3906-c256-20260329b-next3907/finalization_summary.json)

Outcome:

- `2,332` valid unique prompts
- `596,992` valid unique raw candidates
- `64` functional bridge steps
- `20` family-faithful bridge steps

Interpretation:

- the add-on tranche was not huge, but it materially thickened the strict pool again
- the mining lane still looked healthy
- the real question became what the merged pool would do after exact dedup and clustering

### 1.6M merged bundle and retrain readiness

Merged outputs:

- [/Users/svdr/tinker/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/bundle_summary.json](/Users/svdr/tinker/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/bundle_summary.json)
- [/Users/svdr/tinker/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/retrain_readiness_selected_only.json](/Users/svdr/tinker/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/retrain_readiness_selected_only.json)

Key merged counts:

- `198` finalized step hits in the merged source pool
- `179` exact-unique functional hits
- `54` exact-unique family-faithful hits
- `197` lineage clusters at `0.85`
- largest cluster size `2`
- selected-only retrain readiness still passes easily

Interpretation:

- the merged `1.6M` pool is strong enough that lack of positives is no longer the bottleneck
- the pool is still not collapsing into a few giant lineages
- if recipe quality were the real limiting factor before, this was a fair chance to prove it

### strict-core-v6 datasets

Stage A summary:

- [/Users/svdr/tinker/reports/raft/topoff1m-a-strict-core-v6-postprocess-20260329/strict_core_v6_stage_a_summary.json](/Users/svdr/tinker/reports/raft/topoff1m-a-strict-core-v6-postprocess-20260329/strict_core_v6_stage_a_summary.json)

Stage B-lite summary:

- [/Users/svdr/tinker/reports/raft/topoff1m-a-strict-core-v6-postprocess-20260329/strict_core_v6_stage_b_lite_summary.json](/Users/svdr/tinker/reports/raft/topoff1m-a-strict-core-v6-postprocess-20260329/strict_core_v6_stage_b_lite_summary.json)

Stage A contents:

- `124` rows
- `38` unique strict sequences
- `10` old A-run family-faithful uniques, repeated `2x`
- `24` top-slice new family-faithful uniques, repeated `4x`
- `4` canonical purebreds, repeated `2x`

Stage B-lite contents:

- `126` rows
- `40` unique sequences
- same `124` strict rows
- plus only `2` anchors

Interpretation:

- `v6` was the strongest recipe we had actually trained on the merged `1.6M` pool
- it was broader than `v2`, but still more concentrated than the diffuse `v4` branch
- this was the last credible small recipe turn before returning to mining

### strict-core-v6 training

Stage A summary:

- [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v6-stagea-lr1e6-ep3/summary.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v6-stagea-lr1e6-ep3/summary.json)

Stage B-lite summary:

- [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v6-stageb-lite-lr5e7-ep1/summary.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v6-stageb-lite-lr5e7-ep1/summary.json)

Stage A stats:

- `124` pairs
- `3` epochs
- LR `1e-6`

Stage B-lite stats:

- `126` pairs
- `1` epoch
- LR `5e-7`

### strict-core-v6 smoke and full robustness outcome

Stage-A smoke summary:

- [/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-strict-core-v6-stagea-smoke-p48-t08-s41s53s67/robustness_summary.json](/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-strict-core-v6-stagea-smoke-p48-t08-s41s53s67/robustness_summary.json)

Stage-B-lite full robustness summary:

- [/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-strict-core-v6-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json](/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-strict-core-v6-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json)

Smoke outcome:

- official durability gate: failed
- custom smoke gate: passed
- `p48` hits by seed `[0, 1, 0]`
- prompt coverage `1 / 48`

Full robustness outcome:

- `durability_gate.passed: false`
- `p12`: hits by seed `[1, 0, 0]`, prompt coverage `1 / 12`
- `p24`: hits by seed `[0, 1, 0]`, prompt coverage `1 / 24`
- `p48`: hits by seed `[0, 1, 1]`, prompt coverage `2 / 48`

Interpretation:

- `v6` was not dead
- it recovered nonzero signal at every prompt size and got `2 / 3` `p48` seeds with hits
- but prompt coverage was still nowhere near enough to pass
- after `v4`, `v5`, and `v6`, the honest read is that this recipe family still does not cash the current strict pool into durability

### Operational note: `hell1` path mismatch stalled the watcher chain

The `hell1` run did not initially fail because of the model. It stalled because of a path mismatch.

What happened:

- the box had a nested sync layout under `/home/svdr/work/tinker/Users/svdr/tinker/...`
- smoke completed there and wrote its summary there
- the queue watcher polled only the top-level `/home/svdr/work/tinker/reports/...` path
- so the watcher slept forever even though smoke had already finished

What fixed it:

- link the completed smoke suite into the top-level path the watcher expected
- write the smoke decision there
- let the existing watcher continue into `stage-b-lite` and then full robustness

Interpretation:

- this was an operator/pathing failure, not a scientific result
- once the path mismatch was repaired, the queued chain completed cleanly

### Operational note: checkpoint storage cleanup

The remote Tinker checkpoint estate was also pruned aggressively.

Cleanup manifest:

- [/Users/svdr/tinker/reports/checkpoint_cleanup_20260330/summary.txt](/Users/svdr/tinker/reports/checkpoint_cleanup_20260330/summary.txt)
- [/Users/svdr/tinker/reports/checkpoint_cleanup_20260330/keep_paths.txt](/Users/svdr/tinker/reports/checkpoint_cleanup_20260330/keep_paths.txt)
- [/Users/svdr/tinker/reports/checkpoint_cleanup_20260330/delete_paths.txt](/Users/svdr/tinker/reports/checkpoint_cleanup_20260330/delete_paths.txt)

Outcome:

- `123` stale checkpoints deleted
- `6` explicitly retained at cleanup time
- about `676 GB` removed from remote checkpoint storage

Important engineering note:

- the Tinker CLI help advertised direct path deletion, but the installed CLI parser rejected explicit `tinker://...` checkpoint paths
- the cleanup was completed safely through the SDK method `delete_checkpoint_from_tinker_path(...)`

### Decision after v6

At this point the project has spent the current strict pool on multiple real recipe attempts.

Interpretation:

- mining is still the strong part of the system
- the merged `1.6M` pool is real and diverse
- but `v4`, `v5`, and `v6` still failed to convert it into durability

Operational implication:

- stop spending on `v7`-style micro-variants of the same retrain family
- the next meaningful move is another mining-backed loop
- the question is no longer whether the data engine works; it does
- the question is how much more strict mass the next tranche needs before a new recipe family can finally clear coverage

## 2026-04-22/23 - Manifold v1.1 p24 Postmortem

Manifold v1.1 moved from offline repair into a capped p24-only stage-A transfer gate. The run completed cleanly after publishing the stage-A checkpoint across Tinker accounts and resuming under a funded key. The account/checkpoint issue is no longer the relevant blocker for this branch.

Operational artifacts:

- postmortem script: [/Users/svdr/tinker/scripts/audit_manifold_v11_gate.py](/Users/svdr/tinker/scripts/audit_manifold_v11_gate.py)
- postmortem report: [/Users/svdr/tinker/reports/analysis/manifold_v11_gate_postmortem_20260423/audit.md](/Users/svdr/tinker/reports/analysis/manifold_v11_gate_postmortem_20260423/audit.md)
- postmortem JSON: [/Users/svdr/tinker/reports/analysis/manifold_v11_gate_postmortem_20260423/audit.json](/Users/svdr/tinker/reports/analysis/manifold_v11_gate_postmortem_20260423/audit.json)
- robustness summary: [/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-manifold-v11-stagea-gate-p24-t08-s41s53s67-c128/robustness_summary.json](/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-manifold-v11-stagea-gate-p24-t08-s41s53s67-c128/robustness_summary.json)
- gate decision: [/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-manifold-v11-stagea-gate-p24-t08-s41s53s67-c128/p24_gate_decision.json](/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-manifold-v11-stagea-gate-p24-t08-s41s53s67-c128/p24_gate_decision.json)

Gate result:

- completed runs: `3`
- missing runs: `0`
- tier-2 hits by seed: `[0, 0, 0]`
- prompt coverage by seed: `[0, 0, 0]`
- prompts with any tier-2 across seeds: `0`
- gate passed: `false`

Failure taxonomy:

- selected records: `72`
- selected modes: `28` stability-only, `17` geometry-only, `24` single-motif/no-geometry/no-ESM, `2` motif spam, `1` missing motif
- raw candidate records: `9,216`
- raw modes: `3,569` missing motif, `2,946` single-motif/no-geometry/no-ESM, `2,617` motif spam, `43` geometry-only, `41` stability-only
- raw single-motif candidates: `3,030`
- raw geometry-valid candidates: `218`
- raw ESM-valid candidates: `41`
- raw single-motif plus geometry plus ESM candidates: `0`
- selected mean absolute length delta: `63.917`
- raw mean absolute length delta: `88.262`

Interpretation:

- This is a scientific failure, not an ops failure.
- The selector did not merely miss a hidden bridge; the raw p24 pool had zero single-motif plus geometry plus ESM candidates.
- v1.1 split into proxy fragments: stability-only and geometry-only rows appeared, but the strict conjunction never appeared.
- Length conditioning is still materially poor.
- No p48, stage-B, retry, or broad mining is justified from v1.1.

Decision:

- stop the v1.1 branch
- keep the GPU drained and killable
- move to v1.2 offline-first construction
- require nonzero strict-conjunction density in offline replay before paying for another Tinker gate

v1.2 requirements:

- hard-gate family motif identity, single motif count, catalytic blueprint, family length band, and requested-length obedience before inclusion
- use v9 and v1.1 invalids as explicit negative contrast
- split repair into two lanes: raise ESM for geometry-valid rows and repair geometry for ESM-valid rows
- only treat rows as trainable bridge candidates when single motif, geometry, and ESM pass together

v1.2 offline lane builder:

- script: [/Users/svdr/tinker/scripts/build_manifold_v12_offline_lanes.py](/Users/svdr/tinker/scripts/build_manifold_v12_offline_lanes.py)
- summary: [/Users/svdr/tinker/reports/analysis/manifold_v12_offline_lanes_20260423/v12_offline_lanes_summary.json](/Users/svdr/tinker/reports/analysis/manifold_v12_offline_lanes_20260423/v12_offline_lanes_summary.json)
- geometry-valid but ESM-failing rows: `43`
- ESM-valid but geometry-failing rows: `41`
- single-motif background negatives: `2,946` raw, capped to `512`
- motif-failure negatives: `6,186` raw, capped to `512`
- selected length-offtarget failures at abs delta `>40`: `55`

Immediate next offline work:

- use `geometry_valid_needs_esm.jsonl` to test whether same-scaffold/local edits can raise ESM without destroying geometry
- use `esm_valid_needs_geometry.jsonl` to test whether geometry can be repaired without collapsing ESM
- use the two negative lanes as explicit contrastive rejects for any v1.2 curriculum
- do not pay for another Tinker gate until at least one lane produces nonzero single-motif plus geometry plus ESM candidates offline

### v1.2 offline repair-frontier pass

New scripts:

- frontier builder: [/Users/svdr/tinker/scripts/build_manifold_v12_repair_frontier.py](/Users/svdr/tinker/scripts/build_manifold_v12_repair_frontier.py)
- ESM scorer: [/Users/svdr/tinker/scripts/score_manifold_v12_repair_frontier.py](/Users/svdr/tinker/scripts/score_manifold_v12_repair_frontier.py)

Artifacts:

- frontier summary: [/Users/svdr/tinker/reports/analysis/manifold_v12_repair_frontier_20260423/repair_frontier_summary.json](/Users/svdr/tinker/reports/analysis/manifold_v12_repair_frontier_20260423/repair_frontier_summary.json)
- geometry-lane ESM smoke: [/Users/svdr/tinker/reports/analysis/manifold_v12_repair_frontier_20260423/esm_smoke32_summary.json](/Users/svdr/tinker/reports/analysis/manifold_v12_repair_frontier_20260423/esm_smoke32_summary.json)
- ESM-lane score summary: [/Users/svdr/tinker/reports/analysis/manifold_v12_repair_frontier_20260423/esm_lane_score_summary.json](/Users/svdr/tinker/reports/analysis/manifold_v12_repair_frontier_20260423/esm_lane_score_summary.json)
- ready smoke candidates: [/Users/svdr/tinker/reports/analysis/manifold_v12_repair_frontier_20260423/v12_ready_candidates_esm_lane_smoke.jsonl](/Users/svdr/tinker/reports/analysis/manifold_v12_repair_frontier_20260423/v12_ready_candidates_esm_lane_smoke.jsonl)

Frontier result:

- strict pre-ESM repair candidates: `4,678`
- prompt-length/core-screen trainable pre-ESM candidates: `580`
- trainable candidates from geometry-valid/ESM-failing lane: `556`
- trainable candidates from ESM-valid/geometry-failing lane: `24`

ESM smoke:

- geometry-valid/ESM-failing smoke: `32` scored, `0` passed ESM, max `33.28`
- ESM-valid/geometry-failing lane: `24` scored, `24` passed ESM, `23` scored `>=95`
- ESM-valid lane score range: min `94.93`, mean `95.9562`, max `96.82`
- all ready smoke candidates came from one source row: seed `53`, step `12`, length `274`, prompt-length delta `-6`

Interpretation:

- The geometry lane still looks dead for small local motif/D/H edits.
- The ESM lane is alive: geometry repair can preserve high ESM and produce the strict conjunction offline.
- The positive is currently too narrow for Tinker spend because source breadth is `1`.
- Next offline task is breadth: find or construct more ESM-valid, prompt-length-obedient sources before any paid gate.

### v1.2 breadth selector and retargeted stage-A build

New script:

- breadth selector: [/Users/svdr/tinker/scripts/select_manifold_v12_repair_candidates.py](/Users/svdr/tinker/scripts/select_manifold_v12_repair_candidates.py)

New artifacts:

- one-per-source ESM summary: [/Users/svdr/tinker/reports/analysis/manifold_v12_repair_frontier_20260423/esm_lane_one_per_source_summary.json](/Users/svdr/tinker/reports/analysis/manifold_v12_repair_frontier_20260423/esm_lane_one_per_source_summary.json)
- selected repair set: [/Users/svdr/tinker/reports/manifold/topoff1m-a-manifold-v12-20260423/v12_selected_repair_retargeted.jsonl](/Users/svdr/tinker/reports/manifold/topoff1m-a-manifold-v12-20260423/v12_selected_repair_retargeted.jsonl)
- selected summary: [/Users/svdr/tinker/reports/manifold/topoff1m-a-manifold-v12-20260423/v12_selected_repair_retargeted_summary.json](/Users/svdr/tinker/reports/manifold/topoff1m-a-manifold-v12-20260423/v12_selected_repair_retargeted_summary.json)
- stage-A dataset: [/Users/svdr/tinker/reports/raft/topoff1m-a-manifold-curriculum-v12-20260423/manifold_v12_stage_a.jsonl](/Users/svdr/tinker/reports/raft/topoff1m-a-manifold-curriculum-v12-20260423/manifold_v12_stage_a.jsonl)
- stage-A summary: [/Users/svdr/tinker/reports/raft/topoff1m-a-manifold-curriculum-v12-20260423/manifold_v12_stage_a_summary.json](/Users/svdr/tinker/reports/raft/topoff1m-a-manifold-curriculum-v12-20260423/manifold_v12_stage_a_summary.json)
- experiment config: [/Users/svdr/tinker/configs/experiments/strict/topoff1m_a_manifold_curriculum_v12_20260423.json](/Users/svdr/tinker/configs/experiments/strict/topoff1m_a_manifold_curriculum_v12_20260423.json)

Breadth diagnostic result:

- repaired one-per-source ESM lane: `41` scored
- ESM `>=85`: `40 / 41`
- ESM `>=95`: `35 / 41`
- original prompt-length-valid ready rows: `1 / 41`
- score range: min `83.27`, mean `97.5215`, max `99.99`

Selector result:

- raw scored rows considered: `65`
- eligible strict/core/ESM rows after dedupe and delta cap: `63`
- selected rows: `39`
- unique sources: `38`
- unique exact lengths: `29`
- unique length bins: `9`
- motif split: `24` `GYSQG`, `15` `GYSLG`
- ESM score range: min `87.72`, mean `98.0928`, max `99.99`
- max source share: `0.051282`
- original prompt-length-ok rows: `2 / 39`
- retargeted prompt rows: `37 / 39`

Stage-A dataset build:

- selected repair rows: `39`
- purebred anchor rows: `8`
- dataset rows: `47`
- unique sequences: `43`
- prompt source assignment: `47 / 47` nearest train prompts
- resulting max prompt-length delta: `0`

Interpretation:

- The offline manifold constructor has now turned the one-source v1.2 smoke into a breadth-positive selected set.
- The blocker was not ESM or strict-family viability. It was prompt/length conditioning.
- The resulting v1.2 branch is not "replay the failed prompts again." It is "distill repaired strict/core/ESM manifold examples with prompts aligned to their repaired lengths."
- This is offline-ready for a small paid stage-A plus p24-only proof if explicitly approved and if the base checkpoint is available under the funded account.
- No paid training, robustness, or mining was launched during this step.

### v1.2 paid p24 audit and v1.3 offline curriculum

New scripts:

- gate audit: [/Users/svdr/tinker/scripts/audit_manifold_v12_gate.py](/Users/svdr/tinker/scripts/audit_manifold_v12_gate.py)
- v1.3 builder: [/Users/svdr/tinker/scripts/build_manifold_v13_curriculum.py](/Users/svdr/tinker/scripts/build_manifold_v13_curriculum.py)

New artifacts:

- v1.2 gate audit JSON: [/Users/svdr/tinker/reports/analysis/manifold_v12_gate_audit_20260423/audit.json](/Users/svdr/tinker/reports/analysis/manifold_v12_gate_audit_20260423/audit.json)
- v1.2 gate audit report: [/Users/svdr/tinker/reports/analysis/manifold_v12_gate_audit_20260423/audit.md](/Users/svdr/tinker/reports/analysis/manifold_v12_gate_audit_20260423/audit.md)
- v1.3 stage-A dataset: [/Users/svdr/tinker/reports/raft/topoff1m-a-manifold-curriculum-v13-20260423/manifold_v13_stage_a.jsonl](/Users/svdr/tinker/reports/raft/topoff1m-a-manifold-curriculum-v13-20260423/manifold_v13_stage_a.jsonl)
- v1.3 stage-A summary: [/Users/svdr/tinker/reports/raft/topoff1m-a-manifold-curriculum-v13-20260423/manifold_v13_stage_a_summary.json](/Users/svdr/tinker/reports/raft/topoff1m-a-manifold-curriculum-v13-20260423/manifold_v13_stage_a_summary.json)
- v1.3 config: [/Users/svdr/tinker/configs/experiments/strict/topoff1m_a_manifold_curriculum_v13_20260423.json](/Users/svdr/tinker/configs/experiments/strict/topoff1m_a_manifold_curriculum_v13_20260423.json)

v1.2 paid p24 result:

- recovered functional hits: `3`
- recovered family-faithful hits: `2`
- recovered hit prompt steps: `2`, `7`, `14`
- recovered hit prompt lengths: `241`, `215`, `236`
- explicit smoke gate result: pass under `min_seeds_with_hit=2`, `min_prompts_with_hit=2`
- durability gate result: fail because prompt coverage stayed at `3 / 24`
- raw prompt-tier2 coverage also stayed at `3`, so there was no hidden prompt reservoir beyond the recovered hit prompts

Interpretation:

- v1.2 did not fail the way `v1.1` failed. It produced real post-ESM bridge signal in all three seeds.
- The remaining bottleneck is basin width: the branch is still too narrow to satisfy the durability gate.
- That means the next branch should replay the exact recovered hits and widen nearby prompt support, not escalate to stage-B, p48, or mining.

v1.3 offline build:

- dataset rows: `64`
- composition: `39` v1.2 breadth anchors, `8` support scaffolds, `9` gate-hit replays, `8` purebred anchors
- unique sequences: `54`
- support prompt lengths: `214`, `219`, `220`, `224`, `226`, `227`, `228`, `264`
- hit replay rows: `6` family-faithful plus `3` bridge-only
- max sequence repeat: `3`

Branch intent:

- keep the broad v1.2 manifold signal
- explicitly replay the three recovered p24 successes
- widen prompt coverage around the recovered hit basin with exact-length scaffold anchors
- if approved later, keep the next spend capped at `stage-A -> p24` only

### v1.3 paid p24 outcome

Artifacts:

- stage-A summary: [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-manifold-v13-stagea-lr5e7-ep2/summary.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-manifold-v13-stagea-lr5e7-ep2/summary.json)
- robustness summary: [/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-manifold-v13-stagea-gate-p24-t08-s41s53s67-c128/robustness_summary.json](/Users/svdr/tinker/reports/robustness/pearl-topoff1m-a-manifold-v13-stagea-gate-p24-t08-s41s53s67-c128/robustness_summary.json)
- seed `41` summary: [/Users/svdr/tinker/reports/ablations/pearl-topoff1m-a-manifold-v13-stagea-gate-p24-t08-s41s53s67-c128-p24-t0p8-s41/summary.json](/Users/svdr/tinker/reports/ablations/pearl-topoff1m-a-manifold-v13-stagea-gate-p24-t08-s41s53s67-c128-p24-t0p8-s41/summary.json)
- seed `53` summary: [/Users/svdr/tinker/reports/ablations/pearl-topoff1m-a-manifold-v13-stagea-gate-p24-t08-s41s53s67-c128-p24-t0p8-s53/summary.json](/Users/svdr/tinker/reports/ablations/pearl-topoff1m-a-manifold-v13-stagea-gate-p24-t08-s41s53s67-c128-p24-t0p8-s53/summary.json)
- seed `67` summary: [/Users/svdr/tinker/reports/ablations/pearl-topoff1m-a-manifold-v13-stagea-gate-p24-t08-s41s53s67-c128-p24-t0p8-s67/summary.json](/Users/svdr/tinker/reports/ablations/pearl-topoff1m-a-manifold-v13-stagea-gate-p24-t08-s41s53s67-c128-p24-t0p8-s67/summary.json)

Operational notes:

- local `.env` was pointed at a billing-blocked Tinker org, so the launch had to be retried under a funded key already available in-thread
- stage-A completed cleanly and produced checkpoint `tinker://4358dbe3-5c47-5fe0-8a91-6665ab2fa822:train:0/weights/pearl-micro-sft-topoff1m-a-manifold-v13-stagea-lr5e7-ep2`
- p24 finalize was run with `ESM2` on `mps` to avoid the earlier local `cuda` finalize crash
- all robustness processes were gone at completion

Gate result:

- completed runs: `3 / 3`
- durability gate: fail
- tier-2 hits by seed: `[0, 0, 1]`
- prompt coverage across seeds: `1 / 24`
- family-faithful hits: `0`
- only recovered tier-2 event: seed `67`, prompt step `11`, bridge-only
- seed `41`: `9` trainable, `9` stable-only, `5` geometry-only, `0` tier-2
- seed `53`: `11` trainable, `11` stable-only, `6` geometry-only, `0` tier-2
- seed `67`: `12` trainable, `11` stable-only, `3` geometry-only, `1` tier-2, `0` family-faithful

Interpretation:

- v1.3 was not an ops failure. The branch finished and the summary was written.
- The support-widening curriculum raised trainable and stability-dominant counts, but that increase did not translate into family-faithful bridge recovery.
- Relative to v1.2, this was a regression in the metric that matters: v1.2 had `3` post-ESM hits and `2` family-faithful hits across `3 / 24` prompts, while v1.3 ended with one bridge-only hit and zero family-faithful transfer.
- The next move should not be another small variation of the same stage-A replay. The next branch needs an offline constructor/objective redesign that explicitly learns from v1.2 positives and v1.3 negatives.

### Manifold v2 objective panel

New script:

- builder: [/Users/svdr/tinker/scripts/build_manifold_v2_objective_panel.py](/Users/svdr/tinker/scripts/build_manifold_v2_objective_panel.py)

New artifacts:

- summary: [/Users/svdr/tinker/reports/analysis/manifold_v2_objective_panel_20260424/v2_objective_panel_summary.json](/Users/svdr/tinker/reports/analysis/manifold_v2_objective_panel_20260424/v2_objective_panel_summary.json)
- positive anchors: [/Users/svdr/tinker/reports/analysis/manifold_v2_objective_panel_20260424/v2_positive_anchors.jsonl](/Users/svdr/tinker/reports/analysis/manifold_v2_objective_panel_20260424/v2_positive_anchors.jsonl)
- hard negatives: [/Users/svdr/tinker/reports/analysis/manifold_v2_objective_panel_20260424/v2_hard_negatives.jsonl](/Users/svdr/tinker/reports/analysis/manifold_v2_objective_panel_20260424/v2_hard_negatives.jsonl)
- drift negatives: [/Users/svdr/tinker/reports/analysis/manifold_v2_objective_panel_20260424/v2_drift_negatives.jsonl](/Users/svdr/tinker/reports/analysis/manifold_v2_objective_panel_20260424/v2_drift_negatives.jsonl)
- support positives: [/Users/svdr/tinker/reports/analysis/manifold_v2_objective_panel_20260424/v2_support_positives.jsonl](/Users/svdr/tinker/reports/analysis/manifold_v2_objective_panel_20260424/v2_support_positives.jsonl)

Panel inventory:

- `2` v1.2 family-faithful positive anchors
- `45` v1.3 hard negatives, split into `31` stability-only and `14` geometry-only selected rows
- `305` v9/v1.1 drift negatives
- `190` historical support positives
- `542` total rows, all exact-unique by sequence

Interpretation:

- This is not paid-gate ready by itself. It is the offline objective panel for the next manifold v2 constructor.
- The next pass should generate candidates that stay close to the family-faithful anchors and support positives while explicitly avoiding the v1.3 stability-only/geometry-only and v9/v1.1 drift modes.
- Any future paid p24 proof should wait until that constructor shows family-faithful density, source breadth, catalytic blueprint preservation, and prompt/length obedience offline.

### Manifold v2 offline constructor

New script:

- constructor: [/Users/svdr/tinker/scripts/build_manifold_v2_offline_constructor.py](/Users/svdr/tinker/scripts/build_manifold_v2_offline_constructor.py)

New artifacts:

- summary: [/Users/svdr/tinker/reports/analysis/manifold_v2_offline_constructor_20260424/v2_constructor_summary.json](/Users/svdr/tinker/reports/analysis/manifold_v2_offline_constructor_20260424/v2_constructor_summary.json)
- frontier: [/Users/svdr/tinker/reports/analysis/manifold_v2_offline_constructor_20260424/v2_constructor_frontier_pre_esm.jsonl](/Users/svdr/tinker/reports/analysis/manifold_v2_offline_constructor_20260424/v2_constructor_frontier_pre_esm.jsonl)
- selected: [/Users/svdr/tinker/reports/analysis/manifold_v2_offline_constructor_20260424/v2_constructor_selected_pre_esm.jsonl](/Users/svdr/tinker/reports/analysis/manifold_v2_offline_constructor_20260424/v2_constructor_selected_pre_esm.jsonl)

Constructor result:

- frontier: `340` hard-gated pre-ESM candidates
- frontier breadth: `44` parent scaffolds and `8` exact lengths
- selected set: `64` pre-ESM candidates
- selected breadth: `38` parent scaffolds and `8` exact lengths
- mutation mix: `56` one-mutants and `8` two-mutants
- selected quality proxies: `45` family-faithful proxy rows and `64` bridge-quality rows
- all selected rows preserve hard family gates and exact prompt-length obedience
- readiness: `ready_for_esm_scoring: true`, `ready_for_paid_gate: false`

Interpretation:

- The v2 objective redesign now has a concrete candidate handoff.
- This is still pre-ESM. The next required pass is ESM scoring and scored reselection, not training or a Tinker gate.

### April 24, 2026 - Manifold v2 Scoring and Curriculum Finalization

**ESM Scoring Results:**
- Batch 1 (64 candidates): All passed ESM >= 85, mean 99.5.
- Batch 2 (128 candidates, expanded parent pass): All passed ESM >= 85, mean 98.8.
- **Combined Pool:** 192 candidates, all high-stability, all hard-gated for family manifold validity.

**Selection & Readiness:**
- Fixed `scripts/select_manifold_v12_repair_candidates.py` to support v2 nested JSON flags (`family_assessment.strict_manifold_passes`, etc).
- Fixed v2 source-breadth accounting to use `parent_source_key` / `parent_panel_id` instead of v1.2 lane fields.
- Final Reselection: 34 candidates from 18 unique parent source keys.
- Validation: 34 / 34 strict-manifold, core-screen, and ESM-gate passes.
- Readiness Decision: **Passed**. The set has sufficient breadth (14 lengths, 8 length bins) for a small-scale paid gate.

**Curriculum Building:**
- Tool: `scripts/finalize_manifold_v2_curriculum.py`
- Result: Generated `reports/curriculum/manifold_v2_20260424/manifold_v2_curriculum.jsonl`.
- Composition: 34 v2-selected candidates + 8 purebred anchors (total 42 rows).
- Audit metadata is preserved in the finalized curriculum, including sequence/source prompts, source keys, recipe stage, strict bucket, motif, mutation count, validation records, and parent/source provenance.

**Paid Diagnostic Result:**
- Stage-A checkpoint: `pearl-micro-sft-topoff1m-a-manifold-v2-stagea-20260424`.
- p24/c128 gate: `pearl-topoff1m-a-manifold-v2-stagea-gate-p24-c128`.
- Operational status: 3 / 3 seeds completed.
- Scientific status: failed durability. Tier-2 hits by seed were `[0, 1, 0]`, prompt coverage was `1 / 24`, and family-faithful hits were `0`.

**v2.1 Bridge-Weighted Follow-Up:**
- Tool: `scripts/build_manifold_v21_bridge_curriculum.py`
- Config: `configs/experiments/strict/topoff1m_a_manifold_v21_bridge_20260424.json`
- Curriculum: `reports/curriculum/manifold_v21_20260424/manifold_v21_bridge_curriculum.jsonl`
- Composition: `71` rows = `28` v2 strict-breadth anchors, `10` v12 family-hit replays, `3` v12 bridge-hit replays, `2` v2 bridge-hit replays, `12` support prompt anchors, `12` historical family-faithful anchors, and `4` purebred anchors.
- Validation: no missing prompt/sequence fields, no rows longer than 400 aa, and focused v2/v2.1 tests passed.

**Next Step:**
- Launch only the v2.1 stage-A plus p24/c128 diagnostic when `TINKER_API_KEY` is available. Do not launch stage-B, p48, or broad mining until p24 durability improves.

### April 24, 2026 - Manifold v2.1 Diagnostic Outcome

**v2.1 Bridge-Weighted Results:**
- Operational status: 3 / 3 seeds completed.
- Scientific status: **Failed durability**. 
- Functional hits: `0` across all 72 prompts (24 steps * 3 seeds).
- Tier-1/Tier-2 hits: `0`.
- Geometry rate: ~40% (improved over v2).
- Stability dominant rate: 0.0% (significant regression from v2's 33%).

**Interpretation:**
- The v2.1 curriculum reweighted specifically toward measured hits from v1.2 and v2.
- While this improved the model's ability to propose correct catalytic geometry, it appears to have pushed the generation out of the stable manifold (as measured by the local ESM proxy).
- Manifold v2 remains the best-performing iteration to date, having discovered sequence `v2-51eeb6d384a261ad` (Seed 53, Step 21), which represents the most complete functional bridge hit in the campaign.

**Current State:**
- Curriculum and configs for v2 and v2.1 are archived.
- Documentation updated to reflect the regression.

