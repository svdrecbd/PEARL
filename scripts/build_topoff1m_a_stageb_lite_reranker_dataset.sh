#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo_root.sh"
ROOT="${ROOT:-$(repo_root_from_bash_source "${BASH_SOURCE[0]}")}"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT/reports/reranker/topoff1m-a-stageb-lite-1p6m-20260330}"
STRICT_HITS_PATH="${STRICT_HITS_PATH:-$ROOT/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/all_family_faithful_hits_exact.jsonl}"
FUNCTIONAL_HITS_PATH="${FUNCTIONAL_HITS_PATH:-$ROOT/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329/all_functional_hits_exact.jsonl}"
WAVE_A="${WAVE_A:-$ROOT/reports/raft/pearl-topoff1m-a-stageb-lite-raft-stage1-p3907-c256-20260329a}"
WAVE_B="${WAVE_B:-$ROOT/reports/raft/pearl-topoff1m-a-stageb-lite-raft-stage1-p3906-c256-20260329b-next3907}"

python3 "$ROOT/scripts/build_pairwise_reranker_dataset.py" \
  --wave-dir "$WAVE_A" \
  --wave-dir "$WAVE_B" \
  --strict-hits-path "$STRICT_HITS_PATH" \
  --functional-hits-path "$FUNCTIONAL_HITS_PATH" \
  --output-dir "$OUTPUT_DIR" \
  --max-pairs-per-prompt 2 \
  --max-chosen-per-cluster 1 \
  --prompt-holdout-frac 0.1 \
  --bucket-holdout-frac 0.1 \
  --cluster-holdout-frac 0.1 \
  --seed 37
