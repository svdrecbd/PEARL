from __future__ import annotations

from pathlib import Path

from .io_utils import atomic_write_json, load_json_object


def load_sampler_checkpoint_map(map_path: Path) -> dict[str, str]:
    payload = load_json_object(map_path)
    if payload is None:
        return {}
    return {
        str(training_path): str(sampler_path)
        for training_path, sampler_path in payload.items()
        if isinstance(training_path, str) and isinstance(sampler_path, str)
    }


def persist_sampler_checkpoint_mapping(
    map_path: Path,
    *,
    training_checkpoint_path: str,
    sampler_checkpoint_path: str,
) -> None:
    checkpoint_map = load_sampler_checkpoint_map(map_path)
    checkpoint_map[training_checkpoint_path] = sampler_checkpoint_path
    atomic_write_json(map_path, checkpoint_map)

