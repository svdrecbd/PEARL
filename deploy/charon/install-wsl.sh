#!/usr/bin/env bash
set -euo pipefail

usb_root="${1:?usage: install-wsl.sh /mnt/<drive>/PEARL_CHARON}"
test -f "$usb_root/SHA256SUMS"
test "$(uname -m)" = "x86_64"
grep -qi microsoft /proc/version

cd "$usb_root"
sha256sum --check --strict SHA256SUMS

sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  ca-certificates curl git gh jq procps python3 python3-pip python3-venv rsync tar

install_root="$HOME/pearl-charon"
repo_root="$install_root/repo"
bootstrap_root="$HOME/.pearl/charon/bootstrap"
state_root="$HOME/.pearl/charon/state"
mirror_root="/mnt/c/PEARL_CHARON_STATE_MIRROR"

test ! -e "$repo_root"
mkdir -p "$install_root" "$bootstrap_root" "$state_root" "$mirror_root" "$HOME/.config/pearl"
git clone "$usb_root/pearl-frontier-charon.bundle" "$repo_root"
git -C "$repo_root" checkout --detach "$(cat "$usb_root/SOURCE_COMMIT")"
test "$(git -C "$repo_root" rev-parse HEAD)" = "$(cat "$usb_root/SOURCE_COMMIT")"

printf '%s  %s\n' "$(cat "$usb_root/DATA_ARCHIVE_SHA256")" \
  "$usb_root/pearl-scaling-paradox-v1-data-v2.tar.gz" | sha256sum --check --strict
tar -xzf "$usb_root/pearl-scaling-paradox-v1-data-v2.tar.gz" -C "$repo_root"
rsync -a --delete "$usb_root/bootstrap/" "$bootstrap_root/"

python3 -m venv "$repo_root/.venv"
"$repo_root/.venv/bin/python" -m pip install --upgrade pip
"$repo_root/.venv/bin/python" -m pip install -r "$repo_root/requirements.txt"
"$repo_root/.venv/bin/python" -m pip install -r "$repo_root/requirements-dev.txt"

mkdir -p "$install_root/bin"
install -m 0755 "$repo_root/deploy/charon/verify-charon.sh" "$install_root/bin/verify-charon.sh"
install -m 0755 "$repo_root/deploy/charon/arm-charon.sh" "$install_root/bin/arm-charon.sh"
install -m 0755 "$repo_root/deploy/charon/status-charon.sh" "$install_root/bin/status-charon.sh"

if [[ ! -f "$HOME/.config/pearl/charon.env" ]]; then
  install -m 0600 /dev/null "$HOME/.config/pearl/charon.env"
fi

echo "Installation complete. Add TINKER_API_KEY to ~/.config/pearl/charon.env, authenticate gh,"
echo "then run ~/pearl-charon/bin/verify-charon.sh."
