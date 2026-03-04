#!/bin/zsh
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <batch_id>" >&2
  exit 1
fi

BATCH_ID="$1"
ROOT="/Users/svdr/tinker"
PYTHON_BIN="/opt/anaconda3/bin/python"

if [[ -z "${TINKER_API_KEY:-}" ]]; then
  echo "TINKER_API_KEY is required" >&2
  exit 1
fi

case "$BATCH_ID" in
  01|1) BATCH_FILE="val100_batch01.jsonl"; NAME_PREFIX="kimi25-zero-shot-reseed3-batch01" ;;
  02|2) BATCH_FILE="val100_batch02.jsonl"; NAME_PREFIX="kimi25-zero-shot-reseed3-batch02" ;;
  03|3) BATCH_FILE="val100_batch03.jsonl"; NAME_PREFIX="kimi25-zero-shot-reseed3-batch03" ;;
  04|4) BATCH_FILE="val100_batch04.jsonl"; NAME_PREFIX="kimi25-zero-shot-reseed3-batch04" ;;
  *)
    echo "unsupported batch id: $BATCH_ID" >&2
    exit 1
    ;;
esac

RUN_NAME="${NAME_PREFIX}-t0p85-c256-p25"
RUN_DIR="$ROOT/reports/ablations/kimi25-stratified-reseed3/$RUN_NAME"
SUMMARY_PATH="$RUN_DIR/summary.json"

# Never relaunch a completed batch into the same output directory.
if [[ -f "$SUMMARY_PATH" ]]; then
  echo "Completed summary already exists at $SUMMARY_PATH; refusing to relaunch $RUN_NAME." >&2
  exit 0
fi

if pgrep -f "run_ablation.py --name $RUN_NAME" >/dev/null 2>&1; then
  echo "An active run already exists for $RUN_NAME; refusing to launch a duplicate." >&2
  exit 0
fi

exec "$PYTHON_BIN" "$ROOT/scripts/run_kimi_zero_shot_stratified_search.py" \
  --name-prefix "$NAME_PREFIX" \
  --model moonshotai/Kimi-K2.5 \
  --variant motif_prior_soft_v2 \
  --prompts-path "$ROOT/reports/ablations/kimi25-stratified/batches/$BATCH_FILE" \
  --reference-records-path "$ROOT/data/petase_family_expanded/petase_records.jsonl" \
  --output-dir "$ROOT/reports/ablations/kimi25-stratified-reseed3" \
  --prompt-count 25 \
  --candidate-sample-count 256 \
  --second-stage-top-k 16 \
  --plddt-gate-threshold 85 \
  --temperatures 0.85 \
  --top-p 0.98 \
  --top-k 100 \
  --esm2-backend torch \
  --esm2-batch-size 32 \
  --esm2-score-cache-size 8192 \
  --esm2-device mps \
  --python-bin "$PYTHON_BIN" \
  --tinker-python-bin "$PYTHON_BIN"
