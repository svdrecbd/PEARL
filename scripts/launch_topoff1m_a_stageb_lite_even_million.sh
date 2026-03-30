#!/usr/bin/env bash

set -euo pipefail

ROOT="${ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

# Keep this tranche just under the budget line while avoiding prompt overlap
# with the prior 1M stageb-lite wave.
export TOTAL_PROMPTS="${TOTAL_PROMPTS:-3906}"
export PROMPT_OFFSET="${PROMPT_OFFSET:-3907}"
export SHARD_COUNT="${SHARD_COUNT:-12}"
export CANDIDATE_SAMPLE_COUNT="${CANDIDATE_SAMPLE_COUNT:-256}"
export SECOND_STAGE_TOP_K="${SECOND_STAGE_TOP_K:-8}"
export TEMPERATURE="${TEMPERATURE:-0.8}"
export PROMPT_VARIANT="${PROMPT_VARIANT:-motif_prior_soft_v2}"
export DATE_TAG="${DATE_TAG:-20260329b-next3907}"

exec "$ROOT/scripts/launch_topoff1m_a_targeted_raft.sh" stageb-lite
