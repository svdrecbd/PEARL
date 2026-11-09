#!/usr/bin/env python3
"""Export existing Tinker sampler archives to two verified local copies.

This tool is deliberately read-only with respect to Tinker. It requests signed
download URLs for checkpoints that already have type ``sampler``; it never
creates, converts, or deletes a checkpoint. Downloads are resumable, and a
checkpoint is complete only after both destination copies hash identically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tinker


CHUNK_BYTES = 16 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def save_state(primary: Path, mirror: Path, value: dict[str, Any]) -> None:
    atomic_json(primary, value)
    atomic_json(mirror, value)


def checkpoint_filename(tinker_path: str) -> str:
    return f"{hashlib.sha256(tinker_path.encode()).hexdigest()}.tar"


def archive_length(url: str) -> int:
    request = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        content_range = response.headers.get("Content-Range")
        if response.status != 206 or not content_range or "/" not in content_range:
            raise RuntimeError("sampler archive endpoint did not honor a byte-range request")
        return int(content_range.rsplit("/", 1)[1])


def download_with_resume(url: str, destination: Path, expected_bytes: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing = destination.stat().st_size if destination.exists() else 0
    if existing > expected_bytes:
        raise RuntimeError(f"partial file is larger than source archive: {destination}")
    if existing == expected_bytes:
        return

    headers = {"Range": f"bytes={existing}-"} if existing else {}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=300) as response:
        if existing and response.status != 206:
            raise RuntimeError("sampler archive endpoint refused download resumption")
        mode = "ab" if existing else "xb"
        with destination.open(mode) as output:
            while True:
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())

    actual = destination.stat().st_size
    if actual != expected_bytes:
        raise RuntimeError(
            f"archive length mismatch for {destination}: expected {expected_bytes}, got {actual}"
        )


def copy_verified(source: Path, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.stat().st_size == source.stat().st_size:
            if sha256_file(destination) == expected_sha256:
                return
        raise RuntimeError(f"existing second copy is not the expected archive: {destination}")

    partial = destination.with_name(f"{destination.name}.partial.{os.getpid()}")
    with source.open("rb") as reader, partial.open("xb") as writer:
        shutil.copyfileobj(reader, writer, length=CHUNK_BYTES)
        writer.flush()
        os.fsync(writer.fileno())
    if sha256_file(partial) != expected_sha256:
        raise RuntimeError(f"second-copy checksum mismatch: {partial}")
    os.replace(partial, destination)


def load_inventory(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text())
    checkpoints = value.get("checkpoints") if isinstance(value, dict) else value
    if not isinstance(checkpoints, list):
        raise RuntimeError("inventory must be a checkpoint list or an object containing checkpoints")
    sampler = [row for row in checkpoints if row.get("checkpoint_type") == "sampler"]
    if not sampler:
        raise RuntimeError("inventory contains no sampler checkpoints")
    paths = [row.get("tinker_path") for row in sampler]
    if any(not isinstance(path, str) for path in paths) or len(paths) != len(set(paths)):
        raise RuntimeError("sampler checkpoint paths are missing or non-unique")
    return sorted(sampler, key=lambda row: (int(row.get("size_bytes", 0)), row["tinker_path"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--destination-a", type=Path, required=True)
    parser.add_argument("--destination-b", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--state-mirror", type=Path, required=True)
    parser.add_argument("--max-checkpoints", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    checkpoints = load_inventory(args.inventory)
    if args.max_checkpoints:
        checkpoints = checkpoints[: args.max_checkpoints]
    if args.destination_a.resolve() == args.destination_b.resolve():
        raise RuntimeError("destinations must be distinct")

    plan = {
        "contract": "pearl.tinker-sampler-dual-drive-export/1",
        "created_at": utc_now(),
        "inventory": str(args.inventory.resolve()),
        "checkpoint_count": len(checkpoints),
        "provider_accounted_bytes": sum(int(row.get("size_bytes", 0)) for row in checkpoints),
        "destinations": [str(args.destination_a), str(args.destination_b)],
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return 0

    if "TINKER_API_KEY" not in os.environ:
        raise RuntimeError("TINKER_API_KEY is required")
    for destination in (args.destination_a, args.destination_b):
        destination.mkdir(parents=True, exist_ok=True)
        if not os.access(destination, os.W_OK):
            raise RuntimeError(f"destination is not writable: {destination}")

    state: dict[str, Any]
    if args.state.exists():
        state = json.loads(args.state.read_text())
        if state.get("contract") != plan["contract"]:
            raise RuntimeError("existing state has the wrong contract")
    else:
        state = {**plan, "completed": {}, "failures": []}
        save_state(args.state, args.state_mirror, state)

    rest = tinker.ServiceClient().create_rest_client()
    for index, checkpoint in enumerate(checkpoints, start=1):
        tinker_path = checkpoint["tinker_path"]
        if tinker_path in state["completed"]:
            print(f"[{index}/{len(checkpoints)}] RECORDED {tinker_path}", flush=True)
            continue

        filename = checkpoint_filename(tinker_path)
        final_a = args.destination_a / filename
        final_b = args.destination_b / filename
        partial_a = final_a.with_name(f"{filename}.partial")
        print(f"[{index}/{len(checkpoints)}] EXPORT {tinker_path}", flush=True)
        try:
            signed = rest.get_checkpoint_archive_url_from_tinker_path(tinker_path).result()
            expected_bytes = archive_length(signed.url)
            if final_a.exists():
                if final_a.stat().st_size != expected_bytes:
                    raise RuntimeError(f"existing first copy has the wrong length: {final_a}")
                archive_sha256 = sha256_file(final_a)
            else:
                download_with_resume(signed.url, partial_a, expected_bytes)
                archive_sha256 = sha256_file(partial_a)
                os.replace(partial_a, final_a)
            copy_verified(final_a, final_b, archive_sha256)
            state["completed"][tinker_path] = {
                "completed_at": utc_now(),
                "filename": filename,
                "archive_bytes": expected_bytes,
                "archive_sha256": archive_sha256,
                "provider_accounted_bytes": int(checkpoint.get("size_bytes", 0)),
                "copy_a_verified": True,
                "copy_b_verified": True,
            }
            save_state(args.state, args.state_mirror, state)
            print(f"[{index}/{len(checkpoints)}] VERIFIED {filename}", flush=True)
        except (OSError, RuntimeError, urllib.error.URLError) as error:
            state["failures"].append(
                {"at": utc_now(), "tinker_path": tinker_path, "error": str(error)}
            )
            save_state(args.state, args.state_mirror, state)
            raise

    state["terminal_valid"] = len(state["completed"]) == len(checkpoints)
    state["completed_at"] = utc_now()
    save_state(args.state, args.state_mirror, state)
    print(f"VERIFIED {len(checkpoints)} SAMPLER ARCHIVES ON BOTH DRIVES", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
