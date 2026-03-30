from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pearl.detached_jobs import DEFAULT_GRACE_SECONDS, stop_detached


def main() -> None:
    args = parse_args()
    payload = stop_detached(
        Path(args.metadata_path),
        grace_seconds=args.grace_seconds,
        kill_wait_seconds=args.kill_wait_seconds,
    )
    if not payload["stopped"]:
        raise SystemExit(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop a detached PEARL job and its full process group")
    parser.add_argument("--metadata-path", required=True)
    parser.add_argument("--grace-seconds", type=float, default=DEFAULT_GRACE_SECONDS)
    parser.add_argument("--kill-wait-seconds", type=float, default=2.0)
    return parser.parse_args()


if __name__ == "__main__":
    main()
