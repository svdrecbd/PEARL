# Phase 8 DPO Pilot Readout

Date: May 30, 2026 local time.
Updated: June 11, 2026 with W&B/local-metric review and DPO runner logging fix.

This note records what the first paid Phase 8 DPO pass did and did not show. It is intentionally conservative: the post-DPO evaluation was only one slice, `p12`, temperature `0.8`, seed `7`, so it should be treated as a directional diagnostic rather than a stable estimate of DPO-only performance. The slice is too thin to prove that DPO-only works, and also too thin to prove that DPO-only fails.

## What Ran

Tiny smoke:

- Report: [phase8-bio-dpo-smoke/report.json](../reports/tinker_dpo_smoke/phase8-bio-dpo-smoke/report.json)
- Model: `moonshotai/Kimi-K2.6`
- Pairs: `8`
- Result: completed and saved a checkpoint.

3k DPO pilot:

- Report: [phase8-bio-dpo-pilot-3k-final/report.json](../reports/tinker_dpo_smoke/phase8-bio-dpo-pilot-3k-final/report.json)
- Model: `moonshotai/Kimi-K2.6:peft:131072`
- Pairs: `3,000`
- Epochs: `1`
- Batch pairs: `4`
- Batches: `750`
- Beta: `0.05`
- Learning rate: `5e-7`
- Rank: `8`
- Checkpoint: `tinker://68b86c30-7c34-5c97-bb55-01e139610267:train:0/weights/phase8-bio-dpo-pilot-3k-final`

Post-DPO eval slice:

- Summary: [summary.json](../reports/ablations/phase8-bio-dpo-eval-fast-p12-t0p8-s7/summary.json)
- Robustness summary: [robustness_summary.json](../reports/robustness/phase8-bio-dpo-eval-fast/robustness_summary.json)
- Prompt count: `12`
- Temperature: `0.8`
- Seed: `7`
- Candidate samples per prompt: `128`
- Second-stage top-k: `16`
- Folded subset metrics: [fold_metrics.json](../reports/ablations/phase8-bio-dpo-eval-fast-p12-t0p8-s7/folds/fold_metrics.json)

## Training Signal

The DPO training path itself worked, and the June W&B/local-metric review makes the training-distribution signal stronger than the first short summary implied.

- First 10 batch mean DPO loss: `0.703`
- Last 10 batch mean DPO loss: `0.323`
- First 10 batch mean reward margin: `-0.0087`
- Last 10 batch mean reward margin: `3.43`
- First 100 batch mean DPO loss: `0.6775`
- Last 100 batch mean DPO loss: `0.3655`
- First 100 batch mean reward margin: `0.0419`
- Last 100 batch mean reward margin: `2.7476`
- Positive-min-margin batches: `6%` in the first 100, `87%` in the last 100
- Last decile mean DPO loss: `0.352`
- Last decile mean reward margin: `2.886`

Interpretation: the custom-loss Tinker DPO runner, reference-margin calculation, and pair construction are operational. The model learned to increase the chosen-vs-rejected margin on the training distribution.

Caveat: `scripts/run_tinker_dpo_smoke.py` processes the pair file in file order. The late-run margin ramp can mix policy improvement with possible differences between earlier and later pair batches. That does not invalidate the training signal, but it argues for shuffled and/or held-out DPO diagnostics before treating the curve as an unbiased yield estimate.

Infrastructure note: the W&B hook is now additive. The runner again appends every `batch_report` to the final local `report.json`, prints per-batch JSON to stdout, and has a fake-Tinker CLI regression test that fails if train mode loses local batch history.

## Generation Slice

The single completed eval slice had mixed proxy movement:

- Any serine motif: `12 / 12`
- PETase/cutinase-family motif: `2 / 12`
- Sequence-level catalytic geometry: `2 / 12`
- ESM gate pass: `3 / 12`
- Local soft trainability gate: `3 / 12`
- Functional bridge: `0 / 12`
- Family-faithful bridge: `0 / 12`

Interpretation: solo DPO appears to move local sequence/proxy behavior, but this slice does not by itself establish durable family-faithful or functional bridge behavior.

## Folded Subset

Five selected candidates were folded with ESMFold/ESM Atlas-style downstream verification:

| Candidate | Mean pLDDT | Sequence Geometry | CA Triad Geometry |
| --- | ---: | --- | --- |
| Step 0 | `33.09` | pass | fail |
| Step 2 | `36.27` | fail | fail |
| Step 4 | `34.98` | fail | fail |
| Step 9 | `25.61` | pass | fail |
| Step 11 | `26.15` | fail | fail |

Interpretation: the folded subset remains structurally weak. Sequence-level geometry did not survive structural validation in this small selected set.

## Scientific Read

This is a useful result, but it is not a DPO-only verdict.

What is supported:

- The DPO infrastructure works.
- The 10k natural-positive/hard-negative pair file is usable for paid training.
- The model can be pushed strongly toward the desired preference direction on the training objective.
- The post-DPO generation slice produced nonzero local proxy signals.

What is not supported by this slice:

- Solo DPO has not yet shown foldable novel PETase/cutinase-family design.
- Solo DPO has not yet shown family-faithful bridge recovery.
- The one completed p12/temp/seed slice is too small to estimate DPO-only performance precisely.
- The folded subset still matches the structural-hallucination failure mode that motivated OPD, but the current sample is too small to locate the DPO failure mode.

What remains open:

- Whether the training-distribution margin improvement transfers to held-out/shuffled preference batches.
- Whether DPO-only improves at different temperatures or seeds.
- Whether higher prompt coverage exposes family-faithful bridge hits that the p12 slice missed.
- Whether failures are dominated by generation, local selection, fold-model confidence, active-site placement, or family drift.
- Whether the 3k DPO checkpoint needs more pairs, a different beta/lr, more epochs, or better hard-negative composition.
- Whether sparse OPD improves the specific structural failure mode beyond what a better-characterized DPO-only run would achieve.

Working conclusion:

> DPO should remain an active baseline/control and diagnostic generator. Sparse OPD is the next comparison hypothesis, not a replacement forced by this single thin DPO slice.

## Cost Note

The 3k DPO pilot used `moonshotai/Kimi-K2.6:peft:131072`, the 128K-priced endpoint. Based on the local token estimate for the same 3k pair shape:

- `moonshotai/Kimi-K2.6`: about `$14.28`
- `moonshotai/Kimi-K2.6:peft:131072`: about `$50.00`

Use the 32K endpoint unless the run actually requires 128K context.

## Next Step

Use the DPO checkpoint as an active control and diagnostic generator:

1. Keep the May 30 DPO checkpoint as the DPO-only baseline.
2. If budget permits, run additional DPO-only slices across prompts, temperatures, and seeds before calling its yield.
3. Add shuffled and/or held-out DPO diagnostics so the training margin curve is not the only preference-learning evidence.
4. Promote folded failures and low-pLDDT selected candidates into the on-policy negative pool.
5. Build teacher traces for sparse OPD.
6. Run an 8-row sparse OPD paid smoke when the DPO baseline has enough context for a fair comparison.
7. Compare DPO-only versus DPO + sparse OPD on matched small structural readouts before scaling either path.
