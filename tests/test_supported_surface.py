from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

SUPPORTED_DOC_PATHS = [
    ROOT / "README.md",
    ROOT / "docs" / "overview.md",
    ROOT / "docs" / "workflows.md",
    ROOT / "docs" / "operations.md",
    ROOT / "docs" / "science.md",
    ROOT / "docs" / "manifold_construction.md",
    ROOT / "configs" / "experiments" / "README.md",
]

SUPPORTED_CODE_PATHS = [
    ROOT / "main.py",
    ROOT / "scripts" / "build_hybrid_10k_dpo.py",
    ROOT / "scripts" / "preflight_phase8_dpo_dataset.py",
    ROOT / "scripts" / "phase7_mcmc_library_builder.py",
    ROOT / "scripts" / "build_phase7_manifest.py",
    ROOT / "scripts" / "fold_phase7_subset.py",
    ROOT / "scripts" / "plot_phase7_figures.py",
    ROOT / "scripts" / "build_pymol_poster_script.py",
    ROOT / "scripts" / "plot_dpo_flowchart.py",
    ROOT / "scripts" / "run_sft_warmstart.py",
    ROOT / "scripts" / "run_robustness_two_phase.py",
    ROOT / "scripts" / "run_robustness_suite.py",
    ROOT / "scripts" / "run_ablation.py",
    ROOT / "scripts" / "finalize_ablation_from_candidate_audit.py",
    ROOT / "scripts" / "strict_experiment.py",
    ROOT / "scripts" / "build_strict_first_union_curricula.py",
    ROOT / "scripts" / "evaluate_strict_core_smoke_gate.py",
    ROOT / "scripts" / "launch_detached_job.py",
    ROOT / "scripts" / "stop_detached_job.py",
    ROOT / "scripts" / "run_rl_pilot.py",
]

ROOT_SHIM_MODULES = {"petase_family", "local_proxy"}


class SupportedSurfaceTests(unittest.TestCase):
    def test_supported_docs_and_code_do_not_use_machine_local_users_paths(self) -> None:
        paths = SUPPORTED_DOC_PATHS + SUPPORTED_CODE_PATHS
        offenders: list[str] = []
        for path in paths:
            text = path.read_text(encoding="utf-8")
            if "/Users/" in text:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(
            offenders,
            [],
            msg="supported surface leaked machine-local /Users/ paths: " + ", ".join(offenders),
        )

    def test_active_python_entrypoints_do_not_import_root_shims(self) -> None:
        offenders: list[str] = []
        for path in SUPPORTED_CODE_PATHS:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(alias.name in ROOT_SHIM_MODULES for alias in node.names):
                        offenders.append(str(path.relative_to(ROOT)))
                        break
                if isinstance(node, ast.ImportFrom) and node.module in ROOT_SHIM_MODULES:
                    offenders.append(str(path.relative_to(ROOT)))
                    break
        self.assertEqual(
            offenders,
            [],
            msg="active entrypoints imported deprecated root shims: " + ", ".join(offenders),
        )

    def test_root_shims_emit_deprecation_warning_text(self) -> None:
        shim_expectations = {
            ROOT / "petase_family.py": "deprecated",
            ROOT / "local_proxy.py": "deprecated",
        }
        missing: list[str] = []
        for path, needle in shim_expectations.items():
            text = path.read_text(encoding="utf-8").lower()
            if needle not in text or "warnings.warn" not in text:
                missing.append(str(path.relative_to(ROOT)))
        self.assertEqual(
            missing,
            [],
            msg="root shims are missing deprecation warning text: " + ", ".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
