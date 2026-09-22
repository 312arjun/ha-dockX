"""Watch the notch's own z-order once a second.

The notch vanishing behind a maximised window is a z-order problem, and
z-order is invisible until you print it. This runs the real notch and
reports whether Windows still considers it topmost, whether the re-assert
call succeeds, and what has the foreground.

    .venv\\Scripts\\python.exe tools\\topmost_probe.py

Maximise Chrome over it and watch the `topmost` column.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ha_dock import db, win32  # noqa: E402
from ha_dock.ha_client import HaClient  # noqa: E402
from ha_dock.notch_window import NotchWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    tmp = Path(tempfile.mkdtemp(prefix="ha_dock_topmost_"))
    store = db.Store(tmp / "probe.db")
    store.add_entity(db.EntityRow(entity_id="light.probe",
                                  icon="mdi6.lightbulb"))
    store.set("hover_peek", 1)

    notch = NotchWindow(store, HaClient())
    notch.show()
    notch.expansion = 0.0

    state = {"n": 0, "last": ""}
    print(f"{'#':<5}{'visible':<9}{'topmost':<9}{'reassert':<10}"
          f"{'fs?':<6}foreground")

    def tick() -> None:
        hwnd = int(notch.winId())
        topmost = win32.is_topmost(hwnd)
        reasserted = ""
        if not topmost:
            reasserted = "YES" if win32.raise_topmost(hwnd) else "FAILED"
        fg = win32.foreground_window()
        cls = win32.window_class(fg) if fg else "-"
        zoom = "z" if fg and win32.is_zoomed(fg) else " "
        line = (f"{state['n']:<5}{str(notch.isVisible()):<9}"
                f"{str(topmost):<9}{reasserted:<10}"
                f"{str(notch._foreground_is_fullscreen()):<6}"
                f"{cls[:34]} {zoom}")
        state["n"] += 1
        if line[5:] != state["last"]:
            print(line, flush=True)
            state["last"] = line[5:]

    t = QTimer()
    t.timeout.connect(tick)
    t.start(1000)

    print("Ctrl+C in this window, or close the notch, to stop.\n")
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(0)
