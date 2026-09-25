"""Update checking and self-update for the frozen build.

Polls the public repo's latest GitHub Release, compares versions, and — for
a frozen (PyInstaller) install — downloads the new build and hands off to a
detached script that waits for this process to exit, swaps the install
folder, and relaunches. Running from source has no folder to swap, so
"Update" there just opens the release page.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import __version__

REPO = "312arjun/ha-dockX"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
TIMEOUT = 10

_SWAP_PS1 = r"""
$exePath   = "{exe_path}"
$installDir = "{install_dir}"
$newDir    = "{new_dir}"
$backup    = "{backup_dir}"

for ($i = 0; $i -lt 30; $i++) {{
    try {{
        [IO.File]::Open($exePath, 'Open', 'ReadWrite', 'None').Close()
        break
    }} catch {{ Start-Sleep -Milliseconds 500 }}
}}

if (Test-Path $backup) {{ Remove-Item $backup -Recurse -Force }}
Rename-Item $installDir $backup -ErrorAction SilentlyContinue
try {{
    Move-Item $newDir $installDir -Force
    Start-Process (Join-Path $installDir "HA Dock.exe")
    Remove-Item $backup -Recurse -Force -ErrorAction SilentlyContinue
}} catch {{
    # the swap failed after we removed the old folder's name; put it back
    if (Test-Path $backup) {{ Rename-Item $backup $installDir -ErrorAction SilentlyContinue }}
    Start-Process (Join-Path $installDir "HA Dock.exe")
}}
"""


def _parse_version(v: str) -> tuple[int, ...]:
    v = v.lstrip("vV")
    parts = re.findall(r"\d+", v)[:3]
    parts += ["0"] * (3 - len(parts))
    return tuple(int(p) for p in parts)


def is_newer(remote: str, local: str = __version__) -> bool:
    return _parse_version(remote) > _parse_version(local)


class UpdateInfo:
    def __init__(self, data: dict):
        self.tag = data.get("tag_name", "")
        self.version = self.tag.lstrip("vV")
        self.notes = (data.get("body") or "").strip()
        self.html_url = data.get("html_url", "")
        self.asset_url = ""
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.startswith("HA-Dock-") and name.endswith(".zip"):
                self.asset_url = asset.get("browser_download_url", "")
                break


class UpdateChecker(QObject):
    """Runs the network check off the Qt thread."""

    found = Signal(object)      # UpdateInfo, when a newer release exists
    checked = Signal()          # always emitted when the check finishes
    failed = Signal(str)

    def check_async(self) -> None:
        threading.Thread(target=self._run, daemon=True,
                         name="update-check").start()

    def _run(self) -> None:
        try:
            req = urllib.request.Request(
                API_LATEST, headers={"Accept": "application/vnd.github+json",
                                     "User-Agent": "HA-Dock-Updater"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            info = UpdateInfo(data)
            if info.version and is_newer(info.version):
                self.found.emit(info)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.checked.emit()


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    """The folder holding HA Dock.exe and _internal, when frozen."""
    return Path(sys.executable).resolve().parent


class UpdateApplier(QObject):
    """Downloads, verifies, and hands off to the swap script.

    Every step is fail-soft: if the download, the zip, or the exe inside it
    is not what was expected, this stops and reports failure rather than
    touching the current install. The install folder is only ever renamed
    (never deleted) until the new one is confirmed moved into its place.
    """

    progress = Signal(str)
    failed = Signal(str)
    ready_to_restart = Signal()

    def apply_async(self, info: UpdateInfo) -> None:
        threading.Thread(target=self._run, args=(info,), daemon=True,
                         name="update-apply").start()

    def _run(self, info: UpdateInfo) -> None:
        if not info.asset_url:
            self.failed.emit("No build attached to that release")
            return
        try:
            self.progress.emit("Downloading…")
            work = Path(tempfile.mkdtemp(prefix="hadock_update_"))
            zpath = work / "update.zip"
            urllib.request.urlretrieve(info.asset_url, zpath)

            if not zipfile.is_zipfile(zpath):
                self.failed.emit("Downloaded file is not a valid archive")
                return

            self.progress.emit("Extracting…")
            new_dir = work / "new"
            with zipfile.ZipFile(zpath) as zf:
                zf.extractall(new_dir)

            if not (new_dir / "HA Dock.exe").exists():
                self.failed.emit("The build is missing HA Dock.exe")
                return

            installed = install_dir()
            backup = installed.parent / (installed.name + ".old")
            script = work / "swap.ps1"
            script.write_text(_SWAP_PS1.format(
                exe_path=str(installed / "HA Dock.exe"),
                install_dir=str(installed),
                new_dir=str(new_dir),
                backup_dir=str(backup),
            ), encoding="utf-8")

            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                 "-ExecutionPolicy", "Bypass", "-File", str(script)],
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            self.ready_to_restart.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


def open_release_page(info: UpdateInfo) -> None:
    if info.html_url:
        webbrowser.open(info.html_url)
