# Frontier Adaptation v2 sentinel-relay amendment — 2026-08-18

## Scope and evidence boundary

This is a result-blind operational repair authorized after GitHub failed to create the expected
downstream supervisor transitions for successful replication-sentinel children. No loss, reward,
margin, accuracy, sequence, endpoint, or effect-direction artifact was inspected to make this
repair. Training child `32151460370` completed successfully at step 100 without creating a
downstream supervisor transition. After manual supervisor transition `32173257867`, training child
`32174564429` completed successfully at step 350 and again created no downstream supervisor
transition.

The `workflow_run` trigger was present on the default branch during both observations. Regardless of
GitHub's internal suppression mechanism, the observed trigger path is not a durable campaign clock.
The historical v6 no-schedule contract remains preserved as historical evidence. This amendment
changes only how the already-frozen supervisor is invoked; it does not change a run key, model,
dataset, seed, rank, learning rate, checkpoint width, endpoint, evaluation, statistic, exclusion,
budget, or stage boundary.

## Relay contract

`.github/workflows/frontier-adaptation-v2-sentinel-relay.yml` was initially scheduled every ten
minutes and could also be started manually for validation. It is hard-coded to the one exact
replication-sentinel run key.
It has no Tinker credential and cannot dispatch a paid worker directly. Its only permitted mutation
is requesting `frontier-adaptation-v2-supervisor.yml` on `main` with `mode=advance`.

Before that request, the relay must establish all of the following from result-blind control-plane
metadata:

1. the latest exact sentinel child has a recognized supervisor-owned title and dispatch event;
2. that child is terminal success;
3. its named source supervisor is terminal success on the same source SHA;
4. the immutable source-supervisor tag resolves to that SHA;
5. the unique source-supervisor dispatch receipt binds that child run ID to the sentinel run key;
6. no recognized supervisor transition is active; and
7. no newer supervisor transition has already followed the child.

The relay re-snapshots and repeats its decision immediately before mutation. It shares the
supervisor concurrency group, so an active supervisor serializes the relay behind it. A failed,
cancelled, malformed, wrong-event, wrong-SHA, missing-receipt, missing-tag, or otherwise
unrecognized state is a hard failure. An active, absent, or already-advanced state is a successful
no-op.

The supervisor retains all scientific and paid-execution authority. The relay cannot supply a run
key, source supervisor ID, segment endpoint, worker workflow, provider credential, or budget. It
only asks the supervisor to reconstruct authoritative state and decide again.

## Completion and ownership boundary

This relay exists only to carry the exact replication sentinel through terminal training,
evaluation, and the existing `replication_sentinel_hold`. After that hold and creation of the final
Charon package, both the relay and supervisor must be disabled before arming Charon. The relay cannot
launch any of the remaining 47 replication runs.

Subagents remain read-only for this control-plane surface. Any relay stop or failure, missing receipt,
tag mismatch, duplicate provider contract, unclear ownership, or unexpected action is a primary-agent
stop for review.

## 2026-08-19 liveness closeout

The scheduled relay is retired. A transient GitHub artifact-download failure caused supervisor run
`32218023816` to fail during result-blind reconstruction. The relay correctly refused to mask that
failure, but its ten-minute schedule then repeated the same terminal stop without creating new
evidence or a recovery transition. A later manual `status` reconciliation, run `32330913152`,
successfully reconstructed the same campaign state and reproduced one exact next authorization.
This established that the source artifact and checkpoint were intact and that the failure was in
the hosted transport/control plane.

The workflow now has `workflow_dispatch` only and is disabled in GitHub. It remains available as a
readable diagnostic artifact, but it is no longer a campaign clock and may not be re-enabled as a
schedule. Further sentinel work must use an explicit, result-blind supervisor transition or a
separately frozen local-takeover contract. This changes no scientific or paid-execution field.
