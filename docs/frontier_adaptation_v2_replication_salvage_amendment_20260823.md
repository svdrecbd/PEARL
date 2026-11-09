# Frontier adaptation v2 replication-only salvage amendment — 2026-08-23

## Status and reason

This amendment was written after all eight shared-base and 48 replication structural-generation
cells were complete, before any frontier endpoint candidate was folded, and without inspecting any
frontier structural endpoint. The 48 original-cohort adapters are no longer sampling-capable on
Tinker. Their immutable training/evaluation evidence and archived adapter bytes remain preserved,
but the original structural-generation cohort cannot currently be completed under its frozen
native-provider contract.

The program is closing for lack of further training budget. The user authorized completion of the
already-generated replication half so it can provide a labeled directional readout and be archived.
This amendment does not convert that partial readout into the completed preregistered result.

## Exact salvage scope

- Include the eight already-complete shared base cells and all 48 already-complete replication cells.
- Exclude all 48 unavailable original structural cells; do not impute, substitute, regenerate, or
  pool historical observations into their place.
- Preserve every model, arm, replication seed, prompt, sample seed, sample index, denominator rule,
  folding identity, calibration, threshold, and family-stratified analysis from the frozen hybrid
  structural and FP32 folding amendments.
- Report the output as `replication_only_salvage`, not as the 96-cell confirmatory result.

## Required post-generation order

1. Validate and hash the exact 56 completed generation reports.
2. For the confirmatory sample-index-0 core, retain all 21,504 slots in their denominators, globally
   deduplicate valid sequences, run the novelty/memorization and stratification audits, and fold each
   globally unique valid sequence once with result mapping back to every eligible slot.
3. For discovery sample indices 1--3, apply the frozen deterministic filters, global exact dedup,
   pinned ESM2-8M scoring, pinned ESM2-650M rescoring of the top 20%, and the frozen 96 + 24 + 48
   selected/audit panel. Discovery results remain separate from the confirmatory endpoint.
4. Partition the resulting fold set into six immutable disjoint H100 shards. Use the approved stock
   CUDA image and the exact FP32 ESMFold2/ESMC calibration; do not build or use Docker contexts.
5. Require six complete shard receipts before replication-only analysis.

## Result-blind ESM2 identity correction

The first salvage scoring invocation stopped before loading a model or producing a score because
the hybrid amendment's `af8b9c9c...` value is not a revision in either named Hugging Face model
repository. It appears to identify shared upstream source rather than either model artifact. Live
read-only `git ls-remote ... HEAD` resolution before any score was observed returned the exact model
commits below:

- `facebook/esm2_t6_8M_UR50D`: `c731040fcd8d73dceaa04b0a8e6329b345b0f5df`;
- `facebook/esm2_t33_650M_UR50D`: `08e4846e537177426273712802403f7ba8261b6c`.

Salvage discovery scoring binds those two exact commits. This corrects an impossible artifact
identity; it does not change the named models, funnel thresholds, ranking order, selection sizes, or
any observed endpoint.

## Interpretation boundary

The salvage analysis can estimate replication-cohort seed-level arm differences, family contrast
directions, structural yields, and whether any signal is large enough to justify future work. It
cannot establish the preregistered original-plus-replication claim, estimate between-cohort
consistency, or erase the missing original structural cohort. Any manuscript or archive must state
that limitation directly.

## Post-protocol exploratory ESM3 replacement

After the program was designated for closure and the preregistered paper endpoint was abandoned,
the user explicitly authorized replacing the frozen ESM2 discovery ranker with the strongest
locally available ESM3 model rather than preserving the dead confirmatory contract. The in-flight
ESM2 command was stopped without producing a selection artifact. No ESM2 score or shortlist is
consumed downstream.

The replacement ranks all 8,026 survivors of the unchanged deterministic filter from scratch with
`biohub/esm3-sm-open-v1` revision `47f0545b2b6daf26a93439a3cd610f4f7f3d5478`, using ESM code
revision `d0207ea3c8cbf072679ece3bb332787d25e06852`. The scalar score is a deterministic eight-partition
masked mean sequence log-likelihood: every residue is masked and scored exactly once, with
interleaved residue partitions used to make complete scoring tractable on the remaining H100.
The 96 ranked, 24 random-survivor, and 48 disjoint random-audit panels are then selected from this
ESM3-scored population. This output is explicitly exploratory and supersedes the ESM2 discovery
selection only for the replication-only salvage analysis; it does not retroactively alter the
abandoned preregistered endpoint.

## Post-hoc ESM3 repeat-screen correction

Inspection of the first ESM3 ranking, before folding any discovery candidate, showed that masked
sequence likelihood was being dominated by trivially predictable tandem repeats and literal amino
acid alphabet cycles. The unchanged entropy and homopolymer filters did not reject high-entropy
periodic strings. The first ESM3 artifact is retained unchanged as evidence of this failure mode.

The user then authorized a local, zero-GPU post-hoc correction. Every one of the 8,026 ESM3 scores is
retained without recomputation. Before ranking, a sequence is excluded if any of these deterministic
conditions holds: maximum whole-sequence offset agreement across periods 1--100 is at least 0.80;
an exact tandem run covers at least 0.40 of the sequence; fewer than 0.75 of its 5-mers are distinct;
or one residue occupies more than 0.20 of the sequence. The 96 ranked, 24 random-survivor, and 48
disjoint audit panels are rebuilt from the remaining population with seed 20260822.

These thresholds were selected after observing the failed first ESM3 ranking and therefore define
an explicitly post-hoc exploratory analysis, not a preregistered correction. All per-sequence repeat
metrics, overlapping rejection reasons, source hashes, and both old and corrected selections are
preserved. No paid compute may be launched merely to apply this correction.

The completed screen excluded 1,824 unique sequences and retained 6,202. Its corrected funnel SHA is
`aad67099bf44169c28590d3a88afc1a2d08bf48ccb026ee6ada545a0e63c8a2c`; the JSON file SHA-256 is
`471e07e0e829aa8204d7970c30b001b90a01a3964157b3b6889232fa278f2570`. None of the first failed
ESM3 top 96 remains in the corrected top 96. The corrected 168-sequence discovery panel overlaps the
confirmatory fold catalog in 15 sequences, so the rebuilt six-shard packet contains 10,790 unique
folds for 11,419 total confirmatory-plus-discovery mappings.
