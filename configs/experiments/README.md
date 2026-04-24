# Experiment Configs

This directory is the beginning of the config-driven workflow surface.

The intent is:
- reusable workflow logic in `scripts/` and `src/pearl/`
- experiment parameters in `configs/experiments/`
- historical wrapper scripts preserved, but demoted from the supported surface

Current supported config-driven strict experiment examples:
- [strict/topoff1m_a_strict_core_v7_repair_20260412.json](strict/topoff1m_a_strict_core_v7_repair_20260412.json)
- [strict/topoff1m_a_strict_core_v8_coverage_20260413.json](strict/topoff1m_a_strict_core_v8_coverage_20260413.json)
- [strict/topoff1m_a_strict_core_v9_p12p24_repair_20260421.json](strict/topoff1m_a_strict_core_v9_p12p24_repair_20260421.json)
- [strict/topoff1m_a_manifold_curriculum_v12_20260423.json](strict/topoff1m_a_manifold_curriculum_v12_20260423.json)
- [strict/topoff1m_a_manifold_curriculum_v13_20260423.json](strict/topoff1m_a_manifold_curriculum_v13_20260423.json)

Current generic launcher:
- [scripts/strict_experiment.py](../../scripts/strict_experiment.py)
- [scripts/launch_strict_experiment.sh](../../scripts/launch_strict_experiment.sh)

Current generic mining launcher:
- [scripts/mining_experiment.py](../../scripts/mining_experiment.py)
- [scripts/launch_mining_experiment.sh](../../scripts/launch_mining_experiment.sh)

Current generic historical-analysis launcher:
- [scripts/analysis_experiment.py](../../scripts/analysis_experiment.py)
- [scripts/launch_analysis_experiment.sh](../../scripts/launch_analysis_experiment.sh)

Current generic repair/local-exploit launcher:
- [scripts/repair_experiment.py](../../scripts/repair_experiment.py)
- [scripts/launch_repair_experiment.sh](../../scripts/launch_repair_experiment.sh)

Current generic manifold-construction launcher:
- [scripts/manifold_construction_experiment.py](../../scripts/manifold_construction_experiment.py)
- [manifold/topoff1m_a_phase1_constructor_20260422.json](manifold/topoff1m_a_phase1_constructor_20260422.json)

Shared reusable plumbing extracted so far:
- [src/pearl/paths.py](../../src/pearl/paths.py)
- [src/pearl/family.py](../../src/pearl/family.py)
- [src/pearl/esm_proxy.py](../../src/pearl/esm_proxy.py)
- [src/pearl/detached_jobs.py](../../src/pearl/detached_jobs.py)
- [src/pearl/watchers.py](../../src/pearl/watchers.py)
- [src/pearl/checkpoints.py](../../src/pearl/checkpoints.py)
- [src/pearl/io_utils.py](../../src/pearl/io_utils.py)
- [src/pearl/reports.py](../../src/pearl/reports.py)
- [src/pearl/smoke_gate.py](../../src/pearl/smoke_gate.py)
- [src/pearl/strict_curricula.py](../../src/pearl/strict_curricula.py)
- [src/pearl/run_records.py](../../src/pearl/run_records.py)

Mining configs:
- [mining/topoff1m_a_targeted_raft.json](mining/topoff1m_a_targeted_raft.json)
- [mining/topoff1m_a_stageb_lite_even_million.json](mining/topoff1m_a_stageb_lite_even_million.json)
- [mining/topoff1m_a_stageb_lite_coverage_million.json](mining/topoff1m_a_stageb_lite_coverage_million.json)
- [mining/topoff1m_a_stageb_lite_coverage_million_local_gemma.json](mining/topoff1m_a_stageb_lite_coverage_million_local_gemma.json)

Analysis config:
- [analysis/petase_historical_local_exploit.json](analysis/petase_historical_local_exploit.json)
- [analysis/petase_historical_local_exploit_wide.json](analysis/petase_historical_local_exploit_wide.json)

Repair config:
- [repair/topoff1m_a_local_repair_pilot_20260410.json](repair/topoff1m_a_local_repair_pilot_20260410.json)
- [repair/topoff1m_a_local_repair_scaleup_20260412.json](repair/topoff1m_a_local_repair_scaleup_20260412.json)
- [repair/topoff1m_a_v9_p12p24_repair_20260421.json](repair/topoff1m_a_v9_p12p24_repair_20260421.json)

Manifold-construction config:
- [manifold/topoff1m_a_phase1_constructor_20260422.json](manifold/topoff1m_a_phase1_constructor_20260422.json)

Current manifold read:
- Phase 1 scaffold-bank validation passed locally
- Phase 2 pre-ESM frontier generation produced `10,000` same-length strict-manifold candidates
- the recovered `v9` reject artifact is now included as `79` negative rows, with `0` negative family-manifold passes
- Phase 2 ESM scoring was offloaded to the L40S and completed:
  - `10,000 / 10,000` scored
  - min `99.73`, mean `99.9121`, max `99.98`
  - all `10,000` scored `>=95`
- Phase 2 diversity/readiness selection passed:
  - `230` selected strict candidates
  - `79` parent scaffolds
  - `8` unique lengths
  - `130` one-mutants and `100` two-mutants
  - `133` bridge-quality rows across `48` parent scaffolds
  - selected ESM min `99.8`, mean `99.9225`, max `99.98`
- manifold curriculum v1 was built and tested under the `$80` capped branch:
  - config: [strict/topoff1m_a_manifold_curriculum_v1_20260422.json](strict/topoff1m_a_manifold_curriculum_v1_20260422.json)
  - builder: [../../scripts/build_manifold_curriculum.py](../../scripts/build_manifold_curriculum.py)
  - dataset: `238` pairs from `230` selected Phase 2 rows plus `8` purebred rows
  - stage-A run: `pearl-micro-sft-topoff1m-a-manifold-v1-stagea-lr8e7-ep2`
  - gate run: `pearl-topoff1m-a-manifold-v1-stagea-gate-p12p24-t08-s41s53s67-c128`
  - `p12`: passed, tier-2 hits `[1, 2, 0]`
  - `p24`: failed, tier-2 hits `[0, 1, 0]`
  - no retries, stage-B, p48, or paid mining should be launched from this branch
- manifold curriculum v1.1 was built to patch the p24 prompt/length hole, then failed its p24-only gate:
  - config: [strict/topoff1m_a_manifold_curriculum_v11_20260422.json](strict/topoff1m_a_manifold_curriculum_v11_20260422.json)
  - audit: [../../scripts/audit_manifold_v1_gate.py](../../scripts/audit_manifold_v1_gate.py)
  - builder: [../../scripts/build_manifold_v11_curriculum.py](../../scripts/build_manifold_v11_curriculum.py)
  - audit found `23` p24 holes and `20 / 20` unique p24 requested lengths absent from the Phase 2 selected pool
  - dataset has `216` rows: `160` balanced Phase 2 anchors, `48` p24 prompt-replay strict scaffold anchors, `8` purebred anchors
  - p24 replay anchor mean absolute length delta is `0.042`, max absolute delta `1`
  - paid p24 gate completed cleanly but produced `0` tier-2 hits and `0` raw single-motif plus geometry plus ESM candidates
- manifold curriculum v1.2 used the failed v1.1 gate as an offline repair-frontier source:
  - config: [strict/topoff1m_a_manifold_curriculum_v12_20260423.json](strict/topoff1m_a_manifold_curriculum_v12_20260423.json)
  - lane builder: [../../scripts/build_manifold_v12_offline_lanes.py](../../scripts/build_manifold_v12_offline_lanes.py)
  - repair-frontier builder/scorer/selector:
    - [../../scripts/build_manifold_v12_repair_frontier.py](../../scripts/build_manifold_v12_repair_frontier.py)
    - [../../scripts/score_manifold_v12_repair_frontier.py](../../scripts/score_manifold_v12_repair_frontier.py)
    - [../../scripts/select_manifold_v12_repair_candidates.py](../../scripts/select_manifold_v12_repair_candidates.py)
  - selected `39` strict/core/ESM repair candidates across `38` sources and `29` exact lengths
  - paid p24 gate recovered `3` functional hits and `2` family-faithful hits, but only `3 / 24` prompts were covered
- manifold curriculum v1.3 replayed v1.2 hits plus support prompts and failed to widen the family-faithful basin:
  - config: [strict/topoff1m_a_manifold_curriculum_v13_20260423.json](strict/topoff1m_a_manifold_curriculum_v13_20260423.json)
  - builder: [../../scripts/build_manifold_v13_curriculum.py](../../scripts/build_manifold_v13_curriculum.py)
  - dataset has `64` rows: `39` v1.2 breadth anchors, `8` support prompt scaffolds, `9` gate-hit replays, and `8` purebred anchors
  - paid p24 gate regressed to tier-2 hits `[0, 0, 1]`, prompt coverage `1 / 24`, and `0` family-faithful hits
- current launch policy:
  - do not launch another paid `v1.x` replay, stage-B, p48, or broad mining tranche from this branch line
  - consume the manifold `v2` objective panel before spending again
  - panel builder: [../../scripts/build_manifold_v2_objective_panel.py](../../scripts/build_manifold_v2_objective_panel.py)
  - panel output: `reports/analysis/manifold_v2_objective_panel_20260424/`
  - use its `2` `v1.2` family-faithful hits as positives and `45` `v1.3` stable-only / geometry-only finalists as hard negatives
  - constructor builder: [../../scripts/build_manifold_v2_offline_constructor.py](../../scripts/build_manifold_v2_offline_constructor.py)
  - constructor output: `reports/analysis/manifold_v2_offline_constructor_20260424/`
  - expanded constructor/scoring output: `reports/analysis/manifold_v2_offline_constructor_20260424_batch2/`
  - final v2 selection has `34` strict/core/ESM candidates across `18` parent source keys and `14` exact lengths
  - finalized curriculum: `reports/curriculum/manifold_v2_20260424/manifold_v2_curriculum.jsonl`
  - paid p24/c128 diagnostic completed but failed durability with tier-2 hits `[0, 1, 0]`, prompt coverage `1 / 24`, and `0` family-faithful hits
  - prepared v2.1 bridge-weighted config: [strict/topoff1m_a_manifold_v21_bridge_20260424.json](strict/topoff1m_a_manifold_v21_bridge_20260424.json)
  - prepared v2.1 curriculum: `reports/curriculum/manifold_v21_20260424/manifold_v21_bridge_curriculum.jsonl`
  - v2.1 paid scope is limited to a tiny stage-A train plus p24-only diagnostic gate

Current repair read:
- the April 10 pilot validated the repair lane as a real branch:
  - `48` parents
  - `13,033` evaluated variants
  - `577` survivors
  - `192` strict shortlist rows
  - readiness passed
- the April 12 scale-up then passed with `96` parents, `1,071` survivors, and `231` strict shortlist rows
- the April 21/22 p12/p24 repair rescue failed as a v9 data source:
  - `134` geometry-dominant near-misses
  - `47,489` local variants evaluated
  - `79` loose repair survivors
  - `0` strict shortlist rows
  - readiness failed with `0` retrain positives
- the next strict branch should not be trained from the failed `v9` repair pool
- the current default is offline manifold v2 redesign; paid p12/p24 mining should remain diagnostic-only unless the offline redesign stalls

The historical-analysis path is intended to answer a narrower question than the retrain bundle builders:
- inventory the full finalized historical mining universe
- measure anchor neighborhoods before heavy bundle compression hides them
- build a shortlist of local-exploit-ready anchors

The widened variant exists because the first pass on finalized hit steps came back sparse:
- `petase_historical_local_exploit.json` scans finalized hit representatives
- `petase_historical_local_exploit_wide.json` widens the candidate surface to screened finalized-report near misses while keeping the same anchor source set

It is safe to dry-run end to end without touching the corpus:
- `bash scripts/launch_analysis_experiment.sh --config configs/experiments/analysis/petase_historical_local_exploit.json describe --pretty`
- `bash scripts/launch_analysis_experiment.sh --config configs/experiments/analysis/petase_historical_local_exploit.json launch-pad --dry-run`

The local Gemma trial config is intentionally stage1-only:
- sampling backend is `openai_compatible`
- model name is the served local alias (`gemma-local`)
- tokenizer id must be supplied at launch time because the served alias is not a Hugging Face id
