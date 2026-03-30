from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
REPORTS_DIR = Path(os.environ.get("PEARL_REPORTS_DIR", REPO_ROOT / "reports")).expanduser().resolve()
LOGS_DIR = REPORTS_DIR / "logs"
WARMSTART_DIR = REPORTS_DIR / "warmstart"
ROBUSTNESS_DIR = REPORTS_DIR / "robustness"


def resolve_repo_path(value: str | None) -> str | None:
    if value is None:
        return None
    if value.startswith("tinker://"):
        return value
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path.resolve())
    return str((REPO_ROOT / path).resolve())


def warmstart_summary_path(run_name: str) -> Path:
    return WARMSTART_DIR / run_name / "summary.json"


def robustness_summary_path(run_name: str) -> Path:
    return ROBUSTNESS_DIR / run_name / "robustness_summary.json"


def detached_metadata_path(job_name: str) -> Path:
    return LOGS_DIR / f"{job_name}.json"


def detached_log_path(job_name: str) -> Path:
    return LOGS_DIR / f"{job_name}.log"

