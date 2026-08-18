#!/usr/bin/env bash
set -euo pipefail

install_root="$HOME/pearl-charon"
repo_root="$install_root/repo"
bootstrap_root="$HOME/.pearl/charon/bootstrap"
env_file="$HOME/.config/pearl/charon.env"

test "$(uname -m)" = "x86_64"
grep -qi microsoft /proc/version
systemctl is-system-running >/dev/null || test "$(systemctl is-system-running)" = "degraded"
test -f "$env_file"
chmod 600 "$env_file"
set -a
# The per-user credential file is intentionally outside the bundle.
# shellcheck disable=SC1090
source "$env_file"
set +a
test -n "${TINKER_API_KEY:-}"
gh auth status
test "$(git -C "$repo_root" status --porcelain --untracked-files=no)" = ""
test "$(git -C "$repo_root" rev-parse HEAD)" = "$(jq -r .source_commit "$bootstrap_root/charon_bootstrap.json")"
test "$(df --output=avail -B1 "$repo_root" | tail -n1)" -ge $((20 * 1024 * 1024 * 1024))

"$repo_root/.venv/bin/python" -m pytest -q \
  "$repo_root/tests/test_frontier_charon_replication.py" \
  "$repo_root/tests/test_frontier_original_completion.py" \
  "$repo_root/tests/test_frontier_adaptation_v2.py"

TINKER_RUN_LIST_LIMIT=1000 "$repo_root/.venv/bin/tinker" -f json run list --limit=1000 \
  | jq -e '.runs | type == "array"' >/dev/null

echo "Charon read-only verification passed. No paid work was launched."
