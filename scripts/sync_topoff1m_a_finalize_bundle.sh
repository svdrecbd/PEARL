#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <vm-host-or-ip> [remote-user]" >&2
  exit 1
fi

HOST="$1"
REMOTE_USER="${2:-svdr}"
SSH_KEY_PATH="${SSH_KEY_PATH:-$HOME/.ssh/nebius_h200}"
REMOTE_ROOT="${REMOTE_ROOT:-/home/$REMOTE_USER/work/tinker}"
SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

ssh -i "$SSH_KEY_PATH" "$REMOTE_USER@$HOST" \
  "mkdir -p '$REMOTE_ROOT/scripts' '$REMOTE_ROOT/src/pearl' '$REMOTE_ROOT/data/petase_family_expanded' '$REMOTE_ROOT/reports/logs' '$REMOTE_ROOT/reports/raft' '$REMOTE_ROOT/venvs'"

rsync -av -e "ssh -i $SSH_KEY_PATH" \
  "$REPO_ROOT/main.py" \
  "$REPO_ROOT/local_proxy.py" \
  "$REPO_ROOT/petase_family.py" \
  "$REMOTE_USER@$HOST:$REMOTE_ROOT/"

rsync -av -e "ssh -i $SSH_KEY_PATH" \
  "$REPO_ROOT/src/pearl/" \
  "$REMOTE_USER@$HOST:$REMOTE_ROOT/src/pearl/"

rsync -av -e "ssh -i $SSH_KEY_PATH" \
  "$REPO_ROOT/scripts/finalize_ablation_from_candidate_audit.py" \
  "$REPO_ROOT/scripts/finalize_raft_wave.py" \
  "$REPO_ROOT/scripts/finalize_raft_wave_partition.py" \
  "$REPO_ROOT/scripts/launch_detached_job.py" \
  "$REPO_ROOT/scripts/launch_topoff1m_a_raft_finalize_partition.sh" \
  "$REPO_ROOT/scripts/run_ablation.py" \
  "$REPO_ROOT/scripts/setup_nebius_h100_eval_env.sh" \
  "$REMOTE_USER@$HOST:$REMOTE_ROOT/scripts/"

rsync -av -e "ssh -i $SSH_KEY_PATH" \
  "$REPO_ROOT/data/petase_family_expanded/petase_records.jsonl" \
  "$REMOTE_USER@$HOST:$REMOTE_ROOT/data/petase_family_expanded/"

echo
echo "Next on the VM:"
echo "  bash $REMOTE_ROOT/scripts/setup_nebius_h100_eval_env.sh"
echo "  bash $REMOTE_ROOT/scripts/launch_topoff1m_a_raft_finalize_partition.sh <wave-dir> 0 <partition-count>"
