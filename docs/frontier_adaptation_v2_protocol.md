# Frontier Adaptation v2 Protocol

## Scientific purpose

This is the prospective contemporary-model extension of the frozen Qwen scaling-paradox study. It
tests whether fixed-rank, fixed-update preference adaptation becomes less effective as capacity rises
within current model families. It is not a replacement for Qwen v1 and its observations must never
be pooled into the v2 confirmatory matrix.

The paper-level claim is deliberately narrow: under one frozen rank-32 DPO contract, the
true-preference advantage over a 50% shuffled-label exposure control may decline with model capacity.
The primary experimental unit is an independent training seed. Preference pairs, generated
candidates, and folds are nested observations, not replicates.

This protocol was frozen before any v2 outcome was collected or inspected.

## Models and scientifically valid comparisons

| Family | Model tag | Provider model | Total / active parameters | Role |
| --- | --- | --- | ---: | --- |
| Inkling | `inkling-small` | `thinkingmachines/Inkling-Small` | 276B / 12B | within-family small |
| Inkling | `inkling` | `thinkingmachines/Inkling` | 975B / 41B | within-family large |
| Nemotron 3 | `nemotron3-nano` | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` | 30B / 3B | ladder small |
| Nemotron 3 | `nemotron3-super` | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16` | 120B / 12B | ladder middle |
| Nemotron 3 | `nemotron3-ultra` | `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16` | 550B / 55B | ladder large |
| Nemotron 3.5 | `nemotron3p5-lightning` | `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16` | 30B / 3B | matched-capacity release control |
| GPT-OSS | `gptoss-20b` | `openai/gpt-oss-20b` | 21B / 3.6B | within-family small |
| GPT-OSS | `gptoss-120b` | `openai/gpt-oss-120b` | 117B / 5.1B | within-family large |

Mixing Nemotron 3 and 3.5 is safe only because Lightning is not inserted into the Nemotron 3 size
ladder. Nano-versus-Lightning is a separately labeled matched-capacity release control. It tests
release sensitivity at the same advertised 30B total / 3B active scale; it cannot establish a
capacity trend. Raw parameter counts are never regressed across Inkling, Nemotron, and GPT-OSS.

Primary scaling contrasts are `inkling-small - inkling`, `nemotron3-nano - nemotron3-super`,
`nemotron3-nano - nemotron3-ultra`, and `gptoss-20b - gptoss-120b`, where positive means the smaller
model has the larger seed-matched true-minus-shuffled effect. The ordered Nano/Super/Ultra ladder is
descriptive corroboration. Nano-versus-Lightning is the release control.

## Frozen training matrix

- Original seeds: 17, 29, 43.
- Prospective replication seeds: 362034, 257621, 520620.
- Arms: true preferences and a fixed 50% shuffled-label exposure control.
- Eight models × two arms × three seeds = 48 cells per cohort; 96 confirmatory cells total.
- Rank 32, beta 0.05, learning rate 5e-7, four preference pairs per update, 2,250 optimizer updates.
- Renderer is model-specific and frozen in the model row. Renderer substitution is prohibited.
- The eight 25-step original-cohort smokes are operational checks only. They are not observations.
- Original and replication remain labeled cohorts in every report. Combined summaries retain the
  cohort block and use all six predeclared seeds only after both matrices are complete.

Exact configs and plan hashes:

- `configs/experiments/frontier_adaptation_v2_original.json`
- smoke: `5c81d3419992415bc7b4681027e2c79b4f9ccfd30a0364581fb376e2aa67bb8f`
- original core: `ce4fd33d9f5f8d62d42a4ddc383222adc18c48ba1399920073beaf44879842c6`
- `configs/experiments/frontier_adaptation_v2_replication.json`
- replication core: `85660f7b99193e34a546f9eb50dfe18ff10fe42d3127232686be9b5ee7fd2593`

## Endpoints and analyses

The primary optimization endpoint is the seed-level difference between true and shuffled arms in
held-out per-residue preference-margin change. The frozen real-failure challenge is a separately
reported corroborative endpoint. Every terminal checkpoint is evaluated once, after training, on
both full immutable partitions. Inline or partial evaluation is not accepted.

Each within-family capacity contrast is summarized separately in original, replication, and combined
six-seed cohorts with a t interval, sign counts, and an exact two-sided seed-level sign-flip test.
There is no outcome-dependent p-value gate, rescue stage, model substitution, seed replacement, or
post-hoc family pooling in v2.

The biological endpoint is terminal full structural-gate yield. The exact scope is eight shared base
cells plus 48 original and 48 replication terminal adapters: 104 cells × 96 fixed candidate slots.
Invalid or duplicate generations remain denominator failures; infrastructure failures remain
unobserved and block completion. Fold outputs use the frozen ESMFold revision, calibration, pLDDT
threshold, and side-chain catalytic-triad geometry. Rare-event cell intervals are exact
Clopper–Pearson intervals. Family contrasts again operate on seed-level true-minus-shuffled yields.

## Budget and execution envelope

At freeze, the user reported $3,200.42 Tinker credit and $481.83 GiveMeANode credit. The immutable
plan contains $1,910.27 training and $139.12 endpoint evaluation, a $2,049.39 pre-structural ceiling.
Structural sampling is capped at $10.00 (estimated $8.97), for a $2,059.39 Tinker ceiling. The hard
plan plus the $25.00 continuation-recovery allowance is capped at $2,084.39. The hard authorization
envelope remains $2,300.00. GiveMeANode is capped at $481.83 and six active H100 jobs.

All paid execution is remote and supervisor-owned. Frontier optimization uses the prospective
capacity ramp below, with at most 47 paid cells active inside one cohort. Original and replication
remain mutually exclusive. Structural generation and GiveMeANode folding retain their separate
six-job limits.
Closing or disconnecting the laptop does not stop a dispatched GitHub/Tinker worker or remote H100
job. The laptop is required only to invoke the next transition or perform the mechanically specified
manual GiveMeANode submission boundary.

### Operational continuation amendment

Nemotron 3 Ultra's first core cell demonstrated before endpoint review that a complete 2,250-update
trajectory cannot fit inside the 330-minute supervised-worker boundary: the worker reached 132
updates and retained its last scheduled checkpoint at step 1. This is an execution-duration finding,
not a scientific outcome. The model, seed, data order, optimizer, rank, update budget, endpoints, and
analysis remain frozen.

The frozen smokes also show that the other frontier models have insufficient or uncomfortably narrow
headroom at core length. Executor contract v4 therefore gave every model a conservative,
supervisor-authorized segment size. Executor contract v6 retains every initial width and
prospectively widens only future continuations using result-blind Actions timing evidence:

| Model tag | Initial updates | Continuation updates |
| --- | ---: | ---: |
| `inkling-small` | 150 | 500 |
| `inkling` | 100 | 300 |
| `nemotron3-nano` | 250 | 800 |
| `nemotron3-super` | 150 | 500 |
| `nemotron3-ultra` | 100 | 250 |
| `nemotron3p5-lightning` | 250 | 800 |
| `gptoss-20b` | 300 | 900 |
| `gptoss-120b` | 250 | 800 |

The v4 continuation widths were respectively 250, 150, 400, 250, 150, 400, 450, and 400.
Their completed and already-authorized segments remain immutable evidence. The v6 widths apply only
to a continuation authorized after the v6 source commit; they do not reinterpret or extend a prior
authorization.

Each segment is capped at the original absolute step 2,250 and ends by saving the exact Tinker
optimizer/model state, full ordered batch history, cached reference margins, and hash-bound
nonterminal lineage. The ordinary scientific checkpoints at steps 500, 1,000, 1,500, 2,000, and
terminal 2,250 remain present; extra segment-boundary checkpoints are recovery infrastructure and
are not additional observations. Segment boundaries cannot enter an analysis or create a replicate.

Only the remote supervisor may authorize a continuation. It binds the predecessor Actions run and
artifact, requires monotonic completed steps and the same immutable run contract/provider lineage, and
authorizes one exact next absolute segment boundary. A timeout without a complete auditable segment,
a non-advancing checkpoint, or any lineage disagreement remains a stop condition. The 330-minute
circuit breaker is retained to preserve artifact-upload time; it is not extended toward the hosted-job
ceiling. The recovery-overhead allowance is $25, yielding a maximum Tinker ceiling of $2,084.39,
still inside the unchanged $2,300 authorization envelope.

Tinker represents each restored segment as a new provider training record. This is valid only when
the complete set of DPO records exactly equals the ordered provider IDs encoded by the audited
checkpoint lineage and every record is explicitly uncorrupted. An extra provider record outside that
chain is still a duplicate owner and stops the campaign.

### Scheduling-only performance amendment

The first Ultra workers also exposed a client scheduling defect before endpoint review. The DPO
runner waited for the custom backward result before submitting the corresponding optimizer request.
Tinker's custom-loss API has already completed the policy-logprob forward and submitted the backward
request when `forward_backward_custom` returns its future, so the optimizer request can and should be
submitted immediately, before either future is consumed. Waiting inserted an avoidable remote
worker-pool clock-cycle bubble without changing the intended update.

Executor release `frontier-adaptation-v2-executor-v1.0.2` therefore submits the custom backward and
optimizer requests back-to-back and then consumes both results. It never overlaps different
optimizer steps. Datum order, custom DPO loss, Adam parameters, restored optimizer/model state,
checkpoint boundaries, seeds, endpoints, costs, and every frozen scientific identity remain
unchanged. Each new batch record includes a `pearl.dpo-step-performance/1` timing receipt while the
existing provider `clock_cycle:unique` metric remains the authoritative backend scheduling measure.

The already-running step-2-through-151 Ultra continuation remains an unmodified sequential-schedule
baseline. The next eligible supervisor-authorized continuation is the prospective operational
comparison segment. `scripts/analyze_tinker_dpo_performance.py` must verify the exact historical
batch prefix and compare predeclared non-overlapping step ranges. This comparison is engineering
evidence only: it cannot exclude, relabel, repeat, or otherwise affect a scientific observation.

The comparison completed without endpoint inspection. Steps 152--301 retained the exact batch
prefix and valid checkpoint lineage while reducing median provider clock-cycle gap from 6 to 4 and
the measured worker training interval from about 4 h 12 min to 2 h 20 min, approximately 1.8x
observed end-to-end throughput. This removes an avoidable bubble but does not make the very large
models overnight experiments: the core contract still contains 2,250 serial optimizer updates per
cell, and Inkling and Ultra activate 41B and 55B parameters respectively.

### Deterministic rolling-capacity amendment

The original wave barriers were safe but unnecessarily serialized heterogeneous models: when one
slow cell remained active, as many as five of the six authorized slots could sit empty. Executor
contract v4 keeps the pre-randomized execution order but treats the old waves as frozen ordering and
audit metadata after each cohort sentinel has passed.

Execution order 1 remains a hard sentinel for each cohort. It must have terminal-valid training and
both endpoint evaluations before any later cell in that cohort can start. Thereafter, the supervisor
fills available capacity from one deterministic queue. Valid continuations take priority, then
terminal-checkpoint evaluations, then never-submitted training keys in pre-randomized order.
Original must be completely trained and evaluated before the replication sentinel; cohorts never
overlap. Exact active Actions IDs, kinds, campaigns, run keys, contracts, phases, timestamps, and
statuses are machine-validated before authorization. Unknown, duplicate, stale, or unowned activity
fails closed.

At the validated full-cohort tier, cohort exposure is a temporary liveness exception to that ordinary
priority. While any frozen post-sentinel identity has never started, the supervisor authorizes those
never-submitted training keys first, in their pre-randomized order, before resumptions or evaluations.
Once every identity in the cohort has started, the ordinary continuation-then-evaluation priority
returns. This prospective scheduling rule applies identically to original and replication, preserves
the one-action-type authorization boundary and active-cell cap, and consults no scientific outcome.

This is scheduling only. It changes no model, arm, seed, renderer, pair order, optimizer update,
endpoint, analysis, cohort label, or spend ceiling. Based on frozen smoke timing and the measured
pipeline improvement, strict wave barriers implied roughly 25--29 days end to end; the rolling
six-slot schedule is expected to reduce the clean-path campaign to about 15--18 days, including
endpoint evaluation and the presently estimated three-to-four-day structural phase. Provider
capacity, retries, or infrastructure failures can widen that range; they do not permit a scientific
substitution.

### Prospective 12-to-24-to-cohort capacity ramp

Before any post-sentinel v2 scientific endpoint was inspected, the user authorized a more aggressive
operational ramp because the six-cell schedule made the wall time disproportionate to the scientific
question. Executor contract v5 replaces the fixed six-cell frontier-optimization cap with three
predeclared tiers:

| Tier | Maximum active optimization cells | Machine gate |
| --- | ---: | --- |
| Initial | 12 | cohort sentinel terminal-trained and terminal-evaluated |
| Expanded | 24 | first 12 ordered cells each have an audited segment or at least 20 minutes of fresh, uncorrupted provider progress |
| Full cohort | 47 | first 24 ordered cells satisfy the same operational gate |

The observation is result-blind. The supervisor reads only Actions ownership/status/timestamps and a
sanitized Tinker snapshot containing run key, contract, stable provider ID, corruption state, and
last-request time. It does not read margins, accuracies, losses, rewards, sequences, endpoint reports,
or effect directions. An active cell counts as healthy only when it is `in_progress`, has existed for
at least 20 minutes, has exactly the expected provider continuation ownership, is explicitly
uncorrupted, and made a provider request within the previous 15 minutes. A terminal or nonterminal
segment with a valid hashed audit receipt is stronger progress evidence and also satisfies the gate.
Queued jobs do not satisfy a gate. Duplicate ownership, corruption, wrong contract, stale provider
state, cross-cohort activity, or a non-prefix launch stops advancement.

The maximum is 47 because the already-complete sentinel leaves 47 cells in a 48-cell cohort. GitHub
may queue work above the account's hosted-runner concurrency, and Tinker may time-share clients; the
ramp does not assume linear scaling. Those effects reduce realized speedup but do not change the
scientific observations. If provider capacity absorbs the ramp, original and replication optimization
can approach roughly three to five days combined instead of two weeks; adding endpoint collection
and the separately six-job structural phase gives a best clean-path estimate of roughly six to nine
days. This is an estimate, not a completion promise.

The ramp changes neither the `$2,084.39` total Tinker ceiling nor any model, arm, seed, renderer,
pair order, adapter, optimizer update, checkpoint, endpoint, analysis, or cohort label. It may expose
more of the already-authorized cohort budget concurrently. The replication sentinel and its ramp
remain blocked until every original cell and evaluation is terminal-valid.

### Prospective continuation-efficiency and event-driven refill amendment

Executor contract v6 was frozen on August 16, 2026 after the original cohort's first full-capacity
continuation pass was operationally complete and before any v2 scientific endpoint was inspected.
The amendment used only GitHub Actions identifiers, timestamps, conclusions, model tags, and exact
supervisor-authorized update counts from supervisor run `31978917585` and its 35 child workers. No
loss, reward, margin, accuracy, sequence, endpoint, or effect direction was consulted.

For each model, the prospective continuation width was bounded so the worst successful Actions
elapsed-time-per-update in that pass projected to no more than about 220 minutes. Ultra was kept more
conservative: its 250-update width projects to about 233 minutes under the separately recorded
historical slow continuation, leaving roughly 97 minutes inside the unchanged 330-minute supervised
training window. These are circuit-breaker margins, not performance endpoints or exclusion rules.
An incomplete segment still fails closed and may only resume from its last complete audited
checkpoint after primary review.

Only the number of recovery boundaries changes. Every cell still executes the same ordered 2,250
optimizer updates with the same model, renderer, pair order, seed, adapter, optimizer state, cached
reference margins, checkpoints, terminal endpoint, and analysis. The original and replication plan
hashes, experimental-unit identities, cohort boundary, active-cell cap, and spend ceilings remain
unchanged. The same prospective continuation policy is used for every continuation authorized after
v6, irrespective of cohort or scientific outcome.

Contract v6 also removes avoidable idle time without introducing a scheduler or polling loop. A
successful, supervisor-owned frontier training or checkpoint-evaluation workflow bound to a verified
`frontier-supervisor-<run-id>` tag triggers one new supervisor reconstruction in `advance` mode. The
automatic supervisor resolves the originating supervisor ID from the child title and requires the
retained tag SHA to equal the child's head SHA before checkout or reconstruction. The existing
campaign-global concurrency lock
coalesces simultaneous completion events. The triggered supervisor still reconstructs all audited
artifacts, captures a fresh sanitized provider snapshot, converges the active inventory, computes
one action type, publishes a one-time authorization, and enforces every existing ownership,
lineage, capacity, cohort, and budget gate before dispatch. There is no cron trigger. Failed,
cancelled, unrecognized-ref, non-dispatch, and validation-only child runs cannot auto-advance; they stop the
automatic chain for review. Manual `status` and `advance` remain available, but an operator must not
race an already queued or running automatic supervisor.

### Immutable supervisor-source amendment

Executor contract v7 was frozen on August 16, 2026 after a source-ref race, without inspecting any
scientific outcome. Supervisor `31985313255` began on commit `cf5741589fe87e49cd370c9e0dd688144782bf55`
and published authorization
`c6d2e26b54d8daacf5be110a651ca1ad3d1835493f10a40cb9c636827e674435` immediately before executor
v6 merged. Its dispatcher selected child workflows through moving ref `main`. One child,
`31985920144`, resolved the old commit, passed the exact authorization, and retained ordinary
continuation status. The remaining 34 resolved merge commit
`8367e36a9d6a17c372807bf5b18987453b4c7bde` and failed at the source-commit authorization guard.
For all 34, provider access and the supervised training step were skipped. They incurred zero Tinker
spend, created no provider owner or scientific observation, consume no semantic dispatch claim, and
are not runs or replicates.

Contract v7 creates a run-specific lightweight tag `frontier-supervisor-<run-id>` at the supervisor
workflow's immutable `GITHUB_SHA`, verifies that tag through the GitHub API, and dispatches every
training and evaluation child from it; a branch movement can no longer change code between
authorization and dispatch. Tag creation requires the supervisor's narrowly scoped repository-
contents write permission. Failure to create the tag, an existing tag at another commit, or a
read-back mismatch stops before child dispatch. The tag is retained as audit evidence. The 34
historical pre-authorization shells are listed by exact Actions ID and expected run key in the
executor. Reconstruction accepts them only after re-querying their immutable job steps and failed
log, proving the declared source mismatch and proving that training remained skipped. Any different
head, title, conclusion, job, step conclusion, or error message fails closed. Their sanitized
operational receipts contain no scientific values and never enter lineage, endpoints, spend, or
analysis.

Supervisor `31989649480` later exposed an operational bug in the first v7 tag-existence check. On
commit `586b0b5f7a4bcb2a8e870a2942746d6d73f61fcf`, a missing REST ref returned a 404 JSON body on
standard output; the shell suppressed the nonzero exit and mistook that body for an existing tag at
another commit. Reconstruction, provider snapshotting, and authorization computation succeeded,
and authorization `d9b94d562d644407f846a76a2a8cd01203a7b04d712a80a29efc3d45578c11fd`
was published, but tag creation and every child dispatch were skipped. The tag is absent, no child
title names that supervisor, the reconciled active inventory contained zero paid cells, and the
authorization remains an immutable one-time orphan with zero spend and zero scientific weight. No
endpoint or scientific outcome was inspected to diagnose or repair the failure.

The durable v7 implementation resolves the fully qualified tag through an exact GraphQL ref query,
where an absent ref is a successful null result rather than an error body. Any GraphQL or permission
failure remains fatal. It creates and reads back the immutable tag before publishing authorization,
then initializes an empty dispatch receipt before the first child request so any partial dispatcher
failure retains an exact prefix. These changes alter only control-plane provenance and failure
accounting; all frozen plans, cohorts, endpoints, widths, budgets, and plan hashes are unchanged.

Supervisor `31990831560`, launched against the interim tag hotfix, stopped during artifact
reconstruction before provider snapshotting or authorization when one read-only Actions metadata
query transiently returned nonzero. The same immutable run was immediately readable afterward and
the GitHub API quota was healthy. The manager therefore retries only its explicit allowlist of
read-only GitHub JSON commands up to five times with bounded backoff, reports the terminal error,
and refuses workflow dispatch or any other mutation through that retry path.

Supervisor `31991478845` then stopped while restoring the frozen dataset because its workflow
installation token had exhausted GitHub's release-asset API limit. Reconstruction, provider
snapshotting, authorization, tag creation, and dispatch were all skipped; it produced no campaign
artifact, spend, or scientific observation. The release is public and the archive remains bound to
the same frozen SHA-256 digest. Every frontier-v2 path that restores the dataset—supervisor,
original or replication training, checkpoint evaluation, and structural supervision—now uses the
public release download URL without an authenticated release-API call, retries only transport
failures within a fixed bound, and requires the unchanged strict SHA-256 check before extraction.
HTTP failure, retry exhaustion, or checksum mismatch remains fatal. This changes transport only,
not the dataset or any scientific contract.

### Prospective local-orchestration amendment

On August 16, 2026, after repeated GitHub installation-token quota failures and without inspecting
scientific outcomes, the user authorized an exclusive local control-plane takeover for one exact
frontier continuation authorization. The complete contract is recorded in
`docs/frontier_adaptation_v2_local_orchestration_amendment_20260816.md`. Tinker remains the remote
compute provider; only request submission and supervision move locally. This changes no scientific
identity, update, endpoint, analysis, cohort boundary, plan hash, concurrency cap, or budget.

Local execution is valid only through the hash-chained controller, after the competing GitHub
supervisor is disabled and live GitHub/provider ownership is proven idle and unambiguous. A partial
dispatch is an immutable prefix and never authorizes a retry. The GitHub supervisor cannot be
re-enabled until locally started segments are terminal, audited, and incorporated into versioned
state.

## Prospective interpretation tree (primary-only, never operational)

This tree creates no gate, exclusion, relaunch, or permission. Executors remain result-blind.

1. If original and replication agree in direction across several within-family contrasts and the
   structural endpoint corroborates them, frame the scaling paradox as a cross-family property of
   fixed-rank/fixed-update adaptation, bounded to the tested method and task.
2. If optimization effects reproduce but structural effects do not, frame the result as adaptation
   inertia in preference space without evidence of biological-output transfer.
3. If structural effects reproduce without a clear optimization-margin gradient, treat that as an
   endpoint dissociation requiring mechanistic follow-up, not proof that the optimizer endpoint was
   wrong.
4. If only one family shows the capacity gradient, report family dependence. Do not average it into
   a universal trend.
5. If Nemotron 3 is ordered but Inkling or GPT-OSS is not, distinguish within-generation scaling
   from cross-architecture generality.
6. If Nano and Lightning differ materially at matched capacity, release/training-recipe sensitivity
   is important; do not attribute that difference to parameter scale.
7. If Nano and Lightning agree while the Nano/Super/Ultra ladder is ordered, the capacity account is
   strengthened within Nemotron, but still does not license cross-family raw-parameter regression.
8. If original is positive and replication is null or reversed, the confirmatory conclusion is
   non-replication. Preserve both cohorts and investigate only in a separately versioned study.
9. If all contrasts are null with sufficiently narrow intervals, report a bounded negative result:
   no detectable scaling paradox under this adapter/update/data contract.
10. If intervals are wide or signs unstable, report uncertainty. Do not buy clarity through
    unplanned seeds after outcomes are known.

## Stop rules

Stop before advancing on any renderer failure, plan/hash mismatch, duplicate provider owner,
ambiguous checkpoint lineage, missing endpoint partition, incomplete 96-slot generation/fold cell,
unplanned spend, active-count uncertainty, source-commit mismatch, or request to change a frozen
scientific choice. A primary may diagnose and version a repair; an executor may not improvise one.
