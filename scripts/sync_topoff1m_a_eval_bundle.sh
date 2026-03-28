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

ssh -i "$SSH_KEY_PATH" "$REMOTE_USER@$HOST" \
  "mkdir -p '$REMOTE_ROOT/scripts' '$REMOTE_ROOT/data/petase_family_expanded' '$REMOTE_ROOT/reports/logs' '$REMOTE_ROOT/reports/robustness' '$REMOTE_ROOT/reports/ablations' '$REMOTE_ROOT/notes'"

rsync -av -e "ssh -i $SSH_KEY_PATH" \
  /Users/svdr/tinker/main.py \
  /Users/svdr/tinker/local_proxy.py \
  /Users/svdr/tinker/petase_family.py \
  "$REMOTE_USER@$HOST:$REMOTE_ROOT/"

rsync -av -e "ssh -i $SSH_KEY_PATH" \
  /Users/svdr/tinker/scripts/finalize_ablation_from_candidate_audit.py \
  /Users/svdr/tinker/scripts/run_ablation.py \
  /Users/svdr/tinker/scripts/run_robustness_suite.py \
  /Users/svdr/tinker/scripts/run_robustness_two_phase.py \
  /Users/svdr/tinker/scripts/launch_detached_job.py \
  /Users/svdr/tinker/scripts/stop_detached_job.py \
  /Users/svdr/tinker/scripts/run_nebius_h100_robustness.sh \
  /Users/svdr/tinker/scripts/launch_topoff1m_a_robustness_h100.sh \
  /Users/svdr/tinker/scripts/setup_nebius_h100_eval_env.sh \
  "$REMOTE_USER@$HOST:$REMOTE_ROOT/scripts/"

rsync -av -e "ssh -i $SSH_KEY_PATH" \
  /Users/svdr/tinker/data/petase_family_expanded/petase_records.jsonl \
  /Users/svdr/tinker/data/petase_family_expanded/val_prompts_relevance_ge10.jsonl \
  "$REMOTE_USER@$HOST:$REMOTE_ROOT/data/petase_family_expanded/"

echo
echo "Next on the VM:"
echo "  bash $REMOTE_ROOT/scripts/setup_nebius_h100_eval_env.sh"
echo "  export TINKER_API_KEY=..."
echo "  bash $REMOTE_ROOT/scripts/launch_topoff1m_a_robustness_h100.sh ultra"
echo "  bash $REMOTE_ROOT/scripts/launch_topoff1m_a_robustness_h100.sh balanced"
