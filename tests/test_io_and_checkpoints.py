from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.checkpoints import load_sampler_checkpoint_map, persist_sampler_checkpoint_mapping
from pearl.io_utils import atomic_write_json, load_json_object


class IOAndCheckpointTests(unittest.TestCase):
    def test_atomic_write_and_load_json_object_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "payload.json"
            payload = {"alpha": 1, "beta": "two"}
            atomic_write_json(path, payload)
            self.assertEqual(load_json_object(path), payload)

    def test_load_json_object_rejects_non_object_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "payload.json"
            path.write_text('["not", "an", "object"]', encoding="utf-8")
            self.assertIsNone(load_json_object(path))

    def test_sampler_checkpoint_map_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "map.json"
            persist_sampler_checkpoint_mapping(
                path,
                training_checkpoint_path="tinker://train/weights/a",
                sampler_checkpoint_path="tinker://train/sampler_weights/a",
            )
            persist_sampler_checkpoint_mapping(
                path,
                training_checkpoint_path="tinker://train/weights/b",
                sampler_checkpoint_path="tinker://train/sampler_weights/b",
            )
            self.assertEqual(
                load_sampler_checkpoint_map(path),
                {
                    "tinker://train/weights/a": "tinker://train/sampler_weights/a",
                    "tinker://train/weights/b": "tinker://train/sampler_weights/b",
                },
            )


if __name__ == "__main__":
    unittest.main()
