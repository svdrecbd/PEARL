#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export INSTANCE_LABEL="${INSTANCE_LABEL:-h100-8x}"
exec "$SCRIPT_DIR/run_nebius_prefilter_production.sh" "$@"
