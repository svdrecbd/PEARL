#!/usr/bin/env bash
set -euo pipefail

: "${GMN_OUTPUT_DIR:?GMN_OUTPUT_DIR is required}"
: "${GMN_RESULT_PATH:?GMN_RESULT_PATH is required}"
: "${GMN_CHECKPOINT_DIR:?GMN_CHECKPOINT_DIR is required}"
: "${GMN_METADATA_URL:?GMN_METADATA_URL is required}"
: "${PEARL_PAID_PREFLIGHT_SHA256:?PEARL_PAID_PREFLIGHT_SHA256 is required}"
: "${PEARL_SHARD_INDEX:?PEARL_SHARD_INDEX is required}"

preflight="packet/folding_paid_preflight.json"
shard="packet/shard-${PEARL_SHARD_INDEX}.json"
discovery="packet/discovery_funnel_esm3_repeat_filtered.json"
config="configs/experiments/frontier_adaptation_structural_v2_replication_fp32_folding.json"

python3 - "$preflight" "$PEARL_PAID_PREFLIGHT_SHA256" "$PEARL_SHARD_INDEX" <<'PY'
import hashlib
import json
import pathlib
import sys

preflight_path = pathlib.Path(sys.argv[1])
expected_preflight_sha = sys.argv[2]
shard_index = int(sys.argv[3])
observed_preflight_sha = hashlib.sha256(preflight_path.read_bytes()).hexdigest()
if observed_preflight_sha != expected_preflight_sha:
    raise SystemExit("paid preflight file hash mismatch")
packet = json.loads(preflight_path.read_text())
if packet.get("contract") != "pearl.frontier-replication-salvage-discovery-priority-folding-preflight/1":
    raise SystemExit("wrong paid preflight contract")
if packet.get("approval", {}).get("status") != "explicit_user_approved":
    raise SystemExit("paid folding lacks explicit approval")
if packet.get("execution", {}).get("custom_image_build") is not False:
    raise SystemExit("custom image builds are prohibited")
if packet.get("execution", {}).get("resume") != "checkpoint":
    raise SystemExit("paid folding must declare checkpoint-aware placement")
if packet.get("execution", {}).get("job_count") != 1 or shard_index != 0:
    raise SystemExit("discovery-priority folding is limited to one shard-zero job")
jobs = {int(row["shard_index"]): row for row in packet.get("jobs", [])}
if shard_index not in jobs:
    raise SystemExit("shard is absent from paid preflight")
for relative, expected_sha in packet["source_file_sha256s"].items():
    path = pathlib.Path(relative)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
        raise SystemExit(f"source packet mismatch: {relative}")
job = jobs[shard_index]
shard_path = pathlib.Path(job["context_shard_path"])
if hashlib.sha256(shard_path.read_bytes()).hexdigest() != job["shard_file_sha256"]:
    raise SystemExit("shard file hash mismatch")
PY

if command -v sudo >/dev/null 2>&1; then
  sudo_prefix=(sudo)
else
  sudo_prefix=()
fi
"${sudo_prefix[@]}" apt-get update
"${sudo_prefix[@]}" apt-get install --yes --no-install-recommends \
  build-essential python3-dev python3-pip python3-venv ca-certificates git curl
"${sudo_prefix[@]}" rm -rf /var/lib/apt/lists/*

source_root="$(mktemp -d /tmp/pearl-esmfold2-sources.XXXXXX)"
cleanup() {
  if [[ -n "${checkpoint_pid:-}" ]]; then
    kill "$checkpoint_pid" 2>/dev/null || true
  fi
  case "$source_root" in
    /tmp/pearl-esmfold2-sources.*) rm -rf -- "$source_root" ;;
    *) echo "refusing to remove unexpected source directory: $source_root" >&2 ;;
  esac
}
trap cleanup EXIT

python3 -m pip install --no-cache-dir --break-system-packages "torch==2.11.0"
git init "$source_root/transformers"
git -C "$source_root/transformers" remote add origin https://github.com/Biohub/transformers.git
git -C "$source_root/transformers" fetch --depth 1 origin ef32577f55da19a4989cd7b22e004dc43a4998cb
git -C "$source_root/transformers" checkout --detach FETCH_HEAD
python3 -m pip install --no-cache-dir --break-system-packages "$source_root/transformers"

git init "$source_root/esm"
git -C "$source_root/esm" remote add origin https://github.com/Biohub/esm.git
git -C "$source_root/esm" fetch --depth 1 origin 9b9078cadf4e08bd02e9715ba99313fc5127379a
git -C "$source_root/esm" checkout --detach FETCH_HEAD
sed -i 's#transformers @ git+https://github.com/Biohub/transformers.git@main#transformers==4.57.6#' \
  "$source_root/esm/pyproject.toml"
python3 -m pip install --no-cache-dir --break-system-packages "$source_root/esm"
python3 -m pip freeze --all > "$GMN_OUTPUT_DIR/pip-freeze.txt"

python3 - <<'PY'
import esm
import torch
import transformers
from transformers.models.esmfold2.modeling_esmfold2 import ESMFold2Model

assert ESMFold2Model is not None
assert esm.__version__ == "4.0.0"
assert torch.__version__.split("+")[0] == "2.11.0"
assert transformers.__version__ == "4.57.6"
assert torch.cuda.is_available()
PY

work_dir="$GMN_CHECKPOINT_DIR/discovery-priority"
mkdir -p "$work_dir" "$GMN_OUTPUT_DIR"
(
  while true; do
    sleep 600
    curl -fsS -X POST "$GMN_METADATA_URL/v1/checkpoint" >/dev/null || true
  done
) &
checkpoint_pid=$!

export ESMFOLD_DEVICE="cuda"
python3 scripts/run_frontier_structural_folding_shard.py \
  --config "$config" \
  --shard "$shard" \
  --discovery-selection "$discovery" \
  --output-dir "$work_dir"

kill "$checkpoint_pid" 2>/dev/null || true
wait "$checkpoint_pid" 2>/dev/null || true
checkpoint_pid=""

artifact_dir="$GMN_OUTPUT_DIR/discovery-priority"
mkdir -p "$artifact_dir"
cp -a "$work_dir"/. "$artifact_dir"/

python3 - "$artifact_dir" "$GMN_RESULT_PATH" "$PEARL_SHARD_INDEX" <<'PY'
import hashlib
import json
import pathlib
import sys

artifact_dir = pathlib.Path(sys.argv[1])
result_path = pathlib.Path(sys.argv[2])
shard_index = int(sys.argv[3])
report_path = artifact_dir / "structure_report.json"
report = json.loads(report_path.read_text())
if report.get("status") != "complete" or not report.get("complete"):
    raise SystemExit("folding report is incomplete")
for row in report["results"]:
    sequence_sha = row["sequence_sha256"]
    pdb_path = artifact_dir / "pdb" / f"{sequence_sha}.pdb"
    if not pdb_path.is_file() or hashlib.sha256(pdb_path.read_bytes()).hexdigest() != row["pdb_sha256"]:
        raise SystemExit(f"PDB artifact mismatch: {sequence_sha}")
    row["pdb_path"] = f"discovery-priority/pdb/{sequence_sha}.pdb"
report_path.write_text(json.dumps(report, indent=2) + "\n")
passes = sum(bool(row.get("full_structural_gate_pass")) for row in report["results"])
result = {
    "contract": "pearl.frontier-replication-salvage-discovery-priority-folding-job/1",
    "complete": True,
    "shard_index": shard_index,
    "expected_sequence_count": report["expected_sequence_count"],
    "completed_sequence_count": report["completed_sequence_count"],
    "full_structural_gate_passes": passes,
    "fold_contract_sha256": report["contract"]["fold_contract_sha256"],
    "discovery_funnel_sha256": report["contract"]["discovery_funnel_sha256"],
    "structure_report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
}
result_path.write_text(json.dumps(result, indent=2) + "\n")
PY
