"""Declared Win32 entry points.

ctypes defaults every undeclared argument to a 32-bit C int. That is fine
for flags and coordinates, and silently wrong for handles: on x64 an HWND
is 64 bits, and HWND_TOPMOST is the sentinel value -1 passed *as a handle*.
Handing ctypes a bare Python -1 for that parameter does not reliably
produce the sentinel, so the call fails and the window quietly stops being
topmost — which is exactly how the notch disappeared behind a maximised
window.

Declaring argtypes fixes it, and returning the BOOL lets us tell whether
the call worked instead of assuming.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CAPTION = 0x00C00000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_NOOWNERZORDER = 0x0200

HWND_TOPMOST = wintypes.HWND(-1)

user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
user32.SetWindowPos.restype = wintypes.BOOL

user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND,
                                 ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short


def make_tool_window(hwnd: int) -> None:
    """No focus stealing, no taskbar entry, no Alt-Tab entry."""
    h = wintypes.HWND(hwnd)
    cur = user32.GetWindowLongW(h, GWL_EXSTYLE)
    user32.SetWindowLongW(
        h, GWL_EXSTYLE, cur | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    # a style change only takes effect once the frame is recalculated
    user32.SetWindowPos(
        h, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED
        | SWP_NOOWNERZORDER)


def raise_topmost(hwnd: int) -> bool:
    h = wintypes.HWND(hwnd)
    return bool(user32.SetWindowPos(
        h, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER))


def is_topmost(hwnd: int) -> bool:
    ex = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
    return bool(ex & WS_EX_TOPMOST)


def foreground_window() -> int:
    h = user32.GetForegroundWindow()
    return int(h) if h else 0


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    r = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
        return None
    return r.left, r.top, r.right, r.bottom


def is_zoomed(hwnd: int) -> bool:
    return bool(user32.IsZoomed(wintypes.HWND(hwnd)))


def has_caption(hwnd: int) -> bool:
    style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE)
    return bool(style & WS_CAPTION)


def mouse_button_down() -> bool:
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x01, 0x02))
