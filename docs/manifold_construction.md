# Manifold Construction Plan

## Status

As of April 22, 2026, the project should treat the Kimi sampling plus strict-SFT loop as a partially successful but unreliable discovery engine, not as the primary path to the next result.

The current evidence says:

- `strict-core-v7-repair` was the best historical branch, but its durability was narrow.
- `strict-core-v8-coverage` did not broaden that signal; it regressed at `p12/p24`.
- The `v8` stage-A diagnostic also failed at `p12/p24`, so `stage-b-lite` was not the sole failure.
- The `v9` p12/p24 local repair pass produced stable repaired sequences but `0` strict-valid candidates.
- Another paid mining tranche remains possible, but it is no longer the highest-quality next move unless we explicitly want a diagnostic.

The recommended next phase is to construct candidates inside the PETase/cutinase family manifold from the start.

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

Success:

- no strict reference is falsely rejected
- no failed `v9` survivor is accidentally accepted

### Phase 2: Shallow Same-Length Search

Goal:

- run `1-2` mutation beams around diverse scaffolds
- produce strict-valid variants without paid generation

Initial gate:

- `20+` strict candidates
- `8+` scaffold clusters
- no cluster above `25%`
- all candidates pass strict family validation before any training decision

### Phase 3: Deeper Local Optimization

Goal:

- widen to `3-5` mutations where family gates remain stable
- optimize stability and novelty without drifting out of family space

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

Do not launch another broad paid run until the team decides whether it wants:

- a cheap empirical diagnostic from targeted mining, or
- a direct engineering pivot into the constructor.

The technically cleaner next step is the constructor.
