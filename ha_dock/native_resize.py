"""WM_NCHITTEST-based edge resize for a frameless window — ported from the
iPhone Companion project (ancs_notifier/dashboard.py), which is known to
work reliably.

Windows sends WM_NCHITTEST to ask "what part of the window is this point?".
A frameless window answers HTCLIENT everywhere, which is why it has no
resize borders at all. Answering HTLEFT/HTRIGHT/HTTOP/HTBOTTOM (and the
four corner combinations) at the screen edge hands the drag to the OS, so
it gets the correct cursors, snapping and DPI behaviour for free rather
than reimplementing drag-resize by tracking mouse deltas in Python — which
is what the previous EdgeResizer did, and which never reliably resized on
this machine.
"""

from __future__ import annotations

import ctypes

from PySide6.QtCore import QPoint

try:
    import ctypes.wintypes  # noqa: F401 - import error must not be fatal
    _WINTYPES = True
except (ImportError, ValueError):
    _WINTYPES = False

WM_NCHITTEST = 0x0084
RESIZE_BORDER = 6            # px of grab area inside each edge

_HT = {                      # (left, top, right, bottom) -> hit-test code
    (True, True, False, False): 13,    # HTTOPLEFT
    (False, True, True, False): 14,    # HTTOPRIGHT
    (True, False, False, True): 16,    # HTBOTTOMLEFT
    (False, False, True, True): 17,    # HTBOTTOMRIGHT
    (True, False, False, False): 10,   # HTLEFT
    (False, False, True, False): 11,   # HTRIGHT
    (False, True, False, False): 12,   # HTTOP
    (False, False, False, True): 15,   # HTBOTTOM
}


def native_resize_event(window, event_type, message, border: int = RESIZE_BORDER):
    """Call from the window's nativeEvent override. Returns (True, code)
    to claim the hit test, or None to let Qt handle it normally."""
    if not _WINTYPES or event_type != "windows_generic_MSG" \
            or window.isMaximized():
        return None
    try:
        msg = ctypes.wintypes.MSG.from_address(int(message))
    except (TypeError, ValueError):
        return None
    if msg.message != WM_NCHITTEST:
        return None

    # lParam packs screen coords as two signed 16-bit halves; masking
    # without sign-extending breaks on a monitor left of the primary,
    # where x is negative.
    x = ctypes.c_short(msg.lParam & 0xFFFF).value
    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
    local = window.mapFromGlobal(QPoint(x, y))
    edges = (local.x() <= border,
            local.y() <= border,
            local.x() >= window.width() - border,
            local.y() >= window.height() - border)
    code = _HT.get(edges)
    if code is not None:
        return True, code
    return None
