#!/usr/bin/env bash
set -euo pipefail

input_report="${GENERATION_REPORT:-/workspace/input/generation_report.json}"
output_root="${GMN_OUTPUT_DIR:?GMN_OUTPUT_DIR is required}/scaling-paradox-structural"

if [[ ! -s "$input_report" ]]; then
  echo "generation report is missing: $input_report" >&2
  exit 2
fi

mkdir -p "$output_root"
python3 scripts/run_scaling_paradox_structure.py \
  --generation-report "$input_report" \
  --output-dir "$output_root"

python3 - "$output_root" "$GMN_RESULT_PATH" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
reports = list(root.glob("*/structure_report.json"))
if len(reports) != 1:
    raise SystemExit(f"expected one structure report, found {len(reports)}")
report = json.load(open(reports[0]))
result = {
    "contract": "pearl.scaling-paradox-structural-job/1",
    "complete": report["complete"],
    "expected_candidate_count": report["expected_candidate_count"],
    "completed_candidate_count": report["completed_candidate_count"],
    "full_structural_gate_passes": report["full_structural_gate_passes"],
    "full_structural_gate_yield": report["full_structural_gate_yield"],
    "fold_contract_sha": report["contract"]["fold_contract_sha"],
}
pathlib.Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
PY
