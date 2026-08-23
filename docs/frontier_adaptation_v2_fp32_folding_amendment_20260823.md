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

## Completed calibration and folding successors

The corrected natural-reference calibration completed before endpoint folding in GiveMeANode job
`job-m85x4`. Its downloaded JSON has SHA-256
`b69b6339334a6d16f6774e94b38969e5e7f181c03aaf67dcafcbaf4833e59b12`, records 80 of 80 unique
references, and binds folding-contract SHA-256
`2fb4bc7859951adbcc095615edb0bf2c6b468a05bb2f9fde748fe20de6d8a723`. All references met the
unchanged pLDDT gate and 63.75% exposed both side-chain triad distances, exceeding the prospectively
frozen 85% and 45% operational acceptance gates respectively. These are calibration checks, not
frontier endpoint results.

Production folding uses the separate successor configs:

- `configs/experiments/frontier_adaptation_structural_v2_original_fp32_folding.json`;
- `configs/experiments/frontier_adaptation_structural_v2_replication_fp32_folding.json`.

Each successor explicitly names and hashes its immutable `/3` generation config. The successor
validator requires every generation, prompt, sampling, checkpoint, threshold, analysis, and model
field to be identical to that predecessor and permits only the declared bfloat16/bf16 to
float32/fp32 precision transition. Folding reports bind the successor config hash; generation
reports continue to bind the original generation-config hash. A final production spend/image packet
and explicit paid approval remain required before any endpoint job is submitted.

The user rejected Docker build contexts for production folding before any endpoint fold. No
Dockerfile or Docker-context manifest change is part of this amendment. Production execution must
use a separately versioned stock-image submission packet that binds these successor configs, the
exact source commit, each immutable generation-report hash, and the provider quote.
