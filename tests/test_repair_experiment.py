from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scripts import repair_experiment


class RepairExperimentTests(unittest.TestCase):
    def test_command_bundle_adds_diversity_cap_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = make_config(Path(tmpdir), include_diversity_cap=True)
            commands = repair_experiment.command_bundle(config)
            paths = repair_experiment.repair_paths(config)

            self.assertIn("cap_pool", commands)
            self.assertIn(str(paths["repair_pool_raw_path"]), commands["build_pool"])
            self.assertIn(str(paths["repair_pool_raw_audit_path"]), commands["build_pool"])
            self.assertIn(str(paths["repair_pool_raw_path"]), commands["cap_pool"])
            self.assertIn(str(paths["repair_pool_path"]), commands["cap_pool"])
            self.assertIn(str(paths["repair_pool_audit_path"]), commands["run_native_repair"])

    def test_readiness_command_includes_threshold_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = make_config(Path(tmpdir), include_diversity_cap=True)
            command = repair_experiment.readiness_command(config)
            expected_pairs = {
                "--min-tier2": "24",
                "--min-tier1-proxy": "8",
                "--min-cluster-count": "16",
                "--max-cluster-share": "0.25",
                "--min-train-tier2": "18",
                "--min-train-tier1-proxy": "6",
                "--max-source-share": "0.25",
            }

            for flag, value in expected_pairs.items():
                self.assertIn(flag, command)
                self.assertEqual(command[command.index(flag) + 1], value)
            self.assertIn("--selected-only", command)
            self.assertIn("--require-ready", command)

    def test_legacy_repair_config_skips_cap_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = make_config(Path(tmpdir), include_diversity_cap=False)
            commands = repair_experiment.command_bundle(config)
            paths = repair_experiment.repair_paths(config)

            self.assertNotIn("cap_pool", commands)
            self.assertEqual(paths["repair_pool_raw_path"], paths["repair_pool_path"])
            self.assertIn(str(paths["repair_pool_path"]), commands["build_pool"])


def make_config(root: Path, *, include_diversity_cap: bool) -> dict[str, object]:
    records_path = root / "records.jsonl"
    records_path.write_text("", encoding="utf-8")

    audit_paths = [
        make_audit_path(root, "run-a"),
        make_audit_path(root, "run-b"),
    ]

    repair_pool: dict[str, object] = {
        "selected_only": True,
        "max_geometry_per_step": 1,
        "max_total": 256,
    }
    if include_diversity_cap:
        repair_pool["diversity_cap"] = {
            "max_total": 96,
            "max_per_source_run": 4,
            "max_per_cluster": 2,
            "cluster_mode": "heuristic",
            "cluster_identity_threshold": 0.85,
        }

    return {
        "_config_path": str(root / "repair_config.json"),
        "name": "repair-test",
        "execution": {"mode": "python", "python_bin": sys.executable},
        "records_path": str(records_path),
        "output_dir": str(root / "reports" / "repair"),
        "sources": {"audit_paths": [str(path) for path in audit_paths]},
        "repair_pool": repair_pool,
        "native_repair": {
            "selected_only": True,
            "esm_threshold": 85.0,
            "max_hits": 96,
            "rounds": 3,
            "mutable_radius": 3,
            "top_residues_per_position": 3,
            "beam_size": 6,
            "proposal_device": "auto",
        },
        "validation": {
            "min_esm": 95.0,
            "max_mutations": 2,
            "max_gap_error": 14,
        },
        "readiness": {
            "selected_only": True,
            "min_tier2": 24,
            "min_tier1_proxy": 8,
            "min_cluster_count": 16,
            "max_cluster_share": 0.25,
            "min_train_tier2": 18,
            "min_train_tier1_proxy": 6,
            "max_source_share": 0.25,
            "require_ready": True,
        },
    }


def make_audit_path(root: Path, run_name: str) -> Path:
    run_dir = root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    audit_path = run_dir / "candidate_audit.json"
    audit_path.write_text('{"records": []}', encoding="utf-8")
    return audit_path


if __name__ == "__main__":
    unittest.main()
