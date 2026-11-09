#!/usr/bin/env python3
"""Stream Tinker sampler archives into a checksum-verified S3 archive set.

The laptop is only a bounded in-memory relay: checkpoint archives are never
written to its disk. Each S3 multipart part carries SHA-256, the completed
object's composite SHA-256 is independently recomputed, and a whole-archive
SHA-256 is retained in the terminal manifest. The script never deletes a
Tinker checkpoint and is safe to rerun at object boundaries.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import tinker


STATE_CONTRACTS = {
    "sampler": "pearl.tinker-sampler-s3-export/1",
    "training": "pearl.tinker-training-s3-export/1",
    "all": "pearl.tinker-checkpoint-s3-export/1",
}
PART_BYTES = 32 * 1024 * 1024
DEFAULT_RANGE_CONCURRENCY = 4
PART_ATTEMPTS = 5


class ExportError(RuntimeError):
    """Raised when an export or verification invariant fails."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_bytes(value: dict[str, Any], omitted: str | None = None) -> bytes:
    payload = value if omitted is None else {k: v for k, v in value.items() if k != omitted}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def canonical_sha256(value: dict[str, Any], omitted: str | None = None) -> str:
    return hashlib.sha256(canonical_bytes(value, omitted)).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def load_inventory(path: Path, checkpoint_type: str) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if value.get("contract") != "pearl.tinker-account-checkpoint-inventory/1":
        raise ExportError("inventory has the wrong contract")
    if value.get("inventory_sha256") != canonical_sha256(value, "inventory_sha256"):
        raise ExportError("inventory SHA-256 mismatch")
    checkpoints = [
        row
        for row in value.get("checkpoints", [])
        if checkpoint_type == "all" or row.get("checkpoint_type") == checkpoint_type
    ]
    if not checkpoints:
        raise ExportError(f"inventory contains no {checkpoint_type} checkpoints")
    paths = [row.get("tinker_path") for row in checkpoints]
    if any(not isinstance(item, str) for item in paths) or len(paths) != len(set(paths)):
        raise ExportError("selected checkpoint paths are missing or duplicate")
    value["selected_checkpoints"] = sorted(
        checkpoints, key=lambda row: (int(row["size_bytes"]), row["tinker_path"])
    )
    return value


def archive_length(url: str) -> int:
    request = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        content_range = response.headers.get("Content-Range")
        if response.status != 206 or not content_range or "/" not in content_range:
            raise ExportError("Tinker archive endpoint did not honor a byte-range request")
        return int(content_range.rsplit("/", 1)[1])


def s3_key(prefix: str, tinker_path: str, checkpoint_type: str) -> str:
    name = hashlib.sha256(tinker_path.encode()).hexdigest()
    directory = "samplers" if checkpoint_type == "sampler" else "training"
    return f"{prefix.rstrip('/')}/{directory}/{name}.tar"


def balanced_shard(
    checkpoints: list[dict[str, Any]], shard_count: int, shard_index: int
) -> list[dict[str, Any]]:
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ExportError("invalid shard count or index")
    bins: list[list[dict[str, Any]]] = [[] for _ in range(shard_count)]
    totals = [0] * shard_count
    for checkpoint in sorted(
        checkpoints, key=lambda row: (-int(row["size_bytes"]), row["tinker_path"])
    ):
        target = min(range(shard_count), key=lambda index: (totals[index], index))
        bins[target].append(checkpoint)
        totals[target] += int(checkpoint["size_bytes"])
    return sorted(bins[shard_index], key=lambda row: (int(row["size_bytes"]), row["tinker_path"]))


def composite_sha256(part_digests: list[bytes]) -> str:
    digest = hashlib.sha256(b"".join(part_digests)).digest()
    return f"{base64.b64encode(digest).decode()}-{len(part_digests)}"


def verify_bucket(s3: Any, bucket: str) -> dict[str, Any]:
    versioning = s3.get_bucket_versioning(Bucket=bucket)
    if versioning.get("Status") != "Enabled":
        raise ExportError("S3 bucket versioning is not enabled")
    encryption = s3.get_bucket_encryption(Bucket=bucket)
    rules = encryption["ServerSideEncryptionConfiguration"]["Rules"]
    algorithms = {
        row["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] for row in rules
    }
    if not algorithms & {"AES256", "aws:kms", "aws:kms:dsse"}:
        raise ExportError("S3 bucket default encryption is not enabled")
    public = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
    if not all(public.values()):
        raise ExportError("S3 bucket Block Public Access is incomplete")
    location = s3.get_bucket_location(Bucket=bucket).get("LocationConstraint") or "us-east-1"
    return {
        "versioning": versioning["Status"],
        "default_encryption_algorithms": sorted(algorithms),
        "block_public_access": public,
        "region": location,
    }


def abort_stale_multipart_uploads(s3: Any, bucket: str, prefix: str) -> int:
    """Abort uploads left by an interrupted prior invocation under this exact prefix."""
    count = 0
    paginator = s3.get_paginator("list_multipart_uploads")
    for upload in paginator.paginate(Bucket=bucket, Prefix=f"{prefix.rstrip('/')}/").search(
        "Uploads[]"
    ):
        if upload is None:
            continue
        s3.abort_multipart_upload(
            Bucket=bucket,
            Key=upload["Key"],
            UploadId=upload["UploadId"],
        )
        count += 1
    return count


def head_verified(s3: Any, bucket: str, entry: dict[str, Any]) -> None:
    head = s3.head_object(
        Bucket=bucket,
        Key=entry["s3_key"],
        VersionId=entry["s3_version_id"],
        ChecksumMode="ENABLED",
    )
    checks = {
        "archive bytes": int(head["ContentLength"]) == int(entry["archive_bytes"]),
        "composite SHA-256": head.get("ChecksumSHA256") == entry["s3_composite_sha256"],
        "encryption": head.get("ServerSideEncryption") in {"AES256", "aws:kms", "aws:kms:dsse"},
        "source identity": head.get("Metadata", {}).get("tinker-path-sha256")
        == hashlib.sha256(entry["tinker_path"].encode()).hexdigest(),
    }
    failures = [name for name, valid in checks.items() if not valid]
    if failures:
        raise ExportError("S3 object verification failed: " + ", ".join(failures))


def transfer_part_once(
    s3: Any,
    bucket: str,
    key: str,
    upload_id: str,
    number: int,
    url: str,
    start: int,
    end: int,
) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(request, timeout=300) as response:
        expected_range = f"bytes {start}-{end}/"
        content_range = response.headers.get("Content-Range", "")
        if response.status != 206 or not content_range.startswith(expected_range):
            raise ExportError(f"Tinker archive returned the wrong range for part {number}")
        body = response.read()
    expected_length = end - start + 1
    if len(body) != expected_length:
        raise ExportError(
            f"Tinker archive part {number} length mismatch: "
            f"expected {expected_length}, got {len(body)}"
        )
    digest = hashlib.sha256(body).digest()
    checksum = base64.b64encode(digest).decode()
    response = s3.upload_part(
        Bucket=bucket,
        Key=key,
        UploadId=upload_id,
        PartNumber=number,
        Body=body,
        ChecksumSHA256=checksum,
    )
    if response.get("ChecksumSHA256") != checksum:
        raise ExportError(f"S3 rejected SHA-256 identity for multipart part {number}")
    return {
        "body": body,
        "digest": digest,
        "part": {
            "ETag": response["ETag"],
            "PartNumber": number,
            "ChecksumSHA256": checksum,
        },
    }


def transfer_part(
    s3: Any,
    bucket: str,
    key: str,
    upload_id: str,
    number: int,
    url: str,
    start: int,
    end: int,
) -> dict[str, Any]:
    last_error: BaseException | None = None
    for attempt in range(1, PART_ATTEMPTS + 1):
        try:
            return transfer_part_once(
                s3, bucket, key, upload_id, number, url, start, end
            )
        except (ExportError, OSError, urllib.error.URLError) as error:
            last_error = error
            if attempt == PART_ATTEMPTS:
                break
            delay = min(2 ** (attempt - 1), 16) + random.random()
            print(
                f"  RETRY part={number} attempt={attempt + 1}/{PART_ATTEMPTS} "
                f"after={delay:.1f}s error={error}",
                flush=True,
            )
            time.sleep(delay)
    raise ExportError(
        f"Tinker archive part {number} failed after {PART_ATTEMPTS} attempts: "
        f"{last_error}"
    )


def upload_archive(
    s3: Any,
    bucket: str,
    key: str,
    tinker_path: str,
    url: str,
    expected_bytes: int,
    progress: dict[str, Any],
    range_concurrency: int,
) -> dict[str, Any]:
    response = s3.create_multipart_upload(
        Bucket=bucket,
        Key=key,
        ChecksumAlgorithm="SHA256",
        ChecksumType="COMPOSITE",
        ServerSideEncryption="AES256",
        StorageClass="STANDARD",
        Metadata={"tinker-path-sha256": hashlib.sha256(tinker_path.encode()).hexdigest()},
    )
    upload_id = response["UploadId"]
    progress.update({"upload_id": upload_id, "s3_key": key, "started_at": utc_now()})
    whole = hashlib.sha256()
    part_digests: list[bytes] = []
    completed: dict[int, dict[str, Any]] = {}
    total = 0
    try:
        part_count = (expected_bytes + PART_BYTES - 1) // PART_BYTES
        with ThreadPoolExecutor(max_workers=range_concurrency) as executor:
            for batch_start in range(1, part_count + 1, range_concurrency):
                futures: dict[Future[dict[str, Any]], int] = {}
                batch_end = min(batch_start + range_concurrency, part_count + 1)
                for number in range(batch_start, batch_end):
                    start = (number - 1) * PART_BYTES
                    end = min(start + PART_BYTES, expected_bytes) - 1
                    future = executor.submit(
                        transfer_part,
                        s3,
                        bucket,
                        key,
                        upload_id,
                        number,
                        url,
                        start,
                        end,
                    )
                    futures[future] = number
                batch: dict[int, dict[str, Any]] = {}
                for future in as_completed(futures):
                    number = futures[future]
                    batch[number] = future.result()
                for number in sorted(batch):
                    result = batch[number]
                    body = result.pop("body")
                    digest = result.pop("digest")
                    total += len(body)
                    whole.update(body)
                    part_digests.append(digest)
                    completed[number] = result["part"]
                print(
                    f"  STREAM bytes={total}/{expected_bytes} "
                    f"percent={100 * total / expected_bytes:.1f}",
                    flush=True,
                )

        if total != expected_bytes:
            raise ExportError(
                f"Tinker archive length mismatch: expected {expected_bytes}, got {total}"
            )
        ordered = [completed[index] for index in sorted(completed)]
        expected_composite = composite_sha256(part_digests)
        result = s3.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": ordered},
            ChecksumSHA256=expected_composite,
            ChecksumType="COMPOSITE",
        )
        if result.get("ChecksumSHA256") != expected_composite:
            raise ExportError("completed S3 object composite SHA-256 mismatch")
        return {
            "archive_bytes": total,
            "archive_sha256": whole.hexdigest(),
            "s3_composite_sha256": expected_composite,
            "s3_etag": result["ETag"],
            "s3_version_id": result["VersionId"],
            "part_count": len(ordered),
        }
    except BaseException:
        s3.abort_multipart_upload(
            Bucket=bucket, Key=key, UploadId=upload_id
        )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument(
        "--checkpoint-type",
        choices=("sampler", "training", "all"),
        default="sampler",
    )
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--max-checkpoints", type=int, default=0)
    parser.add_argument(
        "--range-concurrency", type=int, default=DEFAULT_RANGE_CONCURRENCY
    )
    parser.add_argument(
        "--disable-pyqwest",
        action="store_true",
        help="Use Tinker's standard HTTP transport (required on the EC2 relay)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        api_key = os.environ.get("TINKER_API_KEY")
        if not api_key and not args.dry_run:
            raise ExportError("TINKER_API_KEY is required")
        if not 1 <= args.range_concurrency <= 16:
            raise ExportError("--range-concurrency must be between 1 and 16")
        inventory = load_inventory(args.inventory.resolve(), args.checkpoint_type)
        checkpoints = balanced_shard(
            inventory["selected_checkpoints"], args.shard_count, args.shard_index
        )
        if args.max_checkpoints:
            checkpoints = checkpoints[: args.max_checkpoints]
        plan = {
            "contract": STATE_CONTRACTS[args.checkpoint_type],
            "source_inventory_sha256": inventory["inventory_sha256"],
            "identity": inventory["identity"],
            "checkpoint_type": args.checkpoint_type,
            "bucket": args.bucket,
            "prefix": args.prefix.rstrip("/"),
            "shard_count": args.shard_count,
            "shard_index": args.shard_index,
            "checkpoint_count": len(checkpoints),
            "provider_accounted_bytes": sum(int(row["size_bytes"]) for row in checkpoints),
            "source_checkpoint_deletion_authorized": False,
            "api_key_mutation_authorized": False,
        }
        if args.dry_run:
            print(json.dumps(plan, indent=2, sort_keys=True))
            return 0

        s3 = boto3.client(
            "s3",
            config=Config(
                retries={"total_max_attempts": 8, "mode": "adaptive"},
                connect_timeout=20,
                read_timeout=180,
                max_pool_connections=args.range_concurrency + 2,
            ),
        )
        bucket = verify_bucket(s3, args.bucket)
        service_kwargs: dict[str, Any] = {"api_key": api_key}
        if args.disable_pyqwest:
            service_kwargs["_client_config"] = {
                "pjwt_auth_enabled": True,
                "credential_default_source": "api_key",
                "use_pyqwest_transport": False,
            }
        service = tinker.ServiceClient(**service_kwargs)
        rest = service.create_rest_client()
        identity = rest.whoami().result(timeout=60).model_dump(mode="json")
        if identity != inventory["identity"]:
            raise ExportError("authenticated Tinker identity does not match inventory")

        if args.state.exists():
            state = json.loads(args.state.read_text())
            if "checkpoint_type" not in state:
                if args.checkpoint_type != "sampler":
                    raise ExportError(
                        "legacy state can only resume with sampler checkpoint type"
                    )
                state["checkpoint_type"] = "sampler"
                state["state_sha256"] = canonical_sha256(state, "state_sha256")
                atomic_json(args.state, state)
            if "shard_count" not in state and "shard_index" not in state:
                if plan["shard_count"] != 1 or plan["shard_index"] != 0:
                    raise ExportError("legacy state can only resume as shard 0 of 1")
                state["shard_count"] = 1
                state["shard_index"] = 0
                state["state_sha256"] = canonical_sha256(state, "state_sha256")
                atomic_json(args.state, state)
            for field in (
                "contract",
                "source_inventory_sha256",
                "identity",
                "bucket",
                "prefix",
                "shard_count",
                "shard_index",
                "checkpoint_type",
            ):
                if state.get(field) != plan[field]:
                    raise ExportError(f"existing state {field} mismatch")
        else:
            state = {
                **plan,
                "created_at": utc_now(),
                "bucket_controls": bucket,
                "completed": {},
                "in_progress": {},
                "terminal_valid": False,
            }
            state["state_sha256"] = canonical_sha256(state, "state_sha256")
            atomic_json(args.state, state)

        stale_uploads = abort_stale_multipart_uploads(s3, args.bucket, args.prefix)
        if stale_uploads:
            state["in_progress"] = {}
            state["state_sha256"] = canonical_sha256(state, "state_sha256")
            atomic_json(args.state, state)
            print(f"ABORTED {stale_uploads} stale multipart upload(s)", flush=True)

        for index, checkpoint in enumerate(checkpoints, start=1):
            path = checkpoint["tinker_path"]
            recorded = state["completed"].get(path)
            if recorded is not None:
                head_verified(s3, args.bucket, recorded)
                print(f"[{index}/{len(checkpoints)}] RECORDED {path}", flush=True)
                continue
            key = s3_key(args.prefix, path, checkpoint["checkpoint_type"])
            signed = rest.get_checkpoint_archive_url_from_tinker_path(path).result(timeout=600)
            expected = archive_length(signed.url)
            print(f"[{index}/{len(checkpoints)}] EXPORT {path} bytes={expected}", flush=True)
            progress: dict[str, Any] = {}
            state["in_progress"][path] = progress
            state["state_sha256"] = canonical_sha256(state, "state_sha256")
            atomic_json(args.state, state)
            result = upload_archive(
                s3,
                args.bucket,
                key,
                path,
                signed.url,
                expected,
                progress,
                args.range_concurrency,
            )
            entry = {
                "completed_at": utc_now(),
                "tinker_path": path,
                "checkpoint_id": checkpoint["checkpoint_id"],
                "provider_accounted_bytes": int(checkpoint["size_bytes"]),
                "s3_bucket": args.bucket,
                "s3_key": key,
                **result,
            }
            head_verified(s3, args.bucket, entry)
            state["completed"][path] = entry
            state["in_progress"].pop(path, None)
            state["state_sha256"] = canonical_sha256(state, "state_sha256")
            atomic_json(args.state, state)
            print(
                f"[{index}/{len(checkpoints)}] VERIFIED {key} sha256={entry['archive_sha256']}",
                flush=True,
            )

        state["terminal_valid"] = len(state["completed"]) == len(checkpoints)
        if not state["terminal_valid"]:
            raise ExportError("S3 export did not reach the exact checkpoint count")
        state["completed_at"] = utc_now()
        state["archive_bytes"] = sum(
            int(row["archive_bytes"]) for row in state["completed"].values()
        )
        state["state_sha256"] = canonical_sha256(state, "state_sha256")
        atomic_json(args.state, state)
        manifest_body = json.dumps(state, indent=2, sort_keys=True).encode() + b"\n"
        manifest_key = f"{args.prefix.rstrip('/')}/manifest.json"
        manifest_sha = base64.b64encode(hashlib.sha256(manifest_body).digest()).decode()
        put = s3.put_object(
            Bucket=args.bucket,
            Key=manifest_key,
            Body=manifest_body,
            ChecksumSHA256=manifest_sha,
            ServerSideEncryption="AES256",
            ContentType="application/json",
        )
        if put.get("ChecksumSHA256") != manifest_sha:
            raise ExportError("S3 terminal manifest SHA-256 mismatch")
        print(
            json.dumps(
                {
                    "terminal_valid": True,
                    "checkpoint_count": len(state["completed"]),
                    "archive_bytes": state["archive_bytes"],
                    "manifest": f"s3://{args.bucket}/{manifest_key}",
                    "manifest_version_id": put["VersionId"],
                    "state_sha256": state["state_sha256"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (ExportError, ClientError, OSError, ValueError, KeyError, urllib.error.URLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
