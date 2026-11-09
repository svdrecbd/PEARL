#!/usr/bin/env python3
"""Independently verify terminal Tinker-to-S3 export state and exact object versions."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


class VerificationError(RuntimeError):
    """Raised when an archive verification invariant does not hold."""


def canonical_sha256(value: dict[str, Any], omitted: str) -> str:
    payload = {key: item for key, item in value.items() if key != omitted}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise VerificationError(f"expected JSON object: {path}")
    return value


def verify_inventory(value: dict[str, Any]) -> None:
    if value.get("contract") != "pearl.tinker-account-checkpoint-inventory/1":
        raise VerificationError("inventory contract mismatch")
    if value.get("inventory_sha256") != canonical_sha256(value, "inventory_sha256"):
        raise VerificationError("inventory SHA-256 mismatch")


def verify_state(value: dict[str, Any], inventory: dict[str, Any]) -> None:
    if value.get("contract") not in {
        "pearl.tinker-sampler-s3-export/1",
        "pearl.tinker-training-s3-export/1",
        "pearl.tinker-checkpoint-s3-export/1",
    }:
        raise VerificationError("state contract mismatch")
    if value.get("state_sha256") != canonical_sha256(value, "state_sha256"):
        raise VerificationError("state SHA-256 mismatch")
    if value.get("terminal_valid") is not True:
        raise VerificationError("state is not terminal-valid")
    if value.get("source_inventory_sha256") != inventory["inventory_sha256"]:
        raise VerificationError("state source inventory mismatch")
    if value.get("identity") != inventory["identity"]:
        raise VerificationError("state identity mismatch")
    if value.get("source_checkpoint_deletion_authorized") is not False:
        raise VerificationError("state unexpectedly authorizes Tinker deletion")
    if value.get("api_key_mutation_authorized") is not False:
        raise VerificationError("state unexpectedly authorizes API-key mutation")


def verify_manifest(s3: Any, bucket: str, state: dict[str, Any]) -> None:
    key = f"{state['prefix'].rstrip('/')}/manifest.json"
    response = s3.get_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
    with response["Body"] as body:
        observed = body.read()
    expected = json.dumps(state, indent=2, sort_keys=True).encode() + b"\n"
    if observed != expected:
        raise VerificationError(f"terminal manifest body mismatch: {key}")
    checksum = base64.b64encode(hashlib.sha256(observed).digest()).decode()
    if response.get("ChecksumSHA256") != checksum:
        raise VerificationError(f"terminal manifest checksum mismatch: {key}")
    if response.get("ServerSideEncryption") not in {"AES256", "aws:kms", "aws:kms:dsse"}:
        raise VerificationError(f"terminal manifest encryption mismatch: {key}")


def verify_entry(s3: Any, bucket: str, entry: dict[str, Any]) -> None:
    response = s3.head_object(
        Bucket=bucket,
        Key=entry["s3_key"],
        VersionId=entry["s3_version_id"],
        ChecksumMode="ENABLED",
    )
    checks = {
        "archive bytes": int(response["ContentLength"]) == int(entry["archive_bytes"]),
        "composite SHA-256": response.get("ChecksumSHA256")
        == entry["s3_composite_sha256"],
        "encryption": response.get("ServerSideEncryption")
        in {"AES256", "aws:kms", "aws:kms:dsse"},
        "source identity": response.get("Metadata", {}).get("tinker-path-sha256")
        == hashlib.sha256(entry["tinker_path"].encode()).hexdigest(),
    }
    failures = [name for name, valid in checks.items() if not valid]
    if failures:
        raise VerificationError(
            f"S3 object verification failed for {entry['s3_key']}: " + ", ".join(failures)
        )


def active_uploads(s3: Any, bucket: str, prefix: str) -> int:
    count = 0
    paginator = s3.get_paginator("list_multipart_uploads")
    for upload in paginator.paginate(Bucket=bucket, Prefix=f"{prefix.rstrip('/')}/").search(
        "Uploads[]"
    ):
        if upload is not None:
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--state", type=Path, action="append", required=True)
    parser.add_argument("--profile")
    args = parser.parse_args()
    try:
        inventory = read_json(args.inventory.resolve())
        verify_inventory(inventory)
        states = [read_json(path.resolve()) for path in args.state]
        for state in states:
            verify_state(state, inventory)

        buckets = {state["bucket"] for state in states}
        if len(buckets) != 1:
            raise VerificationError("states span multiple S3 buckets")
        bucket = next(iter(buckets))
        selected_type = states[0].get("checkpoint_type", "sampler")
        if any(state.get("checkpoint_type", "sampler") != selected_type for state in states):
            raise VerificationError("states span multiple checkpoint selections")
        expected = {
            row["tinker_path"]: row
            for row in inventory["checkpoints"]
            if selected_type == "all" or row["checkpoint_type"] == selected_type
        }
        completed: dict[str, dict[str, Any]] = {}
        for state in states:
            for path, entry in state["completed"].items():
                if path in completed:
                    raise VerificationError(f"duplicate completed checkpoint: {path}")
                completed[path] = entry
        if set(completed) != set(expected):
            raise VerificationError("completed checkpoint set does not match inventory selection")

        session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
        s3 = session.client(
            "s3",
            config=Config(
                retries={"total_max_attempts": 8, "mode": "adaptive"},
                connect_timeout=10,
                read_timeout=120,
                max_pool_connections=8,
            ),
        )
        archive_bytes = 0
        provider_bytes = 0
        for path in sorted(completed):
            entry = completed[path]
            if entry.get("tinker_path") != path:
                raise VerificationError(f"entry path mismatch: {path}")
            if int(entry["provider_accounted_bytes"]) != int(expected[path]["size_bytes"]):
                raise VerificationError(f"provider byte mismatch: {path}")
            verify_entry(s3, bucket, entry)
            archive_bytes += int(entry["archive_bytes"])
            provider_bytes += int(entry["provider_accounted_bytes"])

        for state in states:
            verify_manifest(s3, bucket, state)
            if active_uploads(s3, bucket, state["prefix"]):
                raise VerificationError(f"active multipart upload remains: {state['prefix']}")

        print(
            json.dumps(
                {
                    "terminal_valid": True,
                    "bucket": bucket,
                    "checkpoint_type": selected_type,
                    "checkpoint_count": len(completed),
                    "provider_bytes": provider_bytes,
                    "archive_bytes": archive_bytes,
                    "state_count": len(states),
                    "exact_versions_verified": len(completed),
                    "active_multipart_uploads": 0,
                    "inventory_sha256": inventory["inventory_sha256"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (VerificationError, ClientError, OSError, ValueError, TypeError, KeyError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
