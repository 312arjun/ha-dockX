"""Start-with-Windows via a .lnk in the user's Startup folder.

Uses the write-script / execute / delete pattern, because inline PowerShell
with `$` variables gets mangled by shell escaping.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

SHORTCUT_NAME = "HA Dock.lnk"

_PS_CREATE = r"""
$shell = New-Object -ComObject WScript.Shell
$folder = $shell.SpecialFolders.Item('{folder}')
if (-not $folder) {{ $folder = [Environment]::GetFolderPath('{netfolder}') }}
$link = Join-Path $folder '{name}'
$sc = $shell.CreateShortcut($link)
$sc.TargetPath = '{target}'
$sc.Arguments = '{args}'
$sc.WorkingDirectory = '{workdir}'
$sc.IconLocation = '{icon}'
$sc.WindowStyle = 7
$sc.Description = 'HA Dock'
$sc.Save()
Write-Output $link
"""

_PS_REMOVE = r"""
$shell = New-Object -ComObject WScript.Shell
$folder = $shell.SpecialFolders.Item('{folder}')
if (-not $folder) {{ $folder = [Environment]::GetFolderPath('{netfolder}') }}
$link = Join-Path $folder '{name}'
if (Test-Path $link) {{ Remove-Item $link -Force }}
Write-Output 'removed'
"""


def _project_root() -> Path:
    if getattr(sys, "frozen", False):          # PyInstaller build
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _launch_target() -> tuple[str, str]:
    """(target, arguments) — the exe directly when frozen, else pythonw."""
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), ""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    runner = pyw if pyw.exists() else exe
    return str(runner), f'"{_project_root() / "run.py"}"'


def _icon_path() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())
    ico = _project_root() / "assets" / "hadock.ico"
    return str(ico) if ico.exists() else ""


def _pythonw() -> Path:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return candidate if candidate.exists() else exe


def _run_ps(script: str) -> tuple[bool, str]:
    tmp = Path(tempfile.gettempdir()) / "ha_dock_shortcut.ps1"
    try:
        tmp.write_text(script, encoding="utf-8")
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(tmp)],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0:
            return False, (proc.stderr or "PowerShell failed").strip()
        return True, proc.stdout.strip()
    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _set_shortcut(enabled: bool, folder: str, netfolder: str) -> tuple[bool, str]:
    if enabled:
        target, args = _launch_target()
        script = _PS_CREATE.format(
            name=SHORTCUT_NAME, folder=folder, netfolder=netfolder,
            target=target, args=args, workdir=str(_project_root()),
            icon=_icon_path(),
        )
    else:
        script = _PS_REMOVE.format(name=SHORTCUT_NAME, folder=folder,
                                   netfolder=netfolder)
    return _run_ps(script)


def set_autostart(enabled: bool) -> tuple[bool, str]:
    """Shortcut in the Startup folder, so HA Dock launches at sign-in."""
    return _set_shortcut(enabled, "Startup", "Startup")


def set_desktop_shortcut(enabled: bool) -> tuple[bool, str]:
    """Shortcut on the Desktop. Goes through GetFolderPath as a fallback,
    because a OneDrive-redirected Desktop is not where you would guess."""
    return _set_shortcut(enabled, "Desktop", "DesktopDirectory")
