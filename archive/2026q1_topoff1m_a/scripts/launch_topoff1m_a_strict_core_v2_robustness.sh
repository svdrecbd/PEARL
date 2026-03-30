#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo_root.sh"
ROOT="${ROOT:-$(repo_root_from_bash_source "${BASH_SOURCE[0]}")}"
CONFIG="$ROOT/configs/experiments/strict/topoff1m_a_strict_core_v2.json"

if [[ "${1:-}" == "stage-a" || "${1:-}" == "stage-b-lite" ]]; then
  STAGE="$1"
  shift
else
  STAGE="stage-a"
fi

case "$STAGE" in
  stage-a)
    RUN_NAME="pearl-topoff1m-a-strict-core-v2-stagea-robustness-2phase-p12p24p48-t08-s41s53s67"
    SUMMARY_PATH="$ROOT/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v2-stagea-lr1e6-ep3/summary.json"
    ;;
  stage-b-lite)
    RUN_NAME="pearl-topoff1m-a-strict-core-v2-stageb-lite-robustness-2phase-p12p24p48-t08-s41s53s67"
    SUMMARY_PATH="$ROOT/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v2-stageb-lite-lr5e7-ep1/summary.json"
    ;;
  *)
    echo "usage: $0 [stage-a|stage-b-lite]" >&2
    exit 1
    ;;
esac

if [[ -n "${ESM_DEVICE:-}" ]]; then
  export STRICT_EXPERIMENT_ESM2_DEVICE="$ESM_DEVICE"
else
  export STRICT_EXPERIMENT_ESM2_DEVICE="mps"
fi

exec bash "$ROOT/scripts/launch_strict_experiment.sh" \
  --config "$CONFIG" \
  launch-robustness \
  --run-name "$RUN_NAME" \
  --checkpoint-summary-path "$SUMMARY_PATH" \
  "$@"
