#!/usr/bin/env bash

set -euo pipefail

VENV_DIR="${VENV_DIR:-$HOME/venvs/pearl-eval-cu124}"

sudo apt-get update
sudo apt-get install -y python3-venv python3-pip python-is-python3

python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
pip install --index-url https://download.pytorch.org/whl/cu124 torch
pip install "tinker==0.16.1" transformers numpy safetensors sentencepiece protobuf tiktoken

python - <<'PY'
import torch, tinker, transformers

print("torch", torch.__version__)
print("cuda", torch.cuda.is_available())
print("device_count", torch.cuda.device_count())
print("gpu", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none")
print("tinker", tinker.__version__)
print("transformers", transformers.__version__)
PY
