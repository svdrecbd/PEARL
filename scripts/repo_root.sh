#!/usr/bin/env bash

repo_root_from_bash_source() {
  local script_source="${1:-${BASH_SOURCE[0]}}"
  local script_dir
  script_dir="$(cd "$(dirname "$script_source")" && pwd)"
  if git -C "$script_dir" rev-parse --show-toplevel >/dev/null 2>&1; then
    git -C "$script_dir" rev-parse --show-toplevel
    return 0
  fi
  cd "$script_dir/.." && pwd
}
