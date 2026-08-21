#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 OUTPUT_TAR_ZST [GIT_REF]" >&2
  exit 2
fi

output_archive="$1"
git_ref="${2:-HEAD}"
if [[ -e "$output_archive" ]]; then
  echo "refusing to overwrite existing context archive: $output_archive" >&2
  exit 2
fi

context_root="$(mktemp -d /tmp/pearl-esmfold2-calibration.XXXXXX)"
cleanup() {
  case "$context_root" in
    /tmp/pearl-esmfold2-calibration.*) rm -rf -- "$context_root" ;;
    *) echo "refusing to remove unexpected temporary path: $context_root" >&2 ;;
  esac
}
trap cleanup EXIT

mkdir -p "$context_root/input"
git archive --format=tar "$git_ref" | tar -xf - -C "$context_root"
printf '{}\n' > "$context_root/input/generation_report.json"
cp "$context_root/deploy/frontier_adaptation_v2/Dockerfile.esmfold2" "$context_root/Dockerfile"
tar -cf - -C "$context_root" . | zstd -T0 -10 -o "$output_archive"
shasum -a 256 "$output_archive"
