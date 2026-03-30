#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo_root.sh"
ROOT="${ROOT:-$(repo_root_from_bash_source "${BASH_SOURCE[0]}")}"
CONFIG="$ROOT/configs/experiments/mining/topoff1m_a_targeted_raft.json"

if [[ "${1:-}" == "stageb-lite" || "${1:-}" == "balanced" || "${1:-}" == "ultra" || "${1:-}" == "ancestor" ]]; then
  VARIANT="$1"
  shift
else
  VARIANT="balanced"
fi

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

exec bash "$ROOT/scripts/launch_mining_experiment.sh" \
  --config "$CONFIG" \
  launch-stage1 \
  --variant-key "$VARIANT" \
  --prompts-path "$PROMPTS_PATH" \
  --total-prompts "$TOTAL_PROMPTS" \
  --prompt-offset "$PROMPT_OFFSET" \
  --shard-count "$SHARD_COUNT" \
  --candidate-sample-count "$CANDIDATE_SAMPLE_COUNT" \
  --second-stage-top-k "$SECOND_STAGE_TOP_K" \
  --temperature "$TEMPERATURE" \
  --prompt-variant "$PROMPT_VARIANT" \
  --date-tag "$DATE_TAG" \
  "$@"
