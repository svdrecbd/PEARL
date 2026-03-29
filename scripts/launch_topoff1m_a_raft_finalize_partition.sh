#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: $0 <wave-dir> <partition-index> <partition-count> [job-suffix]" >&2
  exit 1
fi

ROOT="${ROOT:-$HOME/work/tinker}"
LOG_DIR="$ROOT/reports/logs"
VENV_DIR="${VENV_DIR:-$HOME/venvs/pearl-eval-cu124}"
PYTHON_BIN="${PYTHON_BIN:-$VENV_DIR/bin/python}"
WAVE_DIR="$1"
PARTITION_INDEX="$2"
PARTITION_COUNT="$3"
JOB_SUFFIX="${4:-}"
WAVE_BASENAME="$(basename "$WAVE_DIR")"
PARTITION_TAG="part$(printf '%02d' "$((PARTITION_INDEX + 1))")of$(printf '%02d' "$PARTITION_COUNT")"
JOB_NAME="${WAVE_BASENAME}-finalize-${PARTITION_TAG}"
if [[ -n "$JOB_SUFFIX" ]]; then
  JOB_NAME="${JOB_NAME}-${JOB_SUFFIX}"
fi

mkdir -p "$LOG_DIR"

python3 "$ROOT/scripts/launch_detached_job.py" \
  --job-name "$JOB_NAME" \
  --cwd "$ROOT" \
  --metadata-path "$LOG_DIR/$JOB_NAME.json" \
  --log-path "$LOG_DIR/$JOB_NAME.log" \
  -- "$PYTHON_BIN" "$ROOT/scripts/finalize_raft_wave_partition.py" \
    --wave-dir "$WAVE_DIR" \
    --partition-index "$PARTITION_INDEX" \
    --partition-count "$PARTITION_COUNT" \
    --esm2-device cuda
