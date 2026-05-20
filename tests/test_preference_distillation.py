from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.preference_distillation import (
    PairingConfig,
    build_preference_pairs,
    load_candidate_metric_rows,
    normalize_candidate_rows,
    select_distillation_winners,
)


BASE_SEQUENCE = "ACDEFGHIKLMNPQRSTVWY" * 9


def candidate_row(candidate_id: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "candidate_id": candidate_id,
        "prompt": "Design a PETase/cutinase-like hydrolase around 180 aa.",
        "prompt_family": "petase-family",
        "generation_checkpoint": "checkpoint-a",
        "evaluator_version": "fixture-v1",
        "sequence": BASE_SEQUENCE,
        "length": len(BASE_SEQUENCE),
        "motif_count": 1,
        "family_faithful_pass": True,
        "catalytic_context_pass": True,
        "artifact_free": True,
        "fold_confidence": 92.0,
        "novelty_identity": 0.42,
        "physical_score": 0.9,
        "independent_audit_pass": True,
    }
    row.update(overrides)
    return row


class PreferenceDistillationTests(unittest.TestCase):
    def test_builds_high_confidence_physical_pair_inside_comparable_bucket(self) -> None:
        rows = [
            candidate_row("good", physical_score=0.9),
            candidate_row(
                "repeat-fail",
                sequence=BASE_SEQUENCE[:-1] + "A",
                hard_gate_pass=False,
                repeat_artifact=True,
                artifact_free=False,
                physical_score=0.95,
            ),
            candidate_row(
                "other-checkpoint",
                sequence=BASE_SEQUENCE[:-1] + "C",
                generation_checkpoint="checkpoint-b",
                hard_gate_pass=False,
                repeat_artifact=True,
                artifact_free=False,
            ),
        ]
        candidates = normalize_candidate_rows(rows)
        pairs = build_preference_pairs(candidates, config=PairingConfig(max_pairs_per_bucket=10))

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].chosen_id, "good")
        self.assertEqual(pairs[0].rejected_id, "repeat-fail")
        self.assertEqual(pairs[0].preference_rule, "hard_gate_pass")

    def test_selects_only_pareto_front_winners_for_distillation(self) -> None:
        rows = [
            candidate_row("front-a", fold_confidence=90.0, physical_score=0.9),
            candidate_row("dominated", fold_confidence=88.0, physical_score=0.8),
            candidate_row("front-b", fold_confidence=95.0, physical_score=0.7, independent_audit_pass=False),
            candidate_row("repeat-fail", repeat_artifact=True, artifact_free=False, physical_score=0.99),
        ]
        candidates = normalize_candidate_rows(rows)

        winners = select_distillation_winners(candidates)
        self.assertEqual({winner.candidate_id for winner in winners}, {"front-a", "front-b"})

        audited_winners = select_distillation_winners(candidates, require_independent_audit=True)
        self.assertEqual([winner.candidate_id for winner in audited_winners], ["front-a"])

    def test_cli_writes_pairs_winners_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            candidate_path = tmp / "candidates.jsonl"
            rows = [
                candidate_row("good", physical_score=0.9),
                candidate_row(
                    "bad",
                    sequence=BASE_SEQUENCE[:-1] + "A",
                    hard_gate_pass=False,
                    repeat_artifact=True,
                    artifact_free=False,
                    physical_score=0.95,
                ),
            ]
            candidate_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                encoding="utf-8",
            )
            output_dir = tmp / "out"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_physical_to_sequence_loop.py"),
                    "--name",
                    "fixture",
                    "--candidate-path",
                    str(candidate_path),
                    "--output-dir",
                    str(output_dir),
                ],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            run_dir = output_dir / "fixture"
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            pairs = [
                json.loads(line)
                for line in (run_dir / "physical_dpo_pairs.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            winners = [
                json.loads(line)
                for line in (run_dir / "opd_distillation_winners.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(manifest["pair_count"], 1)
            self.assertEqual(manifest["distillation_winner_count"], 1)
            self.assertEqual(pairs[0]["chosen_id"], "good")
            self.assertEqual(winners[0]["candidate_id"], "good")

    def test_loads_pearl_candidate_audit_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "candidate_audit.json"
            payload = {
                "checkpoint_name": "fixture-checkpoint",
                "skip_stage2_esm": False,
                "records": [
                    {
                        "step": 7,
                        "prompt": "Design a PETase/cutinase-like hydrolase around 180 aa.",
                        "selection_metadata": {"stage1_rank": 1},
                        "candidates": [
                            {
                                key: value
                                for key, value in candidate_row("audit-good", selected=True).items()
                                if key != "generation_checkpoint"
                            },
                            {
                                key: value
                                for key, value in candidate_row(
                                    "audit-bad",
                                    sequence=BASE_SEQUENCE[:-1] + "A",
                                    selected=False,
                                    hard_gate_pass=False,
                                    repeat_artifact=True,
                                    artifact_free=False,
                                    physical_score=0.95,
                                ).items()
                                if key != "generation_checkpoint"
                            },
                        ],
                    }
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            rows = load_candidate_metric_rows(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["prompt"], payload["records"][0]["prompt"])
            self.assertEqual(rows[0]["generation_checkpoint"], "fixture-checkpoint")

            candidates = normalize_candidate_rows(rows)
            pairs = build_preference_pairs(candidates)
            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0].chosen_id, "audit-good")


if __name__ == "__main__":
    unittest.main()
