#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/svdr/tinker"
POSTPROCESS_DIR="$ROOT/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327"
LOG_DIR="$ROOT/reports/logs"
RECORDS_PATH="$ROOT/data/petase_family_expanded/petase_records.jsonl"
MODEL="moonshotai/Kimi-K2.5"
INIT_STATE_PATH="tinker://7a5aeb3f-0652-52d1-849d-9916dfb43c7c:train:0/weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1"
LEARNING_RATE="5e-7"
EPOCHS="1"
BATCH_SIZE="8"
SEED="67"

VARIANT="${1:-ultra}"

case "$VARIANT" in
  ultra)
    DATASET_PATH="$POSTPROCESS_DIR/soft_doping_curriculum_ultra_conservative.jsonl"
    RUN_NAME="pearl-micro-sft-topoff1m-a-ultra-conservative-lr5e7-ep1"
    ;;
  balanced)
    DATASET_PATH="$POSTPROCESS_DIR/soft_doping_curriculum_balanced_strict.jsonl"
    RUN_NAME="pearl-micro-sft-topoff1m-a-balanced-strict-lr5e7-ep1"
    ;;
  *)
    echo "usage: $0 [ultra|balanced]" >&2
    exit 1
    ;;
esac

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is not set" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

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
