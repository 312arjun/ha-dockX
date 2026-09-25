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
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_NOOWNERZORDER = 0x0200

HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)
HWND_BOTTOM = wintypes.HWND(1)
GW_HWNDNEXT = 2
GW_HWNDPREV = 3
HWND_TOP = wintypes.HWND(0)

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
user32.GetTopWindow.argtypes = [wintypes.HWND]
user32.GetTopWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetWindow.restype = wintypes.HWND
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.GetShellWindow.argtypes = []
user32.GetShellWindow.restype = wintypes.HWND


def make_tool_window(hwnd: int, topmost: bool = True) -> None:
    """No focus stealing, no taskbar entry, no Alt-Tab entry.

    `topmost` decides which band it lands in. A desktop-layer widget wants
    False, then push_bottom — otherwise this call would drag it to the top
    and the two would fight each other every tick.
    """
    h = wintypes.HWND(hwnd)
    cur = user32.GetWindowLongW(h, GWL_EXSTYLE)
    user32.SetWindowLongW(
        h, GWL_EXSTYLE, cur | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    # a style change only takes effect once the frame is recalculated
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED \
        | SWP_NOOWNERZORDER
    if topmost:
        user32.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, flags)
    else:
        user32.SetWindowPos(h, HWND_NOTOPMOST, 0, 0, 0, 0,
                            flags | SWP_NOZORDER)


def raise_topmost(hwnd: int) -> bool:
    h = wintypes.HWND(hwnd)
    return bool(user32.SetWindowPos(
        h, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER))


def desktop_window() -> int:
    """The highest window in the desktop layer.

    Progman owns the desktop, but with a wallpaper slideshow a WorkerW
    sits above it holding the actual bitmap. We want whichever is higher.
    """
    cur = user32.GetTopWindow(None)
    while cur:
        buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(cur, buf, 64)
        if buf.value in ("Progman", "WorkerW") \
                and user32.IsWindowVisible(cur):
            return int(cur)
        cur = user32.GetWindow(cur, GW_HWNDNEXT)
    shell = user32.GetShellWindow()
    return int(shell) if shell else 0


def place_above_desktop(hwnd: int) -> bool:
    """Sit immediately above the desktop window, wherever that is.

    Three traps. HWND_BOTTOM is wrong because Show Desktop *raises* the
    desktop above everything, so a window at the absolute bottom ends up
    beneath the wallpaper. SetWindowPos's hWndInsertAfter places the window
    *behind* the one you name, so naming the desktop puts you under it. And
    HWND_NOTOPMOST is itself a z-order move — it lifts the window to the
    top of the ordinary band — so calling it on a timer makes the window
    flash above everything before being sunk again. Hence: clear topmost
    only if it is actually set, and do nothing at all when already in the
    right place.
    """
    h = wintypes.HWND(hwnd)
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER
    desk = desktop_window()
    if not desk:
        return False

    below = user32.GetWindow(h, GW_HWNDNEXT)
    if below and int(below) == desk and not is_topmost(hwnd):
        return True                 # already correct — touch nothing

    if is_topmost(hwnd):
        user32.SetWindowPos(h, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        desk = desktop_window()     # that move may have shuffled things

    above = user32.GetWindow(wintypes.HWND(desk), GW_HWNDPREV)
    if not above or int(above) == hwnd:
        return bool(user32.SetWindowPos(h, HWND_TOP, 0, 0, 0, 0, flags))
    return bool(user32.SetWindowPos(
        h, wintypes.HWND(int(above)), 0, 0, 0, 0, flags))


def push_bottom(hwnd: int) -> bool:
    """Sink the window to the bottom of the z-order — above the wallpaper,
    below every ordinary window.

    This is how a desktop widget behaves: it is simply *there* on the
    desktop, and anything you open covers it. Two calls are needed. The
    first clears WS_EX_TOPMOST, because a window in the topmost band
    cannot be moved below a normal one; the second drops it to the bottom.
    """
    h = wintypes.HWND(hwnd)
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER
    user32.SetWindowPos(h, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    return bool(user32.SetWindowPos(h, HWND_BOTTOM, 0, 0, 0, 0, flags))


def is_at_bottom(hwnd: int) -> bool:
    """True when no ordinary window sits below us — ignoring the shell,
    which owns the wallpaper and always sits underneath everything."""
    shell = {"Progman", "WorkerW"}
    cur = user32.GetTopWindow(None)
    seen_self = False
    while cur:
        if int(cur) == hwnd:
            seen_self = True
        elif seen_self and user32.IsWindowVisible(cur) \
                and not user32.IsIconic(cur):
            buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(cur, buf, 64)
            if buf.value not in shell:
                return False
        cur = user32.GetWindow(cur, GW_HWNDNEXT)
    return seen_self


SW_SHOWNOACTIVATE = 4
SW_MINIMIZE = 6


def is_iconic(hwnd: int) -> bool:
    return bool(user32.IsIconic(wintypes.HWND(hwnd)))


def unminimise(hwnd: int) -> bool:
    """Bring a minimised window back without giving it focus.

    Show Desktop (Win+D) minimises every top-level window, tool windows
    included, so a desktop-layer widget has to undo it.
    """
    return bool(user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE))


def minimise(hwnd: int) -> bool:
    return bool(user32.ShowWindow(wintypes.HWND(hwnd), SW_MINIMIZE))


def is_topmost(hwnd: int) -> bool:
    """Only the *style bit*. Do not trust this to mean the window is
    actually drawn on top: Windows can leave WS_EX_TOPMOST set while
    placing the window down in the ordinary z-order band, which is exactly
    how the notch ended up buried under a maximised window. Use
    is_really_topmost for the truth, or just re-assert unconditionally.
    """
    ex = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
    return bool(ex & WS_EX_TOPMOST)


def is_really_topmost(hwnd: int) -> bool:
    """Walk the z-order and check nothing non-topmost sits above us."""
    cur = user32.GetTopWindow(None)
    while cur:
        if int(cur) == hwnd:
            return True
        if (user32.IsWindowVisible(cur)
                and not user32.IsIconic(cur)
                and not (user32.GetWindowLongW(cur, GWL_EXSTYLE)
                         & WS_EX_TOPMOST)):
            return False        # a normal window is above us
        cur = user32.GetWindow(cur, GW_HWNDNEXT)
    return False


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
