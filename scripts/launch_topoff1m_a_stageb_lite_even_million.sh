#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo_root.sh"
ROOT="${ROOT:-$(repo_root_from_bash_source "${BASH_SOURCE[0]}")}"
CONFIG="$ROOT/configs/experiments/mining/topoff1m_a_stageb_lite_even_million.json"

# Keep this tranche just under the budget line while avoiding prompt overlap
# with the prior 1M stageb-lite wave.
TOTAL_PROMPTS="${TOTAL_PROMPTS:-3906}"
PROMPT_OFFSET="${PROMPT_OFFSET:-3907}"
SHARD_COUNT="${SHARD_COUNT:-12}"
CANDIDATE_SAMPLE_COUNT="${CANDIDATE_SAMPLE_COUNT:-256}"
SECOND_STAGE_TOP_K="${SECOND_STAGE_TOP_K:-8}"
TEMPERATURE="${TEMPERATURE:-0.8}"
PROMPT_VARIANT="${PROMPT_VARIANT:-motif_prior_soft_v2}"
DATE_TAG="${DATE_TAG:-20260329b-next3907}"

exec bash "$ROOT/scripts/launch_mining_experiment.sh" \
  --config "$CONFIG" \
  launch-stage1 \
  --variant-key stageb-lite \
  --total-prompts "$TOTAL_PROMPTS" \
  --prompt-offset "$PROMPT_OFFSET" \
  --shard-count "$SHARD_COUNT" \
  --candidate-sample-count "$CANDIDATE_SAMPLE_COUNT" \
  --second-stage-top-k "$SECOND_STAGE_TOP_K" \
  --temperature "$TEMPERATURE" \
  --prompt-variant "$PROMPT_VARIANT" \
  --date-tag "$DATE_TAG" \
  "$@"
