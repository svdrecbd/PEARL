from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scripts import build_manifold_v2_offline_constructor


def scaffold_sequence(*mutations: tuple[int, str]) -> str:
    residues = list(("ACEFIKLMNPQRTVWY" * 7)[:100])
    residues[27:32] = list("GYSQG")
    residues[84] = "D"
    residues[97] = "H"
    for position, residue in mutations:
        residues[position - 1] = residue
    return "".join(residues)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def panel_row(sequence: str, *, role: str, source: str) -> dict[str, object]:
    return {
        "panel_id": "panel-" + sequence[:8],
        "panel_role": role,
        "panel_label": "positive" if role in {"positive_anchor", "support_positive"} else "negative",
        "panel_source": source,
        "source_run": source,
        "source_seed": 41,
        "source_step": 1,
        "requested_length": len(sequence),
        "sequence": sequence,
        "length": len(sequence),
        "esm_score": 99.0,
        "family_faithful_bridge_passes": role in {"positive_anchor", "support_positive"},
    }


class BuildManifoldV2OfflineConstructorTests(unittest.TestCase):
    def test_builds_hard_gated_selected_constructor_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            panel_dir = root / "panel"
            output_dir = root / "out"
            records_path = root / "records.jsonl"

            base = scaffold_sequence()
            support_a = scaffold_sequence((10, "V"), (20, "T"))
            support_b = scaffold_sequence((12, "W"), (24, "R"))
            hard_negative = scaffold_sequence((10, "V"), (45, "V"))
            drift_negative = scaffold_sequence((12, "W"), (55, "W"))

            active_sites = [
                {"start": 30, "end": 30},
                {"start": 85, "end": 85},
                {"start": 98, "end": 98},
            ]
            write_jsonl(
                records_path,
                [
                    {
                        "accession": f"REF{i}",
                        "sequence": scaffold_sequence((5 + i, "V")),
                        "length": 100,
                        "active_sites": active_sites,
                    }
                    for i in range(5)
                ],
            )
            write_jsonl(panel_dir / "v2_positive_anchors.jsonl", [panel_row(base, role="positive_anchor", source="v12")])
            write_jsonl(
                panel_dir / "v2_support_positives.jsonl",
                [
                    panel_row(support_a, role="support_positive", source="support_a"),
                    panel_row(support_b, role="support_positive", source="support_b"),
                ],
            )
            write_jsonl(
                panel_dir / "v2_hard_negatives.jsonl",
                [panel_row(hard_negative, role="hard_negative", source="v13")],
            )
            write_jsonl(
                panel_dir / "v2_drift_negatives.jsonl",
                [panel_row(drift_negative, role="drift_negative", source="v11")],
            )

            def fake_evaluate_candidate(*, sequence: str, family_stats: dict[str, object], reference_records: list[dict[str, object]]) -> dict[str, object]:
                return {
                    "sequence": sequence,
                    "passes_core_screen": True,
                    "novelty": {"closest_edit_identity": 0.5},
                }

            with patch.object(
                build_manifold_v2_offline_constructor,
                "evaluate_candidate",
                side_effect=fake_evaluate_candidate,
            ), patch.object(
                build_manifold_v2_offline_constructor,
                "precompute_novelty_cache",
                return_value=None,
            ):
                summary = build_manifold_v2_offline_constructor.build_constructor(
                    SimpleNamespace(
                        panel_dir=str(panel_dir),
                        records_path=str(records_path),
                        output_dir=str(output_dir),
                        max_parents=3,
                        max_frontier_candidates=20,
                        max_selected_candidates=4,
                        max_proposals_per_parent=20,
                        max_candidates_per_parent=8,
                        max_selected_per_parent=2,
                        max_selected_per_length=4,
                        relative_profile_bins=20,
                        max_mutable_positions_per_parent=12,
                        residues_per_position=2,
                        mutation_depths="1,2",
                        min_positive_frequency=0.01,
                        max_negative_frequency=1.0,
                        min_objective_score=-5.0,
                        readiness_min_selected=1,
                        readiness_min_parents=1,
                        readiness_min_lengths=1,
                        readiness_min_two_mutants=0,
                    )
                )

            self.assertGreaterEqual(summary["frontier_counts"]["frontier_candidates"], 1)
            self.assertGreaterEqual(summary["selected_counts"]["selected"], 1)
            self.assertTrue(summary["ready_for_esm_scoring"])
            self.assertFalse(summary["ready_for_paid_gate"])

            selected = read_jsonl(output_dir / "v2_constructor_selected_pre_esm.jsonl")
            self.assertTrue(all(row["hard_gate_passes"] for row in selected))
            self.assertTrue(all(row["prompt_length_delta"] == 0 for row in selected))
            self.assertTrue(all(row["needs_esm_score"] for row in selected))
            locked_positions = {28, 29, 30, 31, 32, 85, 98}
            for row in selected:
                mutated_positions = {int(mutation["position"]) for mutation in row["mutations"]}
                self.assertFalse(mutated_positions & locked_positions)


if __name__ == "__main__":
    unittest.main()
