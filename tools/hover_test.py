"""Behavioural test for the notch's hover/pin state machine.

Drives the cursor poller with a fake pointer position rather than moving
the real one, so the auto-hide fix is proved rather than eyeballed.

    .venv\\Scripts\\python.exe tools\\hover_test.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QCursor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ha_dock import db, theme  # noqa: E402
from ha_dock.app import Application  # noqa: E402

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'OK ' if ok else 'FAIL'} {label}: {got!r} (want {want!r})")
    if not ok:
        FAILURES.append(label)


def settle(app: QApplication, notch, ms: int = 600) -> None:
    """Run the event loop long enough for animations to finish."""
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    tmp = Path(tempfile.mkdtemp(prefix="ha_dock_hover_"))
    store = db.Store(tmp / "hover.db")
    store.add_entity(db.EntityRow(entity_id="light.test",
                                  icon="mdi6.lightbulb"))
    ctl = Application(store=store)
    notch = ctl.notch
    notch.show()
    settle(app, notch, 300)

    inside = notch._hover_rect().center()
    outside = QPoint(inside.x() - 900, inside.y() - 900)
    original = QCursor.pos
    QCursor.pos = staticmethod(lambda: _pos[0])
    _pos = [outside]

    try:
        check("starts collapsed", round(notch.expansion, 2), 0.0)

        # 1. hover expands
        _pos[0] = inside
        settle(app, notch, 700)
        check("hover expands", round(notch.expansion), 1)

        # 2. leaving must NOT slam it shut — it waits out auto_collapse_s
        store.set("auto_collapse_s", 3)
        _pos[0] = outside
        settle(app, notch, 1400)
        check("still open 1.4s after leaving", round(notch.expansion), 1)

        # 3. …and folds once that delay has actually elapsed
        settle(app, notch, 2600)
        check("collapses after the delay", round(notch.expansion), 0)

        # 4. a pin holds it open regardless of the pointer
        _pos[0] = inside
        settle(app, notch, 700)
        notch._pinned = True
        _pos[0] = outside
        settle(app, notch, 4200)
        check("pin holds while away", round(notch.expansion), 1)

        # 5. a click anywhere else dismisses it, pinned or not
        notch._click_outside = lambda: True
        settle(app, notch, 700)
        check("click outside collapses", round(notch.expansion), 0)
        check("pin flag cleared", notch._pinned, False)
        notch._click_outside = lambda: False

        # 6. with no entities it must never expand
        store.delete_entity(store.entities()[0].row_id)
        notch.reload()
        _pos[0] = inside
        settle(app, notch, 900)
        check("empty stays collapsed", round(notch.expansion, 2), 0.0)
    finally:
        QCursor.pos = original
        ctl.client.stop()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all hover checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
