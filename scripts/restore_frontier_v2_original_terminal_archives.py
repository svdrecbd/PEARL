#!/usr/bin/env python3
"""Fail-closed restore of the 48 archived frontier-v2 original terminal adapters."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BUCKET = "pearl-checkpoint-archive-20260821-archivebucket-5dacidqdlmoc"
MANIFEST_SHA256 = "3cfa20ddd971bcd9b461315e44dfcfda91377108b1761a932959bff1e76d6062"
CAMPAIGN_ID = "pearl-frontier-adaptation-v2-original"
EXPECTED_COUNT = 48
EXPECTED_SIZE_BYTES = 513_911_255_040
RESTORE_DAYS = 3
RESTORE_TIER = "Standard"
COST_CEILING_USD = Decimal("12.00")
PRICE_LIST_URL = (
    "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/"
    "AmazonS3/current/us-west-2/index.json"
)
PRICE_LIST_VERSION = "20260818181113"
PRICE_LIST_PUBLICATION = "2026-08-18T18:11:13Z"
STANDARD_RETRIEVAL_PER_GB_USD = Decimal("0.0200000000")
STANDARD_RESTORE_REQUEST_USD = Decimal("0.0000500000")
RESTORED_COPY_PER_GB_MONTH_USD = Decimal("0.0210000000")
CONTROL_MANIFEST_KEY = f"control/{MANIFEST_SHA256}/manifest.json"
COMPLETION_RECEIPT_KEY = f"receipts/{MANIFEST_SHA256}/completion.json"
EXPECTED_COMPLETION_SHA256 = (
    "40849b522e491ca03161aff425261f24f2eafd5b68579d1660819def8e05a106"
)
REPORT_DIR = ROOT / "reports" / "frontier_adaptation_v2_s3_restore_20260823"
APPROVAL_PACKET_PATH = REPORT_DIR / "approval_packet.json"
SUBMISSION_RECEIPT_PATH = REPORT_DIR / "submission_receipt.json"


class RestoreError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def archive_receipt_sha256(value: dict[str, Any], field: str) -> str:
    unsigned = {key: item for key, item in value.items() if key != field}
    encoded = (json.dumps(unsigned, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def self_hash(value: dict[str, Any], field: str) -> str:
    return canonical_sha256({key: item for key, item in value.items() if key != field})


def run_aws(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["aws", *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown AWS CLI error"
        raise RestoreError(f"AWS command failed: {message}")
    return result


def get_standard_json(
    key: str, *, expected_object_sha256: str | None = None
) -> dict[str, Any]:
    result = run_aws(
        [
            "s3",
            "cp",
            f"s3://{BUCKET}/{key}",
            "-",
            "--no-progress",
        ]
    )
    if expected_object_sha256 is not None:
        observed_sha256 = hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()
        if observed_sha256 != expected_object_sha256:
            raise RestoreError(
                f"S3 object SHA256 mismatch for {key}: "
                f"expected {expected_object_sha256}, observed {observed_sha256}"
            )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RestoreError(f"S3 object is not valid JSON: {key}") from error
    if not isinstance(value, dict):
        raise RestoreError(f"S3 object is not a JSON object: {key}")
    return value


def expected_archive_key(checkpoint: dict[str, Any]) -> str:
    return (
        f"archives/{MANIFEST_SHA256}/{CAMPAIGN_ID}/{checkpoint['run_key']}/terminal/"
        f"{checkpoint['source_path_sha256']}.tar"
    )


def validate_completion_receipt(receipt: dict[str, Any]) -> None:
    if receipt.get("contract") != "pearl.aws-checkpoint-archive-completion/1":
        raise RestoreError("archive completion receipt has the wrong contract")
    if receipt.get("manifest_sha256") != MANIFEST_SHA256:
        raise RestoreError("archive completion receipt has the wrong manifest")
    if receipt.get("completion_sha256") != EXPECTED_COMPLETION_SHA256:
        raise RestoreError("archive completion receipt hash changed")
    if archive_receipt_sha256(receipt, "completion_sha256") != EXPECTED_COMPLETION_SHA256:
        raise RestoreError("archive completion receipt self-hash mismatch")
    if not receipt.get("terminal_valid") or receipt.get("failures") != []:
        raise RestoreError("archive completion receipt is not terminal-valid")
    if receipt.get("completed_checkpoint_count") != 276:
        raise RestoreError("archive completion receipt does not cover 276 checkpoints")


def validate_object_receipt(
    checkpoint: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    source_hash = checkpoint["source_path_sha256"]
    if receipt.get("contract") != "pearl.aws-checkpoint-archive-receipt/1":
        raise RestoreError(f"wrong object receipt contract for {source_hash}")
    if receipt.get("manifest_sha256") != MANIFEST_SHA256:
        raise RestoreError(f"wrong manifest in object receipt {source_hash}")
    supplied_receipt_hash = receipt.get("receipt_sha256")
    if supplied_receipt_hash != archive_receipt_sha256(receipt, "receipt_sha256"):
        raise RestoreError(f"object receipt self-hash mismatch for {source_hash}")
    source = receipt.get("source")
    archive = receipt.get("archive_object")
    if not isinstance(source, dict) or not isinstance(archive, dict):
        raise RestoreError(f"object receipt is incomplete for {source_hash}")
    if source != checkpoint:
        raise RestoreError(f"object receipt source mismatch for {source_hash}")
    if archive.get("bucket") != BUCKET:
        raise RestoreError(f"object receipt bucket mismatch for {source_hash}")
    if archive.get("key") != expected_archive_key(checkpoint):
        raise RestoreError(f"object receipt key mismatch for {source_hash}")
    if archive.get("storage_class") != "DEEP_ARCHIVE":
        raise RestoreError(f"object receipt storage-class mismatch for {source_hash}")
    if archive.get("checksum_algorithm") != "SHA256":
        raise RestoreError(f"object receipt lacks SHA256 for {source_hash}")
    if archive.get("checksum_type") != "COMPOSITE":
        raise RestoreError(f"object receipt checksum type mismatch for {source_hash}")
    if not archive.get("version_id") or not archive.get("whole_archive_sha256"):
        raise RestoreError(f"object receipt lacks immutable identity for {source_hash}")
    return {
        "run_key": checkpoint["run_key"],
        "source_path_sha256": source_hash,
        "object_receipt_sha256": supplied_receipt_hash,
        "key": archive["key"],
        "version_id": archive["version_id"],
        "size_bytes": archive["size_bytes"],
        "checksum_sha256": archive["checksum_sha256"],
        "whole_archive_sha256": archive["whole_archive_sha256"],
    }


def head_archive(row: dict[str, Any]) -> dict[str, Any]:
    result = run_aws(
        [
            "s3api",
            "head-object",
            "--bucket",
            BUCKET,
            "--key",
            row["key"],
            "--version-id",
            row["version_id"],
            "--checksum-mode",
            "ENABLED",
            "--output",
            "json",
        ]
    )
    try:
        head = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RestoreError(f"invalid HeadObject response for {row['key']}") from error
    expected_metadata = {
        "campaign-id": CAMPAIGN_ID,
        "manifest-sha256": MANIFEST_SHA256,
        "run-key": row["run_key"],
        "source-path-sha256": row["source_path_sha256"],
        "sampler-export-size-bytes": str(row["size_bytes"]),
    }
    checks = {
        "ContentLength": row["size_bytes"],
        "ChecksumSHA256": row["checksum_sha256"],
        "ChecksumType": "COMPOSITE",
        "VersionId": row["version_id"],
        "StorageClass": "DEEP_ARCHIVE",
        "ServerSideEncryption": "AES256",
    }
    for field, expected in checks.items():
        if head.get(field) != expected:
            raise RestoreError(
                f"HeadObject {field} mismatch for {row['source_path_sha256']}"
            )
    metadata = head.get("Metadata") or {}
    for field, expected in expected_metadata.items():
        if metadata.get(field) != expected:
            raise RestoreError(
                f"HeadObject metadata {field} mismatch for {row['source_path_sha256']}"
            )
    restore = head.get("Restore")
    if restore is None:
        restore_state = "cold"
    elif 'ongoing-request="true"' in restore:
        restore_state = "in_progress"
    elif 'ongoing-request="false"' in restore:
        restore_state = "restored"
    else:
        raise RestoreError(f"unrecognized restore state for {row['source_path_sha256']}")
    return {**row, "restore": restore, "restore_state": restore_state}


def audit_inventory() -> list[dict[str, Any]]:
    completion = get_standard_json(COMPLETION_RECEIPT_KEY)
    validate_completion_receipt(completion)
    manifest = get_standard_json(
        CONTROL_MANIFEST_KEY, expected_object_sha256=MANIFEST_SHA256
    )
    if manifest.get("manifest_content_sha256") != archive_receipt_sha256(
        manifest, "manifest_content_sha256"
    ):
        raise RestoreError("control manifest internal content hash mismatch")
    checkpoints = [
        row
        for row in manifest.get("checkpoints", [])
        if row.get("campaign_id") == CAMPAIGN_ID and row.get("terminal") is True
    ]
    checkpoints.sort(key=lambda row: row["run_key"])
    if len(checkpoints) != EXPECTED_COUNT:
        raise RestoreError(
            f"expected {EXPECTED_COUNT} original terminal checkpoints, found {len(checkpoints)}"
        )
    receipt_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {
            executor.submit(
                get_standard_json,
                f"receipts/{MANIFEST_SHA256}/objects/{checkpoint['source_path_sha256']}.json",
            ): checkpoint
            for checkpoint in checkpoints
        }
        for future in as_completed(futures):
            checkpoint = futures[future]
            receipt_rows.append(validate_object_receipt(checkpoint, future.result()))
    receipt_rows.sort(key=lambda row: row["run_key"])
    if len({row["key"] for row in receipt_rows}) != EXPECTED_COUNT:
        raise RestoreError("archive object keys are not unique")
    if len({row["version_id"] for row in receipt_rows}) != EXPECTED_COUNT:
        raise RestoreError("archive object version IDs are not unique")
    if sum(row["size_bytes"] for row in receipt_rows) != EXPECTED_SIZE_BYTES:
        raise RestoreError("terminal archive byte total mismatch")
    audited: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(head_archive, row): row for row in receipt_rows}
        for future in as_completed(futures):
            audited.append(future.result())
    audited.sort(key=lambda row: row["run_key"])
    return audited


def cost_projection() -> dict[str, Any]:
    decimal_gb = Decimal(EXPECTED_SIZE_BYTES) / Decimal(1_000_000_000)
    retrieval = decimal_gb * STANDARD_RETRIEVAL_PER_GB_USD
    requests = Decimal(EXPECTED_COUNT) * STANDARD_RESTORE_REQUEST_USD
    restored_copy = (
        decimal_gb
        * RESTORED_COPY_PER_GB_MONTH_USD
        * Decimal(RESTORE_DAYS)
        / Decimal(30)
    )
    total = retrieval + requests + restored_copy
    if total > COST_CEILING_USD:
        raise RestoreError("projected restore cost exceeds the hard ceiling")
    return {
        "currency": "USD",
        "decimal_gb": str(decimal_gb),
        "standard_retrieval": str(retrieval.quantize(Decimal("0.000001"))),
        "restore_requests": str(requests.quantize(Decimal("0.000001"))),
        "three_day_restored_copy": str(restored_copy.quantize(Decimal("0.000001"))),
        "projected_total": str(total.quantize(Decimal("0.000001"))),
        "hard_ceiling": str(COST_CEILING_USD),
        "not_included": [
            "taxes",
            "future data transfer or compute",
            "GET, LIST, and HeadObject requests used for verification",
        ],
        "price_basis": {
            "url": PRICE_LIST_URL,
            "version": PRICE_LIST_VERSION,
            "publication_date": PRICE_LIST_PUBLICATION,
            "standard_retrieval_per_gb": str(STANDARD_RETRIEVAL_PER_GB_USD),
            "standard_restore_request": str(STANDARD_RESTORE_REQUEST_USD),
            "restored_copy_per_gb_month": str(RESTORED_COPY_PER_GB_MONTH_USD),
            "month_days_assumption": 30,
        },
    }


def build_approval_packet(inventory: list[dict[str, Any]]) -> dict[str, Any]:
    state_counts = {
        state: sum(row["restore_state"] == state for row in inventory)
        for state in ("cold", "in_progress", "restored")
    }
    packet = {
        "contract": "pearl.frontier-v2-original-terminal-s3-restore-approval/1",
        "created_at": utc_now(),
        "scope": "restore_exact_48_original_terminal_sampler_archives",
        "bucket": BUCKET,
        "region": "us-west-2",
        "manifest_sha256": MANIFEST_SHA256,
        "completion_receipt_sha256": EXPECTED_COMPLETION_SHA256,
        "campaign_id": CAMPAIGN_ID,
        "restore_request": {
            "days": RESTORE_DAYS,
            "tier": RESTORE_TIER,
        },
        "expected_object_count": EXPECTED_COUNT,
        "expected_size_bytes": EXPECTED_SIZE_BYTES,
        "inventory_sha256": canonical_sha256(inventory),
        "inventory": inventory,
        "preflight_restore_state_counts": state_counts,
        "cost_projection": cost_projection(),
        "hard_stops": [
            "any archive manifest, completion receipt, or object receipt hash mismatch",
            "any key, version, size, checksum, encryption, metadata, or storage-class mismatch",
            "any object outside the exact original terminal 48-object set",
            "any projected cost above 12.00 USD",
            "any source deletion, Tinker API access, candidate generation, or scientific inspection",
        ],
        "scientific_boundary": {
            "storage_only": True,
            "source_checkpoint_deletion_authorized": False,
            "tinker_api_access_authorized": False,
            "candidate_generation_authorized": False,
            "scientific_values_inspected": False,
        },
    }
    packet["approval_packet_sha256"] = canonical_sha256(packet)
    return packet


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_and_validate_approval(path: Path) -> dict[str, Any]:
    packet = json.loads(path.read_text(encoding="utf-8"))
    if packet.get("contract") != "pearl.frontier-v2-original-terminal-s3-restore-approval/1":
        raise RestoreError("wrong restore approval contract")
    if packet.get("approval_packet_sha256") != self_hash(
        packet, "approval_packet_sha256"
    ):
        raise RestoreError("restore approval packet self-hash mismatch")
    if Decimal(packet["cost_projection"]["projected_total"]) > COST_CEILING_USD:
        raise RestoreError("restore approval packet exceeds cost ceiling")
    return packet


def submit_restore(row: dict[str, Any]) -> dict[str, Any]:
    if row["restore_state"] != "cold":
        return {
            "key": row["key"],
            "version_id": row["version_id"],
            "action": f"already_{row['restore_state']}",
            "returncode": 0,
        }
    request = json.dumps(
        {"Days": RESTORE_DAYS, "GlacierJobParameters": {"Tier": RESTORE_TIER}},
        separators=(",", ":"),
    )
    result = run_aws(
        [
            "s3api",
            "restore-object",
            "--bucket",
            BUCKET,
            "--key",
            row["key"],
            "--version-id",
            row["version_id"],
            "--restore-request",
            request,
        ],
        check=False,
    )
    return {
        "key": row["key"],
        "version_id": row["version_id"],
        "action": "submitted" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stderr": result.stderr.strip(),
    }


def execute_restore(approval_path: Path) -> dict[str, Any]:
    approval = load_and_validate_approval(approval_path)
    before = audit_inventory()
    if canonical_sha256(before) != approval.get("inventory_sha256"):
        raise RestoreError("live inventory changed after approval packet creation")
    submissions: list[dict[str, Any]] = []
    for row in before:
        submission = submit_restore(row)
        submissions.append(submission)
        if submission["action"] == "failed":
            break
    failures = [row for row in submissions if row["action"] == "failed"]
    after = audit_inventory()
    state_counts = {
        state: sum(row["restore_state"] == state for row in after)
        for state in ("cold", "in_progress", "restored")
    }
    terminal_valid = not failures and state_counts["cold"] == 0 and len(submissions) == EXPECTED_COUNT
    receipt = {
        "contract": "pearl.frontier-v2-original-terminal-s3-restore-submission/1",
        "submitted_at": utc_now(),
        "approval_packet_sha256": approval["approval_packet_sha256"],
        "bucket": BUCKET,
        "manifest_sha256": MANIFEST_SHA256,
        "restore_request": approval["restore_request"],
        "expected_object_count": EXPECTED_COUNT,
        "expected_size_bytes": EXPECTED_SIZE_BYTES,
        "submissions": submissions,
        "post_submission_restore_state_counts": state_counts,
        "post_submission_inventory_sha256": canonical_sha256(after),
        "failures": failures,
        "terminal_valid": terminal_valid,
        "scientific_boundary": approval["scientific_boundary"],
    }
    receipt["submission_receipt_sha256"] = canonical_sha256(receipt)
    write_json(SUBMISSION_RECEIPT_PATH, receipt)
    if not terminal_valid:
        raise RestoreError(
            f"restore submission was not terminal-valid; receipt: {SUBMISSION_RECEIPT_PATH}"
        )
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--submit", action="store_true")
    parser.add_argument("--approval-packet", type=Path, default=APPROVAL_PACKET_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.prepare:
            inventory = audit_inventory()
            packet = build_approval_packet(inventory)
            write_json(APPROVAL_PACKET_PATH, packet)
            print(json.dumps(packet, indent=2, sort_keys=True))
        else:
            receipt = execute_restore(args.approval_packet)
            print(json.dumps(receipt, indent=2, sort_keys=True))
    except (RestoreError, OSError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
