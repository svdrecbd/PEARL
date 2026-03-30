#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$ROOT/reports/raft/topoff1m-a-stageb-lite-1p6m-postprocess-20260329"
POSTPROCESS_DIR="$ROOT/reports/raft/topoff1m-a-strict-core-v6-postprocess-20260329"

OLD_REPEAT="${STRICT_CORE_V6_OLD_REPEAT:-2}"
NEW_REPEAT="${STRICT_CORE_V6_NEW_REPEAT:-4}"
PURE_REPEAT="${STRICT_CORE_V6_PURE_REPEAT:-2}"
ANCHOR_COUNT="${STRICT_CORE_V6_ANCHOR_COUNT:-2}"
NEW_TOP_K="${STRICT_CORE_V6_NEW_TOP_K:-20}"

mkdir -p "$POSTPROCESS_DIR"

python3 "$ROOT/scripts/build_strict_first_union_curricula.py" \
  --old-strict-path "$ROOT/reports/nebius_sequence_eval/topoff1m-a-postprocess-20260327/family_faithful_bridges.jsonl" \
  --new-strict-path "$SOURCE_DIR/lineage_family_representatives.jsonl" \
  --purebred-path "$ROOT/data/petase_family_expanded/kimi_micro_sft_top9_unicorn_only.jsonl" \
  --anchor-path "$SOURCE_DIR/lineage_bridge_only_representatives.jsonl" \
  --stage-a-output-path "$POSTPROCESS_DIR/strict_core_v6_stage_a.jsonl" \
  --stage-a-summary-path "$POSTPROCESS_DIR/strict_core_v6_stage_a_summary.json" \
  --stage-b-output-path "$POSTPROCESS_DIR/strict_core_v6_stage_b_lite.jsonl" \
  --stage-b-summary-path "$POSTPROCESS_DIR/strict_core_v6_stage_b_lite_summary.json" \
  --selected-new-output-path "$POSTPROCESS_DIR/strict_core_v6_selected_new_family_faithful.jsonl" \
  --old-repeat "$OLD_REPEAT" \
  --new-repeat "$NEW_REPEAT" \
  --pure-repeat "$PURE_REPEAT" \
  --anchor-count "$ANCHOR_COUNT" \
  --new-top-k "$NEW_TOP_K"
