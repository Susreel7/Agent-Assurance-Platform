"""Entry point for `python -m aap_cli`.

The `aap` console script is the documented invocation, but it only works if the
install put it on PATH. In a CI container that is often not true, and asking a
pipeline author to debug PATH is a good way to have the gate removed instead.
`python -m aap_cli` works wherever the package is importable.
"""

from __future__ import annotations

import sys

from aap_cli.main import main

if __name__ == "__main__":
    sys.exit(main())
