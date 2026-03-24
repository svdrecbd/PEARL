#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export GPU_LABEL="${GPU_LABEL:-h100}"
exec "$SCRIPT_DIR/run_nebius_prefilter_benchmark.sh" "$@"
