#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSTPROCESS_DIR="$ROOT/reports/raft/topoff1m-a-strict-core-v3-postprocess-20260329"
LOG_DIR="$ROOT/reports/logs"
RECORDS_PATH="$ROOT/data/petase_family_expanded/petase_records.jsonl"
MODEL="moonshotai/Kimi-K2.5"
RUN_NAME="pearl-micro-sft-topoff1m-a-strict-core-v3-lr15e7-ep2"
SUMMARY_PATH="$ROOT/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v2-stagea-lr1e6-ep3/summary.json"
PYTHON_BIN="${TINKER_PYTHON_BIN:-python}"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is not set" >&2
  exit 1
fi

if [[ ! -f "$SUMMARY_PATH" ]]; then
  echo "Missing strict-core-v2 stage-a summary: $SUMMARY_PATH" >&2
  exit 1
fi

if [[ -n "${STRICT_CORE_V3_INIT_STATE_PATH:-}" ]]; then
  INIT_STATE_PATH="$STRICT_CORE_V3_INIT_STATE_PATH"
else
  INIT_STATE_PATH="$("$PYTHON_BIN" - <<PY
import json
from pathlib import Path
summary = json.loads(Path("$SUMMARY_PATH").read_text())
print(summary["checkpoint_path"])
PY
)"
fi

mkdir -p "$LOG_DIR"

python3 "$ROOT/scripts/launch_detached_job.py" \
  --job-name "$RUN_NAME" \
  --cwd "$ROOT" \
  --metadata-path "$LOG_DIR/$RUN_NAME.json" \
  --log-path "$LOG_DIR/$RUN_NAME.log" \
  --env "TINKER_API_KEY=$TINKER_API_KEY" \
  -- "$PYTHON_BIN" "$ROOT/scripts/run_sft_warmstart.py" \
    --name "$RUN_NAME" \
    --dataset-path "$POSTPROCESS_DIR/strict_core_v3_stage_a.jsonl" \
    --records-path "$RECORDS_PATH" \
    --model "$MODEL" \
    --init-state-path "$INIT_STATE_PATH" \
    --epochs 2 \
    --batch-size 8 \
    --learning-rate 1.5e-6 \
    --seed 97

