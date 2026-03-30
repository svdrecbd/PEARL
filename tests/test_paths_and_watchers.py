from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.paths import REPO_ROOT, detached_log_path, detached_metadata_path, resolve_repo_path
from pearl.watchers import wait_for_path, wait_for_path_or_abort


class PathsAndWatchersTests(unittest.TestCase):
    def test_resolve_repo_path_handles_relative_and_tinker_paths(self) -> None:
        self.assertEqual(resolve_repo_path("reports/example.json"), str((REPO_ROOT / "reports/example.json").resolve()))
        self.assertEqual(resolve_repo_path("tinker://checkpoint"), "tinker://checkpoint")

    def test_detached_path_helpers_use_logs_dir(self) -> None:
        self.assertTrue(str(detached_metadata_path("job-a")).endswith("/reports/logs/job-a.json"))
        self.assertTrue(str(detached_log_path("job-a")).endswith("/reports/logs/job-a.log"))

    def test_wait_for_existing_path_returns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ready.txt"
            path.write_text("ok", encoding="utf-8")
            wait_for_path(path, poll_seconds=0.001)
            self.assertTrue(path.exists())

    def test_wait_for_path_or_abort_short_circuits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "missing.txt"
            self.assertFalse(
                wait_for_path_or_abort(path, should_abort=lambda: True, poll_seconds=0.001)
            )


if __name__ == "__main__":
    unittest.main()
