"""Retired command-line entry point.

DataInsight is now a browser-first application. Keeping this small module lets
``python -m src`` fail with an actionable message instead of running the old
single-file workflow against the v2 Snapshot model.
"""

from __future__ import annotations

import sys


def main() -> None:
    """Explain the supported application entry point."""
    print(
        "The DataInsight CLI has been retired. Start the web workspace with "
        "'uvicorn src.api.app:app --reload'.",
        file=sys.stderr,
    )
    raise SystemExit(2)


if __name__ == "__main__":
    main()
