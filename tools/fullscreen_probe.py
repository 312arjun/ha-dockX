"""Report what Windows says about the foreground window, once a second.

Run it, then maximise Chrome, then play something fullscreen, and compare
the lines. This exists because 'maximised' and 'fullscreen' are not
distinguishable from the window rectangle alone.

    .venv\\Scripts\\python.exe tools\\fullscreen_probe.py
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

u = ctypes.windll.user32

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_POPUP = 0x80000000
SM_CXSCREEN, SM_CYSCREEN = 0, 1
SPI_GETWORKAREA = 0x0030


def work_area() -> wintypes.RECT:
    r = wintypes.RECT()
    u.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
    return r


def main() -> int:
    screen_w = u.GetSystemMetrics(SM_CXSCREEN)
    screen_h = u.GetSystemMetrics(SM_CYSCREEN)
    wa = work_area()
    print(f"screen   {screen_w}x{screen_h}")
    print(f"workarea {wa.left},{wa.top} -> {wa.right},{wa.bottom}")
    print("Ctrl+C to stop.\n")
    print(f"{'class':<26}{'rect':<30}{'zoomed':<8}"
          f"{'caption':<9}{'covers':<8}title")

    last = ""
    while True:
        hwnd = u.GetForegroundWindow()
        if hwnd:
            cls = ctypes.create_unicode_buffer(128)
            u.GetClassNameW(hwnd, cls, 128)
            title = ctypes.create_unicode_buffer(160)
            u.GetWindowTextW(hwnd, title, 160)
            r = wintypes.RECT()
            u.GetWindowRect(hwnd, ctypes.byref(r))
            style = u.GetWindowLongW(hwnd, GWL_STYLE)
            zoomed = bool(u.IsZoomed(hwnd))
            caption = bool(style & WS_CAPTION)
            covers = (r.left <= 0 and r.top <= 0
                      and r.right >= screen_w and r.bottom >= screen_h)
            line = (f"{cls.value[:25]:<26}"
                    f"{f'{r.left},{r.top} {r.right},{r.bottom}':<30}"
                    f"{str(zoomed):<8}{str(caption):<9}{str(covers):<8}"
                    f"{title.value[:40]}")
            if line != last:
                print(line, flush=True)
                last = line
        time.sleep(1)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(0)
