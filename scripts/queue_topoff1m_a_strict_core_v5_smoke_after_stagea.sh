#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE_A_SUMMARY="$ROOT/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v5-stagea-lr1e6-ep3/summary.json"

while [[ ! -f "$STAGE_A_SUMMARY" ]]; do
  sleep 20
done

bash "$ROOT/scripts/launch_topoff1m_a_strict_core_v5_smoke.sh"
