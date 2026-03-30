#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/svdr/tinker"
POSTPROCESS_DIR="$ROOT/reports/raft/topoff1m-a-strict-first-union-postprocess-20260327"
LOG_DIR="$ROOT/reports/logs"
RECORDS_PATH="$ROOT/data/petase_family_expanded/petase_records.jsonl"
MODEL="moonshotai/Kimi-K2.5"
BASE_INIT_STATE_PATH="tinker://6c592489-8afb-558c-a9b3-7331cf4d62ed:train:0/weights/pearl-micro-sft-topoff1m-a-balanced-strict-lr5e7-ep1"
STAGE="${1:-stage-a}"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is not set" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

case "$STAGE" in
  stage-a)
    RUN_NAME="pearl-micro-sft-topoff1m-a-strict-first-union-stagea-lr1e6-ep2"
    DATASET_PATH="$POSTPROCESS_DIR/strict_first_union_stage_a.jsonl"
    INIT_STATE_PATH="$BASE_INIT_STATE_PATH"
    LEARNING_RATE="1e-6"
    EPOCHS="2"
    BATCH_SIZE="8"
    SEED="67"
    ;;
  stage-b)
    RUN_NAME="pearl-micro-sft-topoff1m-a-strict-first-union-stageb-lr5e7-ep1"
    DATASET_PATH="$POSTPROCESS_DIR/strict_first_union_stage_b.jsonl"
    STAGE_A_SUMMARY_PATH="$ROOT/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-first-union-stagea-lr1e6-ep2/summary.json"
    if [[ -n "${STRICT_FIRST_STAGE_A_CHECKPOINT:-}" ]]; then
      INIT_STATE_PATH="$STRICT_FIRST_STAGE_A_CHECKPOINT"
    elif [[ -f "$STAGE_A_SUMMARY_PATH" ]]; then
      INIT_STATE_PATH="$(python - <<'PY'
import json
from pathlib import Path
summary = json.loads(Path('/Users/svdr/tinker/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-first-union-stagea-lr1e6-ep2/summary.json').read_text())
print(summary['checkpoint_path'])
PY
)"
    else
      echo "Stage A summary is missing; set STRICT_FIRST_STAGE_A_CHECKPOINT or run stage-a first" >&2
      exit 1
    fi
    LEARNING_RATE="5e-7"
    EPOCHS="1"
    BATCH_SIZE="8"
    SEED="71"
    ;;
  *)
    echo "usage: $0 [stage-a|stage-b]" >&2
    exit 1
    ;;
esac

python "$ROOT/scripts/launch_detached_job.py" \
  --job-name "$RUN_NAME" \
  --cwd "$ROOT" \
  --metadata-path "$LOG_DIR/$RUN_NAME.json" \
  --log-path "$LOG_DIR/$RUN_NAME.log" \
  --env "TINKER_API_KEY=$TINKER_API_KEY" \
  -- python "$ROOT/scripts/run_sft_warmstart.py" \
    --name "$RUN_NAME" \
    --dataset-path "$DATASET_PATH" \
    --records-path "$RECORDS_PATH" \
    --model "$MODEL" \
    --init-state-path "$INIT_STATE_PATH" \
    --epochs "$EPOCHS" \
    --batch-size "$BATCH_SIZE" \
    --learning-rate "$LEARNING_RATE" \
    --seed "$SEED"
