#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON_BIN:-$HOME/venvs/pearl-eval-cu121/bin/python}"
REFERENCE_RECORDS_PATH="${REFERENCE_RECORDS_PATH:-$ROOT/data/petase_family_expanded/petase_records.jsonl}"
SHARDS_DIR="${SHARDS_DIR:-$ROOT/transfers/topoff_1m_run_20260307-232538/shards/A}"
SHARD_GLOB="${SHARD_GLOB:-hpc_ready_A_shard_*.jsonl}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$ROOT/reports/nebius_sequence_eval}"
INSTANCE_LABEL="${INSTANCE_LABEL:-nebius-prod}"
WAVE_NAME="${WAVE_NAME:-}"
PLDDT_GATE_THRESHOLD="${PLDDT_GATE_THRESHOLD:-85.0}"
LINE_LIMIT="${LINE_LIMIT:-}"
GPU_COUNT="${GPU_COUNT:-}"
GPU_IDS="${GPU_IDS:-}"
PREFILTER_EVAL_MODE="${PREFILTER_EVAL_MODE:-staged}"
PREFILTER_CPU_WORKERS="${PREFILTER_CPU_WORKERS:-8}"
ESM2_BATCH_SIZE="${ESM2_BATCH_SIZE:-256}"
ESM2_SEQUENCE_BATCH_SIZE="${ESM2_SEQUENCE_BATCH_SIZE:-1}"
ESM2_SEQUENCE_LENGTH_BUCKET_SPAN="${ESM2_SEQUENCE_LENGTH_BUCKET_SPAN:-32}"
ESM2_SEQUENCE_BATCH_TARGET_RESIDUES="${ESM2_SEQUENCE_BATCH_TARGET_RESIDUES:-0}"
ESM2_PIPELINE_CHUNK_SIZE="${ESM2_PIPELINE_CHUNK_SIZE:-128}"
WORKER_START_STAGGER_SECONDS="${WORKER_START_STAGGER_SECONDS:-0}"
ESM2_ENABLE_TF32="${ESM2_ENABLE_TF32:-1}"
ESM2_DTYPE="${ESM2_DTYPE:-bf16}"
ESM2_USE_TORCH_COMPILE="${ESM2_USE_TORCH_COMPILE:-0}"
ESM2_COMPILE_MODE="${ESM2_COMPILE_MODE:-reduce-overhead}"
HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME}"
TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"
PYTORCH_NO_CUDA_MEMORY_CACHING="${PYTORCH_NO_CUDA_MEMORY_CACHING:-0}"

usage() {
  cat <<'EOF'
usage: run_nebius_prefilter_production.sh [options]

Launches one production-style Nebius wave across multiple local GPUs by pinning one
shard worker per GPU. Completed shards are skipped automatically when summary.json exists.

Options:
  --python-bin <path>                Python executable. Default: ~/venvs/pearl-eval-cu121/bin/python
  --reference-records-path <path>    PETase reference JSONL.
  --shards-dir <path>                Directory containing shard JSONLs.
  --shard-glob <pattern>             Shard filename glob. Default: hpc_ready_A_shard_*.jsonl
  --output-root <path>               Root directory for production outputs.
  --wave-name <name>                 Logical wave name. Default: nebius-prod-<instance>-<stamp>
  --instance-label <label>           Short instance label used in default wave names.
  --gpu-count <n>                    Number of local GPUs to use.
  --gpu-ids <csv>                    Explicit GPU ids (for example 0,1,2,3).
  --prefilter-eval-mode <mode>       'staged' or 'pipeline'. Default: staged.
  --prefilter-cpu-workers <n>        CPU workers per shard process. Default: 8.
  --esm2-batch-size <n>              Residue microbatch size. Default: 256.
  --esm2-sequence-batch-size <n>     Sequence batch size. Default: 1.
  --esm2-sequence-length-bucket-span <n>
                                     Length bucket spread. Default: 32.
  --esm2-sequence-batch-target-residues <n>
                                     Target total masked residues per sequence bucket.
                                     Default: 0 (disabled).
  --esm2-pipeline-chunk-size <n>     Chunk size for staged/pipeline eval. Default: 128.
  --worker-start-stagger-seconds <n> Delay between worker start phases. Default: 0.
  --plddt-gate-threshold <f>         ESM gate threshold. Default: 85.0.
  --line-limit <n>                   Optional record cap for smoke runs.
  -h, --help                         Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python-bin)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --reference-records-path)
      REFERENCE_RECORDS_PATH="$2"
      shift 2
      ;;
    --shards-dir)
      SHARDS_DIR="$2"
      shift 2
      ;;
    --shard-glob)
      SHARD_GLOB="$2"
      shift 2
      ;;
    --output-root)
      OUTPUT_ROOT="$2"
      shift 2
      ;;
    --wave-name)
      WAVE_NAME="$2"
      shift 2
      ;;
    --instance-label)
      INSTANCE_LABEL="$2"
      shift 2
      ;;
    --gpu-count)
      GPU_COUNT="$2"
      shift 2
      ;;
    --gpu-ids)
      GPU_IDS="$2"
      shift 2
      ;;
    --prefilter-eval-mode)
      PREFILTER_EVAL_MODE="$2"
      shift 2
      ;;
    --prefilter-cpu-workers)
      PREFILTER_CPU_WORKERS="$2"
      shift 2
      ;;
    --esm2-batch-size)
      ESM2_BATCH_SIZE="$2"
      shift 2
      ;;
    --esm2-sequence-batch-size)
      ESM2_SEQUENCE_BATCH_SIZE="$2"
      shift 2
      ;;
    --esm2-sequence-length-bucket-span)
      ESM2_SEQUENCE_LENGTH_BUCKET_SPAN="$2"
      shift 2
      ;;
    --esm2-sequence-batch-target-residues)
      ESM2_SEQUENCE_BATCH_TARGET_RESIDUES="$2"
      shift 2
      ;;
    --esm2-pipeline-chunk-size)
      ESM2_PIPELINE_CHUNK_SIZE="$2"
      shift 2
      ;;
    --worker-start-stagger-seconds)
      WORKER_START_STAGGER_SECONDS="$2"
      shift 2
      ;;
    --plddt-gate-threshold)
      PLDDT_GATE_THRESHOLD="$2"
      shift 2
      ;;
    --line-limit)
      LINE_LIMIT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "PYTHON_BIN is not executable: $PYTHON_BIN" >&2
  exit 3
fi
if [[ ! -d "$SHARDS_DIR" ]]; then
  echo "SHARDS_DIR does not exist: $SHARDS_DIR" >&2
  exit 4
fi
if [[ ! -f "$REFERENCE_RECORDS_PATH" ]]; then
  echo "REFERENCE_RECORDS_PATH does not exist: $REFERENCE_RECORDS_PATH" >&2
  exit 5
fi
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi not found; this launcher expects a Nebius GPU VM" >&2
  exit 6
fi

declare -a GPU_ID_ARRAY=()
if [[ -n "$GPU_IDS" ]]; then
  IFS=',' read -r -a GPU_ID_ARRAY <<<"$GPU_IDS"
else
  if [[ -z "$GPU_COUNT" ]]; then
    GPU_COUNT="$(nvidia-smi -L | wc -l | tr -d '[:space:]')"
  fi
  if [[ -z "$GPU_COUNT" || "$GPU_COUNT" -lt 1 ]]; then
    echo "could not determine GPU_COUNT" >&2
    exit 7
  fi
  for ((gpu_id=0; gpu_id<GPU_COUNT; gpu_id+=1)); do
    GPU_ID_ARRAY+=("$gpu_id")
  done
fi

mapfile -t SHARDS < <(find "$SHARDS_DIR" -maxdepth 1 -type f -name "$SHARD_GLOB" | sort)
if [[ "${#SHARDS[@]}" -eq 0 ]]; then
  echo "no shards found in $SHARDS_DIR matching $SHARD_GLOB" >&2
  exit 8
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
INSTANCE_LABEL_SAFE="$(printf '%s' "$INSTANCE_LABEL" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-')"
WAVE_NAME="${WAVE_NAME:-nebius-prod-${INSTANCE_LABEL_SAFE}-${STAMP}}"
WAVE_DIR="$OUTPUT_ROOT/$WAVE_NAME"
RUNS_DIR="$WAVE_DIR/runs"
LOG_DIR="$WAVE_DIR/logs"
WORKER_LOG_DIR="$LOG_DIR/workers"
SHARD_LOG_DIR="$LOG_DIR/shards"
MANIFEST_PATH="$WAVE_DIR/launch_manifest.json"
SHARDS_PATH="$WAVE_DIR/shards.txt"
QUEUE_PATH="$WAVE_DIR/shard_queue.txt"
QUEUE_LOCK_PATH="$WAVE_DIR/shard_queue.lock"
PREWARM_LOG="$LOG_DIR/prewarm.log"

mkdir -p "$RUNS_DIR" "$WORKER_LOG_DIR" "$SHARD_LOG_DIR"

printf '%s\n' "${SHARDS[@]}" > "$SHARDS_PATH"
cp "$SHARDS_PATH" "$QUEUE_PATH"
: > "$QUEUE_LOCK_PATH"

export HF_HOME
export TRANSFORMERS_CACHE
export TOKENIZERS_PARALLELISM
export OMP_NUM_THREADS
export MKL_NUM_THREADS
export NUMEXPR_NUM_THREADS
export PYTORCH_NO_CUDA_MEMORY_CACHING
export PREFILTER_EVAL_MODE
export PREFILTER_CPU_WORKERS
export ESM2_BATCH_SIZE
export ESM2_SEQUENCE_BATCH_SIZE
export ESM2_SEQUENCE_LENGTH_BUCKET_SPAN
export ESM2_SEQUENCE_BATCH_TARGET_RESIDUES
export ESM2_PIPELINE_CHUNK_SIZE
export WORKER_START_STAGGER_SECONDS
export ESM2_ENABLE_TF32
export ESM2_DTYPE
export ESM2_USE_TORCH_COMPILE
export ESM2_COMPILE_MODE

GPU_ID_LIST="$(printf '%s\n' "${GPU_ID_ARRAY[@]}")"
SHARD_COUNT="${#SHARDS[@]}"
export WAVE_NAME INSTANCE_LABEL PYTHON_BIN REFERENCE_RECORDS_PATH SHARDS_DIR SHARD_GLOB
export OUTPUT_ROOT RUNS_DIR GPU_IDS PREFILTER_EVAL_MODE PREFILTER_CPU_WORKERS
export ESM2_BATCH_SIZE ESM2_SEQUENCE_BATCH_SIZE ESM2_SEQUENCE_LENGTH_BUCKET_SPAN
export ESM2_SEQUENCE_BATCH_TARGET_RESIDUES
export ESM2_PIPELINE_CHUNK_SIZE WORKER_START_STAGGER_SECONDS
export PLDDT_GATE_THRESHOLD LINE_LIMIT GPU_ID_LIST SHARD_COUNT

"$PYTHON_BIN" - <<'PY' >"$MANIFEST_PATH"
import json
import os

gpu_ids = [line for line in os.environ["GPU_ID_LIST"].splitlines() if line]
line_limit = os.environ.get("LINE_LIMIT") or None

print(
    json.dumps(
        {
            "wave_name": os.environ["WAVE_NAME"],
            "instance_label": os.environ["INSTANCE_LABEL"],
            "python_bin": os.environ["PYTHON_BIN"],
            "reference_records_path": os.environ["REFERENCE_RECORDS_PATH"],
            "shards_dir": os.environ["SHARDS_DIR"],
            "shard_glob": os.environ["SHARD_GLOB"],
            "output_root": os.environ["OUTPUT_ROOT"],
            "runs_dir": os.environ["RUNS_DIR"],
            "gpu_ids": os.environ.get("GPU_IDS", ""),
            "resolved_gpu_ids": gpu_ids,
            "prefilter_eval_mode": os.environ["PREFILTER_EVAL_MODE"],
            "prefilter_cpu_workers": int(os.environ["PREFILTER_CPU_WORKERS"]),
            "esm2_batch_size": int(os.environ["ESM2_BATCH_SIZE"]),
            "esm2_sequence_batch_size": int(os.environ["ESM2_SEQUENCE_BATCH_SIZE"]),
            "esm2_sequence_length_bucket_span": int(os.environ["ESM2_SEQUENCE_LENGTH_BUCKET_SPAN"]),
            "esm2_sequence_batch_target_residues": int(os.environ["ESM2_SEQUENCE_BATCH_TARGET_RESIDUES"]),
            "esm2_pipeline_chunk_size": int(os.environ["ESM2_PIPELINE_CHUNK_SIZE"]),
            "worker_start_stagger_seconds": int(os.environ["WORKER_START_STAGGER_SECONDS"]),
            "plddt_gate_threshold": float(os.environ["PLDDT_GATE_THRESHOLD"]),
            "line_limit": int(line_limit) if line_limit is not None else None,
            "shard_count": int(os.environ["SHARD_COUNT"]),
        },
        indent=2,
    )
)
PY

{
  echo "[nebius-prod] started_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[nebius-prod] host=$(hostname)"
  echo "[nebius-prod] wave_name=$WAVE_NAME"
  echo "[nebius-prod] runs_dir=$RUNS_DIR"
  echo "[nebius-prod] shard_count=${#SHARDS[@]}"
  echo "[nebius-prod] gpu_ids=${GPU_ID_ARRAY[*]}"
  echo "[nebius-prod] prefilter_eval_mode=$PREFILTER_EVAL_MODE"
  echo "[nebius-prod] prefilter_cpu_workers=$PREFILTER_CPU_WORKERS"
  echo "[nebius-prod] esm2_batch_size=$ESM2_BATCH_SIZE"
  echo "[nebius-prod] esm2_sequence_batch_size=$ESM2_SEQUENCE_BATCH_SIZE"
  echo "[nebius-prod] esm2_sequence_batch_target_residues=$ESM2_SEQUENCE_BATCH_TARGET_RESIDUES"
  echo "[nebius-prod] esm2_pipeline_chunk_size=$ESM2_PIPELINE_CHUNK_SIZE"
  echo "[nebius-prod] worker_start_stagger_seconds=$WORKER_START_STAGGER_SECONDS"
  nvidia-smi -L || true
} | tee "$PREWARM_LOG"

echo "[nebius-prod] prewarming ESM2 model cache on GPU ${GPU_ID_ARRAY[0]}" | tee -a "$PREWARM_LOG"
CUDA_VISIBLE_DEVICES="${GPU_ID_ARRAY[0]}" "$PYTHON_BIN" - <<'PY' | tee -a "$PREWARM_LOG"
import json
from local_proxy import prewarm_esm2_model

print(json.dumps(prewarm_esm2_model(), indent=2))
PY

declare -a WORKER_PIDS=()

run_worker() {
  local slot="$1"
  local gpu_id="$2"
  local total_slots="$3"
  local worker_log="$WORKER_LOG_DIR/gpu${gpu_id}.log"

  {
    echo "[worker] started_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "[worker] slot=$slot gpu_id=$gpu_id total_slots=$total_slots"
  } >>"$worker_log"

  if [[ "$WORKER_START_STAGGER_SECONDS" -gt 0 && "$slot" -gt 0 ]]; then
    local worker_delay=$((slot * WORKER_START_STAGGER_SECONDS))
    echo "[worker] stagger_sleep_seconds=$worker_delay gpu_id=$gpu_id" >>"$worker_log"
    sleep "$worker_delay"
  fi

  while true; do
    local shard_path=""
    exec 9>>"$QUEUE_LOCK_PATH"
    flock 9
    if [[ -s "$QUEUE_PATH" ]]; then
      shard_path="$(head -n 1 "$QUEUE_PATH")"
      tail -n +2 "$QUEUE_PATH" > "${QUEUE_PATH}.tmp"
      mv "${QUEUE_PATH}.tmp" "$QUEUE_PATH"
    fi
    flock -u 9
    exec 9>&-

    if [[ -z "$shard_path" ]]; then
      break
    fi

    local shard_basename
    shard_basename="$(basename "$shard_path" .jsonl)"
    local run_name="${WAVE_NAME}-${shard_basename}"
    local run_dir="$RUNS_DIR/$run_name"
    local summary_path="$run_dir/summary.json"
    local shard_log="$SHARD_LOG_DIR/${run_name}.log"

    if [[ -f "$summary_path" ]]; then
      echo "[worker] skip_completed run_name=$run_name summary=$summary_path" | tee -a "$worker_log"
      continue
    fi

    echo "[worker] launch run_name=$run_name gpu_id=$gpu_id shard=$shard_path" | tee -a "$worker_log" "$shard_log"

    if [[ -n "$LINE_LIMIT" ]]; then
      CUDA_VISIBLE_DEVICES="$gpu_id" "$PYTHON_BIN" "$ROOT/scripts/run_sequence_shard_eval.py" \
        --input-jsonl "$shard_path" \
        --output-dir "$RUNS_DIR" \
        --reference-records-path "$REFERENCE_RECORDS_PATH" \
        --name "$run_name" \
        --plddt-gate-threshold "$PLDDT_GATE_THRESHOLD" \
        --limit "$LINE_LIMIT" >>"$shard_log" 2>&1
    else
      CUDA_VISIBLE_DEVICES="$gpu_id" "$PYTHON_BIN" "$ROOT/scripts/run_sequence_shard_eval.py" \
        --input-jsonl "$shard_path" \
        --output-dir "$RUNS_DIR" \
        --reference-records-path "$REFERENCE_RECORDS_PATH" \
        --name "$run_name" \
        --plddt-gate-threshold "$PLDDT_GATE_THRESHOLD" >>"$shard_log" 2>&1
    fi
  done

  echo "[worker] finished_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) gpu_id=$gpu_id" >>"$worker_log"
}

cleanup() {
  local code=$?
  if [[ "$code" -ne 0 ]]; then
    for pid in "${WORKER_PIDS[@]:-}"; do
      kill "$pid" 2>/dev/null || true
    done
  fi
}
trap cleanup EXIT INT TERM

for slot in "${!GPU_ID_ARRAY[@]}"; do
  gpu_id="${GPU_ID_ARRAY[$slot]}"
  run_worker "$slot" "$gpu_id" "${#GPU_ID_ARRAY[@]}" &
  WORKER_PIDS+=("$!")
done

worker_failures=0
for pid in "${WORKER_PIDS[@]}"; do
  if ! wait "$pid"; then
    worker_failures=$((worker_failures + 1))
  fi
done

completed_count="$(find "$RUNS_DIR" -mindepth 2 -maxdepth 2 -name summary.json | wc -l | tr -d '[:space:]')"

{
  echo "[nebius-prod] completed_summaries=$completed_count"
  echo "[nebius-prod] finished_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[nebius-prod] worker_failures=$worker_failures"
} | tee -a "$PREWARM_LOG"

if [[ "$worker_failures" -ne 0 ]]; then
  exit 9
fi
