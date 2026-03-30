#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo_root.sh"
ROOT="${ROOT:-$(repo_root_from_bash_source "${BASH_SOURCE[0]}")}"
CONFIG="$ROOT/configs/experiments/strict/topoff1m_a_strict_core_v3.json"

if [[ "${1:-}" == "stage-a" ]]; then
  STAGE="$1"
  shift
else
  STAGE="stage-a"
fi

case "$STAGE" in
  stage-a) ;;
  *)
    echo "usage: $0 [stage-a]" >&2
    exit 1
    ;;
esac

if [[ -n "${STRICT_CORE_V3_INIT_STATE_PATH:-}" ]]; then
  export STRICT_EXPERIMENT_INIT_STATE_OVERRIDE="$STRICT_CORE_V3_INIT_STATE_PATH"
fi

exec bash "$ROOT/scripts/launch_strict_experiment.sh" \
  --config "$CONFIG" \
  launch-stage \
  --stage stage-a \
  "$@"
