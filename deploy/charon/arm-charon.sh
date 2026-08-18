#!/usr/bin/env bash
set -euo pipefail

install_root="$HOME/pearl-charon"
repo_root="$install_root/repo"
bootstrap_root="$HOME/.pearl/charon/bootstrap"
state_root="$HOME/.pearl/charon/state"
mirror_root="/mnt/c/PEARL_CHARON_STATE_MIRROR"
env_file="$HOME/.config/pearl/charon.env"
python="$repo_root/.venv/bin/python"

set -a
# The per-user credential file is intentionally outside the bundle.
# shellcheck disable=SC1090
source "$env_file"
set +a
export TINKER_RUN_LIST_LIMIT=1000

test ! -f "$state_root/ledger.jsonl"
"$python" "$repo_root/scripts/manage_frontier_charon_replication.py" \
  --executor-config "$repo_root/configs/experiments/frontier_adaptation_v2_executor.json" \
  prepare --state-dir "$state_root" --mirror-dir "$mirror_root" --bootstrap-dir "$bootstrap_root"
test -f "$state_root/authorization.json"
test "$(tail -n1 "$state_root/ledger.jsonl" | jq -r .event_type)" = "charon_takeover_prepared"

unit_source="$repo_root/deploy/charon/pearl-frontier-charon.service.in"
unit_temp="$(mktemp)"
trap 'rm -f "$unit_temp"' EXIT
sed \
  -e "s|@CHARON_USER@|$USER|g" \
  -e "s|@REPO_ROOT@|$repo_root|g" \
  -e "s|@ENV_FILE@|$env_file|g" \
  -e "s|@PYTHON@|$python|g" \
  -e "s|@STATE_ROOT@|$state_root|g" \
  -e "s|@MIRROR_ROOT@|$mirror_root|g" \
  -e "s|@BOOTSTRAP_ROOT@|$bootstrap_root|g" \
  "$unit_source" > "$unit_temp"
sudo install -m 0644 "$unit_temp" /etc/systemd/system/pearl-frontier-charon.service
sudo systemctl daemon-reload
sudo systemctl enable --now pearl-frontier-charon.service
systemctl --no-pager --full status pearl-frontier-charon.service
