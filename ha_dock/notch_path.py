"""The notch outline: convex body corners, concave flares into the bezel.

This is the one genuinely fiddly piece of painting, so it lives alone and
can be previewed with `python -m ha_dock.notch_path`.

The body is welded to one screen edge. Along that edge, instead of the body
simply stopping, the outline flares outward with a *reverse* arc so it reads
as part of the hardware bezel rather than a bar parked against it.

Those flares are quarter-*ellipses*, not quarter-circles, and that is the
whole trick. A circular flare reaches as far inward as it does along the
bezel, so a long smooth sweep would force a deep notch — which is exactly
backwards for something meant to sit unobtrusively on a screen edge.
Splitting the two radii lets the sweep run as far along the edge as you
like while cutting in only as deep as the notch actually is.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath


def notch_path(rect: QRectF, edge: str = "right", body_radius: float = 20.0,
               edge_radius: float = 12.0,
               edge_sweep: float | None = None) -> QPainterPath:
    """Outline for a notch occupying `rect`, welded to `edge`.

    `rect` is the visible body only.

    `edge_radius` is how deep the flare cuts in from the screen edge. Depth
    is the scarce axis, so the flare takes what it needs there first and the
    body's own corner radius lives on the remainder.

    `edge_sweep` is how far the flare reaches *along* the edge. It bleeds
    that far past `rect` at both ends, so the widget must leave the slack.
    Defaults to `edge_radius`, which gives the old circular corner.
    """
    across = rect.width() if edge in ("left", "right") else rect.height()
    along = rect.height() if edge in ("left", "right") else rect.width()
    if edge_sweep is None:
        edge_sweep = edge_radius

    er = max(0.0, min(edge_radius, across * 0.9))
    br = max(0.0, min(body_radius, across - er, along / 2))
    es = max(er, min(edge_sweep, along))

    if edge in ("left", "right"):
        return _vertical(rect, edge, br, er, es)
    return _horizontal(rect, edge, br, er, es)


def _vertical(r: QRectF, edge: str, br: float, er: float,
              es: float) -> QPainterPath:
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    p = QPainterPath()

    if edge == "right":
        rx = x + w                       # the screen edge itself
        # top flare: comes in along the bezel, curls down into the body
        p.moveTo(rx, y - es)
        p.arcTo(QRectF(rx - 2 * er, y - 2 * es, 2 * er, 2 * es), 0, -90)
        # top-left convex
        p.lineTo(x + br, y)
        p.arcTo(QRectF(x, y, 2 * br, 2 * br), 90, 90)
        # left side
        p.lineTo(x, y + h - br)
        # bottom-left convex
        p.arcTo(QRectF(x, y + h - 2 * br, 2 * br, 2 * br), 180, 90)
        # bottom flare
        p.lineTo(rx - er, y + h)
        p.arcTo(QRectF(rx - 2 * er, y + h, 2 * er, 2 * es), 90, -90)
    else:  # left edge — mirrored
        lx = x
        p.moveTo(lx, y - es)
        p.arcTo(QRectF(lx, y - 2 * es, 2 * er, 2 * es), 180, 90)
        p.lineTo(x + w - br, y)
        p.arcTo(QRectF(x + w - 2 * br, y, 2 * br, 2 * br), 90, -90)
        p.lineTo(x + w, y + h - br)
        p.arcTo(QRectF(x + w - 2 * br, y + h - 2 * br, 2 * br, 2 * br), 0, -90)
        p.lineTo(lx + er, y + h)
        p.arcTo(QRectF(lx, y + h, 2 * er, 2 * es), 90, 90)

    p.closeSubpath()
    return p


def _horizontal(r: QRectF, edge: str, br: float, er: float,
                es: float) -> QPainterPath:
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    p = QPainterPath()

    # Qt arc angles run counter-clockwise from 3 o'clock: 0 right, 90 top,
    # 180 left, 270 bottom. Getting a sweep sign wrong here sends the
    # outline across the body and folds it into a wedge.
    if edge == "top":
        by = y + h
        p.moveTo(x - es, y)
        p.arcTo(QRectF(x - 2 * es, y, 2 * es, 2 * er), 90, -90)
        p.lineTo(x, by - br)
        p.arcTo(QRectF(x, by - 2 * br, 2 * br, 2 * br), 180, 90)
        p.lineTo(x + w - br, by)
        p.arcTo(QRectF(x + w - 2 * br, by - 2 * br, 2 * br, 2 * br), 270, 90)
        p.lineTo(x + w, y + er)
        p.arcTo(QRectF(x + w, y, 2 * es, 2 * er), 180, -90)
    else:  # bottom
        ty = y
        p.moveTo(x - es, y + h)
        p.arcTo(QRectF(x - 2 * es, y + h - 2 * er, 2 * es, 2 * er), 270, 90)
        p.lineTo(x, ty + br)
        p.arcTo(QRectF(x, ty, 2 * br, 2 * br), 180, -90)
        p.lineTo(x + w - br, ty)
        p.arcTo(QRectF(x + w - 2 * br, ty, 2 * br, 2 * br), 90, -90)
        p.lineTo(x + w, y + h - er)
        p.arcTo(QRectF(x + w, y + h - 2 * er, 2 * es, 2 * er), 180, 90)

    p.closeSubpath()
    return p


if __name__ == "__main__":  # pragma: no cover - visual harness
    import sys
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtWidgets import QApplication, QWidget

    class Preview(QWidget):
        def paintEvent(self, _):
            q = QPainter(self)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            q.fillRect(self.rect(), QColor("#2E6F9E"))
            q.setBrush(QColor("#000000"))
            q.setPen(Qt.PenStyle.NoPen)
            body = QRectF(self.width() - 26, 160, 26, 160)
            q.drawPath(notch_path(body, "right", 14, 12, 60))

    app = QApplication(sys.argv)
    w = Preview()
    w.resize(420, 640)
    w.show()
    sys.exit(app.exec())
