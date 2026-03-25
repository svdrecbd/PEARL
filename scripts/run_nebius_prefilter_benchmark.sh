#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$HOME/venvs/pearl-eval-cu121/bin/python}"
REFERENCE_RECORDS_PATH="${REFERENCE_RECORDS_PATH:-$ROOT/data/petase_family_expanded/petase_records.jsonl}"
SHARD_PATH="${SHARD_PATH:-$ROOT/transfers/topoff_1m_run_20260307-232538/shards/A/hpc_ready_A_shard_0001.jsonl}"
LINE_LIMIT="${LINE_LIMIT:-1000}"
PLDDT_GATE_THRESHOLD="${PLDDT_GATE_THRESHOLD:-85.0}"
GPU_LABEL="${GPU_LABEL:-unknown-gpu}"
BENCH_ROOT="${BENCH_ROOT:-$ROOT/reports/nebius_benchmarks}"
PREFILTER_EVAL_MODE="${PREFILTER_EVAL_MODE:-pipeline}"
ESM2_BATCH_SIZE="${ESM2_BATCH_SIZE:-64}"
ESM2_SEQUENCE_BATCH_SIZE="${ESM2_SEQUENCE_BATCH_SIZE:-16}"
ESM2_SEQUENCE_LENGTH_BUCKET_SPAN="${ESM2_SEQUENCE_LENGTH_BUCKET_SPAN:-32}"
ESM2_SEQUENCE_BATCH_TARGET_RESIDUES="${ESM2_SEQUENCE_BATCH_TARGET_RESIDUES:-0}"
ESM2_PIPELINE_CHUNK_SIZE="${ESM2_PIPELINE_CHUNK_SIZE:-256}"
PREFILTER_CPU_WORKERS="${PREFILTER_CPU_WORKERS:-1}"
ESM2_ENABLE_TF32="${ESM2_ENABLE_TF32:-1}"
ESM2_DTYPE="${ESM2_DTYPE:-bf16}"
ESM2_USE_TORCH_COMPILE="${ESM2_USE_TORCH_COMPILE:-0}"
ESM2_COMPILE_MODE="${ESM2_COMPILE_MODE:-reduce-overhead}"
WAVE_NAME="${WAVE_NAME:-}"

usage() {
  cat <<'EOF'
usage: run_nebius_prefilter_benchmark.sh [options]

Runs one local shard-eval benchmark on a Nebius GPU instance and writes
artifacts under reports/nebius_benchmarks/.

Options:
  --gpu-label <label>            Short GPU label used in the run name.
  --python-bin <path>            Python executable. Default: ~/venvs/pearl-eval-cu121/bin/python
  --shard-path <path>            Input shard JSONL. Default: shard A/0001.
  --reference-records-path <p>   PETase reference JSONL.
  --line-limit <n>               Number of records to score. Default: 1000.
  --plddt-gate-threshold <f>     ESM gate threshold. Default: 85.0.
  --bench-root <path>            Output root. Default: reports/nebius_benchmarks
  --wave-name <name>             Override generated wave/run prefix.
  --prefilter-eval-mode <mode>   'pipeline' or 'staged'. Default: pipeline.
  --esm2-batch-size <n>          Override ESM2 residue batch size. Default: 64.
  --esm2-sequence-batch-size <n> Override ESM2 cross-record batch size. Default: 16.
  --esm2-sequence-length-bucket-span <n>
                                 Max length spread within one sequence bucket. Default: 32.
  --esm2-sequence-batch-target-residues <n>
                                 Target total masked residues per sequence bucket. Default: 0.
  --esm2-pipeline-chunk-size <n> Number of valid records scored before CPU eval catches up. Default: 256.
  --prefilter-cpu-workers <n>    CPU worker processes used in staged mode. Default: 1.
  Env defaults:
    ESM2_ENABLE_TF32=1
    ESM2_DTYPE=bf16
    ESM2_USE_TORCH_COMPILE=0
    ESM2_COMPILE_MODE=reduce-overhead
  -h, --help                     Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gpu-label)
      GPU_LABEL="$2"
      shift 2
      ;;
    --python-bin)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --shard-path)
      SHARD_PATH="$2"
      shift 2
      ;;
    --reference-records-path)
      REFERENCE_RECORDS_PATH="$2"
      shift 2
      ;;
    --line-limit)
      LINE_LIMIT="$2"
      shift 2
      ;;
    --plddt-gate-threshold)
      PLDDT_GATE_THRESHOLD="$2"
      shift 2
      ;;
    --bench-root)
      BENCH_ROOT="$2"
      shift 2
      ;;
    --wave-name)
      WAVE_NAME="$2"
      shift 2
      ;;
    --prefilter-eval-mode)
      PREFILTER_EVAL_MODE="$2"
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
    --prefilter-cpu-workers)
      PREFILTER_CPU_WORKERS="$2"
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
if [[ ! -f "$SHARD_PATH" ]]; then
  echo "SHARD_PATH does not exist: $SHARD_PATH" >&2
  exit 4
fi
if [[ ! -f "$REFERENCE_RECORDS_PATH" ]]; then
  echo "REFERENCE_RECORDS_PATH does not exist: $REFERENCE_RECORDS_PATH" >&2
  exit 5
fi

GPU_LABEL_SAFE="$(printf '%s' "$GPU_LABEL" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-')"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WAVE_NAME="${WAVE_NAME:-nebius-bench-${GPU_LABEL_SAFE}-${STAMP}}"
SHARD_BASENAME="$(basename "$SHARD_PATH" .jsonl)"
RUN_NAME="${WAVE_NAME}-${SHARD_BASENAME}"
OUT_DIR="$BENCH_ROOT/$WAVE_NAME/runs"
RUN_DIR="$OUT_DIR/$RUN_NAME"
LOG_PATH="$BENCH_ROOT/$WAVE_NAME/benchmark.log"
mkdir -p "$OUT_DIR"

export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME}"
export PREFILTER_EVAL_MODE
export ESM2_BATCH_SIZE
export ESM2_SEQUENCE_BATCH_SIZE
export ESM2_SEQUENCE_LENGTH_BUCKET_SPAN
export ESM2_SEQUENCE_BATCH_TARGET_RESIDUES
export ESM2_PIPELINE_CHUNK_SIZE
export PREFILTER_CPU_WORKERS
export ESM2_ENABLE_TF32
export ESM2_DTYPE
export ESM2_USE_TORCH_COMPILE
export ESM2_COMPILE_MODE

# Preserve the validated auto-device behavior unless the caller overrides it.
if [[ -z "${ESM2_DEVICE:-}" ]]; then
  unset ESM2_DEVICE || true
fi

{
  echo "[nebius-bench] started_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[nebius-bench] host=$(hostname)"
  echo "[nebius-bench] gpu_label=$GPU_LABEL"
  echo "[nebius-bench] python_bin=$PYTHON_BIN"
  echo "[nebius-bench] shard_path=$SHARD_PATH"
  echo "[nebius-bench] reference_records_path=$REFERENCE_RECORDS_PATH"
  echo "[nebius-bench] wave_name=$WAVE_NAME"
  echo "[nebius-bench] run_name=$RUN_NAME"
  echo "[nebius-bench] out_dir=$OUT_DIR"
  echo "[nebius-bench] line_limit=$LINE_LIMIT"
  echo "[nebius-bench] plddt_gate_threshold=$PLDDT_GATE_THRESHOLD"
  echo "[nebius-bench] prefilter_eval_mode=$PREFILTER_EVAL_MODE"
  echo "[nebius-bench] hf_home=$HF_HOME"
  echo "[nebius-bench] esm2_batch_size=$ESM2_BATCH_SIZE"
  echo "[nebius-bench] esm2_sequence_batch_size=$ESM2_SEQUENCE_BATCH_SIZE"
  echo "[nebius-bench] esm2_sequence_length_bucket_span=$ESM2_SEQUENCE_LENGTH_BUCKET_SPAN"
  echo "[nebius-bench] esm2_sequence_batch_target_residues=$ESM2_SEQUENCE_BATCH_TARGET_RESIDUES"
  echo "[nebius-bench] esm2_pipeline_chunk_size=$ESM2_PIPELINE_CHUNK_SIZE"
  echo "[nebius-bench] prefilter_cpu_workers=$PREFILTER_CPU_WORKERS"
  echo "[nebius-bench] esm2_device=${ESM2_DEVICE:-auto}"
  echo "[nebius-bench] esm2_enable_tf32=$ESM2_ENABLE_TF32"
  echo "[nebius-bench] esm2_dtype=${ESM2_DTYPE:-fp32}"
  echo "[nebius-bench] esm2_use_torch_compile=$ESM2_USE_TORCH_COMPILE"
  echo "[nebius-bench] esm2_compile_mode=$ESM2_COMPILE_MODE"
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi -L || true
  fi
} | tee "$LOG_PATH"

"$PYTHON_BIN" "$ROOT/scripts/run_sequence_shard_eval.py" \
  --input-jsonl "$SHARD_PATH" \
  --output-dir "$OUT_DIR" \
  --reference-records-path "$REFERENCE_RECORDS_PATH" \
  --name "$RUN_NAME" \
  --plddt-gate-threshold "$PLDDT_GATE_THRESHOLD" \
  --limit "$LINE_LIMIT" | tee -a "$LOG_PATH"

SUMMARY_PATH="$RUN_DIR/summary.json"

"$PYTHON_BIN" - <<PY | tee -a "$LOG_PATH"
import json
from pathlib import Path

summary_path = Path(${SUMMARY_PATH@Q})
if not summary_path.exists():
    raise SystemExit(f"summary not found: {summary_path}")

summary = json.loads(summary_path.read_text())
stats = summary["stats"]
records = int(stats["records_evaluated"])
duration = float(stats["duration_seconds"])
sec_per_record = duration / max(1, records)
records_per_hour = 3600.0 / sec_per_record
print(json.dumps({
    "benchmark_summary": {
        "summary_path": str(summary_path),
        "records_evaluated": records,
        "duration_seconds": duration,
        "seconds_per_record": round(sec_per_record, 6),
        "records_per_hour": round(records_per_hour, 2),
        "esm_backend": stats["esm_info"]["backend"],
        "esm_device": stats["esm_info"]["device"],
    }
}, indent=2))
PY

echo "[nebius-bench] finished_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG_PATH"
