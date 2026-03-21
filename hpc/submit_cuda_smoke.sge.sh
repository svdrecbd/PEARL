#!/bin/bash
#$ -S /bin/bash
#$ -cwd
#$ -j y
#$ -o logs/sge/cuda-smoke.$JOB_ID.$TASK_ID.log
#$ -q gpu.q
#$ -l mem_free=8G
#$ -l h_rt=00:10:00

set -euo pipefail

ROOT="${ROOT:-${SGE_O_WORKDIR:-$PWD}}"
PYTHON_BIN="${PYTHON_BIN:?PYTHON_BIN is required}"
CUDA_MODULE="${CUDA_MODULE:-cuda/12.8.1}"
SET_CUDA_VISIBLE_DEVICES="${SET_CUDA_VISIBLE_DEVICES:-1}"

if [[ -f /usr/share/lmod/lmod/init/bash ]]; then
  # shellcheck source=/dev/null
  source /usr/share/lmod/lmod/init/bash
fi
if declare -F module >/dev/null 2>&1; then
  module load "$CUDA_MODULE" 2>/dev/null || module load cuda 2>/dev/null || true
fi

mkdir -p "$ROOT/logs/sge"

if [[ "$SET_CUDA_VISIBLE_DEVICES" == "1" && -n "${SGE_GPU:-}" && "${SGE_GPU}" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
  export CUDA_VISIBLE_DEVICES="$SGE_GPU"
fi

echo "[cuda-smoke] host=$(hostname)"
echo "[cuda-smoke] cuda_module=$CUDA_MODULE"
echo "[cuda-smoke] set_cuda_visible_devices=$SET_CUDA_VISIBLE_DEVICES"
echo "[cuda-smoke] sge_gpu=${SGE_GPU:-undefined}"
echo "[cuda-smoke] cuda_visible_devices=${CUDA_VISIBLE_DEVICES:-undefined}"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -L || true
fi

"$PYTHON_BIN" "$ROOT/scripts/check_torch_cuda_env.py"
