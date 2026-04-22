# Workflows

This repo currently supports a small set of reusable workflows. If a task does not fit one of these, it is probably campaign history rather than supported surface.

## 1. Mine

Purpose:
- run a stage1 mining wave from a chosen prior over a prompt pack or prompt slice

Current scientific default:
- use mining only when the team explicitly wants a paid diagnostic or targeted tranche
- do not treat a blind broad `1M` run as the default next move
- if mining is used next, start with a `50k-75k` p12/p24 exact-hole sweep before scaling to a `250k-300k` targeted tranche
- the prepared coverage-aware million remains a fallback reference design, but the current recommendation is scaffold-first manifold construction

Primary entrypoints:
- [scripts/mining_experiment.py](../scripts/mining_experiment.py)
- [scripts/launch_mining_experiment.sh](../scripts/launch_mining_experiment.sh)
- [scripts/launch_topoff1m_a_targeted_raft.sh](../scripts/launch_topoff1m_a_targeted_raft.sh)
- [scripts/launch_topoff1m_a_stageb_lite_coverage_million.sh](../scripts/launch_topoff1m_a_stageb_lite_coverage_million.sh)
- [scripts/launch_topoff1m_a_stageb_lite_coverage_million_local.sh](../scripts/launch_topoff1m_a_stageb_lite_coverage_million_local.sh)
- [scripts/build_topoff1m_a_stageb_lite_next_million_prompt_pack.py](../scripts/build_topoff1m_a_stageb_lite_next_million_prompt_pack.py)

Config-driven mining examples:
- [configs/experiments/mining/topoff1m_a_targeted_raft.json](../configs/experiments/mining/topoff1m_a_targeted_raft.json)
- [configs/experiments/mining/topoff1m_a_stageb_lite_even_million.json](../configs/experiments/mining/topoff1m_a_stageb_lite_even_million.json)
- [configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million.json](../configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million.json)
- [configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million_local_gemma.json](../configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million_local_gemma.json)

Local-hosted stage1 trial path:
- use the same coverage-aware prompt pack, but point stage1 sampling at a local OpenAI-compatible server on an H200-class box
- this path is stage1 / eval-only only; training and warmstarts still remain Tinker-backed
- operational helpers:
  - [scripts/setup_nebius_h200_local_stage1_env.sh](../scripts/setup_nebius_h200_local_stage1_env.sh)
  - [scripts/launch_local_vllm_server.sh](../scripts/launch_local_vllm_server.sh)
  - [scripts/check_local_openai_sampler.py](../scripts/check_local_openai_sampler.py)
  - [scripts/sync_local_stage1_bundle.sh](../scripts/sync_local_stage1_bundle.sh)

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

## 3. Analyze

Purpose:
- inventory the broader finalized historical mining universe, not just the current canonical retrain bundle
- measure anchor neighborhoods around strict and bridge-only hits before dedup/clustering compresses local structure away
- test whether saved historical surfaces already contain a usable anchor-centered repair lane

Primary entrypoints:
- [scripts/analysis_experiment.py](../scripts/analysis_experiment.py)
- [scripts/launch_analysis_experiment.sh](../scripts/launch_analysis_experiment.sh)
- [scripts/build_historical_hit_universe.py](../scripts/build_historical_hit_universe.py)
- [scripts/build_anchor_neighborhood_report.py](../scripts/build_anchor_neighborhood_report.py)
- [scripts/build_local_exploit_shortlist.py](../scripts/build_local_exploit_shortlist.py)

Config-driven analysis example:
- [configs/experiments/analysis/petase_historical_local_exploit.json](../configs/experiments/analysis/petase_historical_local_exploit.json)
- [configs/experiments/analysis/petase_historical_local_exploit_wide.json](../configs/experiments/analysis/petase_historical_local_exploit_wide.json)

Operational rule:
- this workflow is safe to stage on a dry-run launch pad first
- do not process the historical corpus until you explicitly launch it

Current scientific read:
- finalized-hit surfaces came back sparse
- widening to screened finalized-report winners also came back sparse
- so the analysis workflow now supports a real negative result as well as a discovery pass
- current conclusion: no passive local basin exists in the saved finalized corpus; repair has to come from candidate-audit surfaces or deliberate perturbation generation

Outputs:
- `reports/analysis/.../universe`
- `reports/analysis/.../neighborhoods`
- `reports/analysis/.../shortlist`

## 4. Build Dataset

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

## 5. Repair

Purpose:
- build a repair pool from candidate-audit surfaces
- run same-length native repair around the strongest geometry-positive anchors
- validate strict survivors and check whether they materially improve retrain readiness

Primary entrypoints:
- [scripts/repair_experiment.py](../scripts/repair_experiment.py)
- [scripts/launch_repair_experiment.sh](../scripts/launch_repair_experiment.sh)
- [scripts/build_repair_pool_dataset.py](../scripts/build_repair_pool_dataset.py)
- [scripts/build_kimi_native_repair_dataset.py](../scripts/build_kimi_native_repair_dataset.py)
- [scripts/validate_repair_survivors.py](../scripts/validate_repair_survivors.py)
- [scripts/check_repair_survivor_readiness.py](../scripts/check_repair_survivor_readiness.py)

Config-driven repair example:
- [configs/experiments/repair/topoff1m_a_local_repair_pilot_20260410.json](../configs/experiments/repair/topoff1m_a_local_repair_pilot_20260410.json)
- [configs/experiments/repair/topoff1m_a_local_repair_scaleup_20260412.json](../configs/experiments/repair/topoff1m_a_local_repair_scaleup_20260412.json)

Operational rule:
- treat this as the current gated branch, not as an unproven side experiment
- scale it only with explicit concentration caps across parent runs and source waves
- use a capped parent pool before native repair instead of trusting the raw merged pool order

Current result:
- the April 10 pilot succeeded:
  - `48` parents
  - `13,033` evaluated variants
  - `577` survivors
  - `192` strict shortlist rows
  - `122` strict-bridge consensus rows
  - readiness passed
- the April 12 diversity-capped scale-up also succeeded:
  - `96` parents
  - `28,030` evaluated variants
  - `1,071` survivors
  - `231` strict shortlist rows
  - `128` strict-bridge consensus rows
  - readiness passed with `443` deduped tier-2 positives, `280` tier-1 proxy positives, `largest_cluster_share = 0.0293`, and `max_source_share = 0.0655`
- the repair-derived strict set was then promoted into `strict-core-v7-repair`, which passed the stricter `p48` smoke gate and reached `stage-b-lite`
- the April 21/22 p12/p24 `v9` repair rescue failed:
  - `134` geometry-dominant near-misses
  - `47,489` local variants evaluated
  - `79` loose repair survivors
  - `0` strict shortlist rows
  - `0` strict bridge/family/consensus rows
  - readiness failed with `0` retrain positives

Current operating rule:
- repair remains a supported tool, but not a sufficient p12/p24 rescue path as currently implemented
- do not train on failed repair survivors that pass ESM but fail family scaffold validation
- future repair should preserve family manifold constraints before optimizing ESM or local geometry

## 6. Train

Purpose:
- run SFT warmstarts from a dataset and base checkpoint

Primary entrypoints:
- [scripts/run_sft_warmstart.py](../scripts/run_sft_warmstart.py)
- [scripts/launch_detached_job.py](../scripts/launch_detached_job.py)
- [scripts/strict_experiment.py](../scripts/strict_experiment.py)
- [scripts/launch_strict_experiment.sh](../scripts/launch_strict_experiment.sh)

For strict experiment chains, the supported path is now config-driven:
- [configs/experiments/strict/topoff1m_a_strict_core_v6.json](../configs/experiments/strict/topoff1m_a_strict_core_v6.json)
- [configs/experiments/strict/topoff1m_a_strict_core_v7_repair_20260412.json](../configs/experiments/strict/topoff1m_a_strict_core_v7_repair_20260412.json)
- [configs/experiments/strict/topoff1m_a_strict_core_v8_coverage_20260413.json](../configs/experiments/strict/topoff1m_a_strict_core_v8_coverage_20260413.json)
- [configs/experiments/strict/topoff1m_a_strict_core_v9_p12p24_repair_20260421.json](../configs/experiments/strict/topoff1m_a_strict_core_v9_p12p24_repair_20260421.json)

Operator rule:
- `v9` strict config is a record of the attempted path, not a branch to train from the failed repair output
- only build/train a new strict branch after the source strict pool passes readiness

## 7. Robustness

Purpose:
- run fixed `p12/p24/p48` robustness suites
- run smaller `p48` smoke gates before promoting a branch

Current strict-branch promotion rule:
- a smoke pass now requires at least `2` seeds with hits and at least `2` prompts hit across seeds
- isolated strict hits no longer justify automatic stage-B promotion
- `p48` functional hits without family-faithful signal no longer justify optimism by themselves
- `p12/p24` diagnostics should be run before spending on broader robustness when a branch is suspected of short-context collapse

Primary entrypoints:
- [scripts/run_robustness_two_phase.py](../scripts/run_robustness_two_phase.py)
- [scripts/evaluate_strict_core_smoke_gate.py](../scripts/evaluate_strict_core_smoke_gate.py)
- [scripts/strict_experiment.py](../scripts/strict_experiment.py)

## 8. Reranker

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

## 9. Manifold Construction

Purpose:
- construct PETase/cutinase-family candidates from valid scaffolds instead of asking a generator to rediscover the whole joint constraint
- preserve family length band, motif identity, active-site blueprint, catalytic spacing, and family-core screen as hard constraints
- only optimize stability, novelty, and diversity after strict family validity is guaranteed

Current scientific role:
- this is the recommended hard-route pivot after the `v8` p12/p24 collapse and the failed `v9` local repair rescue
- it is not yet a fully supported code workflow
- the first implementation should be validator-first and local-compute-first

Reference:
- [manifold_construction.md](manifold_construction.md)
