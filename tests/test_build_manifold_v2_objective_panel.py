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

from scripts import build_manifold_v2_objective_panel


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def candidate(sequence: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "sequence": sequence,
        "length": len(sequence),
        "selected": True,
        "is_trainable": True,
        "esm_gate_pass": True,
        "geometry_passes": True,
        "functional_bridge_passes": True,
        "family_faithful_bridge_passes": True,
        "has_family_serine_motif": True,
        "passes_core_screen": True,
        "motif_count": 1,
        "raw_esm_score": 99.0,
        "best_gap_error": 5,
    }
    payload.update(overrides)
    return payload


class BuildManifoldV2ObjectivePanelTests(unittest.TestCase):
    def test_builds_positive_hard_negative_drift_and_support_panel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "panel"
            v12_audit = root / "v12_audit.json"
            v13_audit = root / "v13" / "candidate_audit.json"
            v9_rejects = root / "v9_rejects.jsonl"
            v11_drift = root / "v11_drift.jsonl"
            support = root / "support.jsonl"

            write_json(
                v12_audit,
                {
                    "hit_seed_records": [
                        {
                            "seed": 41,
                            "step": 7,
                            "prompt": "p24 hit",
                            "requested_length": 215,
                            "selected_candidate": candidate("ACDEFGHIKLMNPQRSTVWY", length=300),
                        },
                        {
                            "seed": 67,
                            "step": 2,
                            "prompt": "bridge-only hit",
                            "requested_length": 241,
                            "selected_candidate": candidate(
                                "CDEFGHIKLMNPQRSTVWYA",
                                family_faithful_bridge_passes=False,
                            ),
                        },
                    ]
                },
            )
            write_json(
                v13_audit,
                {
                    "records": [
                        {
                            "step": 0,
                            "prompt": "Generate a sequence with length near 220 aa.",
                            "candidates": [
                                candidate(
                                    "DDDDDDDDDDDDDDDDDDDD",
                                    functional_bridge_passes=False,
                                    family_faithful_bridge_passes=False,
                                    geometry_passes=False,
                                    esm_gate_pass=True,
                                ),
                                candidate(
                                    "EEEEEEEEEEEEEEEEEEEE",
                                    functional_bridge_passes=False,
                                    family_faithful_bridge_passes=False,
                                    geometry_passes=True,
                                    esm_gate_pass=False,
                                ),
                                candidate("FFFFFFFFFFFFFFFFFFFF", selected=False),
                            ],
                        }
                    ]
                },
            )
            write_jsonl(
                v9_rejects,
                [
                    {
                        "sequence": "GGGGGGGGGGGGGGGGGGGG",
                        "length": 20,
                        "esm_score": 99.0,
                        "geometry_passes": True,
                        "functional_bridge_passes": False,
                        "family_faithful_bridge_passes": False,
                    }
                ],
            )
            write_jsonl(
                v11_drift,
                [
                    {
                        "sequence": "HHHHHHHHHHHHHHHHHHHH",
                        "length": 20,
                        "esm_gate_pass": True,
                        "geometry_passes": False,
                        "functional_bridge_passes": False,
                        "family_faithful_bridge_passes": False,
                    }
                ],
            )
            write_jsonl(
                support,
                [
                    {
                        "sequence": "IIIIIIIIIIIIIIIIIIII",
                        "length": 20,
                        "family_faithful_bridge_passes": True,
                        "functional_bridge_passes": True,
                        "esm_score": 98.0,
                    },
                    {
                        "sequence": "JJJJJJJJJJJJJJJJJJJJ",
                        "length": 20,
                        "family_faithful_bridge_passes": False,
                    },
                ],
            )

            summary = build_manifold_v2_objective_panel.build_panel(
                SimpleNamespace(
                    output_dir=str(output_dir),
                    v12_audit_path=str(v12_audit),
                    v13_candidate_audit_paths=[str(v13_audit)],
                    v9_reject_path=str(v9_rejects),
                    v11_drift_paths=[str(v11_drift)],
                    support_positive_paths=[str(support)],
                    max_v9_drift_negatives=10,
                    max_v11_drift_negatives_per_path=10,
                    max_support_positives_per_path=10,
                )
            )

            self.assertEqual(summary["counts"]["positive_anchors"], 1)
            self.assertEqual(summary["counts"]["hard_negatives"], 2)
            self.assertEqual(summary["counts"]["drift_negatives"], 2)
            self.assertEqual(summary["counts"]["support_positives"], 1)
            self.assertFalse(summary["readiness"]["ready_for_paid_gate"])

            positives = read_jsonl(output_dir / "v2_positive_anchors.jsonl")
            hard_negatives = read_jsonl(output_dir / "v2_hard_negatives.jsonl")
            support_rows = read_jsonl(output_dir / "v2_support_positives.jsonl")
            self.assertEqual(positives[0]["panel_source"], "v12_family_faithful_gate_hit")
            self.assertEqual(
                {row["panel_source"] for row in hard_negatives},
                {"v13_stability_only_selected", "v13_geometry_only_selected"},
            )
            self.assertEqual({row["requested_length"] for row in hard_negatives}, {220})
            self.assertEqual(support_rows[0]["panel_role"], "support_positive")
            self.assertTrue((output_dir / "v2_objective_panel_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
