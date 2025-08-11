"""Run the command line with ``python -m quenchline``.

The console script installed by the package is the usual way in. This exists so
the package can be run out of a checkout without installing it, which is what
the shop's nightly job does on a machine nobody wants to pip install onto.
"""

from __future__ import annotations

import sys

from .cli.main import run


def entry() -> int:
    """Run the command line and give back a shell exit code."""
    return run(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(entry())
