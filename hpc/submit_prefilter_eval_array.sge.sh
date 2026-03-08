#!/bin/bash
#$ -S /bin/bash
#$ -cwd
#$ -j y
#$ -o logs/sge/prefilter-eval.$JOB_ID.$TASK_ID.log
#$ -q gpu.q
#$ -l gpu=1
#$ -l mem_free=64G
#$ -l h_rt=24:00:00
#$ -pe smp 4
#$ -t 1-77

set -euo pipefail
umask 077

ROOT="${ROOT:-${SGE_O_WORKDIR:-$PWD}}"
SIF_PATH="${SIF_PATH:-$ROOT/hpc/pearl_env.sif}"
PYTHON_IN_CONTAINER="${PYTHON_IN_CONTAINER:-python}"

SHARDS_DIR="${SHARDS_DIR:?SHARDS_DIR must point to sequence shard JSONL files}"
SHARD_GLOB="${SHARD_GLOB:-hpc_ready_A_shard_*.jsonl}"
REFERENCE_RECORDS_PATH="${REFERENCE_RECORDS_PATH:-$ROOT/data/petase_family_expanded/petase_records.jsonl}"
WAVE_NAME="${WAVE_NAME:-topoff-1m-prefilter-eval}"
PLDDT_GATE_THRESHOLD="${PLDDT_GATE_THRESHOLD:-85.0}"
ESM2_DEVICE="${ESM2_DEVICE:-cuda}"
LINE_LIMIT="${LINE_LIMIT:-}"

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
SCRATCH_OUT_DIR="${RUN_SCRATCH_DIR}/out"
SCRATCH_HF_DIR="${RUN_SCRATCH_DIR}/hf"
mkdir -p "$SCRATCH_OUT_DIR" "$SCRATCH_HF_DIR"

PERSISTENT_OUT_DIR="${PERSISTENT_OUT_DIR:-$ROOT/reports/hpc_sequence_eval/$WAVE_NAME/runs}"
mkdir -p "$PERSISTENT_OUT_DIR"

cleanup() {
  rm -rf "$RUN_SCRATCH_DIR"
}
trap cleanup EXIT

export HF_HOME="$SCRATCH_HF_DIR"
export TRANSFORMERS_CACHE="$SCRATCH_HF_DIR"
export ESM2_DEVICE

echo "[prefilter-eval] shard=$SHARD_PATH"
echo "[prefilter-eval] run_name=$RUN_NAME"
echo "[prefilter-eval] scratch=$RUN_SCRATCH_DIR"
echo "[prefilter-eval] output=$PERSISTENT_OUT_DIR"

CMD=(
  "$PYTHON_IN_CONTAINER" "$ROOT/scripts/run_sequence_shard_eval.py"
  --input-jsonl "$SHARD_PATH"
  --output-dir "$SCRATCH_OUT_DIR"
  --reference-records-path "$REFERENCE_RECORDS_PATH"
  --name "$RUN_NAME"
  --plddt-gate-threshold "$PLDDT_GATE_THRESHOLD"
)
if [[ -n "$LINE_LIMIT" ]]; then
  CMD+=(--limit "$LINE_LIMIT")
fi

apptainer exec --nv \
  --bind "$ROOT:$ROOT" \
  --bind "$RUN_SCRATCH_DIR:$RUN_SCRATCH_DIR" \
  --bind "$SHARDS_DIR:$SHARDS_DIR" \
  "$SIF_PATH" \
  "${CMD[@]}"

rsync -a "$SCRATCH_OUT_DIR"/ "$PERSISTENT_OUT_DIR"/
echo "[prefilter-eval] synced outputs to $PERSISTENT_OUT_DIR"
