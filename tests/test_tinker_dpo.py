from __future__ import annotations

import os
import math
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.model_rendering import (
    DEEPSEEK_RENDERER,
    GPT_OSS_RENDERER,
    INKLING_RENDERER,
    KIMI_RENDERER,
    NEMOTRON_RENDERER,
    NEMOTRON_ULTRA_RENDERER,
    QWEN3_RENDERER,
    QWEN35_RENDERER,
    RendererContract,
    renderer_diagnostics,
)
from pearl.tinker_dpo import dpo_loss_value, log_sigmoid, split_pair_rows_grouped


class TinkerDpoTests(unittest.TestCase):
    def test_model_native_renderers_preserve_generation_prefix_and_target_mask(self) -> None:
        cases = (
            (
                INKLING_RENDERER,
                "thinkingmachines/Inkling",
            ),
            (
                NEMOTRON_ULTRA_RENDERER,
                "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16",
            ),
            (KIMI_RENDERER, "moonshotai/Kimi-K2.6"),
            (NEMOTRON_RENDERER, "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16"),
            (DEEPSEEK_RENDERER, "deepseek-ai/DeepSeek-V3.1"),
            (QWEN3_RENDERER, "Qwen/Qwen3-8B"),
            (QWEN35_RENDERER, "Qwen/Qwen3.5-9B"),
            (GPT_OSS_RENDERER, "openai/gpt-oss-20b"),
        )
        for renderer_name, model_name in cases:
            with self.subTest(renderer=renderer_name):
                contract = RendererContract(name=renderer_name, model_name=model_name)
                diagnostics = renderer_diagnostics(
                    "Design a protein. Output only uppercase amino acid letters.",
                    "ACDEFGHIKLMNPQRSTVWY",
                    tokenizer=None,
                    contract=contract,
                )
                self.assertTrue(diagnostics["generation_is_supervised_prefix"])
                self.assertGreater(diagnostics["weighted_target_count"], 0)
                self.assertGreater(
                    diagnostics["supervised_token_count"],
                    diagnostics["generation_token_count"],
                )

    def test_grouped_holdout_is_deterministic_and_has_no_chosen_leakage(self) -> None:
        rows = [
            {
                "prompt": f"prompt-{index % 3}",
                "chosen": f"CHOSEN{index // 2}",
                "rejected": f"REJECTED{index}",
                "chosen_record_id": f"record-{index // 2}",
            }
            for index in range(20)
        ]
        train_a, holdout_a = split_pair_rows_grouped(rows, holdout_fraction=0.2, seed=17)
        train_b, holdout_b = split_pair_rows_grouped(rows, holdout_fraction=0.2, seed=17)

        self.assertEqual(train_a, train_b)
        self.assertEqual(holdout_a, holdout_b)
        self.assertEqual(len(holdout_a), 4)
        train_groups = {row["chosen_record_id"] for row in train_a}
        holdout_groups = {row["chosen_record_id"] for row in holdout_a}
        self.assertFalse(train_groups & holdout_groups)

    def test_dpo_loss_value_prefers_larger_policy_margin_than_reference(self) -> None:
        lower_loss = dpo_loss_value(
            policy_chosen_logps=[-10.0],
            policy_rejected_logps=[-15.0],
            reference_margins=[1.0],
            beta=0.1,
        )
        higher_loss = dpo_loss_value(
            policy_chosen_logps=[-14.0],
            policy_rejected_logps=[-15.0],
            reference_margins=[1.0],
            beta=0.1,
        )
        self.assertLess(lower_loss, higher_loss)

    def test_log_sigmoid_is_stable_for_large_values(self) -> None:
        self.assertTrue(math.isfinite(log_sigmoid(1000.0)))
        self.assertTrue(math.isfinite(log_sigmoid(-1000.0)))
        self.assertAlmostEqual(log_sigmoid(0.0), -math.log(2.0))

    def test_shape_only_cli_validates_pairs_without_tinker_client(self) -> None:
        rows = [
            {
                "prompt": "Design a PETase-like hydrolase.",
                "chosen": "ACDEFGHIKLMNPQRSTVWY",
                "rejected": "ACDEFGHIKLMNPQRSTVWA",
                "chosen_id": "good",
                "rejected_id": "bad",
                "preference_rule": "hard_gate_pass",
            },
            {
                "prompt": "Design a PETase-like hydrolase.",
                "chosen": "ACDEFGHIKLMNPQRSTVWC",
                "rejected": "ACDEFGHIKLMNPQRSTVWD",
                "chosen_id": "good-2",
                "rejected_id": "bad-2",
                "preference_rule": "pareto_dominance",
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pairs_path = tmp / "pairs.jsonl"
            output_dir = tmp / "out"
            pairs_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_tinker_dpo_smoke.py"),
                    "--name",
                    "shape-fixture",
                    "--pairs-path",
                    str(pairs_path),
                    "--output-dir",
                    str(output_dir),
                    "--shape-only",
                ],
                check=True,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            report = json.loads((output_dir / "shape-fixture" / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "shape_validated")
            self.assertFalse(report["tinker_client_created"])
            self.assertEqual(report["pair_count"], 2)
            self.assertEqual(report["datum_count"], 4)
            self.assertEqual(report["shape_summary"]["unique_prompt_count"], 1)
            self.assertEqual(report["shape_summary"]["preference_rules"]["hard_gate_pass"], 1)

    def test_train_cli_persists_batch_reports_with_fake_tinker(self) -> None:
        rows = [
            {
                "prompt": "Design a PETase-like hydrolase.",
                "chosen": "ACDEFGHIKLMNPQRSTVWY",
                "rejected": "ACDEFGHIKLMNPQRSTVWA",
            },
            {
                "prompt": "Design a PETase-like hydrolase.",
                "chosen": "ACDEFGHIKLMNPQRSTVWC",
                "rejected": "ACDEFGHIKLMNPQRSTVWD",
            },
            {
                "prompt": "Design a PETase-like hydrolase.",
                "chosen": "ACDEFGHIKLMNPQRSTVWE",
                "rejected": "ACDEFGHIKLMNPQRSTVWF",
            },
        ]
        fake_tinker = """
        class _Result:
            def __init__(self, value):
                self._value = value

            def result(self):
                return self._value

        class _MetricsResult:
            def __init__(self, metrics, loss_fn_outputs=None):
                self.metrics = metrics
                self.loss_fn_outputs = loss_fn_outputs or []

        class _TensorData:
            def __init__(self, values):
                self.data = list(values)
                self.shape = [len(values)]

        class _SavedState:
            def __init__(self, name):
                self.path = f"tinker://fake/{name}"

        class _Model:
            model_name = "fake-model"

        class _Capabilities:
            supported_models = [_Model()]

        class types:
            class AdamParams:
                def __init__(self, **kwargs):
                    self.kwargs = kwargs

            class EncodedTextChunk:
                def __init__(self, tokens):
                    self.tokens = list(tokens)

            class ModelInput:
                def __init__(self, tokens):
                    self.tokens = list(tokens)
                    self.length = len(self.tokens)

                @classmethod
                def from_ints(cls, tokens):
                    return cls(tokens)

                def append(self, chunk):
                    return types.ModelInput(self.tokens + list(chunk.tokens))

            class Datum:
                def __init__(self, *, model_input, loss_fn_inputs):
                    self.model_input = model_input
                    self.loss_fn_inputs = loss_fn_inputs

        class _Tokenizer:
            def encode(self, text, add_special_tokens=False):
                return [(ord(char) % 50) + 1 for char in text]

        class _TrainingClient:
            def __init__(self):
                self.step = 0

            def get_tokenizer(self):
                return _Tokenizer()

            def forward_backward_custom(self, batch_datums, dpo_loss_fn, loss_type_input=None):
                self.step += 1
                pair_count = len(batch_datums) // 2
                return _Result(_MetricsResult({
                    "dpo_loss": 0.5 - (self.step * 0.01),
                    "dpo_reward_margin_mean": float(self.step),
                    "dpo_reward_margin_min": 0.1,
                    "dpo_reward_margin_max": float(self.step) + 0.5,
                    "dpo_pair_count": float(pair_count),
                    "dpo_beta": 0.05,
                }))

            def forward(self, datums, loss_fn):
                outputs = []
                for datum in datums:
                    outputs.append({"logprobs": _TensorData([-1.0] * datum.model_input.length)})
                return _Result(_MetricsResult({}, outputs))

            def optim_step(self, adam_params):
                return _Result(_MetricsResult({"fake_optim_step": float(self.step)}))

            def save_state(self, name):
                return _Result(_SavedState(name))

        class ServiceClient:
            def get_server_capabilities(self):
                return _Capabilities()

            def create_lora_training_client(self, **kwargs):
                return _TrainingClient()

            def create_training_client_from_state(self, **kwargs):
                return _TrainingClient()
        """
        fake_wandb = """
        run = None

        def init(**kwargs):
            global run
            run = object()

        def log(data):
            return None

        def finish():
            global run
            run = None
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_modules = tmp / "fake_modules"
            fake_modules.mkdir()
            (fake_modules / "tinker.py").write_text(textwrap.dedent(fake_tinker), encoding="utf-8")
            (fake_modules / "wandb.py").write_text(textwrap.dedent(fake_wandb), encoding="utf-8")

            pairs_path = tmp / "pairs.jsonl"
            output_dir = tmp / "out"
            run_name = "fake-train"
            run_dir = output_dir / run_name
            run_dir.mkdir(parents=True)
            pairs_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join(
                part for part in [str(fake_modules), env.get("PYTHONPATH", "")] if part
            )

            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_tinker_dpo_smoke.py"),
                    "--name",
                    run_name,
                    "--pairs-path",
                    str(pairs_path),
                    "--output-dir",
                    str(output_dir),
                    "--model",
                    "fake-model",
                    "--batch-pairs",
                    "2",
                ],
                check=True,
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["pair_count"], 3)
            self.assertEqual(report["checkpoint_path"], "tinker://fake/fake-train")
            self.assertEqual(len(report["batches"]), 2)
            self.assertEqual([batch["batch_pair_count"] for batch in report["batches"]], [2, 1])
            self.assertEqual(report["batches"][0]["forward_backward_metrics"]["dpo_pair_count"], 2.0)
            self.assertEqual(report["batches"][1]["forward_backward_metrics"]["dpo_pair_count"], 1.0)


if __name__ == "__main__":
    unittest.main()
