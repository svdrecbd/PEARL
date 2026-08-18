#!/usr/bin/env bash
set -euo pipefail

repo_root="$HOME/pearl-charon/repo"
state_root="$HOME/.pearl/charon/state"
systemctl --no-pager --full status pearl-frontier-charon.service || true
"$repo_root/.venv/bin/python" "$repo_root/scripts/manage_frontier_charon_replication.py" \
  status --state-dir "$state_root"
