# Workflows

This repo currently supports a small set of reusable workflows. If a task does not fit one of these, it is probably campaign history rather than supported surface.

## 1. Mine

Purpose:
- run a stage1 mining wave from a chosen prior over a prompt pack or prompt slice

Primary entrypoints:
- [/Users/svdr/tinker/scripts/mining_experiment.py](/Users/svdr/tinker/scripts/mining_experiment.py)
- [/Users/svdr/tinker/scripts/launch_mining_experiment.sh](/Users/svdr/tinker/scripts/launch_mining_experiment.sh)
- [/Users/svdr/tinker/scripts/launch_topoff1m_a_targeted_raft.sh](/Users/svdr/tinker/scripts/launch_topoff1m_a_targeted_raft.sh)
- [/Users/svdr/tinker/scripts/launch_topoff1m_a_stageb_lite_coverage_million.sh](/Users/svdr/tinker/scripts/launch_topoff1m_a_stageb_lite_coverage_million.sh)
- [/Users/svdr/tinker/scripts/build_topoff1m_a_stageb_lite_next_million_prompt_pack.py](/Users/svdr/tinker/scripts/build_topoff1m_a_stageb_lite_next_million_prompt_pack.py)

Config-driven mining examples:
- [/Users/svdr/tinker/configs/experiments/mining/topoff1m_a_targeted_raft.json](/Users/svdr/tinker/configs/experiments/mining/topoff1m_a_targeted_raft.json)
- [/Users/svdr/tinker/configs/experiments/mining/topoff1m_a_stageb_lite_even_million.json](/Users/svdr/tinker/configs/experiments/mining/topoff1m_a_stageb_lite_even_million.json)
- [/Users/svdr/tinker/configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million.json](/Users/svdr/tinker/configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million.json)

Outputs:
- `reports/raft/...`
- `reports/raft_prompt_packs/...`

## 2. Postprocess

Purpose:
- finalize mining waves
- merge finalized waves into exact-deduped and lineage-aware bundles

Primary entrypoints:
- [/Users/svdr/tinker/scripts/finalize_raft_wave.py](/Users/svdr/tinker/scripts/finalize_raft_wave.py)
- [/Users/svdr/tinker/scripts/finalize_raft_wave_partition.py](/Users/svdr/tinker/scripts/finalize_raft_wave_partition.py)
- [/Users/svdr/tinker/scripts/build_finalized_hit_lineage_bundle.py](/Users/svdr/tinker/scripts/build_finalized_hit_lineage_bundle.py)

Outputs:
- `reports/raft/.../finalization_summary.json`
- `reports/raft/.../bundle_summary.json`

## 3. Build Dataset

Purpose:
- build strict retrain curricula from old strict hits, mined strict reps, purebreds, and optional small anchors

Primary entrypoint:
- [/Users/svdr/tinker/scripts/build_strict_first_union_curricula.py](/Users/svdr/tinker/scripts/build_strict_first_union_curricula.py)

Important current behavior:
- constrained prompt / prompt-bucket / cluster selection
- loud failure on shortfall instead of silent backfill
- config-driven build path available through:
  - [/Users/svdr/tinker/scripts/strict_experiment.py](/Users/svdr/tinker/scripts/strict_experiment.py)
  - [/Users/svdr/tinker/configs/experiments/strict/topoff1m_a_strict_core_v6.json](/Users/svdr/tinker/configs/experiments/strict/topoff1m_a_strict_core_v6.json)

## 4. Train

Purpose:
- run SFT warmstarts from a dataset and base checkpoint

Primary entrypoints:
- [/Users/svdr/tinker/scripts/run_sft_warmstart.py](/Users/svdr/tinker/scripts/run_sft_warmstart.py)
- [/Users/svdr/tinker/scripts/launch_detached_job.py](/Users/svdr/tinker/scripts/launch_detached_job.py)
- [/Users/svdr/tinker/scripts/strict_experiment.py](/Users/svdr/tinker/scripts/strict_experiment.py)
- [/Users/svdr/tinker/scripts/launch_strict_experiment.sh](/Users/svdr/tinker/scripts/launch_strict_experiment.sh)

For strict experiment chains, the supported path is now config-driven:
- [/Users/svdr/tinker/configs/experiments/strict/topoff1m_a_strict_core_v6.json](/Users/svdr/tinker/configs/experiments/strict/topoff1m_a_strict_core_v6.json)

## 5. Robustness

Purpose:
- run fixed `p12/p24/p48` robustness suites
- run smaller `p48` smoke gates before promoting a branch

Primary entrypoints:
- [/Users/svdr/tinker/scripts/run_robustness_two_phase.py](/Users/svdr/tinker/scripts/run_robustness_two_phase.py)
- [/Users/svdr/tinker/scripts/evaluate_strict_core_smoke_gate.py](/Users/svdr/tinker/scripts/evaluate_strict_core_smoke_gate.py)
- [/Users/svdr/tinker/scripts/strict_experiment.py](/Users/svdr/tinker/scripts/strict_experiment.py)

## 6. Reranker

Purpose:
- build prompt-matched preference pairs from mined outputs
- train a lightweight reranker and compare it against scalar proxy baselines

Primary entrypoints:
- [/Users/svdr/tinker/scripts/build_pairwise_reranker_dataset.py](/Users/svdr/tinker/scripts/build_pairwise_reranker_dataset.py)
- [/Users/svdr/tinker/scripts/train_pairwise_reranker.py](/Users/svdr/tinker/scripts/train_pairwise_reranker.py)
- [/Users/svdr/tinker/scripts/build_topoff1m_a_stageb_lite_reranker_dataset.sh](/Users/svdr/tinker/scripts/build_topoff1m_a_stageb_lite_reranker_dataset.sh)
- [/Users/svdr/tinker/scripts/train_topoff1m_a_stageb_lite_reranker.sh](/Users/svdr/tinker/scripts/train_topoff1m_a_stageb_lite_reranker.sh)
