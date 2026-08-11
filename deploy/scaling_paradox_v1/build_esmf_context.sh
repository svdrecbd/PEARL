#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 GENERATION_REPORT OUTPUT_TAR_ZST [GIT_REF]" >&2
  exit 2
fi

generation_report="$1"
output_archive="$2"
git_ref="${3:-HEAD}"

if [[ ! -s "$generation_report" ]]; then
  echo "generation report is missing or empty: $generation_report" >&2
  exit 2
fi
if [[ -e "$output_archive" ]]; then
  echo "refusing to overwrite existing context archive: $output_archive" >&2
  exit 2
fi
command -v git >/dev/null
command -v tar >/dev/null
command -v zstd >/dev/null
command -v python3 >/dev/null

python3 - "$generation_report" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
report = json.loads(path.read_text(encoding="utf-8"))
if report.get("status") != "complete" or report.get("complete") is not True:
    raise SystemExit("generation report must be complete")
if len(report.get("candidates", [])) != int(report.get("expected_candidate_count", -1)):
    raise SystemExit("generation report candidate count does not match its contract")
PY

context_root="$(mktemp -d /tmp/pearl-esmfold-context.XXXXXX)"
cleanup() {
  case "$context_root" in
    /tmp/pearl-esmfold-context.*) rm -rf -- "$context_root" ;;
    *) echo "refusing to remove unexpected temporary path: $context_root" >&2 ;;
  esac
}
trap cleanup EXIT

mkdir -p "$context_root/input"
git archive --format=tar "$git_ref" | tar -xf - -C "$context_root"
cp "$generation_report" "$context_root/input/generation_report.json"
cp "$context_root/deploy/scaling_paradox_v1/Dockerfile.esmfold" "$context_root/Dockerfile.esmfold"
tar -cf - -C "$context_root" . | zstd -T0 -10 -o "$output_archive"

shasum -a 256 "$output_archive"
