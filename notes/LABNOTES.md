# LABNOTES

Internal working notes for **PEARL**: Protein Engineering Adapter via Reinforcement Learning.

This document is meant to do three jobs:

1. Preserve the experimental story from start to finish.
2. Record the engineering failures and fixes that materially changed results.
3. Onboard a new collaborator without forcing them to reconstruct the project from terminal history.

This is a living document. It should be updated whenever we change the search regime, reward/eval definition, or operational workflow.

## Latest Canonical Status (as of March 8, 2026)

- canonical reference policy:
  - `tinker://7a5aeb3f-0652-52d1-849d-9916dfb43c7c:train:0/weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1`
- newest unconfirmed branch:
  - `tinker://6c7881f9-0330-5a3b-8acf-f2a44a7cbf70:train:0/weights/pearl-micro-sft-repair20-from-wave3-lineage-lr5e7-ep1`
- current phase:
  - raw-generation stockpile + local prefilter + Wynton-side heavy scoring / retrain
- next required gate:
  - repair20 durability confirmation at `12 -> 24 -> 48` prompts with fixed seeds
- currently ruled-out paths:
  - resumed PPO
  - broad SFT mixing without strict lineage/diversity controls
  - AlphaFold-scale downstream triage

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

## State Snapshot (after Phase 8, before March 3, 2026)

Best checkpoint for bridge preservation at this snapshot:

- `tinker://e2872501-ad4f-5d06-bbab-9b8255839cc1:train:0/weights/kimi25-micro-sft-top9-unicorn-only-lr1e6-ep2`

But:

- the `48`-prompt eval said it is not robust enough for RL yet

So the project was **not RL-ready** at this snapshot.

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

## Status Snapshot (March 3, 2026)

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

## RAFT / Expert Iteration Snapshot (March 3, 2026)

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

## March 4, 2026 Engineering Update

This section records the engineering cleanup and throughput investigation done after the March 3 snapshot.

### Repo / code hygiene

Before more experiments, the repo was cleaned up enough to reduce operational confusion:

- `LABNOTES.md` moved under `notes/`
- scratch timing scripts moved under `benchmarks/`
- stray local report artifacts moved under `reports/legacy/`
- hot-path code had a cleanup pass:
  - named constants replaced scattered magic numbers
  - duplicated reward / bridge bookkeeping was factored into shared helpers
  - local proxy parsing was simplified

This did not change the scientific state, but it made the runtime path easier to inspect and modify.

### Local evaluator optimizations

The local PETase-family evaluator got several real optimizations:

- cached reference k-mers in memory instead of rebuilding them on every candidate evaluation
- removed wasteful set-union allocation in Jaccard scoring
- switched novelty shortlist selection from full sort to a bounded top-k path
- skipped full novelty scoring for obvious cheap rejects
- kept the tandem-repeat micro-optimization, but confirmed it is minor

Interpretation:

- these changes were worth keeping
- they reduced local stage-1 cost materially
- they did not solve the full prompt-level throughput problem by themselves

### Prompt-0 timing instrumentation

`main.py` was instrumented with explicit timing markers around:

- service client startup
- base model resolution
- training client creation
- tokenizer loading
- prompt loading
- reference loading / family stats
- sampler preparation
- remote sampling
- stage-1 local evaluation
- stage-2 ESM scoring

The first full measured one-prompt eval-only benchmark at `256` candidates showed:

- startup total: `34.8s`
- `create_training_client`: `32.2s`
- `save_weights_and_get_sampling_client`: `6.2s`
- remote sampling: `32.7s`
- stage-1 local evaluation: `11.9s`
- stage-2 ESM scoring: `22.6s`
- total wall clock: `112.8s`

Main conclusion:

- the dominant bottleneck was no longer the old Python novelty path
- the real cost center was remote Tinker startup / sampling, with local ESM second and local stage-1 third

### Reuse / prewarm pass

Two immediate runtime changes were added:

- explicit ESM prewarm so model-load cost is visible at startup
- sampling-client reuse across prompts when weights have not changed

On a `2`-prompt, `64`-candidate eval-only timing run:

- step `1` reused the sampling client with effectively `0s` client-prep cost
- startup included explicit `ESM` prewarm
- this cleaned up repeated per-step overhead, but the main remaining cost was still remote sampling

Conclusion:

- reuse is worth keeping
- prewarm is worth keeping
- neither changes the fundamental fact that remote generation dominates end-to-end time once local scoring is no longer pathological

### Tinker SDK investigation

The SDK was read directly to answer whether the training startup cost was avoidable.

Important findings:

- `ServiceClient()` creates a fresh Tinker session with heartbeat
- `create_training_client_from_state(...)` is expensive by design:
  - fetch weights info
  - create a new LoRA training run
  - load the checkpoint into that run
- `save_weights_and_get_sampling_client()` is also expensive by design, but it is still the natural training-loop path
- there is no clean public API to reattach to an old training client across separate program runs
- there is a clean public direct sampling path for sampler checkpoints:
  - `create_sampling_client(model_path=...)`

That created a clear split:

- eval-only should avoid the training client whenever possible
- actual training runs still need the existing training-client path

### Eval-only sampler resolution

An eval-only fast path was then added:

- if `INIT_STATE_PATH` is already a sampler checkpoint, use it directly
- if a known derived sampler checkpoint exists locally, use it directly
- if the input is only a training checkpoint, resolve or create a matching sampler checkpoint once, then reuse it on future evals

Important SDK caveat discovered during this work:

- Tinker does not let `create_sampling_client(model_path=...)` load a normal `weights` checkpoint
- it requires a `sampler_weights` checkpoint
- also, saving sampler weights from a loaded training checkpoint creates a new sampler checkpoint under a new training run id, not under the original run id

That means naive string replacement from:

- `/weights/...`

to:

- `/sampler_weights/...`

is not enough.

To close that loop, a local mapping file was introduced:

- `.tinker_sampler_checkpoint_map.json`

This stores:

- source training checkpoint path
- resolved derived sampler checkpoint path

and future eval-only runs validate and reuse that sampler path directly.

### Concrete result

For the current reference policy:

- source training checkpoint:
  - `tinker://7a5aeb3f-0652-52d1-849d-9916dfb43c7c:train:0/weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1`
- derived sampler checkpoint:
  - `tinker://29d6d1c5-cf40-5404-9af1-3755d95bd6ed:train:0/sampler_weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1`

Once that mapping existed, a follow-up eval-only benchmark using the mapped sampler path showed:

- startup total: `3.6s`
- no training-client creation
- no sampler-refresh step
- total wall clock on a small `1`-prompt, `8`-candidate run: `31.8s`

Interpretation:

- the eval-only loose end is now actually closed
- future eval / ablation / detached mining runs should reuse sampler checkpoints rather than repeatedly paying the training-client startup tax

### Operational Recommendation Snapshot (March 4, 2026)

At this point the engineering recommendation is:

- for eval-only:
  - use resolved sampler checkpoints and keep the local sampler mapping
- for real training:
  - keep `save_weights_and_get_sampling_client()` as the prompt-loop path
- do not spend more time trying to replace the training-loop sampler refresh with `save_weights_for_sampler(...) + create_sampling_client(...)` unless there is a specific need to verify it experimentally

Reason:

- for training mode, both approaches still pay the save-for-sampler cost
- the named-checkpoint path likely adds extra session creation overhead rather than removing it
- the high-value win was in eval-only reuse, and that win has now been captured

## March 5, 2026 Robustness Cycle Update (Repair17)

This section captures the full `repair16 -> repair17` durability cycle and the final outcome.

### Script and workflow changes

1. Robustness summary ingestion hardening:
   - [run_robustness_suite.py](/Users/svdr/tinker/scripts/run_robustness_suite.py) now resolves existing ablation runs by metadata (`prompt_count`, `seed`, `init_state_path`, `model`, `variant`) instead of relying only on exact run-name directory matches.
   - It now tolerates equivalent temperature naming tokens (`t08` vs `t0p8`) when mapping completed runs.
   - This removed the manual-summary fallback needed in the previous cycle.
2. Repair-pool export cleanup:
   - [build_repair_pool_dataset.py](/Users/svdr/tinker/scripts/build_repair_pool_dataset.py) now supports `--output-audit-path`.
   - It can emit a merged `candidate_audit.json` directly from selected repair-pool rows, making repair waves reproducible from one command.
3. Existing native-repair script remained in active use:
   - [build_kimi_native_repair_dataset.py](/Users/svdr/tinker/scripts/build_kimi_native_repair_dataset.py)

### Repair17 cycle artifacts

Repair pool build (selected candidates only, deduped):

- output pool:
  - [/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_pool_selected.jsonl](/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_pool_selected.jsonl)
- merged audit for repair script input:
  - [/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_pool_selected_audit.json](/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_pool_selected_audit.json)
- summary:
  - [/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_pool_selected_summary.json](/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_pool_selected_summary.json)

Pool composition:

- `37` total rows
- `5` `tier2_hit`
- `32` `geometry_dominant_near_miss`
- sourced from `12` prior repair15/repair16 robustness audits

### Repair wave outcome

Bounded repair wave (`max_hits=16`, `rounds=1`, `radius=2`, `top_residues_per_position=2`, `beam_size=3`):

- survivors:
  - [/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_survivors_wave1.jsonl](/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_survivors_wave1.jsonl)
- best attempts:
  - [/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_best_attempts_wave1.jsonl](/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_best_attempts_wave1.jsonl)
- summary:
  - [/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_summary_wave1.json](/Users/svdr/tinker/reports/robustness/pearl-repair17-cycle-r1/repair_summary_wave1.json)

Result:

- `evaluated_variant_count = 186`
- `survivor_count = 15`

### Repair17 warm-start

Trained a one-epoch micro-SFT continuation from repair16 using the `15` repaired survivors.

- checkpoint:
  - `tinker://a3a29303-c696-574b-adbc-a9180c43aaa4:train:0/weights/pearl-micro-sft-repair17-from-repair16-wave1-lr5e7-ep1`
- summary:
  - [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-repair17-from-repair16-wave1-lr5e7-ep1/summary.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-repair17-from-repair16-wave1-lr5e7-ep1/summary.json)

### Repair17 durability check (`12` prompts, `t=0.8`, seeds `41/53/67`)

Run outputs:

- [/Users/svdr/tinker/reports/ablations/pearl-repair17-robustness-p12-t08-r1-p12-t0p8-s41/summary.json](/Users/svdr/tinker/reports/ablations/pearl-repair17-robustness-p12-t08-r1-p12-t0p8-s41/summary.json)
- [/Users/svdr/tinker/reports/ablations/pearl-repair17-robustness-p12-t08-r1-p12-t0p8-s53/summary.json](/Users/svdr/tinker/reports/ablations/pearl-repair17-robustness-p12-t08-r1-p12-t0p8-s53/summary.json)
- [/Users/svdr/tinker/reports/ablations/pearl-repair17-robustness-p12-t08-r1-p12-t0p8-s67/summary.json](/Users/svdr/tinker/reports/ablations/pearl-repair17-robustness-p12-t08-r1-p12-t0p8-s67/summary.json)

Robustness suite summary:

- [/Users/svdr/tinker/reports/robustness/pearl-repair17-robustness-p12-t08-r1/robustness_summary.json](/Users/svdr/tinker/reports/robustness/pearl-repair17-robustness-p12-t08-r1/robustness_summary.json)

Final vector and gate:

- `tier2_hits_by_seed = [0, 1, 0]`
- `prompt_coverage_by_seed = [0, 1, 0]`
- `bridge_hits_per_prompt.mean = 0.027778`
- `prompts_with_any_tier2_across_seeds = 1`
- durability gate: `FAILED`

Failed gate conditions:

- `seed_support`
- `prompt_coverage`
- `basin_pressure_vs_baseline`

### Comparison vs repair16

Repair17 did not increase durable bridge production:

- bridge vector remained `repair16: [0,1,0] -> repair17: [0,1,0]`
- bridge mean unchanged (`0.027778`)
- basin mix shifted:
  - stability-dominant mean worsened (`0.25 -> 0.277778`)
  - geometry-dominant mean improved (`0.25 -> 0.222222`)

Interpretation:

- this was a sideways move on the core target
- the branch remains in **search/repair mode**
- it is still not freeze-worthy as the canonical reference policy

## March 5, 2026 Wave3 Diversity + Repair20 Update

This section records the readiness hardening pass and the resulting `repair20` warm-start.

### What changed in code/workflow

1. Diversity-capped repair pool builder:
   - added [build_diversity_capped_repair_pool.py](/Users/svdr/tinker/scripts/build_diversity_capped_repair_pool.py)
   - supports caps by source run and identity cluster to avoid gradient domination by near-duplicates.
2. Repair lineage propagation:
   - updated [build_kimi_native_repair_dataset.py](/Users/svdr/tinker/scripts/build_kimi_native_repair_dataset.py)
   - survivors now carry parent-source lineage fields (`source_parent_run`, `source_parent_audit_path`).
3. Readiness attribution fix:
   - added [check_repair_survivor_readiness.py](/Users/svdr/tinker/scripts/check_repair_survivor_readiness.py)
   - source-share can now be computed from embedded lineage (or parent pool mapping) instead of collapsing survivors into one synthetic source.

### Wave3 repair pool and repair run

Built a multirun pool from `12` repair18 robustness audits:

- merged pool:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_multirun.jsonl](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_multirun.jsonl)
- merged summary:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_multirun_summary.json](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_multirun_summary.json)

Pool composition:

- `59` total (`8` tier2 + `51` geometry-dominant)

Diversity capping output:

- capped pool:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_diversity_capped.jsonl](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_diversity_capped.jsonl)
- capped audit:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_diversity_capped_audit.json](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_pool_diversity_capped_audit.json)
- selected after capping: `34`

Repair wave output:

- summary:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_summary_wave3_diversity.json](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_summary_wave3_diversity.json)
- survivors:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_survivors_wave3_diversity.jsonl](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_survivors_wave3_diversity.jsonl)
- lineage-enriched survivors:
  - [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_survivors_wave3_diversity_lineage.jsonl](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_survivors_wave3_diversity_lineage.jsonl)

Wave3 repair result:

- `evaluated_variant_count = 1370`
- `survivor_count = 32`

### Retrain readiness (lineage-aware)

Readiness artifacts:

- [/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_wave3_diversity_readiness_lineage_embedded.json](/Users/svdr/tinker/reports/analysis/backward_lane/pearl-repair18-p12p24p48-wave3/repair_wave3_diversity_readiness_lineage_embedded.json)

Gate result:

- `ready_for_retrain = true`
- checks: `7 / 7 passed`

Key counts:

- `deduped_tier2_count = 40`
- `deduped_tier1_proxy_count = 34`
- `cluster_count = 8`
- `largest_cluster_share = 0.125`
- `max_source_share = 0.25`
- `train_tier2_count = 32`
- `train_tier1_proxy_count = 26`

### Repair20 warm-start

Started one-epoch micro-SFT from repair18 using the `32` lineage-enriched wave3 survivors.

- summary:
  - [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-repair20-from-wave3-lineage-lr5e7-ep1/summary.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-repair20-from-wave3-lineage-lr5e7-ep1/summary.json)
- full report:
  - [/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-repair20-from-wave3-lineage-lr5e7-ep1/report.json](/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-repair20-from-wave3-lineage-lr5e7-ep1/report.json)

Checkpoint produced:

- `tinker://6c7881f9-0330-5a3b-8acf-f2a44a7cbf70:train:0/weights/pearl-micro-sft-repair20-from-wave3-lineage-lr5e7-ep1`

Interpretation:

- readiness hardline is now actually met (not just near-miss),
- lineage/source-share accounting is fixed,
- branch is ready for post-retrain durability confirmation (`12 -> 24 -> 48`, fixed seeds).

## March 7-8, 2026 Pivot Update: Wynton + Budget Burn + Local Prefilter

This section captures the major operational pivot away from local full-eval loops and into:

1. budget-capped raw generation now,
2. heavy scoring/optimization on Wynton GPU later,
3. new local prefiltering so HPC time is not wasted on obvious junk.

### Strategic pivot and budget policy

- Wynton HPC was designated as the target runtime for heavy ESM/geometry and training loops.
- Local machine was repurposed for high-volume Tinker raw generation and preprocessing only.
- Spend policy changed to:
  - burn approximately `USD 1,000` for raw candidate stockpile,
  - allow controlled overrun to hit practical round-number data targets,
  - keep the majority of remaining grant for cluster-side LoRA/RAFT work.

Planning artifact:

- [/Users/svdr/tinker/notes/WYNTON_PIVOT_CHECKLIST.md](/Users/svdr/tinker/notes/WYNTON_PIVOT_CHECKLIST.md)

### Raw-generation campaign summary

Main cohorts launched:

1. `kimi25-raw-10x100-20260307-002408-r01..r10`
2. `kimi25-raw-plus10x50-20260307-012712-r11..r20`
3. top-off cohort for 1M push:
   - `kimi25-topoff1m-20260308-010724-r01..r20`
   - per-run cap `USD 21`, `samples_per_request=64`, `compress=false`

As of `2026-03-08T05:01:36Z`:

- top-off cohort (`20` runs):
  - spend: `USD 281.177182`
  - raw candidates: `229,696`
  - output tokens: `61,721,314`
  - requests: `3,589`
  - runner health snapshot: `20 active`, `0 stalled`, `0 capped`
- all raw-generation progress files combined (`44` runs):
  - spend: `USD 1,292.923572`
  - raw candidates: `1,053,033`
  - output tokens: `283,933,432`

### Data-integrity incident and recovery

A corruption/recovery pass was run on the initial 20-run campaign outputs.

Artifact:

- [/Users/svdr/tinker/reports/raw_generation/recovery_audit_20260307/damage_report.json](/Users/svdr/tinker/reports/raw_generation/recovery_audit_20260307/damage_report.json)

Reported totals (`generated_at_utc = 2026-03-07T17:17:37Z`):

- `expected_candidates = 498,944`
- `recovered_candidates = 494,190`
- `damage_candidates = 4,754`
- `recovery_rate = 0.99047188`
- `aggregate_json_parse_or_schema_errors_seen = 30`

Interpretation:

- the majority of data survived,
- corruption pressure was real enough to justify hardened supervision and salvage-aware ingest.

### Supervision hardening for long local runs

The watchdog path was hardened to reduce bad restarts and preserve run semantics:

- [/Users/svdr/tinker/reports/raw_generation/watchdog_supervisor.py](/Users/svdr/tinker/reports/raw_generation/watchdog_supervisor.py)

Key operational hardening points:

1. run-pattern override via `WATCHDOG_RUN_PATTERNS`.
2. dynamic stale thresholds tied to observed request latency (`STALE_LATENCY_MULTIPLIER`) with minimum floors.
3. restart command preserves key run config flags (`compress`, max-* limits, budget flags).
4. avoids unnecessary restart behavior when runs are already complete/capped.
5. integrated with local `caffeinate` use during overnight generation.

### Local prefilter suite implemented (pre-HPC triage)

To avoid burning Wynton cycles on obvious failures, a local staged prefilter pipeline was implemented:

- core pipeline:
  - [/Users/svdr/tinker/scripts/prefilter_local.py](/Users/svdr/tinker/scripts/prefilter_local.py)
- rules config:
  - [/Users/svdr/tinker/configs/prefilter/local_prefilter_v1.yaml](/Users/svdr/tinker/configs/prefilter/local_prefilter_v1.yaml)
- run-to-run uniqueness comparator:
  - [/Users/svdr/tinker/scripts/snapshot_prefilter_uniqueness.py](/Users/svdr/tinker/scripts/snapshot_prefilter_uniqueness.py)
- fixture + regression smoke:
  - [/Users/svdr/tinker/benchmarks/prefilter_smoke_fixture/raw_samples_fixture.jsonl](/Users/svdr/tinker/benchmarks/prefilter_smoke_fixture/raw_samples_fixture.jsonl)
  - [/Users/svdr/tinker/scripts/check_prefilter_smoke.py](/Users/svdr/tinker/scripts/check_prefilter_smoke.py)

Pipeline stages:

1. `ingest` (parse + salvage),
2. `canonicalize`,
3. `hard-filter`,
4. `exact-dedup`,
5. `near-dedup`,
6. `priority`,
7. `handoff`.

Validation status:

- `check_prefilter_smoke.py` passed.
- production sanity run on `5,000` real records passed end-to-end:
  - hard-filter pass/reject: `4520 / 480`
  - exact dedup unique/dup: `3766 / 754`
  - near-dedup selected/members: `3762 / 4`
  - handoff ready counts: `A=3757`, `B=5`

Important nuance:

- with no novelty reference set, priority naturally collapses toward mostly `A` tier.
- meaningful `A/B/C` stratification requires providing historical reference inputs to `--reference-jsonl`.

### Trigger command at 1M milestone

When the raw-generation target is reached and writes are stable/paused, run:

```bash
python /Users/svdr/tinker/scripts/prefilter_local.py all \
  --inputs /Users/svdr/tinker/reports/raw_generation \
  --out-root /Users/svdr/tinker/reports/prefilter/topoff_1m_run
```

This produces staged outputs plus `summary.json` and scheduler-ready handoff JSONLs for HPC.

### Prefilter execution snapshot (March 8, 2026)

The full local prefilter pipeline was executed against the assembled raw-generation corpus:

- command:
  - `python /Users/svdr/tinker/scripts/prefilter_local.py all --inputs /Users/svdr/tinker/reports/raw_generation --out-root /Users/svdr/tinker/reports/prefilter/topoff_1m_run`
- output root:
  - [/Users/svdr/tinker/reports/prefilter/topoff_1m_run](/Users/svdr/tinker/reports/prefilter/topoff_1m_run)
- summary artifact:
  - [/Users/svdr/tinker/reports/prefilter/topoff_1m_run/summary.json](/Users/svdr/tinker/reports/prefilter/topoff_1m_run/summary.json)
- handoff manifest:
  - [/Users/svdr/tinker/reports/prefilter/topoff_1m_run/handoff/manifest.json](/Users/svdr/tinker/reports/prefilter/topoff_1m_run/handoff/manifest.json)

Observed stage counts:

- ingest:
  - `raw_file_count = 92`
  - `lines_seen = 1,010,348`
  - `records_written = 1,010,346`
  - `json_parse_success = 1,010,213`
  - `json_parse_fail = 135`
  - `salvaged = 133`
  - `source_read_errors = 30` (truncated/corrupt gzip read failures)
- hard-filter:
  - `pass_count = 947,551`
  - `reject_count = 62,795`
- exact dedup:
  - `unique_count = 763,343`
  - `dup_count = 184,208`
- near dedup:
  - `selected_count = 761,987`
  - `cluster_members_count = 1,356`
- priority:
  - `tier_a_count = 761,029`
  - `tier_b_count = 958`
  - `tier_c_count = 0`
- handoff:
  - `hpc_ready_A = 761,029`
  - `hpc_ready_B = 958`
  - `hpc_explore_C_sample = 0`

Operational note:

- `prefilter_local.py` ingest was hardened to tolerate compressed-stream failures (`EOFError`, `zlib.error`, decode errors) on a per-file basis, record them in ingest stats/rejects, and continue rather than aborting the full run.

### HPC handoff sharding + transfer package snapshot (March 8, 2026)

To make SGE-array submission deterministic, the handoff outputs were split into fixed-size shards and bundled with integrity metadata.

- sharded package root:
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538)
- transfer bundle:
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538_bundle.tar.gz](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538_bundle.tar.gz)
- bundle checksum:
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538_bundle.tar.gz.sha256](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538_bundle.tar.gz.sha256)
- shard manifest + checksums:
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/shard_manifest.json](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/shard_manifest.json)
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/SHA256SUMS.txt](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/SHA256SUMS.txt)
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/SHA256_VERIFY.txt](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/SHA256_VERIFY.txt)
- SGE hint file:
  - [/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/sge_array_hint.env](/Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/meta/sge_array_hint.env)

Sharding policy and counts:

- `A`: `10,000` records per shard -> `77` shards (`761,029` total lines)
- `B`: `1,000` records per shard -> `1` shard (`958` total lines)
- recommended array range for `A`: `1-77`

### Sequence-shard HPC scorer path added (March 8, 2026)

The prior SGE templates were prompt-driven (`run_ablation.py`) and did not directly consume `hpc_ready_A/B` sequence records.  
To support prefilter handoff scoring directly on Wynton, a sequence-shard evaluator path was added.

- sequence scorer:
  - [/Users/svdr/tinker/scripts/run_sequence_shard_eval.py](/Users/svdr/tinker/scripts/run_sequence_shard_eval.py)
- SGE array submit template:
  - [/Users/svdr/tinker/hpc/submit_prefilter_eval_array.sge.sh](/Users/svdr/tinker/hpc/submit_prefilter_eval_array.sge.sh)
- docs:
  - [/Users/svdr/tinker/hpc/README.md](/Users/svdr/tinker/hpc/README.md)

Capabilities:

1. Reads one `hpc_ready_*.jsonl` shard,
2. runs ESM proxy + PETase family/geometry evaluation per sequence,
3. writes:
   - `scored_candidates.jsonl`
   - `functional_bridges.jsonl`
   - `rejects.jsonl`
   - `summary.json`

Smoke validation on real shard data:

- command used:
  - `ESM2_DEVICE=cpu python /Users/svdr/tinker/scripts/run_sequence_shard_eval.py --input-jsonl /Users/svdr/tinker/reports/hpc_transfer/topoff_1m_run_20260307-232538/shards/A/hpc_ready_A_shard_0001.jsonl --output-dir /Users/svdr/tinker/reports/hpc_sequence_eval_smoke --reference-records-path /Users/svdr/tinker/data/petase_family_expanded/petase_records.jsonl --name smoke-a0001 --limit 3`
- result:
  - evaluated `3/3` records
  - output artifacts written under:
    - [/Users/svdr/tinker/reports/hpc_sequence_eval_smoke/smoke-a0001](/Users/svdr/tinker/reports/hpc_sequence_eval_smoke/smoke-a0001)
