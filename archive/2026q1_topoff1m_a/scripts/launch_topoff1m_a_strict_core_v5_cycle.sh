#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo_root.sh"
ROOT="${ROOT:-$(repo_root_from_bash_source "${BASH_SOURCE[0]}")}"
CONFIG="$ROOT/configs/experiments/strict/topoff1m_a_strict_core_v5.json"
EXTRA_ARGS=("$@")

bash "$ROOT/scripts/launch_strict_experiment.sh" \
  --config "$CONFIG" \
  build-datasets \
  "${EXTRA_ARGS[@]}"

exec bash "$ROOT/scripts/launch_strict_experiment.sh" \
  --config "$CONFIG" \
  launch-chain \
  "${EXTRA_ARGS[@]}"
