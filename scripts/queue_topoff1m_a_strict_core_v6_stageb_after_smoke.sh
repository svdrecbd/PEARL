#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMOKE_SUMMARY="$ROOT/reports/robustness/pearl-topoff1m-a-strict-core-v6-stagea-smoke-p48-t08-s41s53s67/robustness_summary.json"
SMOKE_DECISION="$ROOT/reports/robustness/pearl-topoff1m-a-strict-core-v6-stagea-smoke-p48-t08-s41s53s67/smoke_gate_decision.json"

while [[ ! -f "$SMOKE_SUMMARY" ]]; do
  sleep 20
done

if python "$ROOT/scripts/evaluate_strict_core_smoke_gate.py" \
  --summary-path "$SMOKE_SUMMARY" \
  --output-path "$SMOKE_DECISION"; then
  bash "$ROOT/scripts/launch_topoff1m_a_strict_core_v6.sh" stage-b-lite
else
  echo "Smoke gate failed; stage-b-lite will not launch" >&2
fi
