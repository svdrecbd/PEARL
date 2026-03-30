#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/reports/logs"
MODEL="moonshotai/Kimi-K2.5"
RUN_NAME="pearl-topoff1m-a-strict-core-v6-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67"
SUMMARY_PATH="$ROOT/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v6-stageb-lite-lr5e7-ep1/summary.json"
PYTHON_BIN="${TINKER_PYTHON_BIN:-python}"
ESM_DEVICE="${ESM_DEVICE:-cuda}"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is not set" >&2
  exit 1
fi

if [[ ! -f "$SUMMARY_PATH" ]]; then
  echo "Checkpoint summary is missing: $SUMMARY_PATH" >&2
  exit 1
fi

INIT_STATE_PATH="$("$PYTHON_BIN" - <<PY
import json
from pathlib import Path
summary = json.loads(Path("$SUMMARY_PATH").read_text())
print(summary["checkpoint_path"])
PY
)"

mkdir -p "$LOG_DIR"

python3 "$ROOT/scripts/launch_detached_job.py" \
  --job-name "$RUN_NAME" \
  --cwd "$ROOT" \
  --metadata-path "$LOG_DIR/$RUN_NAME.json" \
  --log-path "$LOG_DIR/$RUN_NAME.log" \
  --env "TINKER_API_KEY=$TINKER_API_KEY" \
  --env "TINKER_PYTHON_BIN=$PYTHON_BIN" \
  -- "$PYTHON_BIN" "$ROOT/scripts/run_robustness_two_phase.py" \
    --name "$RUN_NAME" \
    --init-state-path "$INIT_STATE_PATH" \
    --model "$MODEL" \
    --variant motif_prior_soft_v2 \
    --suite-sizes 12,24,48 \
    --temperatures 0.8 \
    --seeds 41,53,67 \
    --candidate-sample-count 128 \
    --second-stage-top-k 8 \
    --esm2-device "$ESM_DEVICE" \
    --stockpile-jobs 4 \
    --stockpile-retries 2
