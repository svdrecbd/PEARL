# Phase 8 No-Logits OPD Packet

This packet keeps Phase 8 moving while full-vocabulary logits access is pending.

## Decision

Exact ProteinOPD remains blocked on full-vocabulary student and teacher logits.
Current Tinker APIs are still enough for a useful sparse approximation:

1. Sample on-policy rollouts from the current student policy.
2. Teacher-force each rollout through each preference teacher.
3. Request top-K prompt logprobs for every generated position.
4. Combine teacher top-K distributions with a weighted sparse product-of-experts.
5. Train the student with Tinker cross-entropy over `(N, K)` target tokens and soft weights.

This is not exact full-vocab JSD ProteinOPD. It is a sparse OPD lane that tests the same practical claim:
can on-policy teacher consensus reduce confident structural hallucination while preserving novelty?

## June 2026 DPO Pilot Context

The no-logits OPD lane is still relevant after the first paid DPO pilot.

The May 30, 2026 DPO run showed that the custom-loss DPO infrastructure works: a `3,000`-pair pilot completed and the training loss/reward-margin moved in the expected direction. The June W&B/local-metric review strengthens that read: first-100-batch mean DPO loss was `0.6775` versus last-100 `0.3655`, and first-100 mean reward margin was `0.0419` versus last-100 `2.7476`.

But the only completed post-DPO evaluation slice was `p12`, temperature `0.8`, seed `7`, and the folded subset remained structurally weak:

- `0 / 12` functional bridge hits
- `0 / 12` family-faithful bridge hits
- `0 / 5` folded candidates passed CA-triad distance checks
- folded candidate mean pLDDT range: `25.61-36.27`

Canonical readout: [phase8_dpo_pilot_readout.md](phase8_dpo_pilot_readout.md).

Interpretation: solo DPO should be kept as an active, promising baseline/control. The current DPO-only structural slice is too thin to estimate yield or localize failure, but the folded subset is enough to define the structural-hallucination mode that sparse OPD should be tested against. Before treating OPD as the better path, compare it against a sufficiently characterized DPO-only baseline.

## Current Runnable Materials

- Phase 8 DPO pilot readout:
  - [docs/phase8_dpo_pilot_readout.md](phase8_dpo_pilot_readout.md)
- Sparse target builder:
  - [scripts/build_sparse_opd_targets.py](../scripts/build_sparse_opd_targets.py)
- Sparse target utilities:
  - [src/pearl/opd_lite.py](../src/pearl/opd_lite.py)
- Tinker sparse-OPD smoke runner:
  - [scripts/run_tinker_sparse_opd_smoke.py](../scripts/run_tinker_sparse_opd_smoke.py)
- Static rollout seed builder:
  - [scripts/build_sparse_opd_rollout_seed.py](../scripts/build_sparse_opd_rollout_seed.py)
- Tinker teacher trace collector:
  - [scripts/build_tinker_teacher_traces.py](../scripts/build_tinker_teacher_traces.py)
- Paid-run readiness and cost preflight:
  - [scripts/phase8_paid_run_preflight.py](../scripts/phase8_paid_run_preflight.py)
- Physical DPO/OPD artifact builder:
  - [scripts/run_physical_to_sequence_loop.py](../scripts/run_physical_to_sequence_loop.py)
- Static DPO smoke runner:
  - [scripts/run_tinker_dpo_smoke.py](../scripts/run_tinker_dpo_smoke.py)

## Teacher Trace Schema

One JSONL row is one rollout. The positions must correspond to generated sequence tokens.

```json
{
  "sample_id": "rollout-000001",
  "prompt": "Design a PETase/cutinase-like hydrolase.",
  "sequence": "ACDE...",
  "teachers": {
    "foldability": {
      "weight": 0.35,
      "temperature": 0.7,
      "positions": [
        {"token_ids": [10, 20, 30], "logprobs": [-0.2, -2.1, -3.0]}
      ]
    },
    "family_identity": {
      "weight": 0.35,
      "temperature": 0.7,
      "positions": [
        {"token_ids": [10, 40, 50], "logprobs": [-0.4, -1.5, -2.7]}
      ]
    },
    "developability": {
      "weight": 0.30,
      "temperature": 0.7,
      "positions": [
        {"token_ids": [10, 60, 70], "logprobs": [-0.5, -1.2, -3.2]}
      ]
    }
  }
}
```

Alternative position format is also accepted:

```json
[[10, -0.2], [20, -2.1], [30, -3.0]]
```

## Build Sparse OPD Targets

For a smoke-only static seed panel:

```bash
.venv/bin/python scripts/build_sparse_opd_rollout_seed.py \
  --max-rows 256
```

Collect teacher top-K traces. Replace the `tinker://...` placeholders with actual teacher checkpoint paths:

```bash
.venv/bin/python scripts/build_tinker_teacher_traces.py \
  --name phase8-teacher-traces \
  --rollouts-path reports/opd_lite/rollouts.jsonl \
  --teacher name=foldability,path=tinker://...,weight=0.35,temperature=0.7 \
  --teacher name=family_active_site,path=tinker://...,weight=0.35,temperature=0.7 \
  --teacher name=developability,path=tinker://...,weight=0.20,temperature=0.7 \
  --teacher name=novelty_diversity,path=tinker://...,weight=0.10,temperature=0.7 \
  --top-k 20 \
  --max-rollouts 8
```

```bash
.venv/bin/python scripts/build_sparse_opd_targets.py \
  --name phase8-sparse-opd-targets \
  --teacher-trace-path reports/opd_lite/phase8-teacher-traces/teacher_traces.jsonl \
  --top-k 20 \
  --missing-logprob -30 \
  --min-teacher-count 1
```

Output:

- `reports/opd_lite/phase8-sparse-opd-targets/sparse_opd_targets.jsonl`
- `reports/opd_lite/phase8-sparse-opd-targets/manifest.json`

The target rows contain:

- `target_token_ids`: sparse candidate token IDs per generated position.
- `target_weights`: normalized sparse PoE soft target weights per generated position.
- `position_diagnostics`: sparse disagreement and teacher coverage diagnostics.
- `consensus`: teacher weights, top-K settings, and readiness metadata.

## No-Cost Shape Check

```bash
.venv/bin/python scripts/run_tinker_sparse_opd_smoke.py \
  --name phase8-sparse-opd-shape \
  --targets-path reports/opd_lite/phase8-sparse-opd-targets/sparse_opd_targets.jsonl \
  --shape-only
```

Full preflight and cost estimate:

```bash
.venv/bin/python scripts/phase8_paid_run_preflight.py \
  --name phase8-paid-readiness
```

## Tiny Paid Sparse OPD Smoke

Use this only after the DPO smoke has passed and spend is intentional.

```bash
.venv/bin/python scripts/run_tinker_sparse_opd_smoke.py \
  --name phase8-sparse-opd-smoke \
  --targets-path reports/opd_lite/phase8-sparse-opd-targets/sparse_opd_targets.jsonl \
  --max-rows 8 \
  --batch-size 2 \
  --epochs 1 \
  --model moonshotai/Kimi-K2.6
```

## Recommended Teacher Set Without Full Logits

Keep the first lane small enough to diagnose:

| Teacher | Purpose | Suggested weight |
| --- | --- | ---: |
| Foldability / anti-hallucination | Penalize fold mirages and repeat/domain duplication | 0.35 |
| PETase-family / active-site geometry | Preserve family identity and catalytic context | 0.35 |
| Developability | Solubility, aggregation, expression, manufacturability, biosafety | 0.20 |
| Novelty/diversity gate | Prevent memorized near-neighbor collapse | 0.10 |

Novelty/diversity can start as a gate or sample-selection rule rather than a token-level teacher.

## What This Tests

The first scientific comparison after the May 30 DPO pilot is:

- base model
- SFT model
- DPO model
- sparse OPD model
- DPO + sparse OPD model

Readout:

- pLDDT / pTM
- repeat/domain duplication artifacts
- active-site geometry
- PETase/cutinase-family HMM score
- novelty distance
- diversity
- solubility / aggregation proxies
- expression / manufacturability / biosafety proxies

The key endpoint is whether DPO + sparse OPD reduces structural mirages versus a properly matched DPO-only baseline while preserving novelty. The first DPO-only slice did not pass structural validation, but it was budget-limited; proxy-score improvement without folded-structure improvement should not be treated as success, and one thin fold subset should not be treated as a full DPO verdict. The W&B training curves make DPO more worth characterizing, not less.

## What Stays Blocked

Exact ProteinOPD still needs one of these:

- training-time custom loss over full student logits, or
- full-vocabulary teacher and student next-token logprobs at every rollout position, or
- a hosted primitive that computes the normalized product-of-experts JSD loss server-side.

Once available, the sparse target builder should be replaced by full-vocab PoE/JSD, while preserving the same teacher config, rollout/evaluation protocol, and report structure.
