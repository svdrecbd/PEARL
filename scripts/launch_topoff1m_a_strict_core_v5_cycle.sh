#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/reports/logs"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is not set" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

bash "$ROOT/scripts/build_topoff1m_a_strict_core_v5_datasets.sh"
bash "$ROOT/scripts/launch_topoff1m_a_strict_core_v5.sh" stage-a

python3 "$ROOT/scripts/launch_detached_job.py" \
  --job-name "pearl-topoff1m-a-strict-core-v5-smoke-watcher" \
  --cwd "$ROOT" \
  --metadata-path "$LOG_DIR/pearl-topoff1m-a-strict-core-v5-smoke-watcher.json" \
  --log-path "$LOG_DIR/pearl-topoff1m-a-strict-core-v5-smoke-watcher.log" \
  --env "TINKER_API_KEY=$TINKER_API_KEY" \
  --env "TINKER_PYTHON_BIN=${TINKER_PYTHON_BIN:-python}" \
  -- bash "$ROOT/scripts/queue_topoff1m_a_strict_core_v5_smoke_after_stagea.sh"

python3 "$ROOT/scripts/launch_detached_job.py" \
  --job-name "pearl-topoff1m-a-strict-core-v5-stageb-gate" \
  --cwd "$ROOT" \
  --metadata-path "$LOG_DIR/pearl-topoff1m-a-strict-core-v5-stageb-gate.json" \
  --log-path "$LOG_DIR/pearl-topoff1m-a-strict-core-v5-stageb-gate.log" \
  --env "TINKER_API_KEY=$TINKER_API_KEY" \
  --env "TINKER_PYTHON_BIN=${TINKER_PYTHON_BIN:-python}" \
  -- bash "$ROOT/scripts/queue_topoff1m_a_strict_core_v5_stageb_after_smoke.sh"

python3 "$ROOT/scripts/launch_detached_job.py" \
  --job-name "pearl-topoff1m-a-strict-core-v5-robustness-gate" \
  --cwd "$ROOT" \
  --metadata-path "$LOG_DIR/pearl-topoff1m-a-strict-core-v5-robustness-gate.json" \
  --log-path "$LOG_DIR/pearl-topoff1m-a-strict-core-v5-robustness-gate.log" \
  --env "TINKER_API_KEY=$TINKER_API_KEY" \
  --env "TINKER_PYTHON_BIN=${TINKER_PYTHON_BIN:-python}" \
  -- bash "$ROOT/scripts/queue_topoff1m_a_strict_core_v5_robustness_after_stageb.sh"
