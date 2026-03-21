#!/bin/bash
#$ -S /bin/bash
#$ -cwd
#$ -j y
#$ -o logs/sge/prefilter-eval.$JOB_ID.$TASK_ID.log
#$ -q gpu.q
#$ -l mem_free=64G
#$ -l h_rt=24:00:00
#$ -t 1-77

set -euo pipefail
umask 077

ROOT="${ROOT:-${SGE_O_WORKDIR:-$PWD}}"
SIF_PATH="${SIF_PATH:-$ROOT/hpc/pearl_env.sif}"
PYTHON_IN_CONTAINER="${PYTHON_IN_CONTAINER:-python}"
PYTHON_BIN="${PYTHON_BIN:-}"
CUDA_MODULE="${CUDA_MODULE:-cuda/12.8.1}"
SET_CUDA_VISIBLE_DEVICES="${SET_CUDA_VISIBLE_DEVICES:-0}"

SHARDS_DIR="${SHARDS_DIR:?SHARDS_DIR must point to sequence shard JSONL files}"
SHARD_GLOB="${SHARD_GLOB:-hpc_ready_A_shard_*.jsonl}"
REFERENCE_RECORDS_PATH="${REFERENCE_RECORDS_PATH:-$ROOT/data/petase_family_expanded/petase_records.jsonl}"
WAVE_NAME="${WAVE_NAME:-topoff-1m-prefilter-eval}"
PLDDT_GATE_THRESHOLD="${PLDDT_GATE_THRESHOLD:-85.0}"
ESM2_DEVICE="${ESM2_DEVICE:-}"
LINE_LIMIT="${LINE_LIMIT:-}"

if [[ -f /usr/share/lmod/lmod/init/bash ]]; then
  # Wynton uses Lmod for CUDA runtime/toolkit modules on GPU nodes.
  # shellcheck source=/dev/null
  source /usr/share/lmod/lmod/init/bash
fi
if declare -F module >/dev/null 2>&1; then
  module load "$CUDA_MODULE" 2>/dev/null || module load cuda 2>/dev/null || true
fi

if [[ ! -f "$REFERENCE_RECORDS_PATH" ]]; then
  echo "REFERENCE_RECORDS_PATH does not exist: $REFERENCE_RECORDS_PATH" >&2
  exit 2
fi

mapfile -t SHARD_FILES < <(find "$SHARDS_DIR" -maxdepth 1 -type f -name "$SHARD_GLOB" | sort)
if [[ "${#SHARD_FILES[@]}" -eq 0 ]]; then
  echo "No shard files found in SHARDS_DIR=$SHARDS_DIR with SHARD_GLOB=$SHARD_GLOB" >&2
  exit 3
fi

TASK_INDEX="${SGE_TASK_ID:?SGE_TASK_ID is required for array jobs}"
if (( TASK_INDEX < 1 || TASK_INDEX > ${#SHARD_FILES[@]} )); then
  echo "SGE_TASK_ID=$TASK_INDEX is out of range for ${#SHARD_FILES[@]} shard files" >&2
  exit 4
fi

SHARD_PATH="${SHARD_FILES[$((TASK_INDEX - 1))]}"
SHARD_BASENAME="$(basename "$SHARD_PATH" .jsonl)"
RUN_NAME="${WAVE_NAME}-${SHARD_BASENAME}"

SCRATCH_BASE="${TMPDIR:-/tmp}"
RUN_SCRATCH_DIR="${SCRATCH_BASE}/pearl-prefilter-eval-${JOB_ID}-${TASK_INDEX}"

PERSISTENT_OUT_DIR="${PERSISTENT_OUT_DIR:-$ROOT/reports/hpc_sequence_eval/$WAVE_NAME/runs}"
PERSISTENT_PARENT="$(dirname "$PERSISTENT_OUT_DIR")"
if [[ -e "$PERSISTENT_PARENT" && ! -d "$PERSISTENT_PARENT" ]]; then
  echo "Persistent output parent exists but is not a directory: $PERSISTENT_PARENT" >&2
  exit 6
fi
mkdir -p "$PERSISTENT_OUT_DIR"
JOB_OUTPUT_DIR="${JOB_OUTPUT_DIR:-$PERSISTENT_OUT_DIR}"
if [[ -e "$JOB_OUTPUT_DIR" && ! -d "$JOB_OUTPUT_DIR" ]]; then
  echo "JOB_OUTPUT_DIR exists but is not a directory: $JOB_OUTPUT_DIR" >&2
  exit 7
fi
mkdir -p "$JOB_OUTPUT_DIR"

cleanup() {
  rm -rf "$RUN_SCRATCH_DIR"
}
trap cleanup EXIT

export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME}"
export ESM2_DEVICE
if [[ "$SET_CUDA_VISIBLE_DEVICES" == "1" && -n "${SGE_GPU:-}" && "${SGE_GPU}" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
  export CUDA_VISIBLE_DEVICES="$SGE_GPU"
fi

echo "[prefilter-eval] host=$(hostname)"
echo "[prefilter-eval] shard=$SHARD_PATH"
echo "[prefilter-eval] run_name=$RUN_NAME"
echo "[prefilter-eval] scratch=$RUN_SCRATCH_DIR"
echo "[prefilter-eval] output=$PERSISTENT_OUT_DIR"
echo "[prefilter-eval] job_output_dir=$JOB_OUTPUT_DIR"
echo "[prefilter-eval] hf_home=$HF_HOME"
echo "[prefilter-eval] cuda_module=$CUDA_MODULE"
echo "[prefilter-eval] esm2_device=${ESM2_DEVICE:-auto}"
echo "[prefilter-eval] set_cuda_visible_devices=$SET_CUDA_VISIBLE_DEVICES"
echo "[prefilter-eval] sge_gpu=${SGE_GPU:-undefined}"
if [[ "$SET_CUDA_VISIBLE_DEVICES" == "1" && -n "${SGE_GPU:-}" && ! "${SGE_GPU}" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
  echo "[prefilter-eval] warning=ignoring_non_numeric_sge_gpu"
fi
if [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then
  echo "[prefilter-eval] cuda_visible_devices=$CUDA_VISIBLE_DEVICES"
fi
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -L || true
fi

CMD=(
  "$ROOT/scripts/run_sequence_shard_eval.py"
  --input-jsonl "$SHARD_PATH"
  --output-dir "$JOB_OUTPUT_DIR"
  --reference-records-path "$REFERENCE_RECORDS_PATH"
  --name "$RUN_NAME"
  --plddt-gate-threshold "$PLDDT_GATE_THRESHOLD"
)
if [[ -n "$LINE_LIMIT" ]]; then
  CMD+=(--limit "$LINE_LIMIT")
fi

if [[ -n "$PYTHON_BIN" ]]; then
  echo "[prefilter-eval] mode=direct-python"
  echo "[prefilter-eval] python_bin=$PYTHON_BIN"
  "$PYTHON_BIN" "${CMD[@]}"
else
  if [[ ! -f "$SIF_PATH" ]]; then
    echo "SIF_PATH does not exist and PYTHON_BIN was not provided: $SIF_PATH" >&2
    exit 5
  fi
  echo "[prefilter-eval] mode=apptainer"
  echo "[prefilter-eval] sif=$SIF_PATH"
  apptainer exec --nv \
    --bind "$ROOT:$ROOT" \
    --bind "$RUN_SCRATCH_DIR:$RUN_SCRATCH_DIR" \
    --bind "$SHARDS_DIR:$SHARDS_DIR" \
    "$SIF_PATH" \
    "$PYTHON_IN_CONTAINER" "${CMD[@]}"
fi

if [[ "$JOB_OUTPUT_DIR" != "$PERSISTENT_OUT_DIR" ]]; then
  rsync -a "$JOB_OUTPUT_DIR"/ "$PERSISTENT_OUT_DIR"/
  echo "[prefilter-eval] synced outputs to $PERSISTENT_OUT_DIR"
else
  echo "[prefilter-eval] outputs written directly to $PERSISTENT_OUT_DIR"
fi
