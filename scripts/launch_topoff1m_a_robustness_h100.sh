#!/usr/bin/env bash

set -euo pipefail

ROOT="${ROOT:-$HOME/work/tinker}"
LOG_DIR="$ROOT/reports/logs"
VENV_DIR="${VENV_DIR:-$HOME/venvs/pearl-eval-cu124}"
PYTHON_BIN="${PYTHON_BIN:-$VENV_DIR/bin/python}"
VARIANT="${1:-ultra}"
STOCKPILE_JOBS="${STOCKPILE_JOBS:-4}"
STOCKPILE_RETRIES="${STOCKPILE_RETRIES:-2}"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is not set" >&2
  exit 1
fi

case "$VARIANT" in
  ultra)
    RUN_NAME="pearl-topoff1m-a-ultra-robustness-2phase-h100-p12p24p48-t08-s41s53s67"
    INIT_STATE_PATH="tinker://1e7f1980-2a80-5bb3-a31c-a9c30bf61124:train:0/weights/pearl-micro-sft-topoff1m-a-ultra-conservative-lr5e7-ep1"
    ;;
  balanced)
    RUN_NAME="pearl-topoff1m-a-balanced-robustness-2phase-h100-p12p24p48-t08-s41s53s67"
    INIT_STATE_PATH="tinker://6c592489-8afb-558c-a9b3-7331cf4d62ed:train:0/weights/pearl-micro-sft-topoff1m-a-balanced-strict-lr5e7-ep1"
    ;;
  *)
    echo "usage: $0 [ultra|balanced]" >&2
    exit 1
    ;;
esac

mkdir -p "$LOG_DIR"

python3 "$ROOT/scripts/launch_detached_job.py" \
  --job-name "$RUN_NAME" \
  --cwd "$ROOT" \
  --metadata-path "$LOG_DIR/$RUN_NAME.json" \
  --log-path "$LOG_DIR/$RUN_NAME.log" \
  --env "TINKER_API_KEY=$TINKER_API_KEY" \
  --env "PYTHON_BIN=$PYTHON_BIN" \
  -- bash "$ROOT/scripts/run_nebius_h100_robustness.sh" \
    --name "$RUN_NAME" \
    --init-state-path "$INIT_STATE_PATH" \
    --model moonshotai/Kimi-K2.5 \
    --variant baseline \
    --suite-sizes 12,24,48 \
    --temperatures 0.8 \
    --seeds 41,53,67 \
    --candidate-sample-count 128 \
    --second-stage-top-k 16 \
    --second-stage-esm-weight 0.4 \
    --second-stage-motif-weight 0.3 \
    --second-stage-geometry-weight 0.3 \
    --second-stage-template-weight 0.05 \
    --stockpile-jobs "$STOCKPILE_JOBS" \
    --stockpile-retries "$STOCKPILE_RETRIES" \
    --esm2-device cuda
