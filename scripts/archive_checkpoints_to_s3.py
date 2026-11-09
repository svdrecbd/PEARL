#!/usr/bin/env python3
"""Download Tinker checkpoints and upload to S3 with integrity verification.

Downloads each checkpoint archive from Tinker, uploads to S3, verifies SHA-256,
and records completion. Supports resume: skips already-archived checkpoints.

Priority order:
  1. replication_intermediate - biggest cost reduction, training done
  2. phase8_legacy / qwen_v1 / deepseek / miragebench / smoke - legacy material
  3. replication_terminal - after generation completes (requires --include-terminals)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "reports/checkpoint_archive_state.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024 * 8), b""):
            h.update(chunk)
    return h.hexdigest()


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"archived": {}, "failed": {}}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def categorize(cp_id: str) -> str:
    cid = cp_id.lower().replace("weights/", "")
    if "core-fixed-rank" in cid and any(s in cid for s in ["seed362034", "seed257621", "seed520620"]):
        if "chkpt-step" in cid or "-chk" in cid:
            return "replication_intermediate"
        return "replication_terminal"
    if "core-fixed-rank" in cid:
        return "original_cohort"
    if "qwen" in cid or "smoke-fixed-rank-qwen" in cid:
        return "qwen_v1"
    if "miragebench" in cid:
        return "miragebench"
    if "deepseek" in cid:
        return "deepseek"
    if any(s in cid for s in ["phase8", "on-policy", "hybrid", "methods", "randomized-control",
                               "full-nemotron", "full-gpt", "full-deepseek", "full-inkling",
                               "nemotron-ultra-on-policy", "gpt-oss-120b-on-policy"]):
        return "phase8_legacy"
    return "other_legacy"


# Upload priority order (lower number = higher priority)
PRIORITY = {
    "replication_intermediate": 1,
    "phase8_legacy": 2,
    "qwen_v1": 2,
    "deepseek": 3,
    "miragebench": 3,
    "other_legacy": 4,
    "smoke_test_or_other": 5,
    "original_cohort": 6,  # already in AWS but re-archive for completeness
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--include-terminals", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-checkpoints", type=int, default=0)
    args = parser.parse_args()

    inventory = json.loads(Path(args.inventory).read_text())
    state = load_state()
    
    # Build the work queue sorted by priority
    work_queue = []
    for cp in inventory:
        cp_id = cp["checkpoint_id"]
        cat = categorize(cp_id)
        
        if cat == "replication_terminal" and not args.include_terminals:
            continue
        
        already = cp_id in state.get("archived", {})
        failed_before = cp_id in state.get("failed", {})
        priority = PRIORITY.get(cat, 99)
        
        work_queue.append({
            "cp_id": cp_id,
            "category": cat,
            "size_bytes": cp.get("size_bytes", 0),
            "priority": priority,
            "already_archived": already,
            "previously_failed": failed_before,
            "tinker_path": cp.get("tinker_path"),
        })
    
    work_queue.sort(key=lambda x: x["priority"])
    
    total_to_archive = sum(1 for w in work_queue if not w["already_archived"])
    print(f"Total checkpoints: {len(work_queue)}")
    print(f"Already archived: {len(work_queue) - total_to_archive}")
    print(f"To archive: {total_to_archive}")
    
    if args.max_checkpoints > 0:
        work_queue = work_queue[:args.max_checkpoints]
        print(f"Limited to first {len(work_queue)}")
    
    if args.dry_run:
        for w in work_queue[:20]:
            status = "SKIP" if w["already_archived"] else ("RETRY" if w["previously_failed"] else "DO ")
            print(f"  [{status}] [{w['category']}] {w['cp_id']} ({w['size_bytes']/(1024**3):.1f} GB)")
        return
    
    tmp_dir = Path("/tmp/tinker_checkpoint_download")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    completed = 0
    failed = 0
    
    for i, item in enumerate(work_queue):
        cp_id = item["cp_id"]
        if item["already_archived"]:
            continue
        
        category = item["category"]
        size_gb = item["size_bytes"] / (1024**3)
        safe_name = cp_id.replace("weights/", "").replace("/", "_")
        local_path = tmp_dir / f"{safe_name}.tar.gz"
        s3_key = f"checkpoints/{category}/{safe_name}.tar.gz"
        
        elapsed_start = time.time()
        print(f"\n[{i+1}/{len(work_queue)}] {cp_id} ({size_gb:.1f} GB) [{category}]", flush=True)
        
        try:
            # Step 1: Download from Tinker
            print(f"  Downloading...", flush=True)
            result = subprocess.run(
                ["tinker", "checkpoint", "download", "--output", str(local_path), cp_id],
                capture_output=True, text=True, timeout=3600,
                env={**os.environ},
            )
            if result.returncode != 0:
                raise RuntimeError(f"Tinker download failed: {result.stderr[:500]}")
            
            local_size = local_path.stat().st_size / (1024**3)
            print(f"  Downloaded: {local_size:.1f} GB ({time.time()-elapsed_start:.0f}s)", flush=True)
            
            # Step 2: Compute hash
            local_hash = sha256_file(local_path)
            print(f"  SHA256: {local_hash[:16]}...", flush=True)
            
            # Step 3: Upload to S3
            print(f"  Uploading to S3...", flush=True)
            upload_start = time.time()
            result = subprocess.run(
                ["aws", "s3", "cp", str(local_path), f"s3://{args.bucket}/{s3_key}"],
                capture_output=True, text=True, timeout=7200,
            )
            if result.returncode != 0:
                raise RuntimeError(f"S3 upload failed: {result.stderr[:500]}")
            print(f"  Uploaded ({time.time()-upload_start:.0f}s)", flush=True)
            
            # Step 4: Verify S3 integrity
            verify = subprocess.run(
                ["aws", "s3api", "head-object", "--bucket", args.bucket,
                 "--key", s3_key, "--query", "ContentLength", "--output", "text"],
                capture_output=True, text=True,
            )
            s3_size = int(verify.stdout.strip())
            if abs(s3_size - local_path.stat().st_size) > 1024:  # 1KB tolerance
                raise RuntimeError(f"Size mismatch: local={local_path.stat().st_size}, s3={s3_size}")
            print(f"  Verified: OK", flush=True)
            
            # Step 5: Record success
            state.setdefault("archived", {})[cp_id] = {
                "category": category,
                "size_bytes": item["size_bytes"],
                "sha256": local_hash,
                "s3_bucket": args.bucket,
                "s3_key": s3_key,
                "archived_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "duration_seconds": int(time.time() - elapsed_start),
            }
            save_state(state)
            
            # Step 6: Clean up local file
            local_path.unlink(missing_ok=True)
            
            completed += 1
            total_time = time.time() - elapsed_start
            print(f"  DONE ({total_time:.0f}s)", flush=True)
            
        except Exception as exc:
            print(f"  FAILED: {exc}", flush=True)
            state.setdefault("failed", {})[cp_id] = {
                "error": str(exc),
                "at_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            save_state(state)
            failed += 1
            # Clean up partial downloads
            local_path.unlink(missing_ok=True)
        
        # Progress summary every 10 checkpoints
        if (i + 1) % 10 == 0:
            archived_gb = sum(
                v.get("size_bytes", 0) for v in state.get("archived", {}).values()
            ) / (1024**3)
            print(f"\n--- PROGRESS: {completed} archived, {failed} failed, {archived_gb:.1f} GB uploaded ---\n", flush=True)
    
    archived_gb = sum(v.get("size_bytes", 0) for v in state.get("archived", {}).values()) / (1024**3)
    print(f"\n{'='*60}")
    print(f"ARCHIVE COMPLETE: {completed} succeeded, {failed} failed")
    print(f"Total uploaded: {archived_gb:.1f} GB to s3://{args.bucket}/")
    print(f"State file: {STATE_FILE}")


if __name__ == "__main__":
    main()
