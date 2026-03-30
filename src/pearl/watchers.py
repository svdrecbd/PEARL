from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path


DEFAULT_POLL_SECONDS = 20.0


def wait_for_path(path: Path, *, poll_seconds: float = DEFAULT_POLL_SECONDS) -> None:
    while not path.exists():
        time.sleep(poll_seconds)


def wait_for_path_or_abort(
    path: Path,
    *,
    should_abort: Callable[[], bool],
    poll_seconds: float = DEFAULT_POLL_SECONDS,
) -> bool:
    while not path.exists():
        if should_abort():
            return False
        time.sleep(poll_seconds)
    return True
