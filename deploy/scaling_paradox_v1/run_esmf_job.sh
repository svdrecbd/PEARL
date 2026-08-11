#!/usr/bin/env bash
set -euo pipefail

input_report="${GENERATION_REPORT:-/workspace/input/generation_report.json}"
output_root="${GMN_OUTPUT_DIR:?GMN_OUTPUT_DIR is required}/scaling-paradox-structural"

if [[ ! -s "$input_report" ]]; then
  echo "generation report is missing: $input_report" >&2
  exit 2
fi

mkdir -p "$output_root"
structural_config="${STRUCTURAL_CONFIG:-}"
if [[ -z "$structural_config" ]]; then
  structural_config="$(python3 - "$input_report" <<'PY'
import json
import sys

campaign = json.load(open(sys.argv[1]))["contract"]["campaign_id"]
configs = {
    "pearl-scaling-paradox-v1": "configs/experiments/scaling_paradox_structural_v1.json",
    "pearl-scaling-paradox-v1-replication": "configs/experiments/scaling_paradox_structural_v1_replication.json",
    "pearl-frontier-adaptation-v2-original": "configs/experiments/frontier_adaptation_structural_v2_original.json",
    "pearl-frontier-adaptation-v2-replication": "configs/experiments/frontier_adaptation_structural_v2_replication.json",
}
if campaign not in configs:
    raise SystemExit(f"unknown structural campaign: {campaign}")
print(configs[campaign])
PY
)"
fi
python3 scripts/run_scaling_paradox_structure.py \
  --config "$structural_config" \
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
    "generation_run_key": report["contract"]["generation_run_key"],
    "generation_contract_sha": report["contract"]["generation_contract_sha"],
}
pathlib.Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
PY
