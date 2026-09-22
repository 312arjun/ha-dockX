"""Render the app mark to assets/hadock.png and assets/hadock.ico.

The mark is drawn from the Material Design Icons font at runtime, so the
icon files are generated rather than checked in — one source of truth.

    .venv\\Scripts\\python.exe tools\\make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from ha_dock import theme, ui_kit  # noqa: E402

SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> int:
    app = QApplication(sys.argv)  # noqa: F841  (needed for font loading)
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(exist_ok=True)

    png = assets / "hadock.png"
    ui_kit.app_icon(512, theme.BRAND).save(str(png))
    print(f"OK  {png}")

    try:
        from PIL import Image

        ico = assets / "hadock.ico"
        Image.open(png).convert("RGBA").save(
            ico, sizes=[(s, s) for s in SIZES])
        print(f"OK  {ico}")
    except ImportError:
        print("!! Pillow not installed, so no .ico was written.")
        print("   .venv\\Scripts\\python.exe -m pip install pillow")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
