from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scripts import audit_manifold_v11_gate


class AuditManifoldV11GateTests(unittest.TestCase):
    def test_postmortem_detects_disjoint_geometry_and_esm_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            suite_dir = root / "reports" / "robustness" / "suite-v11"
            run_dir = root / "reports" / "ablations" / "suite-v11-p24-t0p8-s41"
            suite_dir.mkdir(parents=True)
            run_dir.mkdir(parents=True)
            summary_path = suite_dir / "robustness_summary.json"
            audit_path = run_dir / "candidate_audit.json"

            write_json(
                summary_path,
                {
                    "suite_name": "suite-v11",
                    "completed_run_count": 1,
                    "missing_run_count": 0,
                    "durability_gate": {
                        "passed": False,
                        "group_results": [
                            {
                                "prompt_count": 24,
                                "temperature": 0.8,
                                "tier2_hits_by_seed": [0],
                                "prompt_coverage_by_seed": [0],
                                "conditions": [
                                    {"id": "seed_support", "actual": {"seeds_with_tier2": 0}},
                                    {
                                        "id": "prompt_coverage",
                                        "actual": {"prompts_with_any_tier2_across_seeds": 0},
                                    },
                                ],
                            }
                        ],
                    },
                    "groups": [
                        {
                            "prompt_count": 24,
                            "temperature": 0.8,
                            "runs": [
                                {
                                    "run_name": "suite-v11-p24-t0p8-s41",
                                    "seed": 41,
                                    "summary_path": str(run_dir / "summary.json"),
                                }
                            ],
                        }
                    ],
                },
            )
            write_json(
                audit_path,
                {
                    "records": [
                        {
                            "step": 0,
                            "prompt": "Generate a sequence with length near 220 aa.",
                            "candidates": [
                                candidate(
                                    selected=True,
                                    motif_count=1,
                                    geometry_passes=True,
                                    esm_gate_pass=False,
                                    length=220,
                                ),
                                candidate(
                                    selected=False,
                                    motif_count=1,
                                    geometry_passes=False,
                                    esm_gate_pass=True,
                                    length=221,
                                ),
                            ],
                        },
                        {
                            "step": 1,
                            "prompt": "Generate a sequence with length near 240 aa.",
                            "candidates": [
                                candidate(
                                    selected=True,
                                    motif_count=1,
                                    geometry_passes=False,
                                    esm_gate_pass=True,
                                    length=240,
                                ),
                                candidate(
                                    selected=False,
                                    motif_count=2,
                                    geometry_passes=True,
                                    esm_gate_pass=True,
                                    length=241,
                                ),
                            ],
                        },
                    ]
                },
            )

            output_json = root / "reports" / "analysis" / "audit.json"
            output_md = root / "reports" / "analysis" / "audit.md"
            args = SimpleNamespace(
                robustness_summary_path=str(summary_path),
                ablation_root=str(root / "reports" / "ablations"),
                output_json=str(output_json),
                output_md=str(output_md),
            )

            audit = audit_manifold_v11_gate.build_audit(args)
            output_json.parent.mkdir(parents=True)
            output_json.write_text(json.dumps(audit), encoding="utf-8")
            audit_manifold_v11_gate.write_markdown(output_md, audit)

            self.assertIn(
                "no_raw_candidate_satisfied_the_single_motif_geometry_esm_conjunction",
                audit["diagnoses"],
            )
            self.assertIn(
                "selected_candidates_split_between_geometry_only_and_stability_only",
                audit["diagnoses"],
            )
            self.assertEqual(audit["raw_population"]["conjunction_counts"]["motif1_and_geometry_and_esm"], 0)
            self.assertEqual(audit["selected_population"]["mode_counts"]["geometry_only"], 1)
            self.assertEqual(audit["selected_population"]["mode_counts"]["stability_only"], 1)
            self.assertIn("Recommended v1.2 Direction", output_md.read_text(encoding="utf-8"))


def candidate(
    *,
    selected: bool,
    motif_count: int,
    geometry_passes: bool,
    esm_gate_pass: bool,
    length: int,
) -> dict[str, object]:
    sequence = "A" * length
    return {
        "selected": selected,
        "extracted_sequence": sequence,
        "length": length,
        "stage1_rank": 1,
        "stage2_rank": 1 if selected else 2,
        "stage2_score": 0.5,
        "hard_gate_pass": motif_count == 1,
        "is_trainable": motif_count == 1,
        "trainability_reason": "ok" if motif_count == 1 else "motif_spam_rejected",
        "motif_count": motif_count,
        "has_family_serine_motif": motif_count >= 1,
        "geometry_passes": geometry_passes,
        "esm_gate_pass": esm_gate_pass,
        "passes_core_screen": geometry_passes,
        "functional_bridge_passes": motif_count == 1 and geometry_passes and esm_gate_pass,
        "family_faithful_bridge_passes": False,
        "raw_esm_score": 96.0 if esm_gate_pass else 40.0,
        "geometry_score": 0.8 if geometry_passes else 0.1,
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
