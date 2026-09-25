"""Rewrite ha_dock/__init__.py's __version__ to match a tag. Called by CI.

    .venv\\Scripts\\python.exe tools\\set_version.py v1.2.0
    .venv\\Scripts\\python.exe tools\\set_version.py 1.2.0
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

INIT = Path(__file__).resolve().parent.parent / "ha_dock" / "__init__.py"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: set_version.py <version>", file=sys.stderr)
        return 1
    version = sys.argv[1].lstrip("vV")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        print(f"!! '{version}' is not X.Y.Z", file=sys.stderr)
        return 1

    text = INIT.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'__version__\s*=\s*"[^"]*"', f'__version__ = "{version}"', text)
    if n != 1:
        print(f"!! expected exactly one __version__ line, found {n}",
              file=sys.stderr)
        return 1
    INIT.write_text(new_text, encoding="utf-8")
    print(f"OK  __version__ = \"{version}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
