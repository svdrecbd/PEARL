# Experiment Configs

This directory is the beginning of the config-driven workflow surface.

The intent is:
- reusable workflow logic in `scripts/` and `src/pearl/`
- experiment parameters in `configs/experiments/`
- historical wrapper scripts preserved, but demoted from the supported surface

Current supported config-driven strict experiment examples:
- [strict/topoff1m_a_strict_core_v7_repair_20260412.json](strict/topoff1m_a_strict_core_v7_repair_20260412.json)
- [strict/topoff1m_a_strict_core_v8_coverage_20260413.json](strict/topoff1m_a_strict_core_v8_coverage_20260413.json)

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

Current repair read:
- the April 10 pilot validated the repair lane as a real branch:
  - `48` parents
  - `13,033` evaluated variants
  - `577` survivors
  - `192` strict shortlist rows
  - readiness passed
- the April 12 scale-up then passed with `96` parents, `1,071` survivors, and `231` strict shortlist rows
- the next strict branch now shifts from “can repair transfer at all?” to “can we broaden prompt coverage without buying another million-candidate tranche yet?”

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
