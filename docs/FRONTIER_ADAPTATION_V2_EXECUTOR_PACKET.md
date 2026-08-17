# Frontier Adaptation v2 Executor Packet

## Role

You are an Executor, not a research or engineering decision-maker. Read `AGENTS.md`,
`docs/SUBAGENT_RUNBOOK.md`, and `docs/frontier_adaptation_v2_protocol.md` completely. You may invoke
one exact supervisor transition, monitor, collect operational artifacts, run frozen validators, and
perform the mechanically specified GiveMeANode boundary. You may not inspect endpoint values,
interpret results, change code or contracts, choose a model/seed/renderer, dispatch a paid worker
directly, cancel, substitute, relaunch, or spawn another agent.

## Clean path

The complete order is fixed:

1. original eight-model renderer smokes;
2. original 48-cell core and full two-partition checkpoint evaluations;
3. replication 48-cell core and full two-partition checkpoint evaluations;
4. frozen optimization analysis;
5. 104 structural-generation cells;
6. 104 remotely owned ESMFold jobs;
7. frozen original, replication, and combined structural analyses;
8. primary-agent interpretation and manuscript writing.

Frontier optimization follows the machine-enforced 12-to-24-to-47 capacity ramp below. Original and
replication never overlap. Structural generation and GiveMeANode folding remain capped at six active
jobs. Tinker pre-structure is capped at $2,049.39; planned total Tinker is
$2,059.39, with a separately bounded $25 continuation-recovery allowance and a combined $2,084.39
ceiling inside the $2,300 authorization envelope. GiveMeANode is capped at $481.83. Hash mismatch,
duplicate ownership, missing lineage, partial artifact, unknown active count, renderer failure,
unplanned spend, or an unhandled state means stop and escalate.

## Optimization supervisor

Primary-only local takeover exception: the project owner prospectively authorized the exact process
in `docs/frontier_adaptation_v2_local_orchestration_amendment_20260816.md` after GitHub quota failures.
That path does not grant an Executor or subagent local paid authority. Only the primary may prepare
and start one existing machine authorization with `scripts/manage_frontier_local_wave.py`, and only
after disabling the GitHub supervisor and proving result-blind provider ownership. Any local intent,
partial prefix, process failure, or ledger mismatch is a stop; never rerun the controller or re-enable
GitHub to fill the remainder.

Status is result-blind and no-spend:

```bash
gh workflow run frontier-adaptation-v2-supervisor.yml --ref main -f mode=status
```

Executor contract v6 normally refills capacity automatically. Each successful supervisor-owned
frontier training or checkpoint-evaluation child bound to a verified `frontier-supervisor-<run-id>`
tag triggers one result-blind supervisor `advance`; the trigger first requires that tag SHA to equal
the child's head SHA. Simultaneous events coalesce behind the existing campaign-global lock. Before
invoking a
manual transition, query the supervisor runs and do not proceed while an automatic supervisor is
queued or in progress. There is no time-based schedule. A failed, cancelled, validation-only,
non-dispatch, or unrecognized-ref child does not auto-advance and remains a stop for review.

Executor contract v7 creates and verifies immutable tag `frontier-supervisor-<run-id>` at the exact
supervisor commit and dispatches every child from that tag rather than moving `main`. Tag creation,
collision, or read-back failure stops before child dispatch. This prevents an in-flight authorization
from crossing a merge boundary. Supervisor
`31985313255` crossed the earlier moving-ref boundary once: child `31985920144` retained the old head
and its ordinary authorized continuation, while 34 exact children on merge commit `8367e36` failed
before provider access or training. Those 34 are machine-audited pre-authorization shells with zero
spend and zero scientific weight; they do not consume a dispatch claim. Any failure that does not
match that exact registry and step-level proof remains an escalation.

The first v7 tag check failed closed in supervisor `31989649480` because `gh api` emitted a missing-
ref 404 body on standard output and the shell treated it as an existing tag. Authorization
`d9b94d562d644407f846a76a2a8cd01203a7b04d712a80a29efc3d45578c11fd` was preserved, but no tag,
dispatch receipt, child workflow, provider run, spend, or scientific observation was created. The
authorization is an immutable one-time orphan and must never be reused. The durable check uses an
exact GraphQL qualified-ref lookup, verifies the tag before publishing authorization, and initializes
the dispatch receipt before requesting the first child. Executors must not replace this with parsing
human-readable REST error text.

Interim supervisor `31990831560` stopped during reconstruction on a transient read-only Actions
metadata failure; provider snapshotting, authorization, and dispatch were skipped. The manager may
retry only allowlisted GitHub reads with bounded backoff and must fail closed afterward. It never
retries workflow dispatches or other writes.

Supervisor `31991478845` stopped before reconstruction because its installation token exhausted the
GitHub release-asset API limit. It created no authorization, tag, child, provider run, spend, or
scientific observation. Every frontier-v2 dataset restore now uses the public release URL with
bounded transport retries and the unchanged strict SHA-256 verification, without calling the
authenticated release API. Never remove or weaken the digest check.

When explicitly assigned a transition, or assigned to carry the frozen clean path until a stop
condition:

```bash
gh workflow run frontier-adaptation-v2-supervisor.yml --ref main -f mode=advance
```

Do not call `frontier-adaptation-v2.yml` or
`frontier-adaptation-v2-checkpoint-evaluation.yml` directly. The supervisor reconstructs state from
Actions artifacts, validates predecessors, counts active workers, publishes a one-time authorization,
and dispatches only the next frozen transition batch. Workers are GitHub/Tinker-owned; laptop disconnect does not
stop them. A training worker has a 330-minute supervised window. Invoke the next supervisor
transition only after at least one prior child is terminal and auditable or capacity is otherwise
known to be available. Do not tight-poll: use Actions completion state or a bounded status check.

The supervisor may internally repeat artifact reconstruction when, and only when, active inventory
finds a paid worker that became terminal after the preceding reconstruction. Each crossing must add
at least one new audited Actions marker, and the total crossings cannot exceed the frozen active-cell
cap. Every retry occurs before authorization, refreshes both Actions artifacts and the result-blind
provider snapshot, and cannot dispatch on a stale attempt. No audited progress, an error of any other
kind, or exhaustion of that finite bound fails closed. This internal convergence does not renew an
Executor's authority or permit an Executor to rerun a failed supervisor.

Every frontier model is deliberately segmented because the frozen smoke timings provide inadequate
headroom to promise a 2,250-update core inside that window. Current initial/continuation widths are
150/500 for Inkling Small, 100/300 for Inkling, 250/800 for Nano, 150/500 for Super, 100/250 for
Ultra, 250/800 for Lightning, 300/900 for GPT-OSS 20B, and 250/800 for GPT-OSS 120B. These v6
continuation-only increases were frozen prospectively from result-blind Actions timing; prior
segment authorizations remain immutable. Segment sizes are selected only by the protocol and
controller; the Executor never selects them. A continuation is not a relaunch: it
restores the predecessor artifact and exact optimizer/model state, retains the run key, contract,
seed, data order, cached reference margins, provider owner, and ordered batch history, and advances
to one absolute step authorized in the receipt. The pre-segmentation Ultra Actions run `31554744343`
is an exact allowlisted step-1 bootstrap; the manager validates it mechanically and does not count
the unpersisted steps 2--132.

For an Executor this introduces no discretionary command. After any segment is terminal and its
artifact exists, invoke the same supervisor `status` or assigned `advance` transition shown above.
The supervisor will return or dispatch `dispatch_training_resume` when and only when the continuation
is valid. Never call the worker directly, enter a source run ID, choose a segment size, extend the
timeout, or treat an intermediate segment as terminal training evidence. An unexpected timeout or
incomplete segment artifact is an escalation, not permission to retry. Multiple Tinker DPO records
are expected only for restored segments; the terminal provider audit must prove that their IDs
exactly equal the checkpoint lineage. Any additional or missing ID is a duplicate/ownership failure.

Core scheduling is rolling after a hard sentinel. Execution order 1 in each cohort must complete
training and both endpoint evaluations before later keys become eligible. The controller then
validates the exact active-run inventory and fills free slots, in deterministic priority order:

1. valid resumable segments in the pre-randomized run order;
2. evaluations for terminal-trained cells;
3. never-submitted training cells in the pre-randomized run order.

There is one controller-enforced full-tier liveness rule. Once the validated 47-cell tier is open,
any still-unstarted frozen post-sentinel identities temporarily move ahead of resumptions and
evaluations. They are dispatched in pre-randomized order until every cohort identity has started;
then the ordinary priority above resumes. This applies to original and replication alike. It is not
Executor discretion and does not authorize manual key selection, mixed action types, extra cells, or
outcome inspection.

The old wave number remains audit metadata; it is not a reason to leave slots idle. Original must be
entirely complete before replication begins. One authorization contains only one action type. If it
fills fewer than all evidence-authorized free slots, an Executor assigned to carry the clean path may
invoke `advance` again after that supervisor run has succeeded so the controller can authorize the
next action type. Stop if the supervisor returns a non-dispatch action other than an ordinary
capacity or observation-window wait, or if ownership is ambiguous.

After each cohort sentinel is terminal-trained and terminal-evaluated, capacity is mechanical:

1. the supervisor may fill up to 12 active training/evaluation cells;
2. after the first 12 ordered post-sentinel cells each have either a valid segment receipt or 20
   minutes of fresh uncorrupted provider progress, it may fill to 24;
3. after the first 24 satisfy the same gate, it may fill all 47 post-sentinel cohort cells.

The controller—not the Executor—evaluates those gates from sanitized operational state. It requires
an exact Actions identity and contract, `in_progress` state for a live-progress gate, a 20-minute
observation window, exactly the expected provider continuation owners, `corrupted=false`, and a
provider request no more than 15 minutes old. A queued GitHub job counts against authorized exposure
but does not prove provider health. Scientific endpoint values, losses, rewards, margins, sequences,
and effect directions are neither collected nor consulted.

When assigned to carry the clean path, invoke `advance` once after the sentinel audit. After that
supervisor succeeds, wait until at least 20 minutes after the last of the tier's active workers
started, then invoke `advance` again. Repeat once for the 24-to-47 gate. If some cells finish an
auditable segment earlier, the controller may accept those receipts without waiting. Do not manually
declare a tier healthy, change the timestamps, inspect scientific logs, or directly dispatch the
remainder. GitHub runner queuing or stale provider activity produces an ordinary wait; corruption,
duplicate ownership, a wrong contract, or cross-cohort activity is an escalation.

The source release includes the scheduling-only v1.0.2 amendment described in the protocol. It
submits the custom backward and optimizer requests before waiting on either result and records
operational timing evidence. This changes no scientific contract and grants no new Executor choice.
Do not hand-edit performance rows or choose comparison windows. After the first v1.0.2 continuation
is terminal-valid, a primary may run the frozen comparison against its exact v1.0.1 predecessor:

```bash
python scripts/analyze_tinker_dpo_performance.py \
  --baseline-batches BASELINE_ARTIFACT/batch_reports_checkpoint.json \
  --candidate-batches CANDIDATE_ARTIFACT/batch_reports_checkpoint.json \
  --baseline-start-step 2 --baseline-end-step 151 \
  --candidate-start-step 152 --candidate-end-step 301 \
  --output PERFORMANCE_COMPARISON_JSON
```

If the predecessor ends at a different supervisor-authorized boundary, stop for a primary to version
the comparison rather than inventing new ranges. Performance evidence never advances or blocks a
scientific wave; only the ordinary continuation audit does.

That prospective comparison is now complete and mechanically valid; it showed about 1.8x observed
end-to-end throughput for the candidate segment. It grants no Executor authority and requires no
repeat. Executor contract v4 added bounded segmentation for all models and the rolling-capacity
queue. Executor contract v5 added only the prospective result-blind capacity ramp. Executor contract
v6 widens future continuation boundaries and adds completion-triggered supervisor refills using only
sanitized operational evidence. Executor contract v7 pins child source commits through retained
run-specific audit tags and records the exact zero-spend moving-ref incident. None changes any
scientific identity or total planned spend.

For local no-spend reconstruction:

```bash
export PEARL_FRONTIER_STATE="$PWD/reports/frontier_adaptation_v2_state"
python scripts/manage_scaling_paradox_campaign.py \
  --executor-config configs/experiments/frontier_adaptation_v2_executor.json \
  sync-github --state-dir "$PEARL_FRONTIER_STATE"
python scripts/manage_scaling_paradox_campaign.py \
  --executor-config configs/experiments/frontier_adaptation_v2_executor.json \
  write-manifest --output "$PEARL_FRONTIER_STATE/campaign_manifest.json"
```

The frozen analysis command, after all 96 evaluation receipts exist, is:

```bash
python scripts/analyze_frontier_adaptation_v2.py \
  --evaluations-root EVALUATION_ARTIFACT_ROOT \
  --state-dir "$PEARL_FRONTIER_STATE" \
  --output "$PEARL_FRONTIER_STATE/analysis/frontier_optimization.json"
```

An Executor runs it but does not open or interpret its output.

## Structural generation

```bash
gh workflow run frontier-adaptation-v2-structural-supervisor.yml --ref main -f mode=status
gh workflow run frontier-adaptation-v2-structural-supervisor.yml --ref main -f mode=advance
```

The supervisor refuses to build the 104-cell manifest until all required training and evaluation
receipts are terminal-valid. It dispatches at most six exact generation jobs and retains every one of
the 96 candidate slots per cell.

After all generation artifacts exist, build the exact GMN manifest from a clean checkout at the
frozen `frontier-adaptation-v2-executor-v1.0.1` executor tag:

```bash
python scripts/build_frontier_adaptation_gmn_manifest.py \
  --structural-manifest STRUCTURAL_MANIFEST \
  --generation-root GENERATION_ARTIFACT_ROOT \
  --context-output-dir GMN_CONTEXT_DIR \
  --git-ref EXACT_TAG_COMMIT_SHA \
  --output FRONTIER_GMN_MANIFEST
```

The manual provider boundary is mechanical and one-job-at-a-time:

```bash
python scripts/manage_frontier_adaptation_gmn.py --manifest FRONTIER_GMN_MANIFEST next \
  --state-dir GMN_STATE --quoted-max-cost-usd PROVIDER_QUOTE \
  --output GMN_STATE/next_authorization.json
python scripts/manage_frontier_adaptation_gmn.py --manifest FRONTIER_GMN_MANIFEST prepare-submission \
  --state-dir GMN_STATE --authorization GMN_STATE/next_authorization.json \
  --context-archive SELECTED_CONTEXT_TAR_ZST \
  --output GMN_STATE/prepared_context.json
# Submit only the exact prepared context on the specified NVIDIA H100 image/entrypoint.
python scripts/manage_frontier_adaptation_gmn.py --manifest FRONTIER_GMN_MANIFEST record-submission \
  --state-dir GMN_STATE --prepared-context GMN_STATE/prepared_context.json \
  --provider-job-id PROVIDER_JOB_ID --output GMN_STATE/last_submission.json
python scripts/manage_frontier_adaptation_gmn.py --manifest FRONTIER_GMN_MANIFEST audit-result \
  --state-dir GMN_STATE --job-key SELECTED_JOB_KEY --provider-job-id PROVIDER_JOB_ID \
  --gmn-result gmn_result.json --structure-report structure_report.json \
  --output GMN_STATE/last_result_receipt.json
```

Never submit before the one-time reservation and prepared-context receipt. Record the immutable
provider ID immediately. If network loss interrupts only the remote ledger anchor, use the exact
`retry-anchor` command; do not append a second event or resubmit the job.

Run each cohort's structural analyzer separately, with replication pointed at the exact original base
reports, then combine:

```bash
python scripts/analyze_frontier_adaptation_structural.py \
  --config configs/experiments/frontier_adaptation_structural_v2_original.json \
  --reports-dir ORIGINAL_REPORTS --structural-manifest STRUCTURAL_MANIFEST \
  --output ORIGINAL_ANALYSIS
python scripts/analyze_frontier_adaptation_structural.py \
  --config configs/experiments/frontier_adaptation_structural_v2_replication.json \
  --reports-dir REPLICATION_REPORTS --shared-base-reports-dir ORIGINAL_BASE_REPORTS \
  --structural-manifest STRUCTURAL_MANIFEST --output REPLICATION_ANALYSIS
python scripts/analyze_frontier_adaptation_structural_combined.py \
  --original ORIGINAL_ANALYSIS --replication REPLICATION_ANALYSIS --output COMBINED_ANALYSIS
```

The interpretation tree in `docs/frontier_adaptation_v2_protocol.md` is primary-only background. It
must never influence execution, exclusions, retries, or stopping behavior.
