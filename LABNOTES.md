# LABNOTES

Internal working notes for **PEARL**: Protein Engineering Adapter via Reinforcement Learning.

This document is meant to do three jobs:

1. Preserve the experimental story from start to finish.
2. Record the engineering failures and fixes that materially changed results.
3. Onboard a new collaborator without forcing them to reconstruct the project from terminal history.

This is a living document. It should be updated whenever we change the search regime, reward/eval definition, or operational workflow.

## Project Goal

Generate PETase/cutinase-like protein candidates that satisfy all of the following:

- single catalytic serine motif
- plausible catalytic geometry under the sequence-level evaluator
- high local ESM proxy score (`ESM >= 85`)
- strong family plausibility
- enough diversity to avoid trivial motif-spam collapse

The current workflow is:

1. sample candidates from a remote frontier model via Tinker
2. filter/rerank locally with a sequence-level family/geometry evaluator
3. score stability locally with an ESM-2 masked-LM proxy
4. use mined positives for short supervised warm-starts
5. only turn on RL after the bridge manifold is stable enough

## Core Terms

### Unicorn

A candidate is treated as a **unicorn** when it satisfies the practical bridge condition:

- `motif_count == 1`
- `geometry_passes == true`
- `esm_gate_pass == true`

In practice we also expect:

- `hard_gate_pass == true`

### Bridge

The **bridge** is the narrow intersection between:

- stable single-site protein-like generations
- and geometry-correct catalytic generations

Most failure modes in this project are different ways of missing that intersection.

### Catalytic Doping

**Catalytic Doping** is the current repair regime:

- start from high-ESM, single-motif, non-geometry candidates
- keep most of the backbone fixed
- relocate or repair catalytic windows only
- rescore for geometry + ESM

This is the current post-mining direction after broad sampling saturated.

## Repo Landmarks

- Public-facing project doc: [README.md](/Users/svdr/tinker/README.md)
- Main loop: [main.py](/Users/svdr/tinker/main.py)
- Family evaluator: [petase_family.py](/Users/svdr/tinker/petase_family.py)
- Local ESM proxy: [local_proxy.py](/Users/svdr/tinker/local_proxy.py)
- Ablation runner: [run_ablation.py](/Users/svdr/tinker/scripts/run_ablation.py)
- Stratified mining runner: [run_kimi_zero_shot_stratified_search.py](/Users/svdr/tinker/scripts/run_kimi_zero_shot_stratified_search.py)
- SFT warm-start runner: [run_sft_warmstart.py](/Users/svdr/tinker/scripts/run_sft_warmstart.py)
- Detached launcher: [launch_detached_job.py](/Users/svdr/tinker/scripts/launch_detached_job.py)
- Detached reseed launcher: [launch_reseed3_batch_detached.sh](/Users/svdr/tinker/scripts/launch_reseed3_batch_detached.sh)
- Catalytic Doping builder: [build_catalytic_doping_candidates.py](/Users/svdr/tinker/scripts/build_catalytic_doping_candidates.py)

## Chronology

### Phase 0: Bootstrap

Initial state:

- toy prompt loop
- missing `tinker` and `local_proxy` modules
- no real backend validation

Temporary compatibility shims were used only to prove the loop shape, then removed.

### Phase 1: Real Tinker Integration

We replaced the shim path with the real Tinker API flow and verified:

- remote sampling
- `forward_backward`
- `optim_step`
- remote checkpoint save

The early dry run proved the infrastructure, not the biology.

### Phase 2: Data Expansion

We built a real UniProt-derived dataset under [data/petase_family_expanded](/Users/svdr/tinker/data/petase_family_expanded).

Important point:

- broad family data became abundant
- true high-value positives did not

This distinction remained central for the rest of the project.

### Phase 3: Evaluation Layer

We built a real evaluator around:

- validity
- entropy/diversity
- family serine motifs
- sequence-level catalytic geometry
- novelty
- ESM proxy gating

This let us stop guessing and start measuring exact failure modes.

### Phase 4: Qwen Branch

Key finding:

- Qwen could generate protein-like sequences
- but it struggled to produce the PETase-family bridge reliably

Observed failure modes:

- generic stable proteins with weak family signal
- motif-forced collapse into brittle low-trainability outputs
- repetitive scaffold spam
- geometry washout under RL continuation

Important positive result:

- short SFT warm-starts could restore full-length geometry-capable generation

Important negative result:

- reward shaping alone did not solve the missing grammar problem

Conclusion:

- Qwen validated the experimental stack
- but it was not the right long-term inner-loop model for this problem

### Phase 5: Kimi Pivot

We moved to `moonshotai/Kimi-K2.5` as a clean architecture branch.

Key reason:

- the bottleneck had become global positional planning under blueprint constraints
- that is where a stronger frontier MoE model had a chance to help

Zero-shot Kimi result:

- first branch to show raw `single_motif + geometry` mass

That was the decisive proof that the architecture pivot was justified.

### Phase 6: Kimi Mining

We ran aggressive zero-shot mining around `t = 0.85`.

Original successful sweep:

- Batch 1: `2` unicorns
- Batch 2: `0`
- Batch 3: `3`
- Batch 4: `0`
- total original: `5`

Reseed 3:

- Batch 1: `+1`
- Batch 2: `+2` by evidence, but full raw sequences later lost to an overwrite incident
- Batch 3: `+3`
- Batch 4: `+0`

Total unicorn evidence:

- `11`

Recoverable unicorn sequences on disk:

- `9`

Perfect wildtypes:

- `3`

Usable positives at the end of the main mining phase:

- `9 recoverable unicorns + 3 wildtypes = 12`

### Phase 7: Kimi Micro-SFT Experiments

#### Top-5 branch

Dataset:

- `3` perfect wildtypes
- `2` Kimi-native unicorns

Checkpoint:

- `tinker://587cd86e-7adb-54d3-b931-bca85c8ac57f:train:0/weights/kimi25-micro-sft-top5-lr1e6-ep2`

Key result:

- produced a real holdout bridge hit on the 12-prompt audit

This became the initial gold branch.

#### Top-12 direct from base

Dataset:

- `3` wildtypes
- `9` recoverable unicorns

Checkpoint:

- `tinker://ee1fed04-67bb-5965-99e1-7493f6e432f5:train:0/weights/kimi25-micro-sft-top12-lr1e6-ep2`

Result:

- more stable
- but lost the holdout bridge

#### Top-12 continuation from top-5

Checkpoint:

- `tinker://0ca0c340-2a8e-5c42-b316-fe8e075e36e0:train:0/weights/kimi25-micro-sft-top12-cont-from-top5-lr5e7-ep1`

Result:

- also lost the bridge
- even more conservative than the top-5 branch

Interpretation:

- adding more positives did not help by default
- the extra examples likely blurred the narrow Kimi-native bridge manifold

#### Top-9 unicorn-only

Dataset:

- `9` recoverable unicorns
- no wildtypes

Checkpoint:

- `tinker://e2872501-ad4f-5d06-bbab-9b8255839cc1:train:0/weights/kimi25-micro-sft-top9-unicorn-only-lr1e6-ep2`

12-prompt result:

- recovered a real bridge hit again
- selected hit:
  - `motif_count = 1`
  - `geometry_passes = true`
  - `esm_gate_pass = true`
  - `raw_esm_score = 99.56`

Important nuance:

- that hit had `has_family_serine_motif = false`

Interpretation:

- removing wildtypes likely helped preserve the bridge
- but the branch still needed larger-scale validation

### Phase 8: 48-Prompt Validation of Unicorn-Only Branch

We scaled the unicorn-only branch to a `48`-prompt eval-only sweep using 4 parallel 12-prompt shards.

Aggregate result:

- `6144` candidates
- `2048` single-motif candidates
- `68` single-motif + ESM-pass candidates
- `57` single-motif + geometry candidates
- `0` single-motif + geometry + ESM candidates

Interpretation:

- the bridge manifold is still present
- but it is too fragile at larger evaluation scale
- broad validation on this branch did not support immediate RL

This was the point where broad mining stopped looking attractive.

## What We Learned

### 1. The bridge is real

We have repeatedly seen:

- zero-shot Kimi unicorns
- a small Kimi-native micro-SFT transferring the bridge at least once

So the bridge is not imaginary.

### 2. The bridge is fragile

Repeated `12`-prompt audits and the `48`-prompt validation showed:

- the intersection is real
- but sparse and unstable

### 3. Broad “better data” can be worse

More positives did not automatically help.

The likely failure mode:

- extra positives pulled the model toward a safer stable/family manifold
- but away from the narrow bridge manifold

### 4. Wildtypes are not automatically helpful

The unicorn-only branch strongly suggests the wildtypes were at least partly washing out the Kimi-native bridge.

### 5. Broad mining has diminishing returns

By the end of the 48-prompt eval, we had many:

- stable single-site candidates
- geometry-positive candidates

But still failed to close the intersection robustly.

That is why the project is pivoting toward constrained repair.

## Bugs, Failures, and Fixes

### Missing modules bootstrap

Problem:

- initial script did not run due to missing `tinker` / `local_proxy`

Resolution:

- temporary shim for loop validation only
- later replaced with real backend integration

### Validation leak

Problem:

- an early “validation” path was still performing training steps

Resolution:

- explicit `eval_only` support added
- holdout interpretation corrected

### API / SDK drift

Problem:

- old Tinker SDK version stopped being accepted by the backend

Resolution:

- active environment updated to supported SDK

### Duplicate batch overwrite incident

Problem:

- a stale Batch 2 relaunch reused the same output path
- final `candidate_audit.json` got overwritten

What survived:

- counts and step-level evidence

What was lost:

- exact full sequences of the two Batch 2 unicorns

Fixes:

- duplicate-run guards added to [run_reseed3_batch.sh](/Users/svdr/tinker/scripts/run_reseed3_batch.sh)
- relaunch blocked if `summary.json` exists
- relaunch blocked if matching run name is already active

### Partial-run data loss

Problem:

- interrupted runs used to lose everything if they had not finished

Fix:

- [main.py](/Users/svdr/tinker/main.py) now writes partial `report.json` and `candidate_audit.json` after every completed prompt using atomic replace

### Flaky background jobs

Problem:

- shell-backgrounded jobs often died before `main.py` actually entered the loop

Root cause:

- inherited fragile session/stdin/stdout state from short-lived parent shells

Fix:

- added [launch_detached_job.py](/Users/svdr/tinker/scripts/launch_detached_job.py)
- added [launch_reseed3_batch_detached.sh](/Users/svdr/tinker/scripts/launch_reseed3_batch_detached.sh)
- detached jobs now get:
  - new session
  - closed stdin
  - direct log files
  - metadata files with PID/command/cwd

### MLX investigation

Question:

- can the local ESM masked-LM proxy be ported to MLX?

Result:

- MLX is installed
- no ready MLX-native masked ESM path was found
- current safe production path remains torch + MPS

Artifacts:

- [probe_mlx_esm_backend.py](/Users/svdr/tinker/scripts/probe_mlx_esm_backend.py)
- local notes in [FORLATERUSE.md](/Users/svdr/tinker/FORLATERUSE.md)

## Current State

Best current checkpoint for bridge preservation:

- `tinker://e2872501-ad4f-5d06-bbab-9b8255839cc1:train:0/weights/kimi25-micro-sft-top9-unicorn-only-lr1e6-ep2`

But:

- the `48`-prompt eval said it is not robust enough for RL yet

So the project is currently **not RL-ready**.

However:

- the bridge exists
- the model can produce high-ESM stable candidates in volume
- and we now have a cleaner understanding of the failure mode

New state after the first Catalytic Doping pilot:

- the relocation-aware repair pass succeeded
- it produced `220` repaired `geometry + ESM` survivors from `55` stable parents
- those survivors are not `220` independent scaffolds, but they are strong enough to justify a repair-derived SFT branch

Primary artifacts:

- analysis note:
  - [kimi_catalytic_doping_val48_reloc_v1_analysis.md](/Users/svdr/tinker/reports/analysis/kimi_catalytic_doping_val48_reloc_v1_analysis.md)
- survivor pool:
  - [kimi_catalytic_doping_survivors_val48_reloc_v1.jsonl](/Users/svdr/tinker/data/petase_family_expanded/kimi_catalytic_doping_survivors_val48_reloc_v1.jsonl)
- run summary:
  - [kimi_catalytic_doping_val48_reloc_v1_summary.json](/Users/svdr/tinker/data/petase_family_expanded/kimi_catalytic_doping_val48_reloc_v1_summary.json)

## Why Catalytic Doping Exists

The `48`-prompt eval gave the clearest diagnosis yet:

- many high-ESM single-motif candidates
- many geometry-positive candidates
- zero candidates in the intersection

That means the next search problem is no longer:

- “sample more from scratch”

It is:

- “take the stable side and graft/repair the catalytic geometry into it”

Catalytic Doping is our name for that regime.

## Catalytic Doping: Definition

Current intended regime:

1. harvest stable backbones:
   - `motif_count == 1`
   - high `ESM`
   - preferably family-positive
   - not already geometry-positive
2. infer or use a blueprint
3. if needed, neutralize the existing serine motif
4. relocate a family-like serine motif toward the catalytic window
5. place D/H around blueprint and gap anchors
6. rescore for:
   - `motif_count == 1`
   - geometry
   - `ESM >= 85`
7. use surviving repaired candidates as cleaner positives

Current implementation path:

- [build_catalytic_doping_candidates.py](/Users/svdr/tinker/scripts/build_catalytic_doping_candidates.py)

## Short-Term Next Steps

1. Downselect the `220` Catalytic Doping survivors to a compact, diverse training set.
2. Keep at most `1-2` repaired variants per parent prompt-step and prefer scaffold diversity over raw count.
3. Run a small repair-derived SFT branch from the current best Kimi checkpoint.
4. Re-evaluate on the `12`-prompt holdout first, then scale to `24` prompts if the bridge survives.
5. Only revisit RL when the repaired branch holds up at larger eval scale.

### Strict Tier-1 Doping Failure

We explicitly tried the hard-canonical version next:

- only canonical graft motifs: `GYSLG`, `GYSQG`
- only parent backbones with `has_family_serine_motif = true`
- low-LR continuation from the best `top9` checkpoint

Result:

- [summary.json](/Users/svdr/tinker/reports/ablations/kimi25-micro-sft-top9-plus-doping24strict-cont-lr5e7-ep1-val12-t08-c128/summary.json)
- `functional_bridge_rate = 0.0`
- `family_faithful_bridge_rate = 0.0`

Interpretation:

- strict biology pressure successfully increased family-looking stable outputs
- but it over-constrained the model and killed the bridge entirely
- the best geometry attempts under this branch were unstable or multi-motif

This is an important negative result:

- **hard Tier 1 supervision collapses the physics**

### Soft Doping Pivot

The next repair-derived curriculum should be softer:

- majority Tier 2 anchors from the loose doping shortlist
- minority Tier 1 pull from canonical purebreds and strict repaired examples

This keeps the spatial/ESM manifold alive while applying a gentler family-faithful pull instead of a hard wall.

### Soft Doping Failure

We ran the soft-doping curriculum from:

- `tinker://fc8cb9c3-0d7f-518d-9668-977fcafef21f:train:0/weights/kimi25-micro-sft-top9-soft-doping41-cont-lr5e7-ep1`

on the standard `12`-prompt holdout, sharded into four `3`-prompt runs for speed.

Final result:

- Tier 2 functional bridge: `0 / 12`
- Tier 1 family-faithful bridge: `0 / 12`

Pattern:

- some shards produced geometry without enough ESM
- other shards produced strong stable single-site outputs without geometry
- the soft curriculum did not preserve the Tier 2 bridge

Interpretation:

- SFT appears exhausted for this problem family
- the model treats our synthetic repairs as conflicting local optima rather than a clean path to the intersection
- further SFT-only mixing is more likely to confuse the latent backbone grammar than to recover Tier 1

### RL Pivot

The current reference policy for RL is:

- `tinker://7a5aeb3f-0652-52d1-849d-9916dfb43c7c:train:0/weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1`

Reason:

- it is the only branch that held a Tier 2 functional bridge at larger (`24`-prompt) holdout scale
- it still does not produce Tier 1 family-faithful bridges
- but it gives us a real, non-zero gradient to optimize

Planned PPO pilot reward ladder:

- `0` if `ESM < 85` or no catalytic geometry
- `1` for Tier 2 (`motif_count == 1` + geometry + `ESM >= 85`)
- `6` for Tier 1 (Tier 2 + `has_family_serine_motif = true`)

Operational stance:

- short pilot only (`20-30` steps)
- very low learning rate
- large rollout batch
- no full RL campaign until the pilot shows the bridge can be strengthened without collapsing the policy

### PPO Pilot Outcome

The PPO pilot was operationally stable but scientifically starved.

Artifacts:

- [/Users/svdr/tinker/reports/rl_pilot/kimi25-ppo-tier-bridge-pilot20-c2048-lr1e6/report.json](/Users/svdr/tinker/reports/rl_pilot/kimi25-ppo-tier-bridge-pilot20-c2048-lr1e6/report.json)
- [/Users/svdr/tinker/reports/rl_pilot/kimi25-ppo-tier-bridge-pilot20-c2048-lr1e6/candidate_audit.json](/Users/svdr/tinker/reports/rl_pilot/kimi25-ppo-tier-bridge-pilot20-c2048-lr1e6/candidate_audit.json)

Observed:

- `3 / 20` steps completed before termination
- `0` Tier 2 hits
- `0` Tier 1 hits
- each step produced `31-41` geometry-positive candidates out of `2048`
- selected samples repeatedly hit geometry, and one even hit family-faithful geometry, but all had `ESM` in the `20s-30s`

Interpretation:

- PPO was not failing because of infrastructure
- PPO was failing because the reward landscape was too sparse
- the model had learned a "spaghetti" regime: satisfy geometry cheaply without producing a foldable backbone

Decision:

- terminate PPO
- keep the hard `ESM >= 85` floor
- pivot to RAFT / Expert Iteration

## RAFT Pivot

Reference policy:

- `tinker://7a5aeb3f-0652-52d1-849d-9916dfb43c7c:train:0/weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1`

Phase 1 plan:

1. generate `30k-50k` candidates offline from the reference policy
2. score locally with the existing geometry and ESM filters
3. keep only Tier 2 / Tier 1 successes
4. run a tiny success-only SFT to ratchet the generator forward

Operational note:

- detached launches now use [/Users/svdr/tinker/scripts/launch_detached_job.py](/Users/svdr/tinker/scripts/launch_detached_job.py)
- job metadata redacts API-like secrets

## Longer-Term Validation Path

If the bridge becomes robust enough:

1. short RL pilot
2. larger eval-only sweep
3. shortlist generation
4. AlphaFold / structural triage on shortlist
5. possibly wet-lab work if the computational stack justifies it

## Notes for New Collaborators

If you are new to this repo, do not start by changing RL.

Do this first:

1. read [README.md](/Users/svdr/tinker/README.md)
2. read this file
3. inspect:
   - [main.py](/Users/svdr/tinker/main.py)
   - [petase_family.py](/Users/svdr/tinker/petase_family.py)
   - [local_proxy.py](/Users/svdr/tinker/local_proxy.py)
4. understand the unicorn definition
5. understand the bridge failure mode
6. do not reuse output paths for new experiments
7. prefer detached launcher or foreground execution over shell backgrounding

## Bottom Line

PEARL is not in a failure state. It is in a narrow-manifold state.

The project has already answered several major questions:

- does the bridge exist? yes
- can Kimi hit it? yes
- does naive scaling of the positive set solve it? no
- is the broad eval robust enough yet? no
- is constrained catalytic repair the right next move? yes

That is where we are.

## Funding And Platform Constraint

This project is currently being developed under a `USD 5,000` grant / credit from Thinking Machines.

That funding is constrained to the Thinking Machines platform, so the core generation / training work is forced onto Tinker rather than being freely portable to another provider or local training stack.

Practical implication:

- remote model generation and training flow happen through Tinker
- local work is mainly evaluation, scoring, filtering, and experiment orchestration
- when iteration speed becomes poor, part of that bottleneck is simply the platform constraint rather than a mistake in the local code

This matters for interpreting the project timeline and engineering decisions. Several choices that might be simpler off-platform are currently not available because the grant has to be spent inside Tinker.

## Current Status Snapshot

As of March 3, 2026:

- all active PEARL processes are stopped
- best current reference policy is still:
  - `tinker://7a5aeb3f-0652-52d1-849d-9916dfb43c7c:train:0/weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1`
- Tier 2 functional bridge exists, but only weakly
- Tier 1 family-faithful bridge is still absent

Recovered positive data:

- `11` unicorns by evidence
- only `9` recoverable unicorn sequences on disk
- `3` wildtypes
- effective reusable positive pool for SFT was therefore `12`, not `14`

Branch results:

- `top5` micro-SFT:
  - weak but real Tier 2 bridge
- `top12` and continuation:
  - worse than `top5`
- `top9 unicorn-only`:
  - recovered the weak bridge
- loose mixed doping:
  - best practical branch
  - held Tier 2 at `24`-prompt scale, but still no Tier 1
- strict canonical-only doping:
  - killed the bridge
- soft-doping curriculum:
  - killed the bridge

Current interpretation:

- SFT has mostly exhausted its useful easy wins
- adding more synthetic positives without extreme care tends to blur or kill the bridge
- the model repeatedly finds:
  - geometry without enough fold stability
  - or strong fold stability without the right geometry

## PPO Outcome

The PPO pilot is now a closed negative result.

Summary:

- operationally stable
- scientifically starved
- geometry appeared repeatedly
- one selected sample even hit family-faithful geometry
- but all selected geometry-positive samples had very poor `ESM` and received reward `0`

Interpretation:

- PPO was not failing because of crashes or wrapper bugs
- PPO was failing because the reward was too sparse for online optimization on this landscape
- the model entered a "spaghetti" regime: easy geometry, no foldable backbone

Decision:

- PPO is not the current path forward
- do not resume it without a fundamentally different reward regime or much denser success rate

## RAFT / Expert Iteration Status

RAFT remains the correct conceptual direction, but the first implementation pass exposed a throughput problem.

What happened:

- broad detached RAFT wave launched successfully
- detached process supervision worked
- but the current `run_ablation.py -> main.py` path was too slow in the first-prompt stage to be operationally useful at the intended scale
- even after reducing concurrency and shrinking to a `10`-prompt proof run, the first prompt still took too long to make this shape of mining practical

Interpretation:

- RAFT as an idea is still alive
- current RAFT execution path is too slow
- before more large-scale RAFT mining, the mining implementation needs to be reshaped so we can get through prompt `0` in sane time

## Practical Assessment

The project is:

- not hopeless
- not solved
- not RL-ready
- not ready for AlphaFold-scale downstream validation
- still worth pursuing

The most accurate one-line summary is:

- the bridge is real, but fragile

The current bottleneck is not whether Kimi can ever hit the right manifold.
The bottleneck is whether we can make the search / optimization loop reach that manifold reliably and cheaply enough to iterate.
