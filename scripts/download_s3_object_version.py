#!/usr/bin/env python3
"""Download one exact S3 object version with concurrent multipart transfers."""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


class Progress:
    def __init__(self, expected_bytes: int) -> None:
        self.expected_bytes = expected_bytes
        self.transferred = 0
        self.last_reported = 0.0
        self.started = time.monotonic()
        self.lock = threading.Lock()

    def __call__(self, byte_count: int) -> None:
        with self.lock:
            self.transferred += byte_count
            now = time.monotonic()
            if now - self.last_reported < 10 and self.transferred < self.expected_bytes:
                return
            elapsed = max(now - self.started, 0.001)
            rate = self.transferred / elapsed / 1_000_000
            percent = self.transferred / self.expected_bytes * 100
            print(
                f"S3_PROGRESS bytes={self.transferred}/{self.expected_bytes} "
                f"percent={percent:.1f} rate_MBps={rate:.1f}",
                flush=True,
            )
            self.last_reported = now


def download(
    bucket: str,
    key: str,
    version_id: str,
    region: str,
    destination: Path,
    expected_bytes: int,
    concurrency: int,
) -> None:
    client = boto3.client(
        "s3",
        region_name=region,
        config=Config(
            retries={"total_max_attempts": 12, "mode": "adaptive"},
            connect_timeout=10,
            read_timeout=120,
            max_pool_connections=max(32, concurrency * 2),
        ),
    )
    metadata = client.head_object(Bucket=bucket, Key=key, VersionId=version_id)
    actual_remote_bytes = int(metadata["ContentLength"])
    if actual_remote_bytes != expected_bytes:
        raise RuntimeError(
            f"remote size mismatch: expected {expected_bytes}, got {actual_remote_bytes}"
        )
    restore = metadata.get("Restore", "")
    if 'ongoing-request="false"' not in restore:
        raise RuntimeError(f"object is not restored: {restore or 'no restore metadata'}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    progress = Progress(expected_bytes)
    transfer = TransferConfig(
        multipart_threshold=32 * 1024 * 1024,
        multipart_chunksize=32 * 1024 * 1024,
        max_concurrency=concurrency,
        max_io_queue=128,
        io_chunksize=1024 * 1024,
        use_threads=True,
    )
    client.download_file(
        bucket,
        key,
        str(destination),
        ExtraArgs={"VersionId": version_id},
        Callback=progress,
        Config=transfer,
    )
    with destination.open("rb") as handle:
        os.fsync(handle.fileno())
    actual_local_bytes = destination.stat().st_size
    if actual_local_bytes != expected_bytes:
        raise RuntimeError(
            f"local size mismatch: expected {expected_bytes}, got {actual_local_bytes}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-bytes", type=int, required=True)
    parser.add_argument("--concurrency", type=int, default=16)
    args = parser.parse_args()
    if args.expected_bytes <= 0 or args.concurrency <= 0:
        parser.error("expected bytes and concurrency must be positive")

    try:
        download(
            bucket=args.bucket,
            key=args.key,
            version_id=args.version_id,
            region=args.region,
            destination=args.destination,
            expected_bytes=args.expected_bytes,
            concurrency=args.concurrency,
        )
    except (BotoCoreError, ClientError, OSError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
