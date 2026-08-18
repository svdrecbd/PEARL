# Frontier Adaptation v2 Local-Orchestration Amendment — 2026-08-16

## Status and reason

This is a prospective, result-blind operational amendment. It was authorized after repeated GitHub
installation-token quota failures prevented the frontier supervisor from reconstructing already
audited Actions artifacts. No loss, reward, margin, accuracy, sequence, endpoint, or effect direction
was inspected or used.

The frozen experiment is unchanged. Models, cohorts, arms, seeds, renderers, data order, rank, beta,
learning rate, optimizer state, total 2,250 updates, segment boundaries, endpoints, analyses, plan
hashes, active-cell cap, and spend ceilings remain exactly as declared. Tinker still performs the
paid computation remotely. Only the process that submits and supervises the already-authorized
Tinker requests moves from a GitHub-hosted runner to the project owner's Mac.

## Exclusive takeover contract

Local paid execution is permitted only through `scripts/manage_frontier_local_wave.py` and only for
one exact machine-generated `dispatch_training_resume` authorization. It is not a general local
launcher and does not authorize new cells, alternate boundaries, evaluation substitutions, retries,
or a second wave.

Before any paid request, the controller must prove all of the following:

1. the source supervisor status run completed successfully and supplied the exact authorization;
2. the authorization canonical SHA, plan SHA, run keys, source Actions IDs, completed steps, segment
   endpoints, and semantic dispatch claims all validate;
3. no frontier supervisor, training worker, or checkpoint-evaluation worker is queued or running;
4. the competing GitHub frontier supervisor is manually disabled;
5. every predecessor artifact is downloaded once, audited against its frozen plan row, and copied to
   an immutable local source backup before its working directory is resumed;
6. a fresh exhaustive, result-blind provider snapshot reproduces the exact authorization and finds no
   unknown contract, corruption, ambiguous owner, or duplicate outside the already-classified
   quarantine;
7. the controller source is a clean Git commit and the local API credential is present without being
   written to the ledger.

Any disagreement stops before launch. A partial launch is an immutable valid prefix: already-started
segments continue, later keys are not started, and nothing is automatically retried.

## Exact-once and audit guarantees

The controller writes a canonical JSONL hash chain before and after each boundary. The ledger records
the takeover, source restoration receipts, live provider snapshot hash, per-key launch intent,
process ID, exact authorization receipt, exit state, and result-blind artifact-audit receipt. Each
event is `fsync`ed to both the ignored repository state directory and a separate local mirror.

For every run key, intent is durable before process creation. If the controller or network fails
between intent and the recorded trainer PID, that key becomes an incident requiring provider and
process reconciliation; the controller must never infer that absence of a receipt means the request
was not accepted. Re-running `prepare` or `launch` against a nonempty ledger is forbidden.

The controller remains alive under macOS `caffeinate` while its trainers run. Sleep prevention is
availability infrastructure only. It provides no retry authority and does not weaken the checkpoint,
lineage, ownership, or artifact gates.

## Scientific disposition

A locally supervised continuation is the same experimental unit only when it restores the exact
authorized predecessor checkpoint and optimizer/model state, retains the run key and complete ordered
batch history, advances monotonically to the exact authorized endpoint, and passes the frozen
continuation or terminal artifact audit. It is not a replicate. Process locality is operational
metadata and is not an analysis factor.

Local failure never creates permission to replace a seed, relaunch a segment, choose a different
checkpoint, inspect an outcome, or resume from an unrecorded provider object. Original and
replication remain separate, and replication remains blocked until the complete original cohort is
terminal-trained and terminal-evaluated.

## Return to GitHub ownership

The GitHub supervisor may be re-enabled only after every locally started key is terminal and audited,
the local ledger and provider lineage have been incorporated into a versioned controller state, and a
no-spend status reconstruction proves exactly one owner per semantic dispatch claim. Re-enabling it
while any local trainer or unresolved local intent exists is a duplicate-run incident.

## Prospective original-completion automation

Before the active 35-cell local wave produced any endpoint evaluation, the project owner authorized
an additional result-blind operational controller: `scripts/manage_frontier_original_completion.py`.
Its authority is mechanically bounded to the already-frozen original/core plan SHA
`ce4fd33d9f5f8d62d42a4ddc383222adc18c48ba1399920073beaf44879842c6`.

After—and only after—the active wave records 35 valid segment audits, the controller may:

1. recognize the nine cells whose existing authorization already reaches update 2,250;
2. preserve immutable backups of the other 26 intermediate artifacts, audit their exact checkpoint
   and optimizer lineage, and continue those same experimental units directly to update 2,250;
3. consolidate the 13 pre-existing and 35 local terminal-training receipts into an exact 48-cell
   original cohort;
4. evaluate the exact 35 original cells lacking an immutable endpoint evaluation, using the same
   frozen evaluator, holdout, challenge set, normalization, and checkpoint contract; and
5. emit a 48-training/48-evaluation completion gate and exit.

Direct continuation to the already-frozen terminal update changes only operational slicing after the
current wave. It does not change optimizer state, batch order, total updates, checkpoint identity,
endpoint, cohort, exclusion, or analysis. The decision was made without inspecting loss, reward,
margin, accuracy, sequence, endpoint, or effect direction.

The controller writes a durable launch intent before every process creation and a start record after
it. An intent lacking a start record is permanently ambiguous and causes a human-escalation stop;
it is never retried automatically. A recorded start may be recovered only by finding its unique live
process or by passing the complete frozen artifact audit. Provider snapshots and authorizations are
immutable once written and are not regenerated during recovery.

This automation grants no authority whatsoever for replication, structural sampling, analysis,
outcome inspection, exclusions, conditional stages, or publication decisions. Its final state is a
hard conversational boundary: original optimization is complete, replication has not started, and
the primary agent must return to the project owner before any next step.

On the sole authoritative Mac, the controller runs through the versioned
`deploy/macos/org.pearl.frontier-original-completion.plist`. The launch agent restarts only an
unexpected nonzero exit. A safety stop or successful 48/48 completion exits zero, so neither can
become an automatic retry loop. The wrapper loads the ignored local credential, enforces an
exhaustive provider-list bound, and holds `caffeinate`; it contains no replication entrypoint.
