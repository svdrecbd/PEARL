from __future__ import annotations

import argparse
import importlib
import json
from typing import Any

from transformers import AutoConfig


def main() -> None:
    args = parse_args()
    report = {
        "model_name": args.model_name,
        "python_modules": probe_modules(
            [
                "mlx",
                "mlx.core",
                "mlx.nn",
                "mlx_lm",
                "torch",
                "transformers",
            ]
        ),
    }

    config = AutoConfig.from_pretrained(args.model_name)
    report["hf_config"] = {
        "model_type": getattr(config, "model_type", None),
        "architectures": list(getattr(config, "architectures", []) or []),
    }
    report["mlx_backend_ready"] = is_mlx_backend_ready(report["hf_config"])
    if not report["mlx_backend_ready"]:
        report["mlx_blocker"] = (
            "The current proxy depends on masked-LM scoring for an ESM model. "
            "The installed MLX stack does not expose a ready ESM masked-LM backend, "
            "so torch/mps remains the production scorer."
        )

    print(json.dumps(report, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check whether the local ESM scorer can be migrated to MLX")
    parser.add_argument("--model-name", default="facebook/esm2_t6_8M_UR50D")
    return parser.parse_args()


def probe_modules(names: list[str]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name in names:
        try:
            module = importlib.import_module(name)
            results[name] = {
                "available": True,
                "version": getattr(module, "__version__", None),
            }
        except Exception as exc:  # pragma: no cover - diagnostic path
            results[name] = {
                "available": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
    return results


def is_mlx_backend_ready(config: dict[str, Any]) -> bool:
    model_type = str(config.get("model_type") or "").lower()
    architectures = [str(item).lower() for item in config.get("architectures", [])]
    if model_type in {"esm"}:
        return False
    if any("maskedlm" in item for item in architectures):
        return False
    return False


if __name__ == "__main__":
    main()
