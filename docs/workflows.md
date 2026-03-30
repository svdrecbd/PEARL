# Workflows

This repo currently supports a small set of reusable workflows. If a task does not fit one of these, it is probably campaign history rather than supported surface.

## 1. Mine

Purpose:
- run a stage1 mining wave from a chosen prior over a prompt pack or prompt slice

Current scientific default:
- use mining to increase cross-prompt strict coverage, not just raw strict-hit count
- current next-tranche path is the coverage-aware `stageb-lite` million with an adversarial prompt slice for historically weak-conversion buckets

Primary entrypoints:
- [scripts/mining_experiment.py](../scripts/mining_experiment.py)
- [scripts/launch_mining_experiment.sh](../scripts/launch_mining_experiment.sh)
- [scripts/launch_topoff1m_a_targeted_raft.sh](../scripts/launch_topoff1m_a_targeted_raft.sh)
- [scripts/launch_topoff1m_a_stageb_lite_coverage_million.sh](../scripts/launch_topoff1m_a_stageb_lite_coverage_million.sh)
- [scripts/build_topoff1m_a_stageb_lite_next_million_prompt_pack.py](../scripts/build_topoff1m_a_stageb_lite_next_million_prompt_pack.py)

Config-driven mining examples:
- [configs/experiments/mining/topoff1m_a_targeted_raft.json](../configs/experiments/mining/topoff1m_a_targeted_raft.json)
- [configs/experiments/mining/topoff1m_a_stageb_lite_even_million.json](../configs/experiments/mining/topoff1m_a_stageb_lite_even_million.json)
- [configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million.json](../configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million.json)

Outputs:
- `reports/raft/...`
- `reports/raft_prompt_packs/...`

## 2. Postprocess

Purpose:
- finalize mining waves
- merge finalized waves into exact-deduped and lineage-aware bundles

Primary entrypoints:
- [scripts/finalize_raft_wave.py](../scripts/finalize_raft_wave.py)
- [scripts/finalize_raft_wave_partition.py](../scripts/finalize_raft_wave_partition.py)
- [scripts/build_finalized_hit_lineage_bundle.py](../scripts/build_finalized_hit_lineage_bundle.py)

Outputs:
- `reports/raft/.../finalization_summary.json`
- `reports/raft/.../bundle_summary.json`

## 3. Build Dataset

Purpose:
- build strict retrain curricula from old strict hits, mined strict reps, purebreds, and optional small anchors

Primary entrypoint:
- [scripts/build_strict_first_union_curricula.py](../scripts/build_strict_first_union_curricula.py)

Important current behavior:
- constrained prompt / prompt-bucket / cluster selection
- loud failure on shortfall instead of silent backfill
- current prototype policy is coverage-first: prompt diversity first, then prompt-bucket / cluster diversity, then quality ranking
- config-driven build path available through:
  - [scripts/strict_experiment.py](../scripts/strict_experiment.py)
  - [configs/experiments/strict/topoff1m_a_strict_core_v6.json](../configs/experiments/strict/topoff1m_a_strict_core_v6.json)

## 4. Train

Purpose:
- run SFT warmstarts from a dataset and base checkpoint

Primary entrypoints:
- [scripts/run_sft_warmstart.py](../scripts/run_sft_warmstart.py)
- [scripts/launch_detached_job.py](../scripts/launch_detached_job.py)
- [scripts/strict_experiment.py](../scripts/strict_experiment.py)
- [scripts/launch_strict_experiment.sh](../scripts/launch_strict_experiment.sh)

For strict experiment chains, the supported path is now config-driven:
- [configs/experiments/strict/topoff1m_a_strict_core_v6.json](../configs/experiments/strict/topoff1m_a_strict_core_v6.json)

## 5. Robustness

Purpose:
- run fixed `p12/p24/p48` robustness suites
- run smaller `p48` smoke gates before promoting a branch

Current strict-branch promotion rule:
- a smoke pass now requires at least `2` seeds with hits and at least `2` prompts hit across seeds
- isolated strict hits no longer justify automatic stage-B promotion

Primary entrypoints:
- [scripts/run_robustness_two_phase.py](../scripts/run_robustness_two_phase.py)
- [scripts/evaluate_strict_core_smoke_gate.py](../scripts/evaluate_strict_core_smoke_gate.py)
- [scripts/strict_experiment.py](../scripts/strict_experiment.py)

## 6. Reranker

Purpose:
- build prompt-matched preference pairs from mined outputs
- train a lightweight reranker and compare it against scalar proxy baselines

Current scientific role:
- reranker is a diagnostic / measurement lane first
- do not treat it as a generator-training default until it clearly beats the strongest scalar reward baselines on the harder held-out splits

Primary entrypoints:
- [scripts/build_pairwise_reranker_dataset.py](../scripts/build_pairwise_reranker_dataset.py)
- [scripts/train_pairwise_reranker.py](../scripts/train_pairwise_reranker.py)
- [scripts/build_topoff1m_a_stageb_lite_reranker_dataset.sh](../scripts/build_topoff1m_a_stageb_lite_reranker_dataset.sh)
- [scripts/train_topoff1m_a_stageb_lite_reranker.sh](../scripts/train_topoff1m_a_stageb_lite_reranker.sh)
