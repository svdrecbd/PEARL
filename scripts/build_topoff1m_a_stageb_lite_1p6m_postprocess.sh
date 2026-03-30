#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329"
WAVE1="$ROOT/reports/raft/pearl-topoff1m-a-stageb-lite-raft-stage1-p3907-c256-20260329a"
WAVE2="$ROOT/reports/raft/pearl-topoff1m-a-stageb-lite-raft-stage1-p3906-c256-20260329b-next3907"

mkdir -p "$OUT_DIR"

python3 "$ROOT/scripts/build_finalized_hit_lineage_bundle.py" \
  --wave-dir "$WAVE1" \
  --wave-dir "$WAVE2" \
  --output-dir "$OUT_DIR"

python3 "$ROOT/scripts/check_retrain_readiness.py" \
  "$WAVE1/runs" \
  "$WAVE2/runs" \
  --selected-only \
  > "$OUT_DIR/retrain_readiness_selected_only.json"
