#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${TINKER_PYTHON_BIN:-python}"
ESM_DEVICE="${ESM_DEVICE:-cuda}"
WAIT_FOR_SUMMARY="$ROOT/reports/robustness/pearl-topoff1m-a-strict-core-v2-stageb-lite-robustness-2phase-l40-p12p24p48-t08-s41s53s67/robustness_summary.json"
V3_WARMSTART_SUMMARY="$ROOT/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v3-lr15e7-ep2/summary.json"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is not set" >&2
  exit 1
fi

until [[ -f "$WAIT_FOR_SUMMARY" ]]; do
  sleep 30
done

bash "$ROOT/scripts/launch_topoff1m_a_strict_core_v3.sh"

until [[ -f "$V3_WARMSTART_SUMMARY" ]]; do
  sleep 15
done

TINKER_PYTHON_BIN="$PYTHON_BIN" ESM_DEVICE="$ESM_DEVICE" \
  bash "$ROOT/scripts/launch_topoff1m_a_strict_core_v3_robustness.sh"
