from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.steering.telemetry import TelemetryLogger, TelemetrySchema


class TelemetryTests(unittest.TestCase):
    def test_schema_serialization_and_deserialization(self) -> None:
        schema = TelemetrySchema(
            sample_id="test-sample-123",
            step_index=5,
            partial_sequence="MNAST",
            token_logprobs=[-0.12, -0.45],
            model_name="test-model",
            entropy=[1.2, 0.9],
            active_site_geometry={"passes_geometry": True, "collapsed": False},
            tandem_repeats={"violates_repeat_cap": False},
            esm_logprob=-12.5,
            esm_fold_plddt=88.4,
            constraints_applied={"tandem_cap": 15},
            operator_flags=["good"],
        )

        d = schema.to_dict()
        self.assertEqual(d["sample_id"], "test-sample-123")
        self.assertEqual(d["step_index"], 5)
        self.assertEqual(d["partial_sequence"], "MNAST")
        self.assertEqual(d["token_logprobs"], [-0.12, -0.45])
        self.assertEqual(d["model_name"], "test-model")
        self.assertEqual(d["entropy"], [1.2, 0.9])
        self.assertEqual(d["active_site_geometry"], {"passes_geometry": True, "collapsed": False})
        self.assertEqual(d["tandem_repeats"], {"violates_repeat_cap": False})
        self.assertEqual(d["esm_logprob"], -12.5)
        self.assertEqual(d["esm_fold_plddt"], 88.4)
        self.assertEqual(d["constraints_applied"], {"tandem_cap": 15})
        self.assertEqual(d["operator_flags"], ["good"])

        reconstructed = TelemetrySchema.from_dict(d)
        self.assertEqual(reconstructed.sample_id, schema.sample_id)
        self.assertEqual(reconstructed.step_index, schema.step_index)
        self.assertEqual(reconstructed.partial_sequence, schema.partial_sequence)
        self.assertEqual(reconstructed.token_logprobs, schema.token_logprobs)
        self.assertEqual(reconstructed.model_name, schema.model_name)
        self.assertEqual(reconstructed.entropy, schema.entropy)
        self.assertEqual(reconstructed.active_site_geometry, schema.active_site_geometry)
        self.assertEqual(reconstructed.tandem_repeats, schema.tandem_repeats)
        self.assertEqual(reconstructed.esm_logprob, schema.esm_logprob)
        self.assertEqual(reconstructed.esm_fold_plddt, schema.esm_fold_plddt)
        self.assertEqual(reconstructed.constraints_applied, schema.constraints_applied)
        self.assertEqual(reconstructed.operator_flags, schema.operator_flags)

    def test_logger_writing_replaying_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            logger = TelemetryLogger(run_name="smoke-run", output_dir=tmpdir_path)

            # Assert log file does not exist yet
            self.assertFalse(logger.log_file.exists())
            self.assertEqual(logger.replay_logs(), [])

            # Log step 1: Normal state
            logger.log_sequence_state(
                sample_id="candidate-1",
                step_index=0,
                partial_sequence="MNAST",
                token_logprobs=[-0.1],
                model_name="test-model",
            )
            self.assertTrue(logger.log_file.exists())

            # Log step 2: Collapse starts (failure onset)
            logger.log_sequence_state(
                sample_id="candidate-1",
                step_index=1,
                partial_sequence="MNASTFAPQS",
                token_logprobs=[-0.1, -0.2],
                model_name="test-model",
                tandem_repeats={"violates_repeat_cap": True},
            )

            # Log step 3: Collapse continues, but now operator intervenes and flags it
            logger.log_sequence_state(
                sample_id="candidate-1",
                step_index=2,
                partial_sequence="MNASTFAPQSFA",
                token_logprobs=[-0.1, -0.2, -0.3],
                model_name="test-model",
                tandem_repeats={"violates_repeat_cap": True},
                operator_flags=["tandem_repeat"],
                constraints_applied={"tandem_cap": 10},
            )

            # Log step 4: Normal state recovered (operator steered the model out)
            logger.log_sequence_state(
                sample_id="candidate-1",
                step_index=3,
                partial_sequence="MNASTFAPQSV",
                token_logprobs=[-0.1, -0.2, -0.3, -0.05],
                model_name="test-model",
                tandem_repeats={"violates_repeat_cap": False},
                esm_fold_plddt=91.2, # Finished viable candidate
            )

            # Replay logs and assert correctness
            history = logger.replay_logs()
            self.assertEqual(len(history), 4)
            self.assertEqual(history[0].step_index, 0)
            self.assertEqual(history[1].tandem_repeats["violates_repeat_cap"], True)
            self.assertEqual(history[2].operator_flags, ["tandem_repeat"])
            self.assertEqual(history[3].esm_fold_plddt, 91.2)

            # Compute steering metrics
            metrics = logger.compute_steering_metrics()
            self.assertEqual(metrics["run_name"], "smoke-run")
            self.assertEqual(metrics["total_steps_logged"], 4)
            self.assertEqual(metrics["total_human_interventions"], 1)  # Intervened at step 2 (constraints + flags)
            
            # Failure occurred at step 1. Operator flagged/detected it at step 2.
            # Time-to-failure-detection: step 2 - step 1 = 1 step
            self.assertEqual(metrics["time_to_failure_detection_steps"], 1.0)
            
            # Normal candidate reached at step 3. Viable rate = 1.0 (since 1 finished and it folded cleanly)
            self.assertEqual(metrics["viable_candidate_rate"], 1.0)
            self.assertEqual(metrics["metrics_summary"]["total_finished_candidates"], 1)
            self.assertEqual(metrics["metrics_summary"]["viable_candidates_generated"], 1)


if __name__ == "__main__":
    unittest.main()
