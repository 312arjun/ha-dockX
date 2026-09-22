"""Run HA Dock with Qt warnings traced back to the Python line that caused
them.

    .venv\\Scripts\\python.exe tools\\run_traced.py

Qt warnings normally arrive as a bare line of text with no indication of
which call produced them. This installs a message handler that prints the
Python stack alongside, so a warning that only appears when you click
something can still be pinned down.

Filter to one kind of warning:

    .venv\\Scripts\\python.exe tools\\run_traced.py --match "Point size"
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import qInstallMessageHandler  # noqa: E402

SEEN: set[str] = set()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="",
                    help="only trace warnings containing this text")
    ap.add_argument("--all", action="store_true",
                    help="trace every repeat, not just the first of each")
    args = ap.parse_args()

    def handler(_mode, _ctx, message: str) -> None:
        if args.match and args.match.lower() not in message.lower():
            return
        if not args.all and message in SEEN:
            return
        SEEN.add(message)
        print(f"\n=== {message} ===", flush=True)
        # drop this frame; the interesting caller is above it
        print("".join(traceback.format_stack()[:-1]), flush=True)

    qInstallMessageHandler(handler)

    from ha_dock.app import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
