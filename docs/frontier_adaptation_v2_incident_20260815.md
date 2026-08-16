# Frontier adaptation v2 dispatch incident — 2026-08-15

## Status

Contained. All six Frontier adaptation v2 GitHub Actions workflows were disabled
manually on 2026-08-15 while the recovery was prepared. Existing workers were not
cancelled because their supervisor authorizations restore canonical predecessors;
workflow disablement prevents new dispatch without destroying useful lineage.

This record is operational evidence. It does not amend the frozen scientific
protocol, plans, estimands, exclusions, seeds, model set, endpoints, or analysis.

## What happened

The campaign supervisor reconstructed completed GitHub artifacts, then captured a
provider snapshot, then queried active Actions runs. A continuation could complete
after artifact reconstruction but before the active-run query. In that interval it
was neither present in reconstructed state nor active. The controller therefore
treated the same cell as dispatchable and submitted the same source checkpoint and
segment endpoint a second time.

Two supervisor runs encountered this time-of-check/time-of-use gap:

- supervisor `31872082233` began before canonical continuations `31870576104` and
  `31870580331` became reconstructable, then dispatched redundant workers
  `31872368393` and `31872376941`;
- supervisor `31872666324` began before canonical continuations `31870568644` and
  `31870593521` became reconstructable, then dispatched redundant workers
  `31872940776` and `31872956133`.

Each redundant worker restored the same source Actions run and reached the same
segment endpoint as its earlier canonical worker. These are operational duplicates,
not replicates, and are excluded from scientific checkpoint lineage.

## Exact disposition

| Run key | Canonical Actions run | Redundant Actions run | Frozen endpoint |
| --- | ---: | ---: | ---: |
| `core-fixed-rank-nemotron3p5-lightning-shuffled-seed43-bd8aadf4c8` | `31870576104` | `31872368393` | 1050 |
| `core-fixed-rank-inkling-small-shuffled-seed43-b3b60c4690` | `31870580331` | `31872376941` | 650 |
| `core-fixed-rank-gptoss-120b-true-seed43-79c733d9e7` | `31870568644` | `31872940776` | 1050 |
| `core-fixed-rank-gptoss-120b-true-seed17-6aecd7fbc1` | `31870593521` | `31872956133` | 1050 |

The executor registry binds every quarantine entry to its run key, source commit,
source Actions run, endpoint, canonical and redundant supervisor IDs, supervisor
authorization hashes, worker-authorization receipt hashes, and redundant provider
training-run ID. Reconstruction validates the canonical and redundant artifacts
against those exact claims, requires identical lineage before the final provider
branch, and writes a content-hashed quarantine receipt. Quarantined providers are
permitted only as an exact disjoint set during the terminal provider audit.

## Corrective controls

1. The supervisor now obtains the Actions inventory through the campaign manager.
   If a recognized paid run is terminal but lacks its reconstructed marker, the
   supervisor stops and requires a fresh reconstruction; it does not dispatch.
2. Every training or evaluation authorization carries a semantic dispatch claim
   over campaign, stage, run key, action, source Actions run, and segment endpoint.
   Reusing a claim is rejected even when the supervisor authorization receipt is new.
3. The four redundant continuations are separated from legacy continuation handling.
   They cannot overwrite canonical submission, continuation, or evaluation evidence.
4. Terminal provider identity must equal canonical checkpoint lineage plus the exact
   configured quarantine. Unknown, overlapping, or missing provider identities fail
   closed.

## High-concurrency follow-up — 2026-08-16

After the 24-cell tier opened, supervisor `31965179273` encountered the protected
terminal-after-reconstruction condition: training run `31961922223` completed between
artifact reconstruction and active-inventory capture. No authorization was published
and no child was dispatched. This was the circuit breaker working, but at high
concurrency repeated ordinary completions could force repeated manual supervisor runs.

The supervisor now recognizes this exact condition through a dedicated process exit
code and performs at most two internal retries. Before each retry it reconstructs
Actions artifacts again, rewrites the frozen manifest, and refreshes the sanitized
provider snapshot. Authorization and dispatch remain downstream of a successful fresh
inventory. Every other exception and exhaustion of the three total attempts still
fails closed. This is an operational liveness repair; it changes no scientific
identity, observation, endpoint, analysis, cohort boundary, or budget.

## Full-tier scheduling follow-up — 2026-08-16

Supervisor `31968329435` correctly opened the full 47-cell tier but retained the
ordinary resume-first queue priority. With 13 cells terminal and evaluated, 24 cells
already exposed, and 11 frozen cells never started, it authorized 17 resumptions.
That was contract-valid but defeated the purpose of opening the full cohort tier:
long-running cells could repeatedly reclaim free slots while later frozen identities
remained starved.

Before any remaining unstarted-cell endpoint was inspected, the primary prospectively
amended scheduling liveness. At the validated full-cohort tier only, never-submitted
frozen identities take temporary priority in pre-randomized order until every cohort
identity has started. Ordinary resume-then-evaluate-then-new ordering then returns.
The controller applies the same rule to original and replication and records the
chosen priority in each authorization. This changes scheduling only: no scientific
identity, data, model, seed, endpoint, estimand, exclusion, cohort boundary, or spend
ceiling changed.

## Re-enable gate

Do not re-enable paid dispatch until all of the following are true:

- the recovery changes have passed the focused and full repository test suites;
- both frozen core plans regenerate to their recorded contract hashes and contain
  48 unique run identities each;
- a fresh read-only GitHub reconstruction produces the four exact quarantine
  receipts and no unowned completed paid run;
- a current provider snapshot passes capacity and identity validation;
- a status-only supervisor run succeeds from the merged recovery commit.

Enable the paid worker and evaluation workflows only after that status-only run.
