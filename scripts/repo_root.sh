#!/usr/bin/env bash

repo_root_from_bash_source() {
  local script_source="${1:-${BASH_SOURCE[0]}}"
  local script_dir
  script_dir="$(cd "$(dirname "$script_source")" && pwd)"
  git -C "$script_dir" rev-parse --show-toplevel
}
