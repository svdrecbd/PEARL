#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo_root.sh"
ROOT="${ROOT:-$(repo_root_from_bash_source "${BASH_SOURCE[0]}")}"

VENV_DIR="${VENV_DIR:-$HOME/venvs/pearl-local-stage1-cu124}"
PYTHON_BIN="${PYTHON_BIN:-$VENV_DIR/bin/python}"
MODEL="${MODEL:-}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-gemma-local}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.92}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-64}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
DTYPE="${DTYPE:-bfloat16}"
API_KEY="${API_KEY:-${PEARL_OPENAI_API_KEY:-}}"
TRUST_REMOTE_CODE="${TRUST_REMOTE_CODE:-1}"
JOB_NAME="${JOB_NAME:-vllm-${SERVED_MODEL_NAME}}"
METADATA_PATH="${METADATA_PATH:-$ROOT/reports/logs/${JOB_NAME}.json}"
LOG_PATH="${LOG_PATH:-$ROOT/reports/logs/${JOB_NAME}.log}"

if [[ -z "$MODEL" ]]; then
  echo "Set MODEL to the Hugging Face model id to serve, for example MODEL=google/gemma-4-31b-it" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python runtime not found at $PYTHON_BIN. Run scripts/setup_nebius_h200_local_stage1_env.sh first." >&2
  exit 1
fi

mkdir -p "$(dirname "$METADATA_PATH")" "$(dirname "$LOG_PATH")"

COMMAND=(
  "$PYTHON_BIN"
  -m
  vllm.entrypoints.openai.api_server
  --model
  "$MODEL"
  --served-model-name
  "$SERVED_MODEL_NAME"
  --host
  "$HOST"
  --port
  "$PORT"
  --gpu-memory-utilization
  "$GPU_MEMORY_UTILIZATION"
  --max-model-len
  "$MAX_MODEL_LEN"
  --max-num-seqs
  "$MAX_NUM_SEQS"
  --tensor-parallel-size
  "$TENSOR_PARALLEL_SIZE"
  --dtype
  "$DTYPE"
)
if [[ -n "$API_KEY" ]]; then
  COMMAND+=(--api-key "$API_KEY")
fi
if [[ "$TRUST_REMOTE_CODE" != "0" ]]; then
  COMMAND+=(--trust-remote-code)
fi

exec "$PYTHON_BIN" "$ROOT/scripts/launch_detached_job.py" \
  --job-name "$JOB_NAME" \
  --cwd "$ROOT" \
  --metadata-path "$METADATA_PATH" \
  --log-path "$LOG_PATH" \
  -- "${COMMAND[@]}"
