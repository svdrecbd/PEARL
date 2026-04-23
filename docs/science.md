# Science Status

## Current State (April 22, 2026)

The project is at a strategy reset.

The `stage-b-lite` mined-data engine, strict validators, robustness harness, and local repair tooling all work operationally. The scientific issue is that the current Kimi sampling plus strict-SFT plus repair loop is not reliably producing or preserving a robust PETase/cutinase-family manifold at the short-context `p12/p24` gates.

Current canonical mined pool:

- `1,597,184` raw candidates across the first `1.0M` tranche plus the `596,992` add-on tranche
- `179` exact-unique functional hits
- `54` exact-unique family-faithful hits
- `197` lineage clusters at `0.85`

Core references:

- [reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/bundle_summary.json](../reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/bundle_summary.json)
- [reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/retrain_readiness_selected_only.json](../reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/retrain_readiness_selected_only.json)

## Best Historical Branch: `strict-core-v7-repair`

`v7` remains the best empirical branch.

- stage-A checkpoint:
  - `tinker://59c10b59-45ec-5ed4-92a9-7c06e4241d0b:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stagea-lr1e6-ep3`
- stage-B-lite checkpoint:
  - `tinker://7bb7b832-45c0-5ac0-8cea-1c3bc3f1d7ea:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v7-repair-stageb-lite-lr5e7-ep1`
- stage-A `p48` smoke passed:
  - hits by seed `[0, 2, 1]`
  - prompt coverage `3 / 48`
- full stage-B-lite robustness failed:
  - `p12`: `[0, 0, 0]`, coverage `0 / 12`
  - `p24`: `[0, 2, 0]`, coverage `2 / 24`
  - `p48`: `[0, 3, 1]`, coverage `4 / 48`

Interpretation:

> `v7` proved that repair-derived strict data can transfer, but it did not prove the model learned a broad, durable manifold.

References:

- [reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_stage_a_summary.json](../reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_stage_a_summary.json)
- [reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_stage_b_lite_summary.json](../reports/raft/topoff1m-a-strict-core-v7-repair-20260412/strict_core_v7_stage_b_lite_summary.json)
- [reports/robustness/pearl-topoff1m-a-strict-core-v7-repair-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json](../reports/robustness/pearl-topoff1m-a-strict-core-v7-repair-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67/robustness_summary.json)

## Latest Negative Branch: `strict-core-v8-coverage`

`v8` was built to broaden `v7` with bucket-capped strict selection and more bridge-anchor diversity. It failed the intended test.

- stage-A checkpoint:
  - `tinker://0e007439-8486-58fd-8a5a-9769ced7e0b2:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v8-coverage-stagea-lr1e6-ep3`
- stage-B-lite checkpoint:
  - `tinker://789989aa-dbe7-522b-a82a-1bccd9060a06:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v8-coverage-stageb-lite-lr5e7-ep1`
- stage-A `p48` smoke:
  - seed `41`: `3` functional, `2` family-faithful
  - seed `53`: `1` functional, `0` family-faithful
  - seed `67`: `0` functional, `0` family-faithful
- full stage-B-lite robustness:
  - `p12`: functional `[0, 0, 0]`, family-faithful `[0, 0, 0]`
  - `p24`: functional `[0, 0, 0]`, family-faithful `[0, 0, 0]`
  - `p48`: functional `[0, 3, 3]`, family-faithful `[0, 0, 0]`
- stage-A p12/p24 diagnostic:
  - `p12`: functional `[0, 0, 0]`, family-faithful `[0, 0, 0]`
  - `p24`: functional `[0, 0, 0]`, family-faithful `[0, 0, 0]`

Interpretation:

> Stage B was not the only problem. The `v8` stage-A generator itself failed the short-context manifold test.

## Failed `v9` p12/p24 Local Repair Rescue

The `v9` rescue tried to repair `v8` p12/p24 near-misses locally before training a new branch.

Config:

- [configs/experiments/repair/topoff1m_a_v9_p12p24_repair_20260421.json](../configs/experiments/repair/topoff1m_a_v9_p12p24_repair_20260421.json)
- [configs/experiments/strict/topoff1m_a_strict_core_v9_p12p24_repair_20260421.json](../configs/experiments/strict/topoff1m_a_strict_core_v9_p12p24_repair_20260421.json)

Repair pool:

- `12` source audits
- `134` geometry-dominant near-misses
- `0` tier-2 hits
- mean ESM score `31.6049`
- mean geometry score `0.5971`

Native repair:

- `134` hits processed
- `47,489` local variants evaluated
- `79` loose survivors
- max survivor ESM `99.08`
- mean survivor ESM `95.943`

Strict validation:

- `0` strict shortlist
- `0` strict bridge
- `0` strict family
- `0` strict consensus
- `79 / 79` rejected

Dominant rejection reasons:

- `79` failed family core screen
- `79` missing family serine motif
- `79` outside family length band
- `61` above strict catalytic gap limit

Readiness:

- `ready_for_retrain: false`
- base positives: `0`
- survivor positives: `0`

Interpretation:

> The repair pass found stable geometry-ish sequences, but they were not strict PETase/cutinase-family sequences. The failure is family-manifold drift, not runtime failure.

## Failed Manifold v1.1 p24 Transfer Test

The manifold pivot produced a validator-first offline constructor and then a capped v1.1 p24-only train/gate. The branch completed operationally, but failed scientifically.

Artifacts:

- postmortem report: [reports/analysis/manifold_v11_gate_postmortem_20260423/audit.md](../reports/analysis/manifold_v11_gate_postmortem_20260423/audit.md)
- robustness summary: [reports/robustness/pearl-topoff1m-a-manifold-v11-stagea-gate-p24-t08-s41s53s67-c128/robustness_summary.json](../reports/robustness/pearl-topoff1m-a-manifold-v11-stagea-gate-p24-t08-s41s53s67-c128/robustness_summary.json)
- gate decision: [reports/robustness/pearl-topoff1m-a-manifold-v11-stagea-gate-p24-t08-s41s53s67-c128/p24_gate_decision.json](../reports/robustness/pearl-topoff1m-a-manifold-v11-stagea-gate-p24-t08-s41s53s67-c128/p24_gate_decision.json)

Gate result:

- completed runs: `3`
- tier-2 hits by seed: `[0, 0, 0]`
- prompt coverage: `0 / 24`
- selected candidates: `72`
- raw candidates audited: `9,216`
- raw single-motif candidates: `3,030`
- raw geometry-valid candidates: `218`
- raw ESM-valid candidates: `41`
- raw single-motif plus geometry plus ESM candidates: `0`

Interpretation:

> v1.1 did not fail because the selector missed a hidden strict candidate. The sampled pool itself had no candidate satisfying the tier-2 proxy conjunction. The branch learned proxy fragments, especially stability-only and geometry-only rows, but did not enter the strict PETase/cutinase functional intersection.

The v1.2 offline lane builder has split the failed v1.1 pool into actionable lanes:

- `43` geometry-valid but ESM-failing rows
- `41` ESM-valid but geometry-failing rows
- `2,946` single-motif background negatives
- `6,186` motif-failure negatives
- `55` selected length-offtarget failures

These lanes are diagnostic/constructor inputs only. They are not a paid training set until offline replay produces nonzero single-motif plus geometry plus ESM candidates.

The first v1.2 offline repair-frontier pass produced a narrow positive:

- `4,678` strict pre-ESM repaired candidates
- `580` prompt-length/core-screen trainable pre-ESM candidates
- geometry-valid/ESM-failing smoke: `0 / 32` ESM-gate passes
- ESM-valid/geometry-failing smoke: `24 / 24` ESM-gate passes
- ESM-valid smoke score range: min `94.93`, mean `95.9562`, max `96.82`

Interpretation:

> v1.2 has shown that geometry can be repaired into high-ESM candidates for at least one ESM-valid source scaffold. It has not yet shown breadth. All `24` ready smoke candidates came from one source row, so the branch is not ready for paid training or robustness.

## Current Read

- mining/data engine: operational
- eval/finalization engine: operational
- local repair tooling: operational
- strict validator: operational and useful
- `v7`: best historical branch, but narrow and possibly partly lucky
- `v8`: failed to broaden `v7`; regressed at `p12/p24`
- `v9` repair rescue: failed to create trainable strict data from p12/p24 near-misses
- manifold `v1.1`: completed p24-only gate but produced `0` tier-2 hits and `0` raw strict-conjunction candidates
- manifold `v1.2` offline: first nonzero strict-conjunction repair signal, but currently one-source narrow
- passive local-exploit lane in finalized corpus: absent
- current SFT/mining loop: not a reliable route to the strict manifold without a strategy change

Current governing objective:

> Construct candidates inside the PETase/cutinase family manifold before optimizing stability or training behavior.

Current negative result:

> High ESM plus local geometry repair is not enough, and v1.1 showed that stability and geometry proxies remain disjoint under the current generator. The next branch must preserve family scaffold, motif identity, length band, catalytic blueprint, and ESM/stability as a conjunction before paid training.

Current positive result:

> The tooling is good enough to tell us when we are fooling ourselves. Phase 1 of the manifold constructor is now online, and the next failure to avoid is paying for more samples that only satisfy fragments of the proxy.

## Manifold Phase 1: Validator-First Constructor

The scaffold-first pivot now has a concrete local entrypoint:

- config: [configs/experiments/manifold/topoff1m_a_phase1_constructor_20260422.json](../configs/experiments/manifold/topoff1m_a_phase1_constructor_20260422.json)
- runner: [scripts/manifold_construction_experiment.py](../scripts/manifold_construction_experiment.py)
- summary: [reports/manifold/topoff1m-a-manifold-phase1-20260422/summary.json](../reports/manifold/topoff1m-a-manifold-phase1-20260422/summary.json)
- round-trip report: [reports/manifold/topoff1m-a-manifold-phase1-20260422/roundtrip_report.json](../reports/manifold/topoff1m-a-manifold-phase1-20260422/roundtrip_report.json)

Current Phase 1 result:

- `12,619` unique sequences in the scaffold bank
- `4,893` family-manifold scaffolds
- `3,769` strict-manifold scaffolds
- `274` strict candidate positives
- `272` strict-positive rows round-tripped with `0` rejects
- `79` recovered `v9` negative rows, with `0` negative family-manifold passes

## Manifold Phase 2: ESM-Scored Frontier

The shallow same-length search now has an ESM-scored frontier:

- frontier: [reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_pre_esm_frontier.jsonl](../reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_pre_esm_frontier.jsonl)
- summary: [reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_pre_esm_summary.json](../reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_pre_esm_summary.json)
- scored frontier: [reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_esm_scored.jsonl](../reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_esm_scored.jsonl)
- score summary: [reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_esm_score_summary.json](../reports/manifold/topoff1m-a-manifold-phase1-20260422/phase2_esm_score_summary.json)

Current Phase 2 result:

- `10,000` strict-manifold same-length candidates
- `4,067` one-mutants
- `5,933` two-mutants
- `96` selected parent scaffolds
- `79` contributing parent scaffolds before the frontier cap was reached
- `8` unique lengths
- `10,000 / 10,000` ESM-scored on the L40S
- min `99.73`, mean `99.9121`, max `99.98`
- all `10,000` scored `>=95`
- diversity/readiness selection passed with `230` selected strict candidates
- selected pool covers `79` parent scaffolds, `8` lengths, `133` bridge-quality rows across `48` parents, and `100` two-mutants
- selected ESM summary: min `99.8`, mean `99.9225`, max `99.98`

## Manifold Curriculum v1 Transfer Gate

We built the first small curriculum from the Phase 2 selected pool and tested whether the signal transferred back into Kimi generation.

Artifacts:

- config: [configs/experiments/strict/topoff1m_a_manifold_curriculum_v1_20260422.json](../configs/experiments/strict/topoff1m_a_manifold_curriculum_v1_20260422.json)
- dataset summary: [reports/raft/topoff1m-a-manifold-curriculum-v1-20260422/manifold_v1_stage_a_summary.json](../reports/raft/topoff1m-a-manifold-curriculum-v1-20260422/manifold_v1_stage_a_summary.json)
- training report: [reports/warmstart/pearl-micro-sft-topoff1m-a-manifold-v1-stagea-lr8e7-ep2/report.json](../reports/warmstart/pearl-micro-sft-topoff1m-a-manifold-v1-stagea-lr8e7-ep2/report.json)
- robustness summary: [reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/robustness_summary.json](../reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/robustness_summary.json)
- p12 gate: [reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/p12_gate_decision.json](../reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/p12_gate_decision.json)
- p24 gate: [reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/p24_gate_decision.json](../reports/robustness/pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128/p24_gate_decision.json)

Curriculum:

- `238` pairs
- `230` selected manifold Phase 2 rows
- `8` canonical purebred rows
- `234` unique sequences
- `133` bridge-quality selected rows

Gate result:

- `p12`: passed, tier-2 hits by seed `[1, 2, 0]`, `2 / 3` seeds with hits, `3` prompts covered
- `p24`: failed, tier-2 hits by seed `[0, 1, 0]`, `1 / 3` seeds with hits, `1` prompt covered

Interpretation:

> The manifold pool is not inert; it can induce strict hits. But v1 still behaves like a narrow attractor, not a robust learned manifold. The immediate failure is p24 prompt coverage, not runtime or scoring infrastructure.

## Manifold Curriculum v1.1 Offline Repair

The v1.1 repair attacks the specific v1 failure mode: p24 prompt/length coverage.

Artifacts:

- audit report: [reports/analysis/manifold_v1_gate_audit_20260422/audit.md](../reports/analysis/manifold_v1_gate_audit_20260422/audit.md)
- audit JSON: [reports/analysis/manifold_v1_gate_audit_20260422/audit.json](../reports/analysis/manifold_v1_gate_audit_20260422/audit.json)
- v1.1 config: [configs/experiments/strict/topoff1m_a_manifold_curriculum_v11_20260422.json](../configs/experiments/strict/topoff1m_a_manifold_curriculum_v11_20260422.json)
- v1.1 dataset summary: [reports/raft/topoff1m-a-manifold-curriculum-v11-20260422/manifold_v11_stage_a_summary.json](../reports/raft/topoff1m-a-manifold-curriculum-v11-20260422/manifold_v11_stage_a_summary.json)

Audit read:

- `23` p24 prompt holes
- `1` weak-hit p24 prompt
- `20 / 20` unique p24 requested lengths absent from the Phase 2 selected pool
- strict scaffold anchors exist at or within `1` aa of those p24 requested lengths

v1.1 dataset:

- `216` rows
- `160` balanced high-ESM Phase 2 anchors
- `48` exact p24 prompt-replay strict scaffold anchors
- `8` canonical purebred anchors
- `33` length buckets
- p24 replay anchor mean absolute length delta `0.042`; max absolute delta `1`

Interpretation:

> v1.1 is not another blind retry. It directly patches the p24 length/prompt hole that v1 exposed. It is still only an offline dataset until reviewed.

## Recommended Direction

Primary next phase:

- review the v1.1 offline curriculum before spending again
- if approved, train only a small stage-A branch and gate p24 first
- add explicit negative steering from v9-style drift, stable-only rows, and geometry-only rows
- start from natural references, canonical purebreds, old strict hits, mined family-faithful reps, and April 12 strict repairs
- infer and lock active-site blueprints
- permit only same-length edits that preserve:
  - family length band
  - canonical `GxSxG` motif identity
  - single active-site motif
  - catalytic `S/D/H` spacing
  - family core screen
- optimize ESM/stability and novelty only after strict family validity is guaranteed

Reference:

- [manifold_construction.md](manifold_construction.md)

Optional paid diagnostic:

- `50k-75k` exact p12/p24 hole sweep
- only scale to `250k-300k` targeted mining if strict or near-strict density appears
- avoid a blind `1M` run unless smaller diagnostics justify it
- do not use paid mining as the immediate next step after the failed manifold v1 p24 gate

Current ruled-out default paths:

- another tiny strict-core SFT tweak
- training on the failed `v9` repair outputs
- retrying manifold v1 unchanged
- treating `p48` functional hits without family-faithful signal as success
- blind `1M` mining as the next default move
- continuing the local Gemma path unchanged

## Repo / Engine State

- supported workflow control flow is config-driven
- shared reusable logic lives under [src/pearl](../src/pearl)
- historical PETase campaign wrappers live under [archive/2026q1_topoff1m_a/scripts](../archive/2026q1_topoff1m_a/scripts) with compatibility symlinks left behind in `scripts/`

For full chronology and engineering incidents, use:

- [notes/LABNOTES.md](../notes/LABNOTES.md)
