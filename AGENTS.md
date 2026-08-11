# PEARL Agent Rules

These rules apply to every agent working in this repository. A **primary agent** is directly
responsible to the user for the current project task. A **subagent** is any delegated, lower-cost, or
context-limited agent working under a primary or supervisor.

1. Read `docs/SUBAGENT_RUNBOOK.md` and `docs/scaling_paradox_v1_protocol.md` before acting. If the
   prospective replication is in scope, also read `docs/scaling_paradox_v1_replication_protocol.md`.
2. The primary agent owns engineering and research judgment within the user's authority. It may
   design, investigate, interpret, and make versioned decisions. It may not silently rewrite a frozen
   contract after data collection begins.
3. A subagent is an executor, not a decision-maker. It may monitor, perform an exact authorized run or
   validation, and make a narrowly mechanical repair such as a missing import. It may not choose or
   change scientific methods, datasets, models, endpoints, statistics, exclusions, budgets, or stages.
4. Subagents default to read-only. Paid execution and minor repairs require an explicit bounded
   assignment described in the runbook.
   Within that assignment, the low-stakes FAQ permits autonomous read-only, reversible, zero-spend,
   scientifically inert choices without asking the primary about every command.
5. Never launch paid training from a laptop process. Use the immutable GitHub Actions workflow and
   one exact run key per dispatch.
6. Never treat duplicate runs as replicates, invent missing observations, hand-select endpoint
   candidates, or combine pilot and confirmatory cohorts.
7. Never stage, import, copy, rewrite, or delete quarantined untracked Concord/California material.
   A dirty worktree is expected; stage only explicit PEARL paths.
8. A primary agent may delegate bounded tasks. A subagent must never delegate or spawn another agent.
9. Stop and escalate on any hash mismatch, duplicate provider contract, unclear run ownership,
   missing checkpoint lineage, incomplete artifact, unplanned spend, or proposed conditional stage.

The runbook is the operational source of truth. Live provider state must always be queried; status
examples and IDs in documentation are restart aids, not evidence that a run is still active.
