"""Build HA Dock into a single-folder Windows app with PyInstaller.

    .venv\\Scripts\\python.exe build.py            # onedir (starts fast)
    .venv\\Scripts\\python.exe build.py --onefile  # single exe, slower start

Output lands in dist\\HA Dock\\. Onedir is the default because a onefile
build unpacks to a temp directory on every launch, which is the wrong
trade-off for something that sits in the tray all day.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
NAME = "HA Dock"


def ensure_icon() -> Path | None:
    """PyInstaller wants .ico. Convert the PNG if no .ico is present."""
    ico = ASSETS / "hadock.ico"
    if ico.exists():
        return ico
    png = next((p for p in (ASSETS / "hadock.png", ASSETS / "icon.png")
                if p.exists()), None)
    if png is None:
        return None
    try:
        from PIL import Image

        img = Image.open(png).convert("RGBA")
        img.save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64),
                             (128, 128), (256, 256)])
        return ico
    except Exception as exc:
        print(f"!! could not build an .ico ({exc}); building without one")
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onefile", action="store_true",
                    help="one exe instead of a folder")
    ap.add_argument("--clean", action="store_true",
                    help="wipe build/ and dist/ first")
    args = ap.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("!! PyInstaller is not installed. Run:")
        print("   .venv\\Scripts\\python.exe -m pip install pyinstaller")
        return 1

    if args.clean:
        for d in (ROOT / "build", ROOT / "dist"):
            shutil.rmtree(d, ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--windowed", "--name", NAME,
        "--onefile" if args.onefile else "--onedir",
        # qtawesome ships its icon fonts as package data, and PyInstaller
        # does not find them on its own
        "--collect-data", "qtawesome",
        # keyring resolves its Windows backend at runtime
        "--hidden-import", "keyring.backends.Windows",
        "--hidden-import", "win32timezone",
        # the single-instance guard talks over a local socket
        "--hidden-import", "PySide6.QtNetwork",
        "--exclude-module", "tkinter",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtQuick3D",
        "--exclude-module", "PySide6.Qt3DCore",
    ]

    if ASSETS.exists():
        cmd += ["--add-data", f"{ASSETS}{__import__('os').pathsep}assets"]

    icon = ensure_icon()
    if icon:
        cmd += ["--icon", str(icon)]

    cmd.append(str(ROOT / "run.py"))

    print("->", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        return proc.returncode

    out = ROOT / "dist" / (f"{NAME}.exe" if args.onefile else NAME)
    print(f"\nOK  built {out}")
    if not args.onefile:
        print(f"OK  launch {out / (NAME + '.exe')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
