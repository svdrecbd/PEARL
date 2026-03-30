#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/svdr/tinker"
LOG_DIR="$ROOT/reports/logs"
MODEL="moonshotai/Kimi-K2.5"
STAGE="${1:-stage-b}"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is not set" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

case "$STAGE" in
  stage-a)
    RUN_NAME="pearl-topoff1m-a-strict-first-union-stagea-robustness-2phase-p12p24p48-t08-s41s53s67"
    SUMMARY_PATH="$ROOT/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-first-union-stagea-lr1e6-ep2/summary.json"
    ;;
  stage-b)
    RUN_NAME="pearl-topoff1m-a-strict-first-union-stageb-robustness-2phase-p12p24p48-t08-s41s53s67"
    SUMMARY_PATH="$ROOT/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-first-union-stageb-lr5e7-ep1/summary.json"
    ;;
  *)
    echo "usage: $0 [stage-a|stage-b]" >&2
    exit 1
    ;;
esac

if [[ ! -f "$SUMMARY_PATH" ]]; then
  echo "Checkpoint summary is missing: $SUMMARY_PATH" >&2
  exit 1
fi

INIT_STATE_PATH="$(python - <<PY
import json
from pathlib import Path
summary = json.loads(Path("$SUMMARY_PATH").read_text())
print(summary["checkpoint_path"])
PY
)"

python "$ROOT/scripts/launch_detached_job.py" \
  --job-name "$RUN_NAME" \
  --cwd "$ROOT" \
  --metadata-path "$LOG_DIR/$RUN_NAME.json" \
  --log-path "$LOG_DIR/$RUN_NAME.log" \
  --env "TINKER_API_KEY=$TINKER_API_KEY" \
  -- python "$ROOT/scripts/run_robustness_two_phase.py" \
    --name "$RUN_NAME" \
    --init-state-path "$INIT_STATE_PATH" \
    --model "$MODEL" \
    --variant motif_prior_soft_v2 \
    --suite-sizes 12,24,48 \
    --temperatures 0.8 \
    --seeds 41,53,67 \
    --candidate-sample-count 128 \
    --second-stage-top-k 8 \
    --esm2-device mps \
    --stockpile-jobs 4 \
    --stockpile-retries 2
