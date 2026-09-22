"""Startup validation — constructs the whole app offscreen and paints the
notch at both ends of its animation. Catches import and paint regressions
without needing a live Home Assistant.

    .venv\\Scripts\\python.exe smoke.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ha_dock import db  # noqa: E402
from ha_dock.app import Application  # noqa: E402


def render(widget, path: Path) -> None:
    img = QImage(max(widget.width(), 1), max(widget.height(), 1),
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    widget.render(img)
    img.save(str(path))


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    tmp = Path(tempfile.mkdtemp(prefix="ha_dock_smoke_"))
    store = db.Store(tmp / "smoke.db")
    for eid, icon, mode in (
        ("light.smoke_lamp", "mdi6.lightbulb", "none"),
        ("switch.smoke_plug", "mdi6.power-socket-eu", "flat"),
        ("sensor.smoke_battery", "mdi6.battery", "ramp"),
    ):
        store.add_entity(db.EntityRow(entity_id=eid, icon=icon,
                                      ring_mode=mode))

    ctl = Application(store=store)
    checks = []

    for size in ("small", "medium", "large"):
        store.set("size", size)
        for edge in ("right", "left", "top"):
            store.set("edge", edge)
            ctl.notch.reload()
            for exp in (0.0, 0.5, 1.0):
                ctl.notch.expansion = exp
                render(ctl.notch, tmp / f"notch_{size}_{edge}_{exp}.png")
            checks.append(f"{size}/{edge}")

    ctl.settings.show()
    for i, name in enumerate(("connection", "entities", "appearance")):
        ctl.settings.set_page(i)
        app.processEvents()
        render(ctl.settings, tmp / f"settings_{name}.png")
    ctl.settings.set_page(0)
    ctl.settings.hide()

    from ha_dock.dialogs import ConfirmDialog, Notice

    dlg = ConfirmDialog(
        "Delete Entities", "Remove 2 entities", "from the notch?",
        items=["light.smoke_lamp", "switch.smoke_plug"],
        note="This only removes them from HA Dock.\n"
             "Nothing in Home Assistant is changed.",
        confirm="Delete", confirm_icon="mdi6.trash-can-outline")
    dlg.show()
    app.processEvents()
    render(dlg, tmp / "dialog_delete.png")
    dlg.close()

    note = Notice("Nothing selected", "No rows are ticked.",
                  "Tick the box at the left of a row.")
    note.show()
    app.processEvents()
    render(note, tmp / "dialog_notice.png")
    note.close()

    store.set("size", "medium")
    store.set("edge", "right")
    ctl.notch.reload()

    print(f"OK  notch rendered for: {', '.join(checks)}")
    print(f"OK  settings window constructed ({len(store.entities())} rows)")
    print(f"OK  artefacts in {tmp}")
    ctl.client.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
