# Frontier adaptation v2 hybrid structural amendment — 2026-08-22

## Status and timing

This prospective, result-blind amendment was written after the ESMFold2 natural-reference
calibration passed all three gates and before any frontier-v2 structural candidate was generated,
folded, or inspected. It changes the generation scope and adds post-generation infrastructure.
The models, arms, seeds, terminal checkpoints, prompt panel, folding runtime, calibration gates,
denominators, inferential units, analysis framework, and spend ceilings for the confirmatory core
do not change from the August 21 amendment.

## Design shape

The campaign adopts the **hybrid confirmatory-plus-discovery** design:

- **Confirmatory core:** exactly 104 cells × 384 slots = 39,936 slots. This is unchanged from the
  August 21 amendment. Every slot remains in its denominator. Invalid generations and within-cell
  duplicate sequences remain failures. The primary endpoint remains full structural-gate yield
  (pLDDT ≥ 70 AND side-chain Ser–His–Asp triad ≤ 3.5 Å) on every valid global-unique sequence.

- **Discovery extension:** each cell generates an additional 1,152 slots per cell by requesting
  four samples per prompt/seed pair instead of one. The first sample index (index 0) constitutes
  the existing confirmatory slot. Sample indices 1, 2, and 3 constitute the discovery extension.
  Discovery slots are separately labeled and never enter the confirmatory denominator or analysis.

Total generation: 104 cells × 24 prompts × 16 sample seeds × 4 sample indices = 159,744 slots.

## Post-generation pipeline

After Tinker generation completes and before any GMN folding submission:

### Global exact deduplication

Build a global map of unique sequence SHA-256 hashes across all 104 cells. Each unique valid
sequence in the confirmatory core is folded exactly once. The resulting fold result is mapped back
to every eligible cell/slot. Within-cell duplicates remain denominator failures as before.
Cross-cell exact duplicates retain their slot mapping but share a single fold computation.

### Novelty/memorization audit

A frozen audit checks every valid candidate against three reference sets:

1. Training DPO preference-pair sequences (chosen and rejected)
2. Held-out evaluation partition sequences
3. Prompt panel reference sequences

For each candidate: report whether it is an **exact match** (SHA-256 collision), a **near match**
(≥ 90% sequence identity via pairwise alignment or k-mer overlap), or **novel**. These labels are
reported as descriptive statistics and do not alter the primary endpoint. A separate
novelty-qualified yield (passes among novel candidates only) is reported alongside the primary.

### Family/prompt/length stratification

Per-cell yields are stratified by prompt length bin before aggregation. The analyzer reports
yield per length-bin per model/arm/seed alongside the cell-wide total. This satisfies the
`family_stratification_required` flag already present in both frontier structural configs.

### Six-shard folding executor

Valid global-unique confirmatory sequences are partitioned into six immutable, disjoint shards.
Each shard is a self-hashed JSON manifest binding the exact set of sequence hashes to their
cell/slot origins. Shards execute as independent GMN batch jobs with per-shard completeness and
hash validation. A shard may be resumed without affecting completed shards.

## Discovery extension funnel

The 119,808 discovery-extension slots pass through a staged funnel inspired by historical PEARL:

1. **Cheap deterministic filters:** amino-acid validity, minimum/maximum length, complexity
   (Shannon entropy ≥ threshold), repeat suppression (no homopolymer runs > N). All thresholds
   frozen in this amendment.
2. **Exact deduplication:** remove exact duplicates globally within the discovery pool.
3. **ESM2-8M plausibility scoring:** score surviving candidates with `facebook/esm2_t6_8M_UR50D`
   revision `af8b9c9c5ca79a3d7f7d1ffca1ada9b0fb0ab876`. Record per-sequence mean log-likelihood.
4. **Bounded ESM2-650M rescoring:** rescore the top 20% by ESM2-8M score using
   `facebook/esm2_t33_650M_UR50D` revision `af8b9c9c5ca79a3d7f7d1ffca1ada9b0fb0ab876`.
5. **Selected-panel folding:** fold the top 96 candidates by combined ESM2 score plus 24
   uniformly random survivors (for unbiased audit). Total selected folds: 120.
6. **Randomized audit:** additionally fold 48 randomly selected candidates that did NOT make
   the top panel, to estimate unselected-pool quality.

Discovery results are reported separately from the confirmatory endpoint. They cannot be pooled
into the primary analysis under any circumstance.

## Budget amendment

| Item | Confirmatory only | Hybrid (confirmatory + discovery) |
|---|---:|---:|
| Tinker generation slots | 39,936 | 159,744 |
| Estimated Tinker cost | $35.86 | $143.44 |
| Tinker ceiling | $40.00 | $160.00 |
| Unique confirmatory folds | ~30,000 est. | ~30,000 est. |
| Selected discovery folds | — | 120 + 48 = 168 |
| ESM2 scoring | — | local CPU/GPU, <$1 |
| GMN folding ceiling | $481.83 | $481.83 (unchanged) |

The increased Tinker ceiling of $160.00 replaces the previous $40.00. The total Tinker authorization
budget becomes $2,204.39 including the $25 continuation-recovery allowance, still inside the $2,300
envelope. The GMN ceiling remains unchanged at $481.83.

## Implementation requirements

Before any paid generation launch, the following must be implemented and pass zero-spend tests:

- [ ] Four-sample-per-request generation worker extension with stable sample indexing
- [ ] Global cross-cell exact-deduplication mapper
- [ ] Novelty/memorization auditor (exact hash match + near-match detection)
- [ ] Family/prompt/length-bin stratified analyzer
- [ ] Six-shard folding manifest builder and executor
- [ ] Discovery funnel filters, ESM2 scorer, selection logic
- [ ] End-to-end shape/hash/denominator/resume/dedup/novelty test suite
- [ ] Updated Tinker generation approval packet at $160.00 ceiling

No paid execution is authorized until every item above is complete and tested.
