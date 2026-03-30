# ENGINEERING STANDARDS

This document exists to prevent repeated operator mistakes in PEARL.

It is not aspirational. It is a hard constraint set.

If a step below cannot be executed exactly, stop and ask the operator before touching the run.

## Scope

These standards apply to:

- mining launches
- rebalances
- VM handoffs
- warmstart launches
- robustness launches
- cleanup
- progress reporting
- artifact counting

## Core Rule

No unrequested topology or budget change is allowed.

That means:

- do not change shard count unless explicitly asked
- do not change prompt count unless explicitly asked
- do not change model prior unless explicitly asked
- do not change device target unless explicitly asked or required to fix a broken launch
- do not arm a stop cap, cleanup, or kill path unless explicitly asked or required to stop known duplicate work

## Verified Incident Log

### INC-001: Duplicate compute burn from second rebalance

Date:
- March 29, 2026

What happened:
- a live wave that had already been rebalanced once was rebalanced again
- the rebalance helper scanned all historical run directories instead of only the latest shard generation
- that caused a new shard generation to be launched against prompts that were already being worked

Impact:
- about `847` prompt-equivalents of duplicate compute
- about `216,832` duplicate raw candidates burned

Root cause:
- code bug in [`scripts/rebalance_stage1_wave.py`](/Users/svdr/tinker/scripts/rebalance_stage1_wave.py)
- operator error in trusting the helper without a generation-filtered dry run

Never again:
- rebalances must only read the latest shard generation
- every rebalance must be dry-run first
- dry-run output must be checked against expected unique completed prompts and remaining prompts
- no second rebalance on the same wave without explicit operator approval

### INC-002: Incomplete duplicate-worker cleanup

Date:
- March 29, 2026

What happened:
- stale `rebal02` run directories and one live `rebal02` worker survived the first cleanup pass

Impact:
- duplicate work continued after the operator believed the duplicate generation was dead
- on-disk progress accounting became polluted

Root cause:
- shell-glob cleanup was not sufficient
- process and filesystem verification were not treated as separate required checks

Never again:
- cleanup is not complete until both of these are true:
  - `pgrep` for the target generation returns zero live workers
  - filesystem sweep confirms zero matching run dirs, prompt files, and metadata files
- cleanup verification must be done with structured checks, not by visual inspection

### INC-003: Wrong device on smoke gate

Date:
- March 29, 2026

What happened:
- a smoke gate launched with `mps` on a GPU VM instead of `cuda`

Impact:
- wasted launch time
- required relaunch

Root cause:
- implicit/default device handling was allowed to survive into a remote GPU path

Never again:
- all remote launches must pass an explicit device
- every GPU launch must assert `cuda=True` before the actual run command is issued
- no smoke gate may rely on ambient defaults

### INC-004: Missing bundle component on finalize VMs

Date:
- March 29, 2026

What happened:
- the finalize bundle sent to the H100 partition VMs was missing `run_ablation.py`

Impact:
- remote finalization launch failed and had to be resynced/relaunched

Root cause:
- incomplete sync manifest

Never again:
- every sync bundle needs an explicit manifest
- remote setup is not complete until the manifest is present and import-checked on the target box

### INC-005: Wrong remote path defaults in warmstart path

Date:
- March 29, 2026

What happened:
- a queued warmstart path still defaulted to a local `/Users/...` report path on the remote VM

Impact:
- remote chain broke and had to be patched/relaunched

Root cause:
- local absolute paths leaked into a remote execution path

Never again:
- any script that can run remotely must resolve paths from repo root or runtime cwd
- no `/Users/...` path is allowed in remote-executed defaults

### INC-006: Stale failed-launch noise polluted live logs

Date:
- multiple March 2026 runs

What happened:
- earlier failed launch traces remained at the top of the same log files used by later good runs

Impact:
- status reading became ambiguous
- extra manual interpretation was required

Root cause:
- relaunches reused log files without a hard run boundary

Never again:
- every relaunch must get a fresh log file or a clear run marker
- status reports must key off live PID, timestamps, and new summary artifacts, not just top-of-file text

### INC-007: Historical recoverability gap on unicorn evidence

Documented in:
- [`notes/LABNOTES.md`](/Users/svdr/tinker/notes/LABNOTES.md)

What happened:
- the notes record `11` unicorns by evidence but only `9` recoverable unicorn sequences on disk

Impact:
- evidence count and usable training data count diverged

Root cause:
- artifact retention and evidence accounting were not kept in strict lockstep

Never again:
- no positive is counted as reusable training data unless its exact artifact path is recorded and present
- evidence count and recoverable-count must be reported separately

### INC-008: Historical duplicate-run risk

Documented in:
- duplicate-run guards were later added to [`scripts/run_reseed3_batch.sh`](/Users/svdr/tinker/scripts/run_reseed3_batch.sh)

What happened:
- launch paths previously allowed duplicate work unless guarded after the fact

Impact:
- wasted compute risk

Never again:
- every launcher must check:
  - live process metadata
  - output dir presence
  - log metadata presence
  - whether the exact named job is already active

### INC-009: Historical rebalance edge case on prior 300k wave

Documented in:
- [`notes/LABNOTES.md`](/Users/svdr/tinker/notes/LABNOTES.md)

What happened:
- the prior coarse stage1 wave hit a rebalance edge case and needed a manual tail fix

Impact:
- automation could not be trusted at the tail

Never again:
- a rebalance tool is not trusted on mixed stopped/relaunched state without a dry-run exact-count check
- if exact remaining prompt count is not obvious, stop and ask instead of improvising

### INC-010: Command and typo hygiene failures

Date:
- repeated across this project cycle

What happened:
- quoting mistakes
- shell-glob cleanup misses
- false-positive greps
- command pipelines that looked valid but were not exact

Impact:
- status confusion
- missed cleanup
- extra operator distrust

Never again:
- use Python for structured checks and destructive cleanup
- shell one-liners are allowed only for simple transport, not for state accounting
- grep patterns must be quoted and tested against exact intended text
- no destructive command should depend on shell expansion when a Python path walk is possible

## Non-Negotiable Operating Rules

### 1. Launch discipline

- every launch must have:
  - exact prompt count
  - exact candidate count
  - exact prior URI
  - exact shard count
  - exact prompt offset if applicable
- these values must be echoed back before the launch is considered complete

### 2. Rebalance discipline

- every rebalance requires:
  - explicit operator approval
  - dry-run first
  - latest-generation-only source selection
  - exact expected `completed_prompt_count`
  - exact expected `remaining_prompt_count`
- if dry-run numbers are surprising, do not proceed

### 3. Budget discipline

- every long run needs a declared spend envelope
- duplicate compute is counted as budget burn even if no data is lost
- if duplicate work is detected:
  - stop it first
  - measure it second
  - only then decide whether to continue

### 4. Cleanup discipline

- cleanup is not done until:
  - target workers are dead
  - stale prompt files are gone
  - stale run dirs are gone
  - stale metadata files are gone
- process state and filesystem state must both be checked

### 5. Reporting discipline

- every status report must distinguish:
  - valid unique progress
  - duplicate burned progress
  - stale artifact residue
- do not report aggregate counts from polluted directories
- if the directory state is ambiguous, say so and clean it before reporting totals

### 6. Device discipline

- no implicit `mps` or `cuda` default on a remote run
- every remote launch must state the intended device explicitly
- every GPU launch must verify:
  - torch import works
  - CUDA is available
  - the intended model/scorer loads on the target box

### 7. Sync discipline

- every VM sync path needs a manifest
- sync success is not assumed from `rsync` alone
- the target box must verify presence of all required scripts before launch

### 8. Log discipline

- failed launch logs and successful relaunch logs must be separable
- never reuse a log file in a way that forces manual archaeology
- every relaunch must be visually and mechanically distinguishable

### 9. Secret discipline

- do not paste secrets into commands that may be echoed back into logs if another path exists
- when a secret must be exported interactively, it must not be repeated in user-facing output

### 10. Typo discipline

- no ad hoc remote shell surgery for structured state unless there is no safer scripted path
- no destructive glob-based cleanup when a short Python script can do exact path targeting
- if a command is easy to misquote, do not use it

## Required Checklists

### Before any launch

- confirm exact run name
- confirm exact prior URI
- confirm exact prompt count
- confirm exact shard count
- confirm exact offset
- confirm exact budget envelope

### Before any rebalance

- confirm operator explicitly asked for rebalance
- run dry-run
- verify latest generation only
- verify completed and remaining counts
- verify stop targets

### After any cleanup

- verify zero live target workers
- verify zero stale target run dirs
- verify zero stale target prompt files
- verify zero stale target metadata/log files

### Before any status message

- verify counts are unique-valid counts
- verify stale generations are excluded
- verify duplicate burn, if any, is called out separately

## Decision Rule After Any New Incident

If an error is:

- budget-impacting
- data-damaging
- duplicate-work-causing
- path-resolution-causing
- cleanup-causing

then:

1. stop the bleeding
2. measure exact impact
3. document the incident here
4. add or tighten the rule that would have prevented it
5. do not continue normal execution until the rule is in place

## Current Standing Order

For the current even-million wave:

- no more topology changes
- no more shard-count changes
- no more rebalances
- status-only unless the operator explicitly requests a new action

