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

## Current Read

- mining/data engine: operational
- eval/finalization engine: operational
- local repair tooling: operational
- strict validator: operational and useful
- `v7`: best historical branch, but narrow and possibly partly lucky
- `v8`: failed to broaden `v7`; regressed at `p12/p24`
- `v9` repair rescue: failed to create trainable strict data from p12/p24 near-misses
- passive local-exploit lane in finalized corpus: absent
- current SFT/mining loop: not a reliable route to the strict manifold without a strategy change

Current governing objective:

> Construct candidates inside the PETase/cutinase family manifold before optimizing stability or training behavior.

Current negative result:

> High ESM plus local geometry repair is not enough. The repair path must preserve family scaffold, motif identity, length band, and catalytic blueprint as hard constraints.

Current positive result:

> The tooling is good enough to tell us when we are fooling ourselves. The next failure to avoid is paying for more samples that only satisfy fragments of the proxy.

## Recommended Direction

Primary next phase:

- build a scaffold-first manifold-construction pipeline
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

Current ruled-out default paths:

- another tiny strict-core SFT tweak
- training on the failed `v9` repair outputs
- treating `p48` functional hits without family-faithful signal as success
- blind `1M` mining as the next default move
- continuing the local Gemma path unchanged

## Repo / Engine State

- supported workflow control flow is config-driven
- shared reusable logic lives under [src/pearl](../src/pearl)
- historical PETase campaign wrappers live under [archive/2026q1_topoff1m_a/scripts](../archive/2026q1_topoff1m_a/scripts) with compatibility symlinks left behind in `scripts/`

For full chronology and engineering incidents, use:

- [notes/LABNOTES.md](../notes/LABNOTES.md)
