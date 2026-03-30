#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSTPROCESS_DIR="$ROOT/reports/raft/topoff1m-a-strict-core-v5-postprocess-20260329"

mkdir -p "$POSTPROCESS_DIR"

python "$ROOT/scripts/build_strict_first_union_curricula.py" \
  --old-strict-path "$ROOT/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/family_faithful_bridges.jsonl" \
  --new-strict-path "$ROOT/reports/raft/topoff1m-a-stageb-lite-1m-postprocess-20260329/lineage_family_representatives.jsonl" \
  --purebred-path "$ROOT/data/petase_family_expanded/kimi_micro_sft_top9_unicorn_only.jsonl" \
  --anchor-path "$ROOT/reports/raft/topoff1m-a-stageb-lite-1m-postprocess-20260329/lineage_bridge_only_representatives.jsonl" \
  --stage-a-output-path "$POSTPROCESS_DIR/strict_core_v5_stage_a.jsonl" \
  --stage-a-summary-path "$POSTPROCESS_DIR/strict_core_v5_stage_a_summary.json" \
  --stage-b-output-path "$POSTPROCESS_DIR/strict_core_v5_stage_b_lite.jsonl" \
  --stage-b-summary-path "$POSTPROCESS_DIR/strict_core_v5_stage_b_lite_summary.json" \
  --selected-new-output-path "$POSTPROCESS_DIR/strict_core_v5_selected_new_family_faithful.jsonl" \
  --old-repeat 2 \
  --new-repeat 4 \
  --pure-repeat 2 \
  --anchor-count 2 \
  --new-top-k 16
