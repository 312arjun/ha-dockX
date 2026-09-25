"""Watch the Lampcord window while you press Win+D.

Run it, wait for 'watching', then press Win+D, wait two seconds, press
Win+D again. Paste the output back.

    .venv\\Scripts\\python.exe tools\\lampcord_probe.py
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

u = ctypes.windll.user32
dwm = ctypes.windll.dwmapi
GW_HWNDNEXT = 2
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x8
DWMWA_CLOAKED = 14


def cloaked(hwnd) -> int:
    v = ctypes.c_int(0)
    dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED,
                              ctypes.byref(v), ctypes.sizeof(v))
    return v.value


def snapshot():
    """z-index of the lampcord and of the desktop, plus its own state."""
    cord = desk = None
    info = {}
    h = u.GetTopWindow(None)
    i = 0
    while h:
        vis = bool(u.IsWindowVisible(h))
        r = wintypes.RECT()
        u.GetWindowRect(h, ctypes.byref(r))
        w, hh = r.right - r.left, r.bottom - r.top
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(h, cls, 64)
        if vis and not u.IsIconic(h) and w > 40 and hh > 40:
            i += 1
            if cls.value in ("Progman", "WorkerW") and desk is None:
                desk = i
        if 150 < w < 200 and 190 < hh < 240 and cls.value.startswith("Qt") \
                and cord is None:
            cord = i if vis else -1
            info = dict(hwnd=int(h), visible=vis,
                        iconic=bool(u.IsIconic(h)),
                        cloaked=cloaked(h),
                        topmost=bool(u.GetWindowLongW(h, GWL_EXSTYLE)
                                     & WS_EX_TOPMOST),
                        rect=(r.left, r.top, w, hh))
        h = u.GetWindow(h, GW_HWNDNEXT)
    return cord, desk, info


def main() -> int:
    cord, desk, info = snapshot()
    if not info:
        print("!! Lampcord window not found — is it running?")
        return 1
    print(f"lampcord hwnd={info['hwnd']}  rect={info['rect']}")
    print("\nwatching for 25s — press Win+D now, wait, then Win+D again\n")
    print(f"{'t':>6}  {'z':>4} {'desk':>5}  vis  icon cloak top  note")
    last = None
    start = time.time()
    while time.time() - start < 25:
        cord, desk, info = snapshot()
        line = (f"{cord} {desk} {info.get('visible')} {info.get('iconic')} "
                f"{info.get('cloaked')} {info.get('topmost')}")
        if line != last:
            note = ""
            if info.get("cloaked"):
                note = "CLOAKED by DWM"
            elif info.get("iconic"):
                note = "MINIMISED"
            elif cord and desk and cord > desk:
                note = "BELOW the desktop -> invisible"
            elif not info.get("visible"):
                note = "hidden"
            print(f"{time.time()-start:>6.1f}  {str(cord):>4} {str(desk):>5}"
                  f"   {str(info.get('visible'))[:1]}    "
                  f"{str(info.get('iconic'))[:1]}    "
                  f"{info.get('cloaked')}   "
                  f"{str(info.get('topmost'))[:1]}    {note}")
            last = line
        time.sleep(0.2)
    print("\ndone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
