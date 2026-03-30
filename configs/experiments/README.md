# Experiment Configs

This directory is the beginning of the config-driven workflow surface.

The intent is:
- reusable workflow logic in `scripts/` and `src/pearl/`
- experiment parameters in `configs/experiments/`
- historical wrapper scripts preserved, but demoted from the supported surface

Current supported config-driven strict experiment example:
- [strict/topoff1m_a_strict_core_v6.json](strict/topoff1m_a_strict_core_v6.json)

Current generic launcher:
- [scripts/strict_experiment.py](../../scripts/strict_experiment.py)
- [scripts/launch_strict_experiment.sh](../../scripts/launch_strict_experiment.sh)

Current generic mining launcher:
- [scripts/mining_experiment.py](../../scripts/mining_experiment.py)
- [scripts/launch_mining_experiment.sh](../../scripts/launch_mining_experiment.sh)

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
