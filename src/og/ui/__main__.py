"""python -m og.ui: serve the local controller page on loopback (Task 32).

HOST and port() are the pinned entry-point surface (wave 4 rev 2.2): loopback
only, OG_UI_PORT overrides the default 8765.
"""

from __future__ import annotations

import contextlib
import os
import sys

from og.ui.server import serve

HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def port() -> int:
    """OG_UI_PORT if set and valid, else 8765."""
    raw = os.environ.get("OG_UI_PORT")
    if raw is None or raw == "":
        return DEFAULT_PORT
    try:
        return int(raw)
    except ValueError:
        print(f"OG_UI_PORT must be an integer, got {raw!r}; using {DEFAULT_PORT}.", file=sys.stderr)
        return DEFAULT_PORT


def main() -> None:
    print(f"Obligation Graph UI on {HOST}:{port()} (Ctrl-C to stop).", file=sys.stderr)
    with contextlib.suppress(KeyboardInterrupt):
        serve(HOST, port())


if __name__ == "__main__":
    main()
