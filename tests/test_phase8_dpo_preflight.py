from __future__ import annotations

import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_PATH = ROOT / "scripts" / "preflight_phase8_dpo_dataset.py"


def load_preflight_module():
    spec = importlib.util.spec_from_file_location("phase8_dpo_preflight", PREFLIGHT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load preflight module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Phase8DpoPreflightTests(unittest.TestCase):
    def test_detects_long_exact_repeat_in_chosen_sequence(self) -> None:
        module = load_preflight_module()
        seq = "ACDEFGHIKLMNPQRS" + "TTTT" + "ACDEFGHIKLMNPQRS"
        repeat = module.longest_exact_repeat(seq, min_len=16)
        self.assertIsNotNone(repeat)
        self.assertEqual(repeat["length"], 16)

    def test_preflight_rejects_generated_or_repeated_chosen_positive(self) -> None:
        module = load_preflight_module()
        chosen = "ACDEFGHIKLMNPQRS" + "TTTT" + "ACDEFGHIKLMNPQRS"
        rejected = "ACDEFGHIKLMNPQRS" + "YYYY" + "ACDEFGHIKLMNPQRS"
        with tempfile.TemporaryDirectory() as tmpdir:
            dataset_path = Path(tmpdir) / "bad.jsonl"
            dataset_path.write_text(
                json.dumps(
                    {
                        "prompt": "Design a PETase/cutinase sequence.",
                        "chosen": chosen,
                        "rejected": rejected,
                        "source_type": "synthetic_length_preserving_artifact_replacement",
                        "chosen_source_type": "phase7_generated_local_library",
                        "chosen_record_id": "CAND_001",
                        "chosen_reviewed": False,
                        "chosen_active_site_count": 0,
                        "chosen_confidence_basis": "generated",
                        "corruption_method": "replace_equal_length_internal_window",
                        "synthetic_artifact_class": "test",
                        "synthetic_artifact": "YYYY",
                        "artifact_site": 20,
                        "artifact_window_length": 4,
                        "replaced_window": "TTTT",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            args = types.SimpleNamespace(
                dataset_path=str(dataset_path),
                min_rows=1,
                require_length_matched=True,
                require_no_duplicate_triples=True,
                require_synthetic_audit=True,
                require_positive_audit=True,
                max_chosen_exact_repeat=15,
            )
            result = module.preflight(args)

        self.assertFalse(result["ready_for_paid_dpo_smoke"])
        self.assertEqual(result["counts"]["chosen_repeat_violations"], 1)
        self.assertTrue(any("chosen_source_type" in failure for failure in result["failures"]))


if __name__ == "__main__":
    unittest.main()
