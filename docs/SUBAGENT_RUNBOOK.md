# PEARL Fail-Closed Subagent Runbook

## Purpose

This is the drop-in guide for a lower-cost or context-limited agent. Its job is to make useful,
bounded progress without repeating the August 10 duplicate-run and contaminated-analysis failure.
If an instruction conflicts with the frozen protocol, the agent stops and reports the conflict.

The subagent is not the scientific principal investigator or engineering lead. It may execute an
already-declared contract; it may not redesign, reinterpret, or extend one.

For the active scaling-paradox campaign, `docs/SCALING_PARADOX_EXECUTOR_PACKET.md` is the exact
happy-path checklist. Its supervisor/receipt process supersedes the older direct-dispatch examples
below. Direct paid worker dispatch is now mechanically rejected.

For the contemporary frontier extension, `docs/frontier_adaptation_v2_protocol.md` and
`docs/FRONTIER_ADAPTATION_V2_EXECUTOR_PACKET.md` are the governing sources. Frontier v2 is a separate
prospective 96-cell confirmatory matrix across Inkling, Nemotron, and GPT-OSS. It does not replace,
relabel, or pool the Qwen v1 observations. Use only the frontier supervisors for v2 paid work.

The clean-path research design and campaign engineering are complete. Remaining clean-path work is
operational: invoke one frozen supervisor transition at a time, monitor remotely owned jobs, audit
their immutable artifacts, execute the frozen analyses, and hand the validated outputs to the
primary for interpretation and manuscript writing. This statement of campaign maturity grants no
additional authority. Any condition that is not already handled mechanically by the supervisor or
this runbook is an escalation to the primary, not an invitation to design a workaround.

## Authority classes

### Primary agent

The primary agent is directly accountable to the user and may exercise engineering and research
judgment within the user's authorization. This includes:

- choosing engineering architecture and implementation strategy;
- investigating unexpected behavior and deciding whether it is mechanical or scientific;
- designing or revising experiments prospectively;
- choosing analysis methods and interpreting validated results;
- deciding whether a stage gate has passed;
- proposing or approving budgets, concurrency, resume, cancellation, or a conditional stage;
- writing scientific claims and manuscript interpretation;
- assigning bounded tasks to subagents and reviewing their output.

Primary authority does not permit retroactive outcome-dependent changes. Once a scientific contract
has collected data, a substantive change requires a new version, explicit rationale, and preservation
of the old observations.

### Subagent

A subagent has no engineering or research decision authority. It may do only the following when the
assignment states the exact scope:

1. **Monitor:** query status, logs, provider metadata, spend, checkpoints, and artifacts; report facts.
2. **Execute:** dispatch or resume exact pre-approved run keys, run frozen validation/analysis
   commands, and download or hash artifacts.
3. **Minor maintainer:** repair an obvious mechanical defect with zero scientific effect, on a branch,
   with focused tests and primary-agent review before deployment.

A repair is minor only when all of these are true:

- it does not change a frozen hash, run identity, dataset contents, model, renderer, seed,
  hyperparameter, prompt, candidate set, endpoint, threshold, cohort, statistic, or interpretation;
- it does not decide whether to exclude, relaunch, cancel, resume, or advance a stage;
- the before/after behavior is unambiguous and can be covered by a focused regression test;
- it creates no paid action on its own.

Examples of minor repairs: a missing import, an incorrect module entrypoint, a non-semantic portable
path fix, or lossless report serialization. Examples that are not minor: changing a dependency
version to alter model behavior, substituting a renderer, adjusting a threshold, skipping a failed
candidate, changing a statistical procedure, or treating an unexpected result as invalid.

If there is any doubt, the issue is not minor. The subagent reports it to the primary agent without
patching, relaunching, or working around it.

## Low-stakes autonomy FAQ

Rigid agents become useless when every harmless choice requires escalation. A subagent may proceed
without asking the primary when **all** of these are true:

1. the action is inside the assigned objective and file/run scope;
2. it is read-only, or a locally reversible mechanical change;
3. it creates no spend and no external mutation;
4. it cannot change a scientific identity, observation, selection, interpretation, or stage gate;
5. the result and rollback are obvious.

If all five are true, use reasonable judgment and continue. If any answer is no or unclear, ask the
primary. A subagent may perform one bounded diagnostic to resolve uncertainty; it must not spiral
through repeated retries or broaden the investigation.

### Can I choose commands and tools for a read-only check?

Yes. Choose among equivalent read-only commands, narrow searches, provider queries, artifact reads,
and log views. Prefer canonical sources and report which source was used.

### Can I retry a failed status query or artifact download?

Yes, up to three bounded attempts with sensible backoff when the operation is idempotent and free.
Retrying a query is not permission to redispatch, resume, cancel, or replace a run.

### Can I answer routine status, timing, path, or terminology questions?

Yes. Query live state when it may have changed, label estimates as estimates, and distinguish queued,
running, checkpointed, terminal, validated, and scientifically analyzed. Do not turn a status answer
into interpretation of an experimental result.

### Can I stop my own watcher or local diagnostic process?

Yes, after verifying it is only a local observer and does not own remote work. Stopping a local
`gh run watch` is harmless; cancelling the GitHub workflow is not.

### Can I use temporary files or adjust presentation?

Yes, under a validated temporary directory. It is also fine to adjust log verbosity, output ordering,
or report formatting when content and hashes are unchanged. Do not overwrite repository artifacts or
clean the dirty worktree.

### Can I fix a missing import, typo, or portable path that blocks my assigned task?

Yes, if it satisfies every minor-repair condition above. Keep the change inside the assigned scope,
use a branch, add a focused regression test, and hand it to the primary for review. Do not merge,
deploy, relaunch, or spend based on the repair without primary approval.

### Can I run an already-frozen validation or analysis script?

Yes. Mechanical execution and verification are allowed. Choosing a different method, modifying the
script's scientific behavior, excluding outputs, or interpreting the result is a primary-agent task.

### Can I classify an obvious operational status?

Yes: for example, `queued`, `build_failed`, `in_progress`, `timed_out`, or `artifact missing`, when
the provider reports it directly. Deciding that a failed cell is scientifically excludable, should be
replaced, or has passed a stage gate belongs to the primary.

### Can I touch unexpected untracked files or make the worktree clean?

No. Ignore and report them. Never stage, move, rewrite, or delete quarantined or user-owned files.

### Can I make a small improvement that seems obviously useful but is outside my assignment?

No. Record it as a suggestion in the handoff. "Useful" is scope expansion, not low-stakes autonomy.

### When should I escalate immediately?

Escalate before any spend, external-state mutation not named in the assignment, frozen-contract
change, scientific judgment, destructive action, duplicate ownership, cancellation/relaunch choice,
or ambiguous repair. Escalation should include the observed fact and smallest safe next action, not a
large speculative diagnosis.

## Supervisor dispatch template

Use this block when assigning work to a lower-cost agent. Do not send a vague instruction such as
"keep the campaign moving."

```text
Read AGENTS.md and docs/SUBAGENT_RUNBOOK.md completely before acting.
SUBAGENT ROLE: Monitor | Executor | Minor maintainer
OBJECTIVE: one bounded deliverable
IN-SCOPE FILES OR RUN KEYS: explicit list
EXTERNAL AUTHORITY: read-only | exact mutations allowed
MAX CONCURRENCY: integer
MAX SPEND EXPOSURE: USD amount, or $0
STOP CONDITIONS: explicit list
REQUIRED VALIDATION: commands or artifact checks
RETURN: the required end-of-task handoff ledger
Do not delegate further. Do not broaden scope. Escalate instead of improvising.
```

## Thirty-second orientation

PEARL is testing a narrow scaling-paradox claim: under a fixed rank-32 adapter and optimizer-update
budget, preference adaptation may show capacity-dependent inertia across Qwen3.5-4B, Qwen3.5-9B,
and Qwen3.6-27B. True-preference training is compared with a 50% shuffled-label exposure control at
seeds 17, 29, and 43. The confirmatory core contains 18 independent training cells. A separately
versioned prospective replication adds seeds 362034, 257621, and 520620 only after the original core
is terminal-valid; replication cells must never be substituted into or silently pooled with v1.

Canonical sources, in priority order:

1. `docs/scaling_paradox_v1_protocol.md` — claim, exclusions, stages, endpoints, and stop rules.
2. `configs/experiments/scaling_paradox_v1.json` — models, seeds, hyperparameters, and stage matrix.
3. `reports/scaling_paradox_v1/core_launch_plan.json` — generated exact run keys and order; regenerate
   read-only if absent.
4. `.github/workflows/scaling-paradox-v1.yml` — the only approved paid Tinker coordinator.
5. `configs/experiments/scaling_paradox_structural_v1.json` and its frozen JSONL panel — biological
   endpoint contract.
6. GitHub Actions artifacts and provider metadata — live/terminal operational evidence.

Replication work additionally requires, in priority order:

1. `docs/scaling_paradox_v1_replication_protocol.md` — cohort separation, seeds, analysis, and gates.
2. `configs/experiments/scaling_paradox_v1_replication.json` — exact replicated matrix.
3. `.github/workflows/scaling-paradox-v1-replication.yml` — its only paid coordinator.

Do not use the untracked `HANDOFF.md`, `PROJECT_LUMINOSITY.md`, `infra/`, old Concord scripts, old
California Synthetic scripts, or old H100 scripts as PEARL authority. They are quarantine material.
Do not stage, move, delete, or import them.

Frozen identities for scaling-paradox v1:

- launch-plan SHA: `f63f3bd2f9f0654c819f3f5a806145847c9b899ae16859d870c7a3b320d43226`
- replication launch-plan SHA: `ac90ed77143986eeaec127983df8306c7ced37cd7aed38b87fdc2cb6e7c66b5d`
- dataset manifest SHA: `1f410d4346b354b789408729c2c7cfc1f0bdef3b9580716171d86593bd9e9a22`
- portable data archive SHA: `ffad79ec8e104bf06979882e186290ea4d94b87531e48b111e954b6c09e8e962`
- structural prompt-panel SHA: `551ccd6e65db9eac2ee6e019ebe4f3744fc46912461ed4b974a09edef144bab9`
- ESMFold revision: `75a3841ee059df2bf4d56688166c8fb459ddd97a`

If a regenerated plan differs, do not update these values and do not launch. Escalate.

## Why the previous campaign failed

The disaster was not caused by one bad model. It was a control-plane failure:

- multiple local processes launched the same paid contracts;
- duplicate processes shared names, logs, and output directories;
- provider identity was not checked before launch;
- incomplete and contaminated datasets were treated as controls;
- accidental duplicates were at risk of being counted as biological replicates;
- provisional figures mixed incompatible cohorts and silently synthesized missing observations;
- scripts labeled as LigandMPNN and ESM3 did not actually run those methods;
- laptop-local processes were mistaken for durable remote execution.

Every rule below blocks one or more of those failure modes.

## Mandatory start-of-task checklist

Report these five items before taking a mutating action:

1. Role and one-sentence task.
2. Exact files, run keys, or provider objects in scope.
3. Whether any action can spend money or change external state.
4. Maximum concurrency and worst-case spend authorized for this task.
5. Stop conditions that will trigger escalation.

Then run read-only checks:

```bash
git status -sb
git branch --show-current
git log -5 --oneline
.venv/bin/python scripts/launch_scaling_paradox_v1.py --stage core
```

For live work, query GitHub and the provider. Never infer state from an old local PID or report:

```bash
gh run list --workflow scaling-paradox-v1.yml --limit 20
.venv/bin/tinker -f json run list --limit=0
```

Do not print secrets. Load `TINKER_API_KEY` only through the encrypted GitHub secret or a local ignored
environment file. Never place it in a command line, issue, PR, report, or chat response.

## Parallel core execution policy

Parallel cells are scientifically permitted because each cell has a unique model, arm, seed,
contract hash, provider identity, and output directory. Completion order is not an experimental
variable. Parallelism is forbidden inside one cell or across two dispatches with the same run key.

The pre-randomized order is retained in consecutive waves with at most six active core cells:

| Wave | Execution orders | Dispatch count after sentinel | Estimated cost ceiling |
| --- | --- | ---: | ---: |
| Sentinel | 1 | 1 | $45.2819 |
| A | 2–6 | 5 | $93.6627 |
| B | 7–12 | 6 | $176.1429 |
| C | 13–18 | 6 | $101.7463 |

This reduces the core from roughly 60–70 sequential hours to approximately 20–24 hours if provider
capacity is available, while limiting the damage radius of an undiscovered failure to one wave.

Wave A is blocked until order 1 has all of the following:

- successful GitHub conclusion;
- downloaded artifact with matching run and launch-plan contracts;
- 2,250 recorded optimizer batches;
- a terminal checkpoint plus ordered checkpoint lineage;
- `corrupted=false` in provider metadata;
- complete holdout and challenge reports.

Wave B is blocked until every Wave A cell is terminal-valid or has been explicitly classified and
resumed. Wave C has the same gate on Wave B. Submit allowed run keys in ascending execution order;
they may run and finish concurrently.

An Executor subagent must obtain run keys from the generated plan, verify the frozen plan SHA, and
dispatch one workflow per run key. There is deliberately no bulk paid shell loop. For each allowed
cell:

```bash
gh workflow run scaling-paradox-v1.yml --ref main \
  -f mode=execute \
  -f stage=core \
  -f run_key=EXACT_RUN_KEY \
  -f launch_plan_sha=f63f3bd2f9f0654c819f3f5a806145847c9b899ae16859d870c7a3b320d43226
```

Immediately record the returned Actions run ID beside the run key. A second dispatch with the same
key is forbidden. If a run times out after training starts, restore that run's artifact and use the
documented `resume_run_id`; never create a replacement experimental unit.

Do not launch `data_exposure` or `adapter_rescue` in parallel with the core merely because budget is
available. Those stages answer conditional questions. Adapter rescue is permitted only if the frozen
core analysis reproduces capacity-dependent inertia.

## Prospective replication execution policy

The replication is a separate 18-cell campaign, not an extension of an active v1 wave. Its exact
seeds are 362034, 257621, and 520620; its estimated Tinker ceiling is $416.83. It remains blocked
until all 18 original v1 cells are terminal-valid and audited. Do not inspect an interim v1 effect to
change its seeds, matrix, analysis, or decision to execute.

Regenerate its plan without spending:

```bash
.venv/bin/python scripts/launch_scaling_paradox_v1.py \
  --config configs/experiments/scaling_paradox_v1_replication.json \
  --stage core \
  --plan-dir reports/scaling_paradox_v1_replication
```

The plan must contain exactly 18 unique keys and reproduce SHA
`ac90ed77143986eeaec127983df8306c7ced37cd7aed38b87fdc2cb6e7c66b5d`. After the original-core gate,
the dedicated replication workflow must first pass in `validate` mode for execution order 1. A
primary may then authorize its paid sentinel. An Executor may dispatch only that exact authorized
key; it cannot infer permission for the remaining wave.

Paid mode additionally requires a reviewed
`configs/experiments/scaling_paradox_v1_replication_gate.json`. Its absence is intentional while v1
is active. Never fabricate, prefill, or weaken this receipt to make the workflow start.

Replication waves are order 1 alone, orders 2–6, orders 7–12, and orders 13–18. Every earlier wave
must be terminal-valid before the next. The six-cell concurrency cap counts active cells in both v1
and replication, and the two campaigns may not overlap. Use:

```bash
gh workflow run scaling-paradox-v1-replication.yml --ref main \
  -f mode=execute \
  -f run_key=EXACT_REPLICATION_RUN_KEY \
  -f launch_plan_sha=ac90ed77143986eeaec127983df8306c7ced37cd7aed38b87fdc2cb6e7c66b5d
```

Record the Actions run ID immediately. Resumes retain the same replication run key and artifact
lineage. A replication cell cannot replace, repair, or count as a missing v1 cell.

## Structural execution policy

The 64-control ESMFold calibration must pass before frozen endpoint prompts are generated or folded.
The controls are methodological only and are excluded from endpoint analysis.

After calibration:

- base-model generation may run concurrently across the three model cells;
- terminal generation may run concurrently only for terminal-valid training cells;
- folding may use multiple independent H100 batch jobs with immutable, disjoint input reports;
- every context must be built by `deploy/scaling_paradox_v1/build_esmf_context.sh` from `git archive`;
- invalid and duplicate generations remain failures in the denominator;
- no candidate may be manually removed, replaced, reward-ranked, or cherry-picked;
- no primary analysis runs until all three base and all 18 terminal cells are complete.

Do not use old untracked H100, ESM3, LigandMPNN, Concord, or California scripts.

## Artifact validation

A GitHub job marked successful is necessary but not sufficient. Download its artifact and verify:

- `run_contract.json` matches the plan entry exactly;
- `report.json` carries the same run-contract SHA;
- terminal reports contain the declared 2,250 batches for core cells;
- terminal checkpoint and `checkpoint_lineage.json` exist;
- dataset, holdout, challenge, renderer, seed, rank, and hyperparameters match;
- no second provider training run exists for the same task and contract;
- reference-policy and DPO worker records are not mistaken for duplicate experimental replicates.

Reference-policy and DPO services may share a run key while having different `pearl_task` metadata.
That is expected. Two DPO trainer records with the same contract are not expected and require
escalation.

## Scientific analysis rules

These rules are executed mechanically by a subagent only when a primary agent has already selected
and frozen the analysis. A subagent may run the declared script and verify outputs; it may not choose
the method, interpret the result, or write the scientific claim.

- Independent training seed is the experimental unit.
- Candidates and prompts are nested observations, not replicates.
- Primary contrasts are true-reference, shuffled-reference, and true-shuffled.
- Qwen3.5-4B versus Qwen3.5-9B is the clean within-release comparison.
- Qwen3.6-27B is a preregistered lineage extension and keeps its release caveat.
- Pilot runs estimate runtime/effect size only; they do not enter confirmatory estimates.
- Full structural passage is a rare-event endpoint with exact intervals and model/seed-stratified
  counts.
- Figure and analysis scripts fail on missing observations. Synthetic fallback data are prohibited.

The prospective, outcome-blind interpretation map is recorded in
`docs/scaling_paradox_v1_protocol.md`. It is context for the primary's eventual manuscript work, not
an executor decision tree. A subagent does not inspect endpoint artifacts, traverse the map, label an
outcome branch, alter execution, or write a scientific claim from it.

## Git and contamination rules

- Start from current `origin/main` and use a `codex/` branch.
- Expect unrelated untracked files. Never use `git add -A`.
- Stage only explicit files created or edited for the assigned task.
- Do not delete, rename, or reorganize user-owned untracked files.
- Do not merge PEARL work with Concord, IMS, California Synthetic, Luminosity, or MirageBench product
  code.
- Generated contexts use `git archive`, not a filesystem copy, so quarantined files stay out.
- Run focused tests, then the tracked test suite appropriate to the change.
- PR text states scientific impact, checks, and whether external spend occurred.

## Immediate stop conditions

Stop without attempting a creative workaround when any of these occurs:

- a hash differs from the frozen identity;
- an exact run key is absent, non-unique, already active, or already terminal;
- more than one DPO trainer owns the same contract;
- an artifact is missing, partial, malformed, or belongs to another run;
- the requested action exceeds the named concurrency or spend cap;
- a dataset, renderer, prompt panel, evaluator, or endpoint would change after data collection began;
- a conditional stage has not passed its gate;
- a script's name overstates what it actually executes;
- a result would require excluding an inconvenient candidate or inventing missing data;
- live provider state and local state disagree;
- the agent is unsure whether an action is read-only or paid.

Escalation is a successful outcome. Report the exact object, observed evidence, expected evidence, and
the smallest safe next action. Do not relaunch, cancel, kill, delete, or redesign to make the error go
away.

## Required end-of-task handoff

Return this compact ledger:

```text
ROLE:
TASK:
OBSERVED:
CHANGED:
VALIDATION:
EXTERNAL MUTATIONS:
SPEND INCURRED / MAX EXPOSURE:
RUN OR ARTIFACT IDS:
BLOCKERS:
NEXT SAFE ACTION:
FILES INTENTIONALLY NOT TOUCHED:
```

Use facts, not reassurance. Clearly distinguish submitted, queued, running, checkpointed, terminal,
validated, and scientifically analyzed.
