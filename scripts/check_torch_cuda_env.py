from __future__ import annotations

import json
import os
import socket
import sys

import torch


def main() -> None:
    payload: dict[str, object] = {
        "hostname": socket.gethostname(),
        "python_executable": sys.executable,
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "env": {
            "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "SGE_GPU": os.environ.get("SGE_GPU"),
        },
    }

    try:
        payload["cuda_available"] = torch.cuda.is_available()
        payload["cuda_device_count"] = torch.cuda.device_count()
    except Exception as exc:
        payload["cuda_probe_error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    if bool(payload["cuda_available"]):
        devices: list[dict[str, object]] = []
        for index in range(int(payload["cuda_device_count"])):
            devices.append(
                {
                    "index": index,
                    "name": torch.cuda.get_device_name(index),
                    "capability": torch.cuda.get_device_capability(index),
                }
            )
        payload["devices"] = devices
        try:
            tensor = torch.tensor([1.0, 2.0, 3.0], device="cuda")
            payload["cuda_tensor_sum"] = float(tensor.sum().item())
        except Exception as exc:
            payload["cuda_tensor_error"] = f"{type(exc).__name__}: {exc}"

    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
