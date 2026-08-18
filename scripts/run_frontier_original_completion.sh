#!/bin/zsh
set -euo pipefail

cd /Users/svdr/tinker
set -a
source /Users/svdr/tinker/.env
set +a
export TINKER_RUN_LIST_LIMIT=1000
exec /usr/bin/caffeinate -dimsu /Users/svdr/tinker/.venv/bin/python \
  /Users/svdr/tinker/scripts/manage_frontier_original_completion.py _run \
  --state-dir /Users/svdr/tinker/reports/frontier_adaptation_v2_local_state \
  --mirror-dir /Users/svdr/.pearl/frontier_adaptation_v2_local_state \
  --bootstrap-state-dir /Users/svdr/tinker/reports/frontier_adaptation_v2_local_state/bootstrap/state \
  --executor-config /Users/svdr/tinker/configs/experiments/frontier_adaptation_v2_executor.json
