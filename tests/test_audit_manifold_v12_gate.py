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

from scripts import audit_manifold_v12_gate


class AuditManifoldV12GateTests(unittest.TestCase):
    def test_build_audit_tracks_recovered_hits_and_prompt_lengths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            suite_dir = root / "reports" / "robustness" / "suite-v12"
            ablation_root = root / "reports" / "ablations"
            suite_dir.mkdir(parents=True)
            ablation_root.mkdir(parents=True)
            summary_path = suite_dir / "robustness_summary.json"

            run_payloads = [
                ("suite-v12-p24-t0p8-s41", 41, 14, True),
                ("suite-v12-p24-t0p8-s53", 53, 7, True),
                ("suite-v12-p24-t0p8-s67", 67, 2, False),
            ]
            runs: list[dict[str, object]] = []
            for run_name, seed, hit_step, family in run_payloads:
                run_dir = ablation_root / run_name
                run_dir.mkdir()
                write_json(run_dir / "summary.json", {"name": run_name, "seed": seed, "prompt_count": 24})
                write_json(
                    run_dir / "candidate_audit.json",
                    {
                        "records": [
                            {
                                "step": hit_step,
                                "prompt": f"Generate a sequence with length near {200 + hit_step} aa.",
                                "candidates": [
                                    candidate(
                                        selected=True,
                                        motif_count=1,
                                        geometry_passes=True,
                                        esm_gate_pass=True,
                                        length=260 + hit_step,
                                        family_faithful=family,
                                    )
                                ],
                            }
                        ]
                    },
                )
                runs.append(
                    {
                        "run_name": run_name,
                        "seed": seed,
                        "summary_path": str(run_dir / "summary.json"),
                    }
                )

            write_json(
                summary_path,
                {
                    "suite_name": "suite-v12",
                    "completed_run_count": 3,
                    "missing_run_count": 0,
                    "durability_gate": {"passed": False, "group_results": []},
                    "groups": [
                        {
                            "prompt_count": 24,
                            "temperature": 0.8,
                            "runs": runs,
                        }
                    ],
                },
            )

            args = SimpleNamespace(
                robustness_summary_path=str(summary_path),
                ablation_root=str(ablation_root),
                output_json=str(root / "audit.json"),
                output_md=str(root / "audit.md"),
            )
            audit = audit_manifold_v12_gate.build_audit(args)

            self.assertEqual(audit["functional_hit_count"], 3)
            self.assertEqual(audit["family_faithful_hit_count"], 2)
            self.assertEqual(audit["hit_prompt_steps"], [2, 7, 14])
            self.assertEqual(audit["hit_prompt_lengths"], [202, 207, 214])
            self.assertIn(
                "paid_gate_recovered_real_hits_across_all_three_seeds",
                audit["diagnoses"],
            )


def candidate(
    *,
    selected: bool,
    motif_count: int,
    geometry_passes: bool,
    esm_gate_pass: bool,
    length: int,
    family_faithful: bool,
) -> dict[str, object]:
    sequence = "A" * length
    return {
        "selected": selected,
        "sequence": sequence,
        "extracted_sequence": sequence,
        "length": length,
        "stage1_rank": 1,
        "stage2_rank": 1,
        "stage2_score": 0.7,
        "hard_gate_pass": motif_count == 1,
        "is_trainable": motif_count == 1,
        "trainability_reason": "ok",
        "motif_count": motif_count,
        "has_family_serine_motif": True,
        "geometry_passes": geometry_passes,
        "esm_gate_pass": esm_gate_pass,
        "passes_core_screen": geometry_passes,
        "functional_bridge_passes": motif_count == 1 and geometry_passes and esm_gate_pass,
        "family_faithful_bridge_passes": family_faithful,
        "raw_esm_score": 95.0 if esm_gate_pass else 40.0,
        "geometry_score": 0.9 if geometry_passes else 0.1,
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
