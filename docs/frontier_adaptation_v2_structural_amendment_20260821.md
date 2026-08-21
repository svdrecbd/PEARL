# Frontier adaptation v2 structural amendment — 2026-08-21

## Status and timing

This is a prospective, result-blind amendment limited to the unstarted structural phase. It was
specified after optimization training began but before any frontier structural candidates were
generated or folded and before any optimization endpoint output was inspected. It does not change
training data, models, arms, ranks, seeds, checkpoints, evaluation partitions, or the experimental
unit. Existing v1 evidence and the completed/active v2 training lineage remain immutable.

No paid structural generation or production folding is authorized merely by this document. The
natural-reference calibration, exact container image digest, measured latency, provider quote, and
projected spend must form a final no-launch preflight packet for explicit user approval.

## Candidate panel

- Retain the frozen 24-prompt panel, generation settings, and terminal-only checkpoint scope.
- Expand sampling from four to sixteen prespecified seeds: `701`, `1701`, `2701`, `3701`, `4701`,
  `5701`, `6701`, `7701`, `8701`, `9701`, `10701`, `11701`, `12701`, `13701`, `14701`, and `15701`.
- Each of the 104 structural cells therefore contains 384 candidate slots; the complete campaign
  contains 39,936 slots.
- Every slot remains in the denominator. Invalid generations and within-cell duplicate sequences
  are failures. Infrastructure interruptions are unobserved and must be resumed, never converted
  into scientific failures or silently omitted.
- Candidates remain nested observations. Independent training seed remains the inferential unit;
  the fourfold candidate expansion does not create additional biological replicates.

## Structure predictor

- Use the full 48-layer `biohub/ESMFold2`, not ESMFold2-Fast.
- Use the separately revision-pinned `biohub/ESMC-6B` backbone.
- Run protein-only, single-sequence inference with no MSA.
- Freeze 20 loops, 100 diffusion steps, one diffusion sample, inference seed `20260821`, bfloat16
  model weights, bf16 ESMC precision, Biohub's fused kernels, and no chunking for these short targets.
- Reload neither model nor inference settings between candidates within a cell. Reset the same fold
  seed before every candidate so resumption and job ordering cannot change a candidate's fold.
- Preserve PDB output, per-candidate hashes, pLDDT >= 70, and the existing 3.5 Å side-chain
  Ser-His-Asp gate. No visual or manual structure selection is permitted.

The runtime lock pins the CUDA base image, Python, Torch, Biohub Transformers and ESM source
commits, model revisions, and ESMC revision. A production fold contract hashes that lock, the
calibration artifact, the inference settings, evaluator, and structure-gate libraries.

## Calibration and paid boundary

Before endpoint folding, the exact production image must fold 80 deterministically selected natural
PETase/cutinase references. The calibration is accepted only if all 80 complete, at least 85% meet
the prospectively unchanged pLDDT >= 70 threshold, and side-chain triad geometry is observable for
at least 45%. These are operational comparability checks, not data-driven threshold selection.
Failure stops the campaign for explicit scientific review; it does not permit tuning against
frontier endpoints.

The calibration records each natural sequence hash and fold latency. The preflight uses the measured
p95 fold latency, measured per-job model-load time, all 39,936 slots, 104 job starts, a 20% runtime
contingency, the live H100 hourly quote, and the immutable $481.83 GiveMeANode ceiling. Production
launch remains blocked until the resulting packet and image digest receive explicit approval.

## Budget amendment

The Tinker sampling estimate increases from $8.97 to $35.86. Its frozen ceiling increases from
$10.00 to $40.00. The resulting planned Tinker ceiling is $2,089.39, or $2,114.39 including the
existing $25.00 continuation-recovery allowance, within the unchanged $2,300 authorization.
GiveMeANode's $481.83 ceiling and six-active-job cap remain unchanged.
