"""Isolated resize diagnostic — a bare frameless window with the exact
same flags as the settings window, but with the grab margin painted a
bright colour and every mouse event printed live.

Run it, then try dragging each edge and corner of the coloured border.

    .venv\\Scripts\\python.exe tools\\resize_diagnostic.py

What to report back:
  - Does the console print anything at all when you click inside the
    coloured border? (tells us whether OS clicks reach the window there)
  - Does the window actually resize when you drag?
  - Does the cursor change to a resize arrow when hovering the border?
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget  # noqa: E402

from ha_dock.ui_kit import EdgeResizer  # noqa: E402

MARGIN = 14


class DiagWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(300, 200)
        self.resize(600, 400)
        self.resizer = EdgeResizer(self)

        inner = QWidget(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        lay.addWidget(inner)
        inner.setStyleSheet("background:#111; border-radius:8px;")
        label = QLabel(
            "Drag the coloured border.\nWatch the console.", inner)
        label.setStyleSheet("color:white; font-size:16px;")
        QVBoxLayout(inner).addWidget(
            label, 0, Qt.AlignmentFlag.AlignCenter)

    def paintEvent(self, ev):
        q = QPainter(self)
        q.fillRect(self.rect(), QColor(255, 80, 0, 140))  # the grab margin
        super().paintEvent(ev)

    def mousePressEvent(self, ev):
        pos = ev.position().toPoint()
        edges = self.resizer.edge_at(pos)
        print(f"PRESS  at {pos.x()},{pos.y()}  edges={edges}", flush=True)
        if edges and self.resizer.begin(pos):
            print("  -> resize STARTED", flush=True)
            return
        print("  -> no edge matched, not starting a resize", flush=True)

    def mouseMoveEvent(self, ev):
        if self.resizer.is_active():
            self.resizer.update(ev.globalPosition().toPoint())
            return
        self.resizer.update_cursor(ev.position().toPoint())

    def mouseReleaseEvent(self, ev):
        if self.resizer.is_active():
            print(f"RELEASE -> final size {self.width()}x{self.height()}",
                  flush=True)
            self.resizer.end()


def main() -> int:
    app = QApplication(sys.argv)
    w = DiagWindow()
    w.show()
    print(f"window shown at {w.geometry()}  margin={MARGIN}px "
          f"(the orange border)")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
