# Frontier adaptation v2 FP32 folding amendment — 2026-08-23

## Status and timing

This is a prospective precision-only amendment to the unstarted frontier-v2 folding phase. It was
approved after eight base-model generation cells had completed, before any frontier-v2 candidate was
folded, and without inspecting any frontier optimization or structural endpoint value. Candidate
generation is independent of ESMFold2 numerical precision and remains bound to its existing
immutable generation contracts.

The August 21 structural amendment specified bfloat16 ESMFold2 weights and bf16 ESMC precision.
Calibration attempts under that precision failed mechanically because the pinned Biohub runtime
constructed float32 feature tensors that could not be consumed consistently by the bfloat16 model.
The successful feasibility job `job-dnui9` loaded ESMFold2 and ESMC in float32, but its result receipt
incorrectly copied the older bfloat16/bf16 identity from the structural config. That receipt is
retained as operational feasibility evidence but is invalid as the production calibration.

## Amended folding identity

The frontier-v2 folding runtime is prospectively frozen to:

- ESMFold2 model dtype `float32`;
- ESMC precision `fp32`;
- the unchanged model and source revisions, single-sequence/no-MSA mode, 20 loops, 100 diffusion
  steps, one diffusion sample, inference seed `20260821`, fused kernels, and no chunking;
- the unchanged pLDDT threshold, side-chain geometry threshold, natural-reference set, selection
  seed, and calibration acceptance gates.

The runtime must reject any precision other than this exact pair. Calibration and production must
record the same folding identity and contract hash. A self-consistent 80-reference calibration must
be rerun under the corrected identity before any endpoint fold is authorized.

## Contract separation and evidence preservation

The existing original and replication structural generation configs and their hashes are immutable
because generation has begun. This amendment therefore uses a separate calibration/folding config;
it does not rewrite those generation contracts or invalidate completed candidate reports. The final
production folding configs and GiveMeANode packet must bind the corrected calibration result while
retaining the exact generation-report hashes.

No candidate, threshold, denominator, model, arm, training seed, prompt, sampling seed, or analysis
changes. No existing calibration or generation artifact is deleted or relabeled. The corrected
calibration remains under the previously approved one-H100, `$14.985` maximum exposure.
