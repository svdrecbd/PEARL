#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE_B_SUMMARY="$ROOT/reports/warmstart/pearl-micro-sft-topoff1m-a-strict-core-v5-stageb-lite-lr5e7-ep1/summary.json"
SMOKE_DECISION="$ROOT/reports/robustness/pearl-topoff1m-a-strict-core-v5-stagea-smoke-p48-t08-s41s53s67/smoke_gate_decision.json"

while [[ ! -f "$STAGE_B_SUMMARY" ]]; do
  if [[ -f "$SMOKE_DECISION" ]] && python - <<PY
import json
from pathlib import Path
payload = json.loads(Path("$SMOKE_DECISION").read_text())
raise SystemExit(0 if not payload.get("passed") else 1)
PY
  then
    echo "Smoke gate failed; robustness watcher exiting without launch" >&2
    exit 0
  fi
  sleep 20
done

bash "$ROOT/scripts/launch_topoff1m_a_strict_core_v5_robustness.sh"
