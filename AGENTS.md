# PEARL Agent Rules

These rules apply to every agent working in this repository, including delegated and lower-cost
agents.

1. Read `docs/SUBAGENT_RUNBOOK.md` and `docs/scaling_paradox_v1_protocol.md` before acting.
2. Default to read-only. Paid execution, cancellation, deletion, protocol changes, data rebuilds,
   and frozen-endpoint access require explicit task authority described in the runbook.
3. Never launch paid training from a laptop process. Use the immutable GitHub Actions workflow and
   one exact run key per dispatch.
4. Never treat duplicate runs as replicates, invent missing observations, hand-select endpoint
   candidates, or combine pilot and confirmatory cohorts.
5. Never stage, import, copy, rewrite, or delete quarantined untracked Concord/California material.
   A dirty worktree is expected; stage only explicit PEARL paths.
6. Never spawn another agent unless the user or supervising agent explicitly authorizes recursive
   delegation.
7. Stop and escalate on any hash mismatch, duplicate provider contract, unclear run ownership,
   missing checkpoint lineage, incomplete artifact, unplanned spend, or proposed conditional stage.

The runbook is the operational source of truth. Live provider state must always be queried; status
examples and IDs in documentation are restart aids, not evidence that a run is still active.
