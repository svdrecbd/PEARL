#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo_root.sh"
ROOT="${ROOT:-$(repo_root_from_bash_source "${BASH_SOURCE[0]}")}"
CONFIG="$ROOT/configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million_local_gemma.json"

DATE_TAG="${DATE_TAG:-20260402a-localgemma}"
SHARD_COUNT="${SHARD_COUNT:-24}"
CANDIDATE_SAMPLE_COUNT="${CANDIDATE_SAMPLE_COUNT:-256}"
SECOND_STAGE_TOP_K="${SECOND_STAGE_TOP_K:-8}"
TEMPERATURE="${TEMPERATURE:-0.8}"
PROMPT_VARIANT="${PROMPT_VARIANT:-motif_prior_soft_v2}"
SAMPLER_BASE_URL="${SAMPLER_BASE_URL:-http://127.0.0.1:8000}"
SAMPLER_TIMEOUT_SECONDS="${SAMPLER_TIMEOUT_SECONDS:-180.0}"
SAMPLER_MAX_RETRIES="${SAMPLER_MAX_RETRIES:-4}"
SAMPLER_TOKENIZER="${SAMPLER_TOKENIZER:-}"
SAMPLER_API_KEY="${SAMPLER_API_KEY:-${API_KEY:-}}"
SAMPLER_TRUST_REMOTE_CODE="${SAMPLER_TRUST_REMOTE_CODE:-1}"
LOCAL_STAGE1_VENV_DIR="${LOCAL_STAGE1_VENV_DIR:-$HOME/venvs/pearl-local-stage1-cu124}"
export TINKER_PYTHON_BIN="${TINKER_PYTHON_BIN:-$LOCAL_STAGE1_VENV_DIR/bin/python}"
export TINKER_MAX_SAFE_PARALLEL_JOBS="${TINKER_MAX_SAFE_PARALLEL_JOBS:-$SHARD_COUNT}"

if [[ -z "$SAMPLER_TOKENIZER" ]]; then
  echo "Set SAMPLER_TOKENIZER to the Hugging Face model id backing the local server." >&2
  exit 1
fi

COMMAND=(
  bash "$ROOT/scripts/launch_mining_experiment.sh"
  --config "$CONFIG"
  launch-stage1
  --variant-key gemma-local-stage1
  --shard-count "$SHARD_COUNT"
  --candidate-sample-count "$CANDIDATE_SAMPLE_COUNT"
  --second-stage-top-k "$SECOND_STAGE_TOP_K"
  --temperature "$TEMPERATURE"
  --prompt-variant "$PROMPT_VARIANT"
  --date-tag "$DATE_TAG"
  --sampler-backend openai_compatible
  --sampler-base-url "$SAMPLER_BASE_URL"
  --sampler-tokenizer "$SAMPLER_TOKENIZER"
  --sampler-timeout-seconds "$SAMPLER_TIMEOUT_SECONDS"
  --sampler-max-retries "$SAMPLER_MAX_RETRIES"
)
if [[ "$SAMPLER_TRUST_REMOTE_CODE" == "0" ]]; then
  COMMAND+=(--no-sampler-trust-remote-code)
else
  COMMAND+=(--sampler-trust-remote-code)
fi
if [[ -n "$SAMPLER_API_KEY" ]]; then
  COMMAND+=(--sampler-api-key "$SAMPLER_API_KEY")
fi

exec "${COMMAND[@]}" "$@"
