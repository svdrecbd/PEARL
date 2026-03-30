#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSTPROCESS_DIR="$ROOT/reports/raft/topoff1m-a-strict-core-v6-postprocess-20260329"
LOG_DIR="$ROOT/reports/logs"
RECORDS_PATH="$ROOT/data/petase_family_expanded/petase_records.jsonl"
MODEL="moonshotai/Kimi-K2.5"
BASE_INIT_STATE_PATH="tinker://f95b13f5-4c21-5851-85d6-f6196bbe2779:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v2-stageb-lite-lr5e7-ep1"
STAGE="${1:-stage-a}"
DEFAULT_CPU_PYTHON="$HOME/venvs/pearl-stage1-cpu/bin/python"
if [[ -n "${TINKER_PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="$TINKER_PYTHON_BIN"
elif [[ -x "$DEFAULT_CPU_PYTHON" ]]; then
  PYTHON_BIN="$DEFAULT_CPU_PYTHON"
else
  PYTHON_BIN="python"
fi

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is not set" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

case "$STAGE" in
  stage-a)
    RUN_NAME="pearl-micro-sft-topoff1m-a-strict-core-v6-stagea-lr1e6-ep3"
    DATASET_PATH="$POSTPROCESS_DIR/strict_core_v6_stage_a.jsonl"
    INIT_STATE_PATH="$BASE_INIT_STATE_PATH"
    LEARNING_RATE="1e-6"
    EPOCHS="3"
    BATCH_SIZE="8"
    SEED="149"
    ;;
  stage-b-lite)
    RUN_NAME="pearl-micro-sft-topoff1m-a-strict-core-v6-stageb-lite-lr5e7-ep1"
    DATASET_PATH="$POSTPROCESS_DIR/strict_core_v6_stage_b_lite.jsonl"
    STAGE_A_SUMMARY_PATH="$ROOT/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v6-stagea-lr1e6-ep3/summary.json"
    if [[ -n "${STRICT_CORE_V6_STAGE_A_CHECKPOINT:-}" ]]; then
      INIT_STATE_PATH="$STRICT_CORE_V6_STAGE_A_CHECKPOINT"
    elif [[ -f "$STAGE_A_SUMMARY_PATH" ]]; then
      INIT_STATE_PATH="$("$PYTHON_BIN" - <<PY
import json
from pathlib import Path
summary = json.loads(Path("$STAGE_A_SUMMARY_PATH").read_text())
print(summary["checkpoint_path"])
PY
)"
    else
      echo "Stage A summary is missing; set STRICT_CORE_V6_STAGE_A_CHECKPOINT or run stage-a first" >&2
      exit 1
    fi
    LEARNING_RATE="5e-7"
    EPOCHS="1"
    BATCH_SIZE="8"
    SEED="151"
    ;;
  *)
    echo "usage: $0 [stage-a|stage-b-lite]" >&2
    exit 1
    ;;
esac

python3 "$ROOT/scripts/launch_detached_job.py" \
  --job-name "$RUN_NAME" \
  --cwd "$ROOT" \
  --metadata-path "$LOG_DIR/$RUN_NAME.json" \
  --log-path "$LOG_DIR/$RUN_NAME.log" \
  --env "TINKER_API_KEY=$TINKER_API_KEY" \
  -- "$PYTHON_BIN" "$ROOT/scripts/run_sft_warmstart.py" \
    --name "$RUN_NAME" \
    --dataset-path "$DATASET_PATH" \
    --records-path "$RECORDS_PATH" \
    --model "$MODEL" \
    --init-state-path "$INIT_STATE_PATH" \
    --epochs "$EPOCHS" \
    --batch-size "$BATCH_SIZE" \
    --learning-rate "$LEARNING_RATE" \
    --seed "$SEED"
