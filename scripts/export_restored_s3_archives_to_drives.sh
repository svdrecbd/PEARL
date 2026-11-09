#!/bin/zsh
set -euo pipefail
setopt NULL_GLOB

# Copy the exact restored AWS archive set to two local drives, verifying the
# manifest SHA-256 after every download and every mirror copy. Safe to rerun.

packet=${1:-/Volumes/PEARL_A/PEARL_ARCHIVE/manifests/aws_original_terminal_48_approval_packet.json}
destination_a=${2:-/Volumes/PEARL_A/PEARL_ARCHIVE/aws_original_terminal_48}
destination_b=${3:-/Volumes/PEARL_B/PEARL_ARCHIVE/aws_original_terminal_48}
log_path=${4:-/Volumes/PEARL_A/PEARL_ARCHIVE/logs/aws_original_terminal_48_transfer.log}

export COPYFILE_DISABLE=1
mkdir -p "$destination_a" "$destination_b" "${log_path:h}"

bucket=$(jq -er '.bucket' "$packet")
region=$(jq -er '.region' "$packet")
expected_count=$(jq -er '.expected_object_count' "$packet")
expected_bytes=$(jq -er '.expected_size_bytes' "$packet")
repo_root=${0:a:h:h}
aws_python=/tmp/pearl-runtime-py312.WoMhEt/venv/bin/python
[[ -x "$aws_python" ]] || { print -u2 "missing AWS Python runtime: $aws_python"; exit 1; }

log() {
  print -r -- "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$log_path"
}

verify_or_adopt() {
  local final=$1 expected_size=$2 expected_sha=$3 candidate actual_size actual_sha
  if [[ -f "$final" ]]; then
    actual_size=$(stat -f %z "$final")
    [[ "$actual_size" == "$expected_size" ]] || return 1
    actual_sha=$(shasum -a 256 "$final" | awk '{print $1}')
    [[ "$actual_sha" == "$expected_sha" ]]
    return
  fi

  for candidate in "$final".partial.* "$final".partial; do
    [[ -f "$candidate" ]] || continue
    actual_size=$(stat -f %z "$candidate")
    [[ "$actual_size" == "$expected_size" ]] || continue
    actual_sha=$(shasum -a 256 "$candidate" | awk '{print $1}')
    if [[ "$actual_sha" == "$expected_sha" ]]; then
      mv "$candidate" "$final"
      return 0
    fi
  done
  return 1
}

completed=0
completed_bytes=0
while IFS=$'\t' read -r size sha version key; do
  filename=${key:t}
  final_a="$destination_a/$filename"
  final_b="$destination_b/$filename"

  if ! verify_or_adopt "$final_a" "$size" "$sha"; then
    temporary_a="$final_a.partial.$$"
    log "DOWNLOAD $((completed + 1))/$expected_count $filename bytes=$size"
    "$aws_python" "$repo_root/scripts/download_s3_object_version.py" \
      --bucket "$bucket" \
      --key "$key" \
      --version-id "$version" \
      --region "$region" \
      --destination "$temporary_a" \
      --expected-bytes "$size" \
      --concurrency 16 \
      2>&1 | tee -a "$log_path"
    actual_size=$(stat -f %z "$temporary_a")
    [[ "$actual_size" == "$size" ]] || { log "FAIL size A $filename expected=$size actual=$actual_size"; exit 1; }
    actual_sha=$(shasum -a 256 "$temporary_a" | awk '{print $1}')
    [[ "$actual_sha" == "$sha" ]] || { log "FAIL sha256 A $filename"; exit 1; }
    mv "$temporary_a" "$final_a"
  fi

  if ! verify_or_adopt "$final_b" "$size" "$sha"; then
    temporary_b="$final_b.partial.$$"
    log "MIRROR $((completed + 1))/$expected_count $filename bytes=$size"
    cp -p "$final_a" "$temporary_b"
    actual_size=$(stat -f %z "$temporary_b")
    [[ "$actual_size" == "$size" ]] || { log "FAIL size B $filename expected=$size actual=$actual_size"; exit 1; }
    actual_sha=$(shasum -a 256 "$temporary_b" | awk '{print $1}')
    [[ "$actual_sha" == "$sha" ]] || { log "FAIL sha256 B $filename"; exit 1; }
    mv "$temporary_b" "$final_b"
  fi

  completed=$((completed + 1))
  completed_bytes=$((completed_bytes + size))
  log "VERIFIED $completed/$expected_count bytes=$completed_bytes/$expected_bytes $filename"
done < <(jq -r '.inventory | sort_by(.size_bytes, .key)[] | [.size_bytes, .whole_archive_sha256, .version_id, .key] | @tsv' "$packet")

[[ "$completed" == "$expected_count" ]] || { log "FAIL count expected=$expected_count actual=$completed"; exit 1; }
[[ "$completed_bytes" == "$expected_bytes" ]] || { log "FAIL bytes expected=$expected_bytes actual=$completed_bytes"; exit 1; }
log "COMPLETE objects=$completed bytes=$completed_bytes dual_drive_verified=true"

if [[ "${PEARL_STOP_AFTER_AWS:-0}" == "1" ]]; then
  log "STOP requested_after_aws=true"
  exit 0
fi

# Continue directly into the read-only Tinker sampler evacuation. The repo env
# supplies the API credential without recording it in logs or on the drives.
set -a
source "$repo_root/.env"
set +a
runtime_python=/tmp/pearl-runtime-py312.WoMhEt/venv/bin/python
[[ -x "$runtime_python" ]] || { log "FAIL missing Tinker Python runtime"; exit 1; }
[[ -n "${TINKER_API_KEY:-}" ]] || { log "FAIL TINKER_API_KEY unavailable"; exit 1; }

log "START Tinker existing-sampler dual-drive export"
"$runtime_python" "$repo_root/scripts/export_tinker_sampler_archives_to_drives.py" \
  --inventory /Volumes/PEARL_A/PEARL_ARCHIVE/manifests/tinker_checkpoint_inventory_20260824.json \
  --destination-a /Volumes/PEARL_A/PEARL_ARCHIVE/tinker_exports \
  --destination-b /Volumes/PEARL_B/PEARL_ARCHIVE/tinker_exports \
  --state /Volumes/PEARL_A/PEARL_ARCHIVE/manifests/tinker_sampler_export_state.json \
  --state-mirror /Volumes/PEARL_B/PEARL_ARCHIVE/manifests/tinker_sampler_export_state.json \
  2>&1 | tee -a /Volumes/PEARL_A/PEARL_ARCHIVE/logs/tinker_sampler_export.log
log "COMPLETE Tinker existing-sampler dual-drive export"
