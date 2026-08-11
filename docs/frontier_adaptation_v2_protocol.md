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
authorization envelope is $2,300.00. GiveMeANode is capped at $481.83 and six active H100 jobs.

All paid execution is remote and supervisor-owned. At most six cells may be active across a campaign.
Closing or disconnecting the laptop does not stop a dispatched GitHub/Tinker worker or remote H100
job. The laptop is required only to invoke the next transition or perform the mechanically specified
manual GiveMeANode submission boundary.

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
