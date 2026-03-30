# Experiment Configs

This directory is the beginning of the config-driven workflow surface.

The intent is:
- reusable workflow logic in `scripts/` and `src/pearl/`
- experiment parameters in `configs/experiments/`
- historical wrapper scripts preserved, but demoted from the supported surface

Current supported config-driven strict experiment example:
- [/Users/svdr/tinker/configs/experiments/strict/topoff1m_a_strict_core_v6.json](/Users/svdr/tinker/configs/experiments/strict/topoff1m_a_strict_core_v6.json)

Current generic launcher:
- [/Users/svdr/tinker/scripts/strict_experiment.py](/Users/svdr/tinker/scripts/strict_experiment.py)
- [/Users/svdr/tinker/scripts/launch_strict_experiment.sh](/Users/svdr/tinker/scripts/launch_strict_experiment.sh)

Current generic mining launcher:
- [/Users/svdr/tinker/scripts/mining_experiment.py](/Users/svdr/tinker/scripts/mining_experiment.py)
- [/Users/svdr/tinker/scripts/launch_mining_experiment.sh](/Users/svdr/tinker/scripts/launch_mining_experiment.sh)

Shared reusable plumbing extracted so far:
- [/Users/svdr/tinker/src/pearl/paths.py](/Users/svdr/tinker/src/pearl/paths.py)
- [/Users/svdr/tinker/src/pearl/detached_jobs.py](/Users/svdr/tinker/src/pearl/detached_jobs.py)
- [/Users/svdr/tinker/src/pearl/watchers.py](/Users/svdr/tinker/src/pearl/watchers.py)
- [/Users/svdr/tinker/src/pearl/checkpoints.py](/Users/svdr/tinker/src/pearl/checkpoints.py)
- [/Users/svdr/tinker/src/pearl/io_utils.py](/Users/svdr/tinker/src/pearl/io_utils.py)
- [/Users/svdr/tinker/src/pearl/reports.py](/Users/svdr/tinker/src/pearl/reports.py)
- [/Users/svdr/tinker/src/pearl/smoke_gate.py](/Users/svdr/tinker/src/pearl/smoke_gate.py)
- [/Users/svdr/tinker/src/pearl/strict_curricula.py](/Users/svdr/tinker/src/pearl/strict_curricula.py)
- [/Users/svdr/tinker/src/pearl/run_records.py](/Users/svdr/tinker/src/pearl/run_records.py)

Mining configs:
- [/Users/svdr/tinker/configs/experiments/mining/topoff1m_a_targeted_raft.json](/Users/svdr/tinker/configs/experiments/mining/topoff1m_a_targeted_raft.json)
- [/Users/svdr/tinker/configs/experiments/mining/topoff1m_a_stageb_lite_even_million.json](/Users/svdr/tinker/configs/experiments/mining/topoff1m_a_stageb_lite_even_million.json)
- [/Users/svdr/tinker/configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million.json](/Users/svdr/tinker/configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million.json)
