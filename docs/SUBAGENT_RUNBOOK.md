# PEARL Fail-Closed Subagent Runbook

## Purpose

This is the drop-in guide for a lower-cost or context-limited agent. Its job is to make useful,
bounded progress without repeating the August 10 duplicate-run and contaminated-analysis failure.
If an instruction conflicts with the frozen protocol, the agent stops and reports the conflict.

The agent is not the scientific principal investigator. It may execute an already-declared contract;
it may not silently redesign one.

## Supervisor dispatch template

Use this block when assigning work to a lower-cost agent. Do not send a vague instruction such as
"keep the campaign moving."

```text
Read AGENTS.md and docs/SUBAGENT_RUNBOOK.md completely before acting.
ROLE: Observer | Builder | Operator | Analyst | Manuscript
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
seeds 17, 29, and 43. The confirmatory core contains 18 independent training cells.

Canonical sources, in priority order:

1. `docs/scaling_paradox_v1_protocol.md` — claim, exclusions, stages, endpoints, and stop rules.
2. `configs/experiments/scaling_paradox_v1.json` — models, seeds, hyperparameters, and stage matrix.
3. `reports/scaling_paradox_v1/core_launch_plan.json` — generated exact run keys and order; regenerate
   read-only if absent.
4. `.github/workflows/scaling-paradox-v1.yml` — the only approved paid Tinker coordinator.
5. `configs/experiments/scaling_paradox_structural_v1.json` and its frozen JSONL panel — biological
   endpoint contract.
6. GitHub Actions artifacts and provider metadata — live/terminal operational evidence.

Do not use the untracked `HANDOFF.md`, `PROJECT_LUMINOSITY.md`, `infra/`, old Concord scripts, old
California Synthetic scripts, or old H100 scripts as PEARL authority. They are quarantine material.
Do not stage, move, delete, or import them.

Frozen identities for scaling-paradox v1:

- launch-plan SHA: `f63f3bd2f9f0654c819f3f5a806145847c9b899ae16859d870c7a3b320d43226`
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

## Choose exactly one operating role

An agent states its role at the beginning and does not expand it without approval.

### Observer

Allowed: inspect Git, GitHub Actions, Tinker metadata, GiveMeANode state, artifacts, hashes, and logs.
No writes or external mutations.

### Builder

Allowed: edit an explicitly scoped tracked PEARL file on a `codex/` branch, run tests, and prepare a
PR. No paid dispatches, cancellations, deletions, data regeneration, or protocol changes.

### Operator

Allowed only when the task names the stage or exact run keys and a spend/concurrency boundary.
May dispatch immutable workflows and download artifacts. May not invent a run, alter the plan,
cancel a provider run, or move to a conditional stage without approval.

### Analyst

Allowed: analyze complete frozen artifacts using the declared unit hierarchy. May not fill missing
data, pool incompatible cohorts, relabel a pilot as confirmatory, or alter selection rules after
seeing outcomes.

### Manuscript

Allowed: write Introduction and Methods from frozen documentation; write Results only from complete,
validated tables. Unknown results remain explicit placeholders. Never infer a result from a running
job, training loss alone, or a candidate-level pooled count.

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

An Operator must obtain run keys from the generated plan, verify the frozen plan SHA, and dispatch
one workflow per run key. There is deliberately no bulk paid shell loop. For each allowed cell:

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

- Independent training seed is the experimental unit.
- Candidates and prompts are nested observations, not replicates.
- Primary contrasts are true-reference, shuffled-reference, and true-shuffled.
- Qwen3.5-4B versus Qwen3.5-9B is the clean within-release comparison.
- Qwen3.6-27B is a preregistered lineage extension and keeps its release caveat.
- Pilot runs estimate runtime/effect size only; they do not enter confirmatory estimates.
- Full structural passage is a rare-event endpoint with exact intervals and model/seed-stratified
  counts.
- Figure and analysis scripts fail on missing observations. Synthetic fallback data are prohibited.

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
