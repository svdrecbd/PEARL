#!/usr/bin/env bash
set -euo pipefail

: "${PEARL_SOURCE_COMMIT:?PEARL_SOURCE_COMMIT is required}"
: "${GMN_OUTPUT_DIR:?GMN_OUTPUT_DIR is required}"

observed_commit="$(git rev-parse HEAD)"
if [[ "$observed_commit" != "$PEARL_SOURCE_COMMIT" ]]; then
  echo "PEARL source commit mismatch: expected $PEARL_SOURCE_COMMIT, observed $observed_commit" >&2
  exit 2
fi

if command -v sudo >/dev/null 2>&1; then
  sudo_prefix=(sudo)
else
  sudo_prefix=()
fi
"${sudo_prefix[@]}" apt-get update
"${sudo_prefix[@]}" apt-get install --yes --no-install-recommends \
  build-essential python3-dev python3-pip python3-venv ca-certificates git
"${sudo_prefix[@]}" rm -rf /var/lib/apt/lists/*

source_root="$(mktemp -d /tmp/pearl-esmfold2-sources.XXXXXX)"
cleanup() {
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
PY

export ESMFOLD2_CALIBRATION=1
exec ./deploy/frontier_adaptation_v2/run_esmfold2_job.sh
