#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo_root.sh"
ROOT="${ROOT:-$(repo_root_from_bash_source "${BASH_SOURCE[0]}")}"
CONFIG="$ROOT/configs/experiments/strict/topoff1m_a_strict_core_v6.json"

if [[ -n "${STRICT_CORE_V6_STAGE_A_CHECKPOINT:-}" ]]; then
  export STRICT_EXPERIMENT_INIT_STATE_OVERRIDE="$STRICT_CORE_V6_STAGE_A_CHECKPOINT"
fi

exec bash "$ROOT/scripts/launch_strict_experiment.sh" \
  --config "$CONFIG" \
  watch-stageb-after-smoke \
  "$@"
