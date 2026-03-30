#!/usr/bin/env bash

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo_root.sh"
ROOT="${ROOT:-$(repo_root_from_bash_source "${BASH_SOURCE[0]}")}"
CONFIG="$ROOT/configs/experiments/mining/topoff1m_a_stageb_lite_coverage_million.json"
DATE_TAG="${DATE_TAG:-20260330c-coverage1m}"
PROMPT_PACK_DIR="$ROOT/reports/raft_prompt_packs/topoff1m-a-stageb-lite-${DATE_TAG}"
PROMPT_PACK_PATH="$PROMPT_PACK_DIR/prompts.jsonl"
PROMPT_PACK_SUMMARY_PATH="$PROMPT_PACK_DIR/summary.json"

TAIL_WAVE_DIR="${TAIL_WAVE_DIR:-$ROOT/reports/raft/pearl-topoff1m-a-stageb-lite-raft-stage1-p3906-c256-20260329b-next3907}"
FUNCTIONAL_HITS_PATH="${FUNCTIONAL_HITS_PATH:-$ROOT/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/all_functional_hits_exact.jsonl}"
FAMILY_HITS_PATH="${FAMILY_HITS_PATH:-$ROOT/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/all_family_faithful_hits_exact.jsonl}"

STANDARD_COUNT="${STANDARD_COUNT:-1865}"
ADVERSARIAL_COUNT="${ADVERSARIAL_COUNT:-467}"
SHARD_COUNT="${SHARD_COUNT:-24}"
CANDIDATE_SAMPLE_COUNT="${CANDIDATE_SAMPLE_COUNT:-256}"
SECOND_STAGE_TOP_K="${SECOND_STAGE_TOP_K:-8}"
TEMPERATURE="${TEMPERATURE:-0.8}"
PROMPT_VARIANT="${PROMPT_VARIANT:-motif_prior_soft_v2}"
MIN_ATTEMPTED_BUCKET_COUNT="${MIN_ATTEMPTED_BUCKET_COUNT:-5}"

mkdir -p "$PROMPT_PACK_DIR"

python3 "$ROOT/scripts/build_topoff1m_a_stageb_lite_next_million_prompt_pack.py" \
  --tail-wave-dir "$TAIL_WAVE_DIR" \
  --functional-hits-path "$FUNCTIONAL_HITS_PATH" \
  --family-hits-path "$FAMILY_HITS_PATH" \
  --standard-count "$STANDARD_COUNT" \
  --adversarial-count "$ADVERSARIAL_COUNT" \
  --min-attempted-bucket-count "$MIN_ATTEMPTED_BUCKET_COUNT" \
  --output-path "$PROMPT_PACK_PATH" \
  --summary-path "$PROMPT_PACK_SUMMARY_PATH"

TOTAL_PROMPTS="$(
python3 - <<PY
import json
from pathlib import Path
summary = json.loads(Path("$PROMPT_PACK_SUMMARY_PATH").read_text())
print(summary["total_prompt_count"])
PY
)"

export PROMPTS_PATH="$PROMPT_PACK_PATH"
export TOTAL_PROMPTS="$TOTAL_PROMPTS"
export PROMPT_OFFSET="0"

exec bash "$ROOT/scripts/launch_mining_experiment.sh" \
  --config "$CONFIG" \
  launch-stage1 \
  --variant-key stageb-lite \
  --prompts-path "$PROMPT_PACK_PATH" \
  --total-prompts "$TOTAL_PROMPTS" \
  --prompt-offset 0 \
  --shard-count "$SHARD_COUNT" \
  --candidate-sample-count "$CANDIDATE_SAMPLE_COUNT" \
  --second-stage-top-k "$SECOND_STAGE_TOP_K" \
  --temperature "$TEMPERATURE" \
  --prompt-variant "$PROMPT_VARIANT" \
  --date-tag "$DATE_TAG" \
  "$@"
