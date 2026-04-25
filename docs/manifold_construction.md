# Manifold Construction Plan

## Status

As of April 23, 2026, the project should treat the Kimi sampling plus strict-SFT loop as a partially successful but unreliable discovery engine, not as the primary path to the next result.

The current evidence says:

- `strict-core-v7-repair` was the best historical branch, but its durability was narrow.
- `strict-core-v8-coverage` did not broaden that signal; it regressed at `p12/p24`.
- The `v8` stage-A diagnostic also failed at `p12/p24`, so `stage-b-lite` was not the sole failure.
- The `v9` p12/p24 local repair pass produced stable repaired sequences but `0` strict-valid candidates.
- Manifold `v1.2` recovered a narrow real basin with `3` functional hits and `2` family-faithful hits across `3 / 24` prompts.
- Manifold `v1.3` tried support-prompt widening and regressed to one bridge-only hit with `0` family-faithful transfer.
- Another paid mining tranche remains possible, but it is no longer the highest-quality next move unless we explicitly want a diagnostic.

The recommended next phase is to build a manifold `v2` offline constructor/objective branch before another paid gate.

Phase 1 of that pivot is now implemented locally:

- runner: `scripts/manifold_construction_experiment.py`
- config: `configs/experiments/manifold/topoff1m_a_phase1_constructor_20260422.json`
- output: `reports/manifold/topoff1m-a-manifold-phase1-20260422/`
- result: `ready: true`
- bank: `12,619` unique sequences, `4,893` family-manifold scaffolds, `3,769` strict-manifold scaffolds
- positives: `274` strict candidate positives, `0` strict-positive round-trip rejects
- negatives: recovered `79` `v9` reject rows, with `0` negative family-manifold passes
- Phase 2 ESM-scored frontier: `10,000` same-length strict-manifold candidates, all scoring `>=95`
- Phase 2 diversity selection: `230` selected strict candidates, `79` parent scaffolds, `8` lengths, `100` two-mutants, readiness passed

## Central Hypothesis

The project has been asking a language model to satisfy too many coupled constraints at once:

- family length band
- PETase/cutinase scaffold identity
- single canonical `GxSxG` active-site motif
- compatible catalytic `S/D/H` spacing
- ESM/stability score
- novelty and diversity
- prompt-general behavior after retraining

The observed failures are consistent with the model satisfying fragments of the proxy while missing the joint object. The next system should make family membership, motif identity, length band, and catalytic blueprint constraints hard constraints before optimizing stability or novelty.

## Strategy Shift

Old search order:

1. Generate full sequences.
2. Score for motif, geometry, family, and stability.
3. Repair near-misses.
4. Train if enough strict rows survive.

New search order:

1. Start from valid family scaffolds or validated strict rows.
2. Lock the family scaffold, active-site motif, catalytic blueprint, and length regime.
3. Propose only allowed same-length edits.
4. Reject any edit path that leaves the family manifold.
5. Optimize within the constrained manifold for stability, geometry, novelty, and diversity.

## Inputs

Initial scaffold bank:

- natural PETase/cutinase references from `data/petase_family_expanded/petase_records.jsonl`
- canonical purebreds from `data/petase_family_expanded/kimi_micro_sft_top9_unicorn_only.jsonl`
- old strict family-faithful hits from `reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/family_faithful_bridges.jsonl`
- mined family-faithful representatives from `reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/lineage_family_representatives.jsonl`
- April 12 strict repair rows from `reports/repair/topoff1m-a-local-repair-scaleup-20260412/repair_validated_strict.jsonl`
- optionally, the best `v7` ingredients, but not failed `v8/v9` repair outputs unless used only as negative examples

The scaffold bank should be clustered before search. The first constructor should not mutate one dominant family member into many near-duplicates.

## Blueprint Extraction

For each scaffold, infer and lock:

- sequence length and allowed length band
- canonical `GxSxG` motif window
- exact catalytic serine position
- allowed `D` and `H` residue windows
- empirical `S-D`, `D-H`, and `S-H` gap bands
- family-core conserved windows
- mutable and immutable residue masks

Initial version should be same-length only. Insertions and deletions should be deferred until same-length construction produces clean candidates.

## Search Operator

Start with constrained masked-LM substitution search:

- proposal model: ESM masked LM or another local protein model
- edit type: same-length substitutions only
- edit mask: exclude active-site motif, catalytic residues, strongly conserved core windows, and any position whose mutation causes immediate family-screen failure
- beam state: scaffold id, blueprint, sequence, mutation list, score vector, rejection reasons
- beam objective: strict-family validity first, stability and diversity second

Hard rejects:

- leaves family length band
- loses canonical family motif
- creates extra active-site motif hits
- loses catalytic `S/D/H` blueprint
- violates strict gap limits
- fails family core screen
- exceeds mutation-count budget for the current phase

## Scoring Order

The `v9` repair failure showed that high ESM after geometry repair is not sufficient. The scoring order should be:

1. family scaffold gate
2. single canonical motif gate
3. catalytic blueprint and gap gate
4. family core screen
5. ESM/stability score
6. novelty and diversity

Any scoring function that ranks high-ESM non-family sequences above strict family-valid sequences is wrong for this phase.

## Phases

### Phase 1: Validator-First Constructor

Goal:

- build the scaffold bank
- implement blueprint extraction
- implement edit masks
- prove that unedited input scaffolds round-trip through the validator

Current entrypoint:

- config: `configs/experiments/manifold/topoff1m_a_phase1_constructor_20260422.json`
- runner: `scripts/manifold_construction_experiment.py`
- build: `python scripts/manifold_construction_experiment.py --config configs/experiments/manifold/topoff1m_a_phase1_constructor_20260422.json build-bank`
- validate: `python scripts/manifold_construction_experiment.py --config configs/experiments/manifold/topoff1m_a_phase1_constructor_20260422.json validate-roundtrip`

Success:

- no strict reference is falsely rejected
- no failed `v9` survivor is accidentally accepted

Current result:

- `272` strict-positive rows round-tripped with `0` rejects
- `79` recovered `v9` negative rows round-tripped with `0` family-manifold passes

### Phase 2: Shallow Same-Length Search

Goal:

- run `1-2` mutation beams around diverse scaffolds
- produce strict-valid variants without paid generation

Current entrypoint:

- command: `python scripts/manifold_construction_experiment.py --config configs/experiments/manifold/topoff1m_a_phase1_constructor_20260422.json build-phase2-frontier`
- output: `reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_pre_esm_frontier.jsonl`
- summary: `reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_pre_esm_summary.json`

Current result:

- `10,000` pre-ESM candidates
- `96` selected parent scaffolds
- `79` processed/contributing parent scaffolds before the `10,000` frontier cap was reached
- mutation histogram: `4,067` one-mutants and `5,933` two-mutants
- `8` unique sequence lengths
- no ESM or Tinker scoring was run; every row has `needs_esm_score: true` and `esm_score: null`

ESM scoring result:

- scored file: `reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_esm_scored.jsonl`
- score summary: `reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_esm_score_summary.json`
- remote device: L40S via `ESM2_DEVICE=cuda`
- `10,000 / 10,000` candidates scored
- min `99.73`, mean `99.9121`, max `99.98`
- all `10,000` scored `>=95`

Selection/readiness result:

- command: `python scripts/manifold_construction_experiment.py --config configs/experiments/manifold/topoff1m_a_phase1_constructor_20260422.json select-phase2`
- selected file: `reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_selected_strict.jsonl`
- selection summary: `reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_selection_summary.json`
- result: `ready_for_curriculum_build: true`
- `230` selected strict candidates from `10,000` eligible scored candidates
- `79` parent scaffolds and `8` unique lengths
- mutation histogram: `130` one-mutants and `100` two-mutants
- bridge-quality rows: `133` rows across `48` parent scaffolds
- max parent share `0.013043`; max length share `0.165217`
- selected ESM summary: min `99.8`, mean `99.9225`, max `99.98`

The Phase 2 pool is now large and diverse enough for local curriculum construction. It is not yet evidence that a trained model will clear p12/p24 robustness; that still requires a separate training and robustness decision.

### Manifold Curriculum v1 Transfer Test

The first transfer test from the selected Phase 2 pool has completed.

Config and artifacts:

- config: `configs/experiments/strict/topoff1m_a_manifold_curriculum_v1_20260422.json`
- builder: `scripts/build_manifold_curriculum.py`
- stage-A dataset: `reports/raft/topoff1m-a-manifold-curriculum-v1-20260422/manifold_v1_stage_a.jsonl`
- stage-A summary: `reports/raft/topoff1m-a-manifold-curriculum-v1-20260422/manifold_v1_stage_a_summary.json`
- stage-A report: `reports/warmstart/pearl-micro-sft-topoff1m-a-manifold-v1-stagea-lr8e7-ep2/report.json`
- robustness summary: `reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/robustness_summary.json`
- gate decisions:
  - `reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/p12_gate_decision.json`
  - `reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/p24_gate_decision.json`

Curriculum:

- `238` training pairs
- `230` selected Phase 2 rows
- `8` canonical purebred rows
- `234` unique sequences
- `133` bridge-quality selected rows
- mutation histogram: `130` one-mutants and `100` two-mutants

Training branch:

- run: `pearl-micro-sft-topoff1m-a-manifold-v1-stagea-lr8e7-ep2`
- base checkpoint: `strict-core-v7-repair-stageb-lite`
- epochs: `2`
- learning rate: `8e-7`
- batch size: `8`
- budget scope: stage-A train plus p12/p24 gate only; no stage-B, no p48, no paid mining

Gate result:

- `p12`: passed
  - tier-2 hits by seed `[1, 2, 0]`
  - `2 / 3` seeds with hits
  - `3` prompts with tier-2 hits across seeds
- `p24`: failed
  - tier-2 hits by seed `[0, 1, 0]`
  - `1 / 3` seeds with hits
  - `1` prompt with tier-2 hits across seeds

Interpretation:

- The selected Phase 2 pool can move the model toward strict hits.
- The transfer remains narrow and does not survive broader `p24` prompt coverage.
- This branch should stop here. The next work is offline audit and curriculum redesign, not a retry, stage-B, p48, or paid mining.

### Manifold Curriculum v1.1 Offline Repair

The v1.1 repair is built as an offline dataset, not a launched train branch.

New tools:

- audit: `scripts/audit_manifold_v1_gate.py`
- builder: `scripts/build_manifold_v11_curriculum.py`
- config: `configs/experiments/strict/topoff1m_a_manifold_curriculum_v11_20260422.json`

Artifacts:

- audit JSON: `reports/analysis/manifold_v1_gate_audit_20260422/audit.json`
- audit report: `reports/analysis/manifold_v1_gate_audit_20260422/audit.md`
- v1.1 dataset: `reports/raft/topoff1m-a-manifold-curriculum-v11-20260422/manifold_v11_stage_a.jsonl`
- v1.1 summary: `reports/raft/topoff1m-a-manifold-curriculum-v11-20260422/manifold_v11_stage_a_summary.json`

Audit result:

- `p24` prompt holes: `23`
- `p24` weak-hit prompts: `1`
- unique `p24` requested lengths missing from Phase 2 selected pool: `20 / 20`
- `p12`: functional `3`, family-faithful `1`, ESM-gate `11`, geometry `13`, final trainable `11`
- `p24`: functional `1`, family-faithful `0`, ESM-gate `28`, geometry `17`, final trainable `28`

v1.1 dataset:

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

Important correction:

- The actual v1 hits should not be directly replayed by default.
- They were strict but badly length-mismatched to their prompts.
- v1.1 instead uses the exact p24 prompt text with strict scaffold anchors at the requested lengths.

### Manifold Curriculum v1.1 p24 Gate Outcome

The v1.1 stage-A branch was launched as a capped p24-only transfer test and completed cleanly after publishing the stage-A checkpoint across Tinker accounts.

Artifacts:

- postmortem script: `scripts/audit_manifold_v11_gate.py`
- postmortem JSON: `reports/analysis/manifold_v11_gate_postmortem_20260423/audit.json`
- postmortem report: `reports/analysis/manifold_v11_gate_postmortem_20260423/audit.md`
- robustness summary: `reports/robustness/pearl-topoff1m-a-manifold-v11-stagea-gate-p24-t08-s41s53s67-c128/robustness_summary.json`
- gate decision: `reports/robustness/pearl-topoff1m-a-manifold-v11-stagea-gate-p24-t08-s41s53s67-c128/p24_gate_decision.json`

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

- This was not an ops failure; checkpoint publishing, resume, ESM finalization, and gate writing all worked.
- The selector did not merely choose the wrong candidate; the raw pool contained no candidate satisfying the tier-2 proxy conjunction.
- v1.1 split probability mass between stability-only and geometry-only outputs instead of entering the strict family-functional intersection.
- Length conditioning remained poor enough to be a first-class failure mode.
- No p48, stage-B, retry, or broader mining is justified from this branch.

### Manifold v1.2 Offline-First Direction

v1.2 should not start as another paid train branch. It should start as an offline constructor and validator pass that proves it can separate positives from known v9/v1.1 negatives before any Tinker spend.

Initial tooling:

- lane builder: `scripts/build_manifold_v12_offline_lanes.py`
- lane output: `reports/analysis/manifold_v12_offline_lanes_20260423/`
- lane summary: `reports/analysis/manifold_v12_offline_lanes_20260423/v12_offline_lanes_summary.json`

Current lane inventory from v1.1 p24:

- geometry-valid but ESM-failing repair lane: `43` raw rows, `43` selected after dedupe/limit
- ESM-valid but geometry-failing repair lane: `41` raw rows, `41` selected after dedupe/limit
- single-motif background negatives: `2,946` raw rows, `512` selected after dedupe/limit
- motif-failure negatives: `6,186` raw rows, `512` selected after dedupe/limit
- selected length-offtarget failures at abs delta `>40`: `55`

Initial v1.2 repair-frontier tooling:

- frontier builder: `scripts/build_manifold_v12_repair_frontier.py`
- ESM scorer: `scripts/score_manifold_v12_repair_frontier.py`
- breadth selector: `scripts/select_manifold_v12_repair_candidates.py`
- frontier summary: `reports/analysis/manifold_v12_repair_frontier_20260423/repair_frontier_summary.json`
- ESM-valid lane score summary: `reports/analysis/manifold_v12_repair_frontier_20260423/esm_lane_score_summary.json`
- ESM one-per-source summary: `reports/analysis/manifold_v12_repair_frontier_20260423/esm_lane_one_per_source_summary.json`
- ready smoke candidates: `reports/analysis/manifold_v12_repair_frontier_20260423/v12_ready_candidates_esm_lane_smoke.jsonl`

Initial repair-frontier result:

- strict pre-ESM repair frontier: `4,678` candidates
- prompt-length/core-screen trainable pre-ESM frontier: `580` candidates
- trainable by lane: `556` geometry-valid/ESM-failing lane, `24` ESM-valid/geometry-failing lane
- trainable operations: `408` existing-motif plus D/H repairs, `160` motif-relocation plus D/H repairs, `12` motif canonicalizations

ESM smoke result:

- geometry-valid/ESM-failing smoke: `32` scored, `0` ESM-gate passes, max `33.28`
- ESM-valid/geometry-failing smoke: `24` scored, `24` ESM-gate passes, `23` scored `>=95`
- ESM-valid lane score range: min `94.93`, mean `95.9562`, max `96.82`
- all `24` ready smoke candidates came from one source row: seed `53`, step `12`, length `274`, prompt-length delta `-6`

ESM-valid lane breadth diagnostic:

- one repaired representative per ESM-valid/geometry-failing source: `41` scored
- ESM `>=85`: `40 / 41`
- ESM `>=95`: `35 / 41`
- strict ready under original prompt-length gate: `1 / 41`
- score range: min `83.27`, mean `97.5215`, max `99.99`

Interpretation:

- The geometry lane is not rescued by small motif/D/H edits; it remains low ESM.
- The ESM lane can be repaired into single-motif plus geometry plus ESM candidates without collapsing ESM.
- The remaining bottleneck is prompt/length conditioning. Most repaired candidates are strict/core/ESM-positive but not faithful to the original sampled prompt length.
- v1.2 should use length-retargeted training prompts before any paid gate, not replay the failed original prompt lengths unchanged.

v1.2 breadth-selected curriculum:

- selected candidates: `reports/manifold/topoff1m-a-manifold-v12-20260423/v12_selected_repair_retargeted.jsonl`
- selection summary: `reports/manifold/topoff1m-a-manifold-v12-20260423/v12_selected_repair_retargeted_summary.json`
- stage-A dataset: `reports/raft/topoff1m-a-manifold-curriculum-v12-20260423/manifold_v12_stage_a.jsonl`
- stage-A summary: `reports/raft/topoff1m-a-manifold-curriculum-v12-20260423/manifold_v12_stage_a_summary.json`
- experiment config: `configs/experiments/strict/topoff1m_a_manifold_curriculum_v12_20260423.json`

Breadth-selected result:

- selected strict/core/ESM candidates: `39`
- unique sources: `38`
- unique exact lengths: `29`
- length bins: `9`
- motif split: `24` `GYSQG`, `15` `GYSLG`
- ESM score range: min `87.72`, mean `98.0928`, max `99.99`
- prompt retargeted rows: `37 / 39`
- max source share: `0.051282`

Stage-A dataset result:

- dataset rows: `47`
- selected repair rows: `39`
- purebred anchors: `8`
- unique sequences: `43`
- prompt source: `47 / 47` nearest train prompts
- max prompt-length delta after retargeting: `0`

Required changes:

- make single canonical family motif, family motif identity, catalytic blueprint, and length band hard gates before training inclusion
- use v1.1 stability-only and geometry-only candidates as explicit negative contrast
- split repair into two lanes: raise ESM for geometry-valid rows, and repair geometry for ESM-valid rows
- require the full single-motif plus geometry plus ESM conjunction before treating a row as a bridge candidate
- retarget prompts to the repaired sequence lengths before curriculum inclusion; do not train these rows against the failed original length requests

v1.2 stop/go rule:

- stop if offline replay still produces zero single-motif plus geometry plus ESM candidates
- stop if positives are not cleanly separated from v9/v1.1 negatives
- only consider a tiny paid p24 gate after the offline audit shows strict-conjunction density, source breadth, and length-retargeted prompt obedience

v1.2 paid p24 outcome:

- robustness summary: `reports/robustness/pearl-topoff1m-a-manifold-v12-stagea-gate-p24-t08-s41s53s67-c128/robustness_summary.json`
- gate audit: `reports/analysis/manifold_v12_gate_audit_20260423/audit.json`
- audit report: `reports/analysis/manifold_v12_gate_audit_20260423/audit.md`
- recovered post-ESM functional hits: `3`
- family-faithful recovered hits: `2`
- hit prompts: steps `2`, `7`, `14` with requested lengths `241`, `215`, `236`
- explicit smoke gate: pass under `min_seeds_with_hit=2`, `min_prompts_with_hit=2`
- durability gate: fail because prompt coverage stayed at `3 / 24` and the branch is still too narrow

Interpretation:

- v1.2 did recover real hits; it is not another pure geometry/stability split failure.
- The next move is still offline breadth work because there was no hidden extra tier-2 reservoir outside those three recovered prompts.

v1.3 offline curriculum:

- gate audit script: `scripts/audit_manifold_v12_gate.py`
- curriculum builder: `scripts/build_manifold_v13_curriculum.py`
- experiment config: `configs/experiments/strict/topoff1m_a_manifold_curriculum_v13_20260423.json`
- stage-A dataset: `reports/raft/topoff1m-a-manifold-curriculum-v13-20260423/manifold_v13_stage_a.jsonl`
- stage-A summary: `reports/raft/topoff1m-a-manifold-curriculum-v13-20260423/manifold_v13_stage_a_summary.json`

v1.3 build result:

- dataset rows: `64`
- composition: `39` v1.2 breadth anchors, `8` support prompt scaffolds, `9` gate-hit replays, `8` purebred anchors
- support prompt lengths: `214`, `219`, `220`, `224`, `226`, `227`, `228`, `264`
- hit replay rows: `6` family-faithful plus `3` bridge-only

v1.3 paid p24 outcome:

- stage-A summary: `reports/warmstart/pearl-micro-sft-topoff1m-a-manifold-v13-stagea-lr5e7-ep2/summary.json`
- robustness summary: `reports/robustness/pearl-topoff1m-a-manifold-v13-stagea-gate-p24-t08-s41s53s67-c128/robustness_summary.json`
- completed runs: `3 / 3`
- tier-2 hits by seed: `[0, 0, 1]`
- prompt coverage across seeds: `1 / 24`
- family-faithful hits: `0`
- only recovered tier-2 event: seed `67`, prompt step `11`, bridge-only
- stable-only counts by seed: `[9, 11, 11]`
- geometry-only counts by seed: `[5, 6, 3]`

Interpretation:

- v1.3 did finish cleanly, so this is a scientific miss, not an ops failure.
- Widening support prompts raised trainable and stability-dominant counts, but it did not preserve the v1.2 family-faithful basin.
- The branch regressed from v1.2's `3 / 24` prompt coverage and `2` family-faithful hits to one bridge-only hit with zero family-faithful transfer.
- Another near-identical `stage-A -> p24` replay is not justified.

Next rule:

- stop paid manifold v1.x replay branches until offline redesign shows nonzero family-faithful density again
- do not launch stage-B, p48, or mining from this branch line
- use v1.2 family-faithful hits as positive anchors and v1.3 stable-only / geometry-only rows as explicit negatives in the next offline constructor pass

### Phase 3: Deeper Local Optimization

Goal:

- widen to `3-5` mutations where family gates remain stable
- optimize stability and novelty without drifting out of family space
- use the p12-hit / p24-miss postmortem to rebalance parent scaffolds, prompt families, lengths, and mutation masks before the next paid train

Readiness gate:

- `50-100` strict shortlist candidates
- `24+` strict bridge/family candidates
- `16+` clusters
- source/scaffold share below `25%`

### Phase 4: Optional Distillation

Only after the constructed pool is real:

- build a strict curriculum from constructed candidates plus the best historical strict rows
- train a small stage-A branch
- gate on `p12/p24` before paying for `p48` or stage-B

## Relationship To Mining

Paid mining remains useful as a diagnostic, not as the default next move.

If used, run it in this order:

- `50k-75k` exact p12/p24 hole sweep
- only then a `250k-300k` targeted tranche
- avoid a blind `1M` run unless the smaller tranche shows real strict or near-strict density

The mining kill gate should be strict:

- `24+` tier-2/functional bridge candidates
- `8+` family-faithful or strict-family candidates
- `16+` clusters
- no single source bucket above roughly `25%`

If the `300k` targeted tranche fails, that should end the current sampling strategy, not the project. The next phase should still be manifold construction.

## Current Recommendation

Do not launch another paid run from manifold curriculum v1, v1.1, or a v1.3-shaped replay. v1.2 recovered a narrow basin; v1.3 tried to widen it and collapsed to one bridge-only hit with zero family-faithful transfer.

Immediate next step:

- build a manifold v2 offline constructor/objective branch (Complete)
- freeze the v1.2 family-faithful hits as positives and treat the v1.3 stable-only / geometry-only finalists as hard negatives (Complete)
- tighten inclusion around family-faithful transfer, catalytic blueprint preservation, and prompt/length obedience before another paid gate (Complete)

Objective panel built:

- builder: `scripts/build_manifold_v2_objective_panel.py`
- output: `reports/analysis/manifold_v2_objective_panel_20260424/`
- summary: `reports/analysis/manifold_v2_objective_panel_20260424/v2_objective_panel_summary.json`
- panel counts: `2` v1.2 family-faithful positive anchors, `45` v1.3 hard negatives, `305` v9/v1.1 drift negatives, and `190` historical support positives
- readiness: objective panel built; not a paid-gate artifact by itself

Offline constructor built (Phase 1 & 2):

- builder: `scripts/build_manifold_v2_offline_constructor.py`
- batch 1 output: `reports/analysis/manifold_v2_offline_constructor_20260424/`
- batch 2 output: `reports/analysis/manifold_v2_offline_constructor_20260424_batch2/`
- total candidates scored: `192`
- ESM status: `192 / 192` passed `>= 85`, mean `98.8`

Final Reselection:

- tool: `scripts/select_manifold_v12_repair_candidates.py` (v2-nested support added)
- status: **Ready for Paid Gate**
- selection: `34` candidates across `18` unique parent source keys
- breadth: `8` length bins, `14` exact lengths
- validation: `34 / 34` strict-manifold, core-screen, and ESM-gate passes
- ESM score range: min `92.01`, mean `98.8174`, max `99.95`
- readiness: `"offline selected set has enough strict/core/ESM breadth for a small paid gate"`

Final Curriculum:

- tool: `scripts/finalize_manifold_v2_curriculum.py`
- location: `reports/curriculum/manifold_v2_20260424/manifold_v2_curriculum.jsonl`
- composition: `34` v2-selected candidates, `8` purebred anchors
- audit status: selected-row metadata preserved, including prompts, source keys, selection rank, motif, mutation count, validation fields, and parent/source provenance

Paid p24 diagnostic outcome:

- stage-A checkpoint: `pearl-micro-sft-topoff1m-a-manifold-v2-stagea-20260424`
- gate: `pearl-topoff1m-a-manifold-v2-stagea-gate-p24-c128`
- operational status: `3 / 3` seed runs completed
- scientific status: failed durability with tier-2 hits `[0, 1, 0]`, prompt coverage `1 / 24`, and `0` family-faithful hits

Manifold v2.1 bridge-weighted follow-up:

- builder: `scripts/build_manifold_v21_bridge_curriculum.py`
- config: `configs/experiments/strict/topoff1m_a_manifold_v21_bridge_20260424.json`
- curriculum: `reports/curriculum/manifold_v21_20260424/manifold_v21_bridge_curriculum.jsonl`
- composition: `71` rows: `28` v2 strict-breadth anchors, `10` v12 family-hit replays, `3` v12 bridge-hit replays, `2` v2 bridge-hit replays, `12` support prompt anchors, `12` historical family-faithful anchors, and `4` purebred anchors
- readiness: prepared for stage-A plus p24/c128 diagnostic only; not broad paid-gate ready

Status as of April 24, 2026: **v2.4 clean-room diagnostic completed with 0 bridge hits. Methodological success (loophole closed) but discovery fail. Moving to coupling gap diagnosis.**
