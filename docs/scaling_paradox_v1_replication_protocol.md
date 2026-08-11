# PEARL Scaling-Paradox Prospective Replication Protocol

## Status and separation from v1

This protocol was prospectively declared on August 11, 2026, after the v1 sentinel completed and
while Wave A was running. The replication design was frozen without reading or using sentinel or
Wave A scientific endpoint values. Operational success, runtime, and artifact completeness were
known; effect direction and magnitude were not used.

The frozen v1 protocol, its 18 cells, and seeds 17, 29, and 43 remain unchanged. This document
creates a separate replication campaign. Replication observations must retain their own campaign,
run keys, provider metadata, artifact paths, and cohort label. They may never be relabeled as
original v1 observations or substituted for a failed v1 cell.

## Scientific purpose

The replication asks whether the v1 fixed-rank capacity contrast reproduces under the identical
dataset, renderer, optimizer, adapter, update, holdout, challenge, and structural contracts with
three new independent training seeds. It adds experimental units without expanding the model zoo or
creating candidate-level pseudoreplication.

No new model, hyperparameter, endpoint, exclusion, or threshold is introduced. The Qwen3.5-4B versus
Qwen3.5-9B comparison remains the clean within-release contrast. Qwen3.6-27B remains a separately
reported lineage extension.

## Deterministic seed contract

Training seeds were derived without outcome access. For index `i` in 1, 2, and 3:

```text
digest = SHA256("pearl-scaling-paradox-v1-replication/training-seed/" + i)
seed = unsigned_big_endian_integer(digest[0:4]) modulo 1,000,000
```

The resulting ordered seed set is **362034, 257621, and 520620**. It is disjoint from the v1 set
17, 29, and 43. The replication execution-order seed is 70422207, derived from the first four bytes
of `SHA256("pearl-scaling-paradox-v1-replication/execution-order")` as an unsigned big-endian
integer. Execution order changes scheduling only.

## Frozen replication matrix

The replication core is the exact 3 model × 2 arm × 3 seed factorial: 18 training cells.

- Models: Qwen3.5-4B, Qwen3.5-9B, and Qwen3.6-27B.
- Arms: D10 true preference and the frozen 50% shuffled-label control.
- Rank: 32.
- Beta: 0.05.
- Learning rate: `5e-7`.
- Batch: four preference pairs per optimizer update.
- Updates: 2,250.
- Checkpoints: step 1, every 500 steps, and terminal.
- Dataset, holdout, challenge, renderer, and structural contracts: byte-identical to v1.

The generated plan must contain 18 unique run-contract hashes and must not share a run key,
training seed, campaign ID, or provider contract with v1. Its estimated Tinker ceiling is $416.83.
The frozen replication launch-plan SHA is
`ac90ed77143986eeaec127983df8306c7ced37cd7aed38b87fdc2cb6e7c66b5d`.

## Analysis declared before replication execution

Independent training seed is the experimental unit. Within each model and seed, the primary
optimization contrast is true-preference minus shuffled-control change in held-out per-residue DPO
margin from the matched reference. The clean capacity contrast is the difference of that paired arm
effect between Qwen3.5-4B and Qwen3.5-9B. The analogous 27B contrast is reported separately with the
release-generation caveat.

Analysis proceeds in this order:

1. report the original three-seed v1 cohort under its frozen protocol;
2. report the three-seed replication cohort independently using the same estimands;
3. report direction and magnitude concordance without redefining success from a p-value;
4. perform a combined six-seed analysis with cohort retained as a blocking indicator;
5. use an exact two-sided sign-flip test over the six independent seed-level clean capacity
   contrasts, accompanied by the effect estimate and interval rather than a significance-only claim.

The biological endpoint remains full structural-gate yield. The frozen 24-prompt × 4-sample-seed
panel is reused unchanged. Replication terminal checkpoints add new training-seed experimental units;
the already-frozen base-model panel is a common baseline and is not regenerated or counted twice.
Structural evaluation is restricted to the fixed-rank core; replication data-exposure and rank-128
rescue remain optimization-endpoint controls.
Candidate attempts remain nested observations and every attempted candidate stays in the denominator.
The preregistered v1 checkpoint trajectory remains a secondary v1 analysis; the replication cohort
is required to repeat the primary terminal structural contrast, not every secondary trajectory.

No analysis may select seeds, exclude terminal-valid cells, change a threshold, or add candidates in
response to observed results. Missing or interrupted cells are resumed from their own immutable
lineage; they are not replaced with new seeds.

## Operational gates and waves

Prospective executor amendment: replication paid cells are not authorized by a hand-edited boolean
gate file. They are dispatched only through `.github/workflows/scaling-paradox-supervisor.yml` after
the controller has collected exact original training, provider-identity, and corrected two-partition
evaluation receipts. The supervisor pins one commit, takes the campaign-global lock, and authorizes
one wave of at most six cells. Direct paid worker dispatch is rejected.

The replication data-exposure controls are the exact 4B true-preference 2.5K and 5K cells at seeds
362034, 257621, and 520620. If and only if the frozen combined six-seed gate in
`configs/experiments/scaling_paradox_executor_v1.json` passes, replication repeats the 9B and 27B
true-preference rank-128 rescue at those same three replication seeds. Gate failure skips both
original and replication rescue stages without replacement, tuning, or reinterpretation.

Replication execution is blocked until:

1. all 18 original v1 core cells are terminal-valid or resumed to terminal validity;
2. v1 artifacts pass contract, checkpoint-lineage, provider-identity, holdout, and challenge audits;
3. the replication launch plan regenerates to its frozen SHA from the merged commit;
4. a no-spend run of `.github/workflows/scaling-paradox-v1-replication.yml` verifies the remote
   dataset archive, plan identity, and provider access;
5. the campaign controller observes sanitized evidence receipts for all 18 original cells; and
6. the provider contains no replication run key or contract SHA.

The paid worker fails when its one-time supervisor authorization is absent or does not contain its
exact run key, plan, stage, cohort, and source commit.

After the gate, use the independently randomized order in consecutive waves:

| Wave | Execution orders | Maximum active cells |
| --- | --- | ---: |
| R1 sentinel | 1 | 1 |
| R1-A | 2–6 | 5 after sentinel validation |
| R1-B | 7–12 | 6 after R1-A validation |
| R1-C | 13–18 | 6 after R1-B validation |

The six-active-cell limit includes every scaling-paradox Tinker cell across both campaigns. A
replication wave cannot overlap an active v1 wave. Paid execution runs only through the dedicated
GitHub Actions workflow; a laptop process may generate or verify a plan but may not own training.

## Conditional stages

This August 11 executor amendment prospectively adds the same three replication seeds to the frozen
v1 data-exposure and rank-128 rescue matrices. Replicated data exposure is the exact two-cell 4B
D2.5 comparison at 563 and 2,250 updates for all three replication seeds. It begins only after both
fixed-rank cores are terminal-valid.

Replicated adapter rescue is the exact rank-128 9B and 27B true-preference matrix for all three
replication seeds. Both original and replicated rescue stages remain blocked until the combined
six-seed optimization analysis satisfies every frozen rescue-gate predicate in
`configs/experiments/scaling_paradox_executor_v1.json`. A failed gate skips rescue; it never triggers
parameter tuning, replacement seeds, or an alternate rescue.
