"""Make the package importable however the suite was started.

``pyproject.toml`` sets ``pythonpath = ["src"]`` for pytest, which covers the
normal case. This covers the ones that are not normal: a coverage run started
from a different directory, an editor's test runner, and anybody who types
``pytest`` with a plugin that resets the path. The suite either finds the source
tree beside it or it does not run, and failing here with a clear reason beats
failing in the first import with an unclear one.
"""

from __future__ import annotations

import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "src"

if not SOURCE.is_dir():  # pragma: no cover - only fires on a broken checkout
    raise RuntimeError(f"no source tree at {SOURCE}")

if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
