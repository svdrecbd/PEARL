#!/usr/bin/env bash

set -euo pipefail

ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
VARIANT="${1:-balanced}"
TOTAL_PROMPTS="${TOTAL_PROMPTS:-64}"
PROMPT_OFFSET="${PROMPT_OFFSET:-0}"
SHARD_COUNT="${SHARD_COUNT:-4}"
CANDIDATE_SAMPLE_COUNT="${CANDIDATE_SAMPLE_COUNT:-64}"
SECOND_STAGE_TOP_K="${SECOND_STAGE_TOP_K:-8}"
TEMPERATURE="${TEMPERATURE:-0.8}"
PROMPT_VARIANT="${PROMPT_VARIANT:-baseline}"
DATE_TAG="${DATE_TAG:-20260327}"
PROMPTS_PATH="${PROMPTS_PATH:-$ROOT/data/petase_family_expanded/train_prompts_relevance_ge10.jsonl}"
REFERENCE_RECORDS_PATH="${REFERENCE_RECORDS_PATH:-$ROOT/data/petase_family_expanded/petase_records.jsonl}"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is not set" >&2
  exit 1
fi

case "$VARIANT" in
  stageb-lite)
    INIT_STATE_PATH="tinker://f95b13f5-4c21-5851-85d6-f6196bbe2779:train:0/weights/pearl-micro-sft-topoff1m-a-strict-core-v2-stageb-lite-lr5e7-ep1"
    WAVE_NAME="pearl-topoff1m-a-stageb-lite-raft-stage1-p${TOTAL_PROMPTS}-c${CANDIDATE_SAMPLE_COUNT}-${DATE_TAG}"
    ;;
  balanced)
    INIT_STATE_PATH="tinker://6c592489-8afb-558c-a9b3-7331cf4d62ed:train:0/weights/pearl-micro-sft-topoff1m-a-balanced-strict-lr5e7-ep1"
    WAVE_NAME="pearl-topoff1m-a-balanced-raft-stage1-p${TOTAL_PROMPTS}-c${CANDIDATE_SAMPLE_COUNT}-${DATE_TAG}"
    ;;
  ultra)
    INIT_STATE_PATH="tinker://1e7f1980-2a80-5bb3-a31c-a9c30bf61124:train:0/weights/pearl-micro-sft-topoff1m-a-ultra-conservative-lr5e7-ep1"
    WAVE_NAME="pearl-topoff1m-a-ultra-raft-stage1-p${TOTAL_PROMPTS}-c${CANDIDATE_SAMPLE_COUNT}-${DATE_TAG}"
    ;;
  ancestor)
    INIT_STATE_PATH="tinker://7a5aeb3f-0652-52d1-849d-9916dfb43c7c:train:0/weights/kimi25-micro-sft-top9-plus-doping29-cont-lr5e7-ep1"
    WAVE_NAME="pearl-topoff1m-a-ancestor-raft-stage1-p${TOTAL_PROMPTS}-c${CANDIDATE_SAMPLE_COUNT}-${DATE_TAG}"
    ;;
  *)
    echo "usage: $0 [stageb-lite|balanced|ultra|ancestor]" >&2
    exit 1
    ;;
esac

python "$ROOT/scripts/run_raft_wave.py" \
  --name "$WAVE_NAME" \
  --init-state-path "$INIT_STATE_PATH" \
  --prompts-path "$PROMPTS_PATH" \
  --reference-records-path "$REFERENCE_RECORDS_PATH" \
  --total-prompt-count "$TOTAL_PROMPTS" \
  --prompt-offset "$PROMPT_OFFSET" \
  --shard-count "$SHARD_COUNT" \
  --candidate-sample-count "$CANDIDATE_SAMPLE_COUNT" \
  --second-stage-top-k "$SECOND_STAGE_TOP_K" \
  --temperature "$TEMPERATURE" \
  --variant "$PROMPT_VARIANT" \
  --stage1-only
