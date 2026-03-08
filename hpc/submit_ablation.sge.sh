#!/bin/bash
#$ -S /bin/bash
#$ -cwd
#$ -j y
#$ -o logs/sge/ablation.$JOB_ID.log
#$ -q gpu.q
#$ -l gpu=1
#$ -l mem_free=64G
#$ -l h_rt=24:00:00
#$ -pe smp 4

set -euo pipefail
umask 077

ROOT="${ROOT:-${SGE_O_WORKDIR:-$PWD}}"
SIF_PATH="${SIF_PATH:-$ROOT/hpc/pearl_env.sif}"
PYTHON_IN_CONTAINER="${PYTHON_IN_CONTAINER:-python}"

RUN_NAME="${RUN_NAME:-wynton-ablation-${JOB_ID}}"
MODEL="${MODEL:-moonshotai/Kimi-K2.5}"
VARIANT="${VARIANT:-baseline}"
PROMPTS_PATH="${PROMPTS_PATH:-$ROOT/data/petase_family_expanded/val_prompts_relevance_ge10.jsonl}"
REFERENCE_RECORDS_PATH="${REFERENCE_RECORDS_PATH:-$ROOT/data/petase_family_expanded/petase_records.jsonl}"
INIT_STATE_PATH="${INIT_STATE_PATH:?INIT_STATE_PATH must be set}"

PROMPT_COUNT="${PROMPT_COUNT:-12}"
CANDIDATE_SAMPLE_COUNT="${CANDIDATE_SAMPLE_COUNT:-128}"
SECOND_STAGE_TOP_K="${SECOND_STAGE_TOP_K:-16}"
PLDDT_GATE_THRESHOLD="${PLDDT_GATE_THRESHOLD:-85.0}"
SEED="${SEED:-41}"
SAMPLING_TEMPERATURE="${SAMPLING_TEMPERATURE:-0.8}"
ESM2_DEVICE="${ESM2_DEVICE:-cuda}"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is required in environment" >&2
  exit 2
fi

SCRATCH_BASE="${TMPDIR:-/tmp}"
RUN_SCRATCH_DIR="${SCRATCH_BASE}/pearl-ablation-${JOB_ID}"
SCRATCH_OUT_DIR="${RUN_SCRATCH_DIR}/out"
SCRATCH_HF_DIR="${RUN_SCRATCH_DIR}/hf"
mkdir -p "$SCRATCH_OUT_DIR" "$SCRATCH_HF_DIR"

PERSISTENT_OUT_DIR="${PERSISTENT_OUT_DIR:-$ROOT/reports/ablations}"
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

echo "[ablation] root=$ROOT"
echo "[ablation] scratch=$RUN_SCRATCH_DIR"
echo "[ablation] output=$PERSISTENT_OUT_DIR"

apptainer exec --nv \
  --bind "$ROOT:$ROOT" \
  --bind "$RUN_SCRATCH_DIR:$RUN_SCRATCH_DIR" \
  "$SIF_PATH" \
  "$PYTHON_IN_CONTAINER" "$ROOT/scripts/run_ablation.py" \
    --name "$RUN_NAME" \
    --variant "$VARIANT" \
    --model "$MODEL" \
    --prompts-path "$PROMPTS_PATH" \
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
    --seed "$SEED"

rsync -a "$SCRATCH_OUT_DIR"/ "$PERSISTENT_OUT_DIR"/
echo "[ablation] synced outputs to $PERSISTENT_OUT_DIR"
