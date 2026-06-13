from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.io_utils import load_json_object
from pearl.reports import (
    ReportContext,
    build_report_payload,
    extract_contiguous_step_records,
    persist_progress,
    validate_resume_report_payload,
)
from pearl.smoke_gate import evaluate_smoke_summary


def make_context() -> ReportContext:
    return ReportContext(
        init_state_path="tinker://weights/base",
        eval_only=True,
        prompt_variant="motif_prior_soft_v2",
        candidate_sample_count=256,
        second_stage_top_k=8,
        esm_pll_gate_percentile=0.05,
        second_stage_esm_weight=0.2,
        second_stage_motif_weight=0.2,
        second_stage_geometry_weight=0.6,
        second_stage_template_weight=0.15,
        skip_stage2_esm=False,
        prompts_path="/tmp/prompts.jsonl",
    )


class ReportsAndSmokeTests(unittest.TestCase):
    def test_extract_contiguous_step_records_stops_at_gap(self) -> None:
        records = [
            {"step": 0, "reward": 1.0},
            {"step": 2, "reward": 3.0},
            {"step": 1, "reward": 2.0},
            {"step": 4, "reward": 5.0},
        ]
        contiguous = extract_contiguous_step_records(raw_records=records, prompt_count=5)
        self.assertEqual([record["step"] for record in contiguous], [0, 1, 2])

    def test_validate_resume_report_payload_passes_for_matching_context(self) -> None:
        context = make_context()
        prompts = ["prompt a", "prompt b"]
        payload = build_report_payload(
            requested_model_name="model",
            base_model="base",
            supported_models=["model"],
            checkpoint_name="ckpt",
            checkpoint_path="tinker://weights/base",
            reference_records_path=None,
            prompts=prompts,
            step_records=[{"step": 0, "reward": 1.0}],
            context=context,
        )
        validate_resume_report_payload(
            report_payload=payload,
            prompts=prompts,
            report_path=Path("/tmp/report.json"),
            context=context,
        )

    def test_validate_resume_report_payload_rejects_prompt_count_mismatch(self) -> None:
        context = make_context()
        payload = build_report_payload(
            requested_model_name="model",
            base_model="base",
            supported_models=["model"],
            checkpoint_name="ckpt",
            checkpoint_path="tinker://weights/base",
            reference_records_path=None,
            prompts=["prompt a"],
            step_records=[],
            context=context,
        )
        with self.assertRaises(RuntimeError):
            validate_resume_report_payload(
                report_payload=payload,
                prompts=["prompt a", "prompt b"],
                report_path=Path("/tmp/report.json"),
                context=context,
            )

    def test_persist_progress_writes_report_and_candidate_audit(self) -> None:
        context = make_context()
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "report.json"
            audit_path = Path(tmpdir) / "audit.json"
            report = persist_progress(
                report_path=report_path,
                candidate_audit_path=audit_path,
                requested_model_name="model",
                base_model="base",
                supported_models=["model"],
                checkpoint_name="ckpt",
                checkpoint_path="tinker://weights/base",
                reference_records_path=None,
                prompts=["prompt a"],
                step_records=[{"step": 0, "reward": 2.5}],
                candidate_audit_records=[{"step": 0, "candidate_count": 8}],
                context=context,
            )
            self.assertEqual(report["average_reward"], 2.5)
            self.assertEqual(load_json_object(report_path), report)
            audit_payload = load_json_object(audit_path)
            self.assertIsNotNone(audit_payload)
            self.assertEqual(audit_payload["records"][0]["candidate_count"], 8)

    def test_evaluate_smoke_summary_applies_seed_and_prompt_thresholds(self) -> None:
        payload = {
            "groups": [
                {
                    "prompt_count": 48,
                    "temperature": 0.8,
                    "tier2_hits_by_seed": [0, 2, 1],
                    "prompts_with_any_tier2_across_seeds": 2,
                }
            ]
        }
        decision = evaluate_smoke_summary(
            payload,
            summary_path="/tmp/summary.json",
            prompt_count=48,
            temperature=0.8,
            min_seeds_with_hit=2,
            min_prompts_with_hit=2,
        )
        self.assertTrue(decision["passed"])
        self.assertEqual(decision["seeds_with_hits"], 2)

    def test_evaluate_smoke_summary_errors_when_group_missing(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_smoke_summary(
                {"groups": []},
                summary_path="/tmp/summary.json",
                prompt_count=48,
                temperature=0.8,
                min_seeds_with_hit=2,
                min_prompts_with_hit=2,
            )


if __name__ == "__main__":
    unittest.main()
