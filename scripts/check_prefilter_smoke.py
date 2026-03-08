from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "benchmarks" / "prefilter_smoke_fixture" / "raw_samples_fixture.jsonl"
OUT_ROOT = ROOT / "reports" / "prefilter" / "smoke_fixture_check"


def main() -> None:
    if not FIXTURE_PATH.exists():
        raise SystemExit(f"Fixture not found: {FIXTURE_PATH}")

    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)

    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "prefilter_local.py"),
        "all",
        "--inputs",
        str(FIXTURE_PATH),
        "--out-root",
        str(OUT_ROOT),
    ]
    subprocess.run(cmd, check=True)

    summary_path = OUT_ROOT / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    stages = summary["stages"]

    ingest = stages["ingest"]
    hard_filter = stages["hard_filter"]
    exact_dedup = stages["exact_dedup"]
    handoff = stages["handoff"]

    assert int(ingest["records_written"]) == 6, f"expected 6 records, got {ingest['records_written']}"
    assert int(ingest["salvaged"]) >= 1, f"expected >=1 salvaged line, got {ingest['salvaged']}"
    assert int(hard_filter["reject_count"]) >= 2, f"expected rejects, got {hard_filter['reject_count']}"
    assert int(exact_dedup["dup_count"]) >= 1, f"expected duplicates, got {exact_dedup['dup_count']}"

    tier_a_ready = int(handoff["counts"]["tier_a_ready"])
    tier_b_ready = int(handoff["counts"]["tier_b_ready"])
    assert tier_a_ready + tier_b_ready >= 1, "expected at least one HPC-ready record"

    check_schema_fields(
        pick_first_available_record(
            OUT_ROOT / "handoff" / "hpc_ready_A.jsonl",
            OUT_ROOT / "handoff" / "hpc_ready_B.jsonl",
            OUT_ROOT / "handoff" / "hpc_explore_C_sample.jsonl",
        )
    )

    report: dict[str, Any] = {
        "status": "ok",
        "fixture": str(FIXTURE_PATH),
        "summary_path": str(summary_path),
        "key_counts": {
            "records_written": ingest["records_written"],
            "salvaged": ingest["salvaged"],
            "hard_filter_rejects": hard_filter["reject_count"],
            "exact_dedup_dups": exact_dedup["dup_count"],
            "tier_a_ready": tier_a_ready,
            "tier_b_ready": tier_b_ready,
            "tier_c_sampled": handoff["counts"]["tier_c_sampled"],
        },
    }
    print(json.dumps(report, indent=2))


def pick_first_available_record(*paths: Path) -> dict[str, Any]:
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            line = handle.readline().strip()
            if line:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    return payload
    raise AssertionError("No records available in handoff outputs")


def check_schema_fields(record: dict[str, Any]) -> None:
    required_fields = [
        "schema_version",
        "candidate_id",
        "run_name",
        "source_file",
        "source_line",
        "sequence",
        "sequence_length",
        "reject_reasons",
        "priority_tier",
        "priority_score",
    ]
    missing = [field for field in required_fields if field not in record]
    if missing:
        raise AssertionError(f"Missing required schema fields: {missing}")


if __name__ == "__main__":
    main()
