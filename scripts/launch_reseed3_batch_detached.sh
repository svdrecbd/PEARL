#!/bin/zsh
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <batch_id>" >&2
  exit 1
fi

BATCH_ID="$1"
ROOT="/Users/svdr/tinker"
PYTHON_BIN="/opt/anaconda3/bin/python"
LAUNCHER="$ROOT/scripts/launch_detached_job.py"
RUNNER="$ROOT/scripts/run_reseed3_batch.sh"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is required" >&2
  exit 1
fi

case "$BATCH_ID" in
  01|1) JOB_NAME="pearl-reseed3-batch01" ;;
  02|2) JOB_NAME="pearl-reseed3-batch02" ;;
  03|3) JOB_NAME="pearl-reseed3-batch03" ;;
  04|4) JOB_NAME="pearl-reseed3-batch04" ;;
  *)
    echo "unsupported batch id: $BATCH_ID" >&2
    exit 1
    ;;
esac

LOG_PATH="$ROOT/reports/logs/${JOB_NAME}.log"
METADATA_PATH="$ROOT/reports/logs/${JOB_NAME}.json"

exec "$PYTHON_BIN" "$LAUNCHER" \
  --job-name "$JOB_NAME" \
  --cwd "$ROOT" \
  --metadata-path "$METADATA_PATH" \
  --log-path "$LOG_PATH" \
  --env "TINKER_API_KEY=$TINKER_API_KEY" \
  --env "TINKER_PYTHON_BIN=$PYTHON_BIN" \
  -- "$RUNNER" "$BATCH_ID"
