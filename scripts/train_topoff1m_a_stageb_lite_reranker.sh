#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo_root.sh"
ROOT="${ROOT:-$(repo_root_from_bash_source "${BASH_SOURCE[0]}")}"
DATASET_DIR="${DATASET_DIR:-$ROOT/reports/reranker/topoff1m-a-stageb-lite-1p6m-20260330}"
OUTPUT_DIR="${OUTPUT_DIR:-$DATASET_DIR/reranker_model}"

python3 "$ROOT/scripts/train_pairwise_reranker.py" \
  --dataset-dir "$DATASET_DIR" \
  --output-dir "$OUTPUT_DIR" \
  --epochs 800 \
  --learning-rate 0.05 \
  --l2 0.001 \
  --seed 37 \
  --log-every 50
