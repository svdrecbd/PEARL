from __future__ import annotations

import sys
import warnings
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

warnings.warn(
    "Importing 'petase_family' from the repo root is deprecated; import from 'pearl.family' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from pearl.family import *  # noqa: F401,F403
