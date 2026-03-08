#!/bin/bash
#$ -S /bin/bash
#$ -cwd
#$ -j y
#$ -o logs/sge/raft-array.$JOB_ID.$TASK_ID.log
#$ -q gpu.q
#$ -l gpu=1
#$ -l mem_free=64G
#$ -l h_rt=24:00:00
#$ -pe smp 4
#$ -t 1-4

set -euo pipefail
umask 077

ROOT="${ROOT:-${SGE_O_WORKDIR:-$PWD}}"
SIF_PATH="${SIF_PATH:-$ROOT/hpc/pearl_env.sif}"
PYTHON_IN_CONTAINER="${PYTHON_IN_CONTAINER:-python}"

PROMPTS_DIR="${PROMPTS_DIR:?PROMPTS_DIR must point to pre-sharded JSONL prompt files}"
REFERENCE_RECORDS_PATH="${REFERENCE_RECORDS_PATH:-$ROOT/data/petase_family_expanded/petase_records.jsonl}"
INIT_STATE_PATH="${INIT_STATE_PATH:?INIT_STATE_PATH must be set}"
WAVE_NAME="${WAVE_NAME:-wynton-raft-wave}"
MODEL="${MODEL:-moonshotai/Kimi-K2.5}"
VARIANT="${VARIANT:-baseline}"

CANDIDATE_SAMPLE_COUNT="${CANDIDATE_SAMPLE_COUNT:-256}"
SECOND_STAGE_TOP_K="${SECOND_STAGE_TOP_K:-16}"
PLDDT_GATE_THRESHOLD="${PLDDT_GATE_THRESHOLD:-85.0}"
SEED_BASE="${SEED_BASE:-37}"
SAMPLING_TEMPERATURE="${SAMPLING_TEMPERATURE:-0.8}"
ESM2_DEVICE="${ESM2_DEVICE:-cuda}"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is required in environment" >&2
  exit 2
fi

mapfile -t SHARD_FILES < <(find "$PROMPTS_DIR" -maxdepth 1 -type f -name '*.jsonl' | sort)
if [[ "${#SHARD_FILES[@]}" -eq 0 ]]; then
  echo "No shard files found in PROMPTS_DIR=$PROMPTS_DIR" >&2
  exit 3
fi

TASK_INDEX="${SGE_TASK_ID:?SGE_TASK_ID is required for array jobs}"
if (( TASK_INDEX < 1 || TASK_INDEX > ${#SHARD_FILES[@]} )); then
  echo "SGE_TASK_ID=$TASK_INDEX is out of range for ${#SHARD_FILES[@]} shard files" >&2
  exit 4
fi

SHARD_PATH="${SHARD_FILES[$((TASK_INDEX - 1))]}"
SHARD_BASENAME="$(basename "$SHARD_PATH" .jsonl)"
PROMPT_COUNT="$(wc -l < "$SHARD_PATH" | tr -d ' ')"
SEED="$((SEED_BASE + TASK_INDEX))"
RUN_NAME="${WAVE_NAME}-${SHARD_BASENAME}-s${SEED}"

SCRATCH_BASE="${TMPDIR:-/tmp}"
RUN_SCRATCH_DIR="${SCRATCH_BASE}/pearl-raft-${JOB_ID}-${TASK_INDEX}"
SCRATCH_OUT_DIR="${RUN_SCRATCH_DIR}/out"
SCRATCH_HF_DIR="${RUN_SCRATCH_DIR}/hf"
mkdir -p "$SCRATCH_OUT_DIR" "$SCRATCH_HF_DIR"

PERSISTENT_OUT_DIR="${PERSISTENT_OUT_DIR:-$ROOT/reports/raft/$WAVE_NAME/runs}"
mkdir -p "$PERSISTENT_OUT_DIR"

cleanup() {
  rm -rf "$RUN_SCRATCH_DIR"
}
trap cleanup EXIT

export HF_HOME="$SCRATCH_HF_DIR"
export TRANSFORMERS_CACHE="$SCRATCH_HF_DIR"
export TINKER_SAMPLER_CHECKPOINT_MAP_PATH="${RUN_SCRATCH_DIR}/.tinker_sampler_checkpoint_map.json"
export SAMPLING_TEMPERATURE
export ESM2_DEVICE

echo "[raft] shard=$SHARD_PATH"
echo "[raft] prompt_count=$PROMPT_COUNT"
echo "[raft] scratch=$RUN_SCRATCH_DIR"
echo "[raft] output=$PERSISTENT_OUT_DIR"

apptainer exec --nv \
  --bind "$ROOT:$ROOT" \
  --bind "$RUN_SCRATCH_DIR:$RUN_SCRATCH_DIR" \
  "$SIF_PATH" \
  "$PYTHON_IN_CONTAINER" "$ROOT/scripts/run_ablation.py" \
    --name "$RUN_NAME" \
    --variant "$VARIANT" \
    --model "$MODEL" \
    --prompts-path "$SHARD_PATH" \
    --reference-records-path "$REFERENCE_RECORDS_PATH" \
    --output-dir "$SCRATCH_OUT_DIR" \
    --prompt-count "$PROMPT_COUNT" \
    --candidate-sample-count "$CANDIDATE_SAMPLE_COUNT" \
    --second-stage-top-k "$SECOND_STAGE_TOP_K" \
    --plddt-gate-threshold "$PLDDT_GATE_THRESHOLD" \
    --init-state-path "$INIT_STATE_PATH" \
    --eval-only \
    --resume \
    --capture-candidate-audit \
    --seed "$SEED" \
    --preserve-order

rsync -a "$SCRATCH_OUT_DIR"/ "$PERSISTENT_OUT_DIR"/
echo "[raft] synced outputs to $PERSISTENT_OUT_DIR"
