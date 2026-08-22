# Frontier adaptation v2 local structural execution amendment — 2026-08-22

## Status and timing

This prospective amendment was frozen after both optimization cohorts and their evaluations were
terminal, after the 104-cell structural design was frozen, and before any frontier structural
candidate was generated or any optimization endpoint was inspected. It changes orchestration only.
The models, data, arms, seeds, terminal checkpoints, prompts, 384 candidate slots per cell, folding
runtime, calibration gates, denominators, inferential units, analysis, and spend ceilings do not
change.

## Ownership transfer

The GitHub structural supervisor and structural-generation worker are retired and manually disabled.
They must remain disabled. A single local controller now owns structural generation. Tinker sampling
and GiveMeANode folding remain remote paid compute; only the supervisor and evidence state move to
the operator's machine.

The local authority state is assembled without replaying historical GitHub supervision. It combines:

- the immutable 48-cell original completion handoff;
- the terminal-valid 47-cell local replication completion state;
- the terminal-valid GitHub replication sentinel receipt;
- the exact run contract, terminal report, and checkpoint-lineage files for all 96 trained cells.

Every receipt must self-hash and match its frozen cohort, campaign, run key, and contract. Every
source file must match the SHA-256 recorded in its terminal receipt. The resulting 104-cell manifest
must self-hash and retain exactly eight shared base cells, 48 original cells, and 48 replication
cells. No scientific value is consulted during assembly.

## Local controller

`scripts/manage_frontier_adaptation_local_structural.py` is the only authorized structural-generation
controller. It validates the complete manifest and all 96 trained-source triplets before any action,
holds one nonblocking exclusive-owner lock, caps a wave at six cells, reserves exact per-cell claims,
and invokes the existing resumable generation worker without changing its contract. An interruption
retains completed candidate rows and resumes only the missing prespecified slots.

Shape validation is zero-spend and may run without an execution approval. Paid execution requires a
self-hashed `pearl.frontier-local-structural-execution-approval/1` packet whose exact SHA is separately
armed in the environment. The packet must bind the manifest, the ordered job keys, the completed
calibration, the unchanged $40 Tinker structural ceiling, no scientific changes, and no source
checkpoint deletion.

## Paid boundary

This ownership transfer does not authorize paid generation. The August 21 structural amendment still
controls the paid boundary: the 80-reference ESMFold2 calibration must complete and pass; measured
latency, exact runtime identity, provider quote, and projected production spend must then form the
final no-launch preflight for explicit approval. A failed calibration stops rather than altering the
method or thresholds.
