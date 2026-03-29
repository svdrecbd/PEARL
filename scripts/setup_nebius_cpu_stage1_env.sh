#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y python3-venv python3-pip python-is-python3

python3 -m venv "$HOME/venvs/pearl-stage1-cpu"
source "$HOME/venvs/pearl-stage1-cpu/bin/activate"

python -m pip install --upgrade pip
pip install "tinker==0.16.1" torch transformers sentencepiece protobuf tiktoken

python - <<'PY'
import torch, tinker, transformers
print("python_env_ok", True)
print("torch", torch.__version__)
print("cuda", torch.cuda.is_available())
print("tinker", tinker.__version__)
print("transformers", transformers.__version__)
PY
