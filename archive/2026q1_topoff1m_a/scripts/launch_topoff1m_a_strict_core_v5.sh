#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo_root.sh"
ROOT="${ROOT:-$(repo_root_from_bash_source "${BASH_SOURCE[0]}")}"
CONFIG="$ROOT/configs/experiments/strict/topoff1m_a_strict_core_v5.json"

if [[ "${1:-}" == "stage-a" || "${1:-}" == "stage-b-lite" ]]; then
  STAGE="$1"
  shift
else
  STAGE="stage-a"
fi

case "$STAGE" in
  stage-a|stage-b-lite) ;;
  *)
    echo "usage: $0 [stage-a|stage-b-lite]" >&2
    exit 1
    ;;
esac

if [[ -n "${STRICT_CORE_V5_STAGE_A_CHECKPOINT:-}" ]]; then
  export STRICT_EXPERIMENT_INIT_STATE_OVERRIDE="$STRICT_CORE_V5_STAGE_A_CHECKPOINT"
fi

exec bash "$ROOT/scripts/launch_strict_experiment.sh" \
  --config "$CONFIG" \
  launch-stage \
  --stage "$STAGE" \
  "$@"
