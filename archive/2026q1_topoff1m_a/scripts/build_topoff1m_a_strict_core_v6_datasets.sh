#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo_root.sh"
ROOT="${ROOT:-$(repo_root_from_bash_source "${BASH_SOURCE[0]}")}"
CONFIG="$ROOT/configs/experiments/strict/topoff1m_a_strict_core_v6.json"

OLD_REPEAT="${STRICT_CORE_V6_OLD_REPEAT:-2}"
NEW_REPEAT="${STRICT_CORE_V6_NEW_REPEAT:-4}"
PURE_REPEAT="${STRICT_CORE_V6_PURE_REPEAT:-2}"
ANCHOR_COUNT="${STRICT_CORE_V6_ANCHOR_COUNT:-2}"
NEW_TOP_K="${STRICT_CORE_V6_NEW_TOP_K:-20}"

exec bash "$ROOT/scripts/launch_strict_experiment.sh" \
  --config "$CONFIG" \
  build-datasets \
  --old-repeat "$OLD_REPEAT" \
  --new-repeat "$NEW_REPEAT" \
  --pure-repeat "$PURE_REPEAT" \
  --anchor-count "$ANCHOR_COUNT" \
  --new-top-k "$NEW_TOP_K" \
  "$@"
