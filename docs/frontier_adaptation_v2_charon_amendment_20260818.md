# Frontier Adaptation v2 Charon amendment — 2026-08-18

## Scope and timing

This prospective, result-blind operational amendment was frozen before any Frontier Adaptation v2
replication training began, and scientific values were not consulted in selecting its operational
shape. It does not change the frozen original or replication plan, model
identities, datasets, seeds, rank, optimizer, update counts, checkpoint interval, terminal endpoint,
evaluation partitions, analyses, cohort boundary, planned budget, or scientific interpretation.

The original cohort remains governed by the August 16 original-only completion controller and must
reach an audited 48/48 training/evaluation hard stop. GitHub then owns only the replication sentinel:
execution order 1 must be terminal-trained and terminal-evaluated. At that boundary, executor
contract v8 requires the GitHub supervisor to return the result-blind hold
`replication_sentinel_complete_pending_charon_takeover`; it may not dispatch a post-sentinel cell.

## Dedicated control plane

Charon is a dedicated, continuously powered x86-64 Windows host running Ubuntu 24.04 under WSL2.
Tinker remains the remote compute provider. Charon replaces GitHub only as the post-sentinel request
and supervision control plane. This is not general permission for laptop-local paid execution.

The package is built only after the sentinel hold from a clean immutable commit. It contains the
exact git bundle, the frozen public dataset archive and digest, the original 48/48 completion
handoff, the sentinel receipts, and the successful hold receipt. It contains no credentials.
Installation may be a short supervised procedure; convenience automation is not a scientific
requirement. Before arming, the operator supplies the Tinker credential locally, authenticates the
GitHub CLI, runs the read-only verification suite, and confirms stable power, network, disk, and a
disabled GitHub frontier supervisor.

## Frozen post-sentinel ramp

Charon authorizes exactly the 47 remaining replication run keys in frozen launch-plan order and
starts each directly toward the unchanged terminal step 2250. The runner retains the frozen
500-update scientific checkpoint cadence; removing GitHub's 330-minute worker slicing changes only
the transport boundary, not the optimization trajectory or recorded checkpoints.

Capacity is opened mechanically and without reading scientific values:

1. start the first 12 post-sentinel identities;
2. after every one of those 12 is either terminal-audited or has at least 20 minutes of fresh,
   unique, uncorrupted provider progress, open the prefix to 24;
3. after the first 24 satisfy the same gate, open the complete 47-cell post-sentinel prefix.

The controller then audits exact terminal training receipts, runs the two frozen checkpoint
evaluations for each of those 47 cells, combines them with the GitHub sentinel receipts, writes one
48/48 replication completion gate, and hard-stops. It has no analysis or structural-generation
entrypoint.

## Ownership and failure rules

Preparation requires a clean source tree, exact plan hashes, exact original and sentinel receipt
lineage, a successful matching GitHub hold, a disabled supervisor, no nonterminal GitHub frontier
work, and a fresh provider snapshot containing no post-sentinel replication ownership. Any mismatch
stops before authorization.

Every training and evaluation launch is preceded by a durable, hash-chained intent mirrored to the
Windows filesystem. An intent without a recorded start is ambiguous and is never retried. Existing
provider ownership, duplicate run contracts, stale or corrupted provider progress, missing lineage,
invalid artifacts, reappearing GitHub ownership, source changes, or an incomplete local process set
are fail-closed conditions. Expected safety stops produce a durable blocked state and no automatic
retry. A primary must audit any unexpected controller restart before permitting further work.

Subagents are read-only around Charon. They may report status under an exact assignment, but may not
build, prepare, arm, restart, repair, broaden, or replace this controller, enable or disable the
GitHub supervisor, or fill a partial prefix.
