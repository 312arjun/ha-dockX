"""The detail card that slides out beside a tile.

Codenotch shows a read-only tooltip here. This one carries controls: a
brightness slider for a light, a speed slider for a fan, position for a
cover, volume and transport for a media player.

It is a separate top-level window rather than something painted inside the
notch, because a slider needs real mouse grabbing and the notch is a
masked, non-activating surface that swallows drags.
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QImage, QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from . import domains, theme

try:
    from . import win32
except Exception:  # pragma: no cover - non-Windows dev
    win32 = None

CARD_RADIUS = 16
CARD_PADDING = 16
CARD_WIDTH = 248
ARROW = 9
CARD_GAP = 30             # breathing room between the notch and the card
WHEEL_SIZE = 132
SEND_DEBOUNCE_MS = 160

POPUP_DOMAINS = {"light", "fan", "cover", "media_player", "climate"}
COLOUR_MODES = {"hs", "rgb", "rgbw", "rgbww", "xy"}


def supports_popup(entity_id: str) -> bool:
    """Whether a detail card would actually have anything to show."""
    return domains.domain_of(entity_id) in POPUP_DOMAINS


def supports_colour(attributes: dict) -> bool:
    modes = attributes.get("supported_color_modes") or []
    if isinstance(modes, str):
        modes = [modes]
    return bool(COLOUR_MODES.intersection(str(m).lower() for m in modes))


class ColourWheel(QWidget):
    """An HSV disc: hue around, saturation outward.

    The disc is rasterised once into a QImage and blitted thereafter —
    recomputing seventeen thousand pixels on every paint would make
    dragging the marker crawl.
    """

    picked = Signal(float, float)      # hue 0-360, saturation 0-100

    def __init__(self, diameter: int = WHEEL_SIZE, parent=None):
        super().__init__(parent)
        self._d = diameter
        self.setFixedSize(diameter, diameter)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._hue = 0.0
        self._sat = 0.0
        self._disc = self._render_disc()

    def _render_disc(self) -> QImage:
        d = self._d
        img = QImage(d, d, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        c = (d - 1) / 2.0
        for y in range(d):
            dy = y - c
            for x in range(d):
                dx = x - c
                r = math.hypot(dx, dy) / c
                if r > 1.0:
                    continue
                hue = (math.degrees(math.atan2(-dy, dx)) % 360.0) / 360.0
                img.setPixelColor(
                    x, y, QColor.fromHsvF(hue, min(1.0, r), 1.0))
        return img

    def set_hs(self, hue: float, sat: float) -> None:
        self._hue = hue % 360.0
        self._sat = max(0.0, min(100.0, sat))
        self.update()

    def _from_pos(self, pos) -> tuple[float, float]:
        c = (self._d - 1) / 2.0
        dx, dy = pos.x() - c, pos.y() - c
        r = min(1.0, math.hypot(dx, dy) / c)
        hue = math.degrees(math.atan2(-dy, dx)) % 360.0
        return hue, r * 100.0

    def mousePressEvent(self, ev):
        self._apply(ev.position())

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.MouseButton.LeftButton:
            self._apply(ev.position())

    def _apply(self, pos) -> None:
        hue, sat = self._from_pos(pos)
        self.set_hs(hue, sat)
        self.picked.emit(hue, sat)

    def paintEvent(self, _ev):
        q = QPainter(self)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        q.drawImage(0, 0, self._disc)

        c = (self._d - 1) / 2.0
        rad = self._sat / 100.0 * c
        angle = math.radians(self._hue)
        x = c + math.cos(angle) * rad
        y = c - math.sin(angle) * rad
        q.setBrush(Qt.BrushStyle.NoBrush)
        q.setPen(QPen(QColor("#0A0A0A"), 3))
        q.drawEllipse(QRectF(x - 7, y - 7, 14, 14))
        q.setPen(QPen(QColor("#FFFFFF"), 2))
        q.drawEllipse(QRectF(x - 7, y - 7, 14, 14))


class TilePopup(QWidget):
    """One card, reused for whichever tile is hovered."""

    closed = Signal()

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.entity_id = ""
        self.attributes: dict = {}
        self.state = ""
        self._suppress = False
        self._unit = ""
        self._arrow_y = 0.0
        self._arrow_side = "right"
        self._pending: tuple | None = None
        self._last_sent = 0.0
        self.on_color = ""

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.title = QLabel(self)
        self.title.setStyleSheet(
            f"color:{theme.TEXT}; font-size:14px; font-weight:600;"
            "background:transparent;")
        self.subtitle = QLabel(self)
        self.subtitle.setStyleSheet(
            f"color:{theme.MUTED}; font-size:11px; background:transparent;")
        self.value = QLabel(self)
        self.value.setStyleSheet(
            f"color:{theme.SIGNAL}; font-size:20px; font-weight:600;"
            "background:transparent;")

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.valueChanged.connect(self._slider_moved)
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ height: 6px; border-radius: 3px;
                background: {theme.HAIRLINE}; }}
            QSlider::sub-page:horizontal {{ height: 6px; border-radius: 3px;
                background: {theme.SIGNAL}; }}
            QSlider::handle:horizontal {{ width: 16px; height: 16px;
                margin: -6px 0; border-radius: 8px; background: #FFFFFF; }}
        """)

        self.buttons = QWidget(self)
        self.button_row = QHBoxLayout(self.buttons)
        self.button_row.setContentsMargins(0, 0, 0, 0)
        self.button_row.setSpacing(8)

        self.wheel = ColourWheel(WHEEL_SIZE, self)
        self.wheel.picked.connect(self._colour_picked)
        self.wheel_holder = QWidget(self)
        wh = QHBoxLayout(self.wheel_holder)
        wh.setContentsMargins(0, 4, 0, 2)
        wh.addStretch(1)
        wh.addWidget(self.wheel)
        wh.addStretch(1)
        self.wheel_holder.setVisible(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(CARD_PADDING + ARROW, CARD_PADDING,
                               CARD_PADDING + ARROW, CARD_PADDING)
        lay.setSpacing(6)
        lay.addWidget(self.title)
        lay.addWidget(self.subtitle)
        lay.addSpacing(6)
        lay.addWidget(self.value)
        lay.addWidget(self.slider)
        lay.addWidget(self.wheel_holder)
        lay.addWidget(self.buttons)

        self._send = QTimer(self)
        self._send.setSingleShot(True)
        self._send.timeout.connect(self._flush)

    # -- population -------------------------------------------------------
    def bind(self, entity_id: str, state: str, attributes: dict,
             label: str = "", on_color: str = "") -> None:
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}
        self.on_color = on_color or ""
        domain = domains.domain_of(entity_id)

        self.title.setText(label or domains.friendly_name(
            entity_id, self.attributes))
        self.subtitle.setText(entity_id)

        self._clear_buttons()
        self._suppress = True
        show_wheel = False
        try:
            if domain == "light":
                self._as_slider(self._light_pct(), "%")
                show_wheel = supports_colour(self.attributes)
                if show_wheel:
                    hs = self.attributes.get("hs_color")
                    if not hs and self.on_color:
                        # off, so there is no live colour to show — seed the
                        # marker from the configured one instead
                        c = QColor(self.on_color)
                        hs = (c.hueF() * 360.0, c.saturationF() * 100.0) \
                            if c.isValid() else (0, 0)
                    hs = hs or (0, 0)
                    try:
                        self.wheel.set_hs(float(hs[0]), float(hs[1]))
                    except (TypeError, ValueError, IndexError):
                        self.wheel.set_hs(0.0, 0.0)
                self._add_button("Off", lambda: self._call(
                    "light", "turn_off", {}))
                if self.on_color:
                    self._add_swatch_button(self.on_color)
                else:
                    self._add_button("White", lambda: self._call(
                        "light", "turn_on", {"hs_color": [0, 0]}))
            elif domain == "fan":
                self._as_slider(int(
                    self.attributes.get("percentage") or 0), "%")
                self._add_button("Off", lambda: self._call(
                    "fan", "turn_off", {}))
            elif domain == "cover":
                self._as_slider(int(
                    self.attributes.get("current_position") or 0), "%")
                self._add_button("Open", lambda: self._call(
                    "cover", "open_cover", {}))
                self._add_button("Stop", lambda: self._call(
                    "cover", "stop_cover", {}))
                self._add_button("Close", lambda: self._call(
                    "cover", "close_cover", {}))
            elif domain == "media_player":
                vol = self.attributes.get("volume_level") or 0
                self._as_slider(int(round(float(vol) * 100)), "%")
                self._add_button("Prev", lambda: self._call(
                    "media_player", "media_previous_track", {}))
                self._add_button("Play", lambda: self._call(
                    "media_player", "media_play_pause", {}))
                self._add_button("Next", lambda: self._call(
                    "media_player", "media_next_track", {}))
            elif domain == "climate":
                lo = int(float(self.attributes.get("min_temp", 7)))
                hi = int(float(self.attributes.get("max_temp", 35)))
                target = self.attributes.get("temperature")
                self._unit = "\u00b0"
                self.slider.setRange(lo, hi)
                self.slider.setValue(
                    int(target) if target is not None else lo)
                self.slider.setVisible(True)
                self.value.setText(f"{self.slider.value()}\u00b0")
                cur = self.attributes.get("current_temperature")
                if cur is not None:
                    self.subtitle.setText(
                        f"{entity_id}  \u00b7  now {cur}\u00b0")
            else:
                self.slider.setVisible(False)
                self.value.setText(domains.value_text(
                    entity_id, state, self.attributes))
        finally:
            self._suppress = False

        self.wheel_holder.setVisible(show_wheel)
        self.buttons.setVisible(self.button_row.count() > 0)
        self.setFixedWidth(CARD_WIDTH + ARROW * 2)
        self.adjustSize()

    def _colour_picked(self, hue: float, sat: float) -> None:
        if self._suppress or not self.entity_id:
            return
        self._pending = ("light", "turn_on",
                         {"hs_color": [round(hue, 1), round(sat, 1)]})
        self._send.start(SEND_DEBOUNCE_MS)

    def _light_pct(self) -> int:
        b = self.attributes.get("brightness")
        if b is None:
            return 100 if domains.is_on(self.state) else 0
        return int(round(float(b) / 255.0 * 100))

    def _as_slider(self, value: int, unit: str) -> None:
        self._unit = unit
        self.slider.setRange(0, 100)
        self.slider.setValue(max(0, min(100, value)))
        self.slider.setVisible(True)
        self.value.setText(f"{self.slider.value()}{unit}")

    def _clear_buttons(self) -> None:
        while self.button_row.count():
            item = self.button_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _add_button(self, text: str, handler) -> None:
        btn = QPushButton(text, self.buttons)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(30)
        btn.setStyleSheet(f"""
            QPushButton {{ background:{theme.RAISED}; color:{theme.TEXT};
                border:1px solid {theme.HAIRLINE}; border-radius:8px;
                padding:4px 10px; font-size:11px; }}
            QPushButton:hover {{ border:1px solid {theme.SIGNAL};
                color:{theme.SIGNAL}; }}
        """)
        btn.clicked.connect(handler)
        self.button_row.addWidget(btn)

    def _add_swatch_button(self, hex_colour: str) -> None:
        """The configured default, shown in its own colour so it is obvious
        what pressing it will do."""
        c = QColor(hex_colour)
        if not c.isValid():
            return
        btn = QPushButton("Default", self.buttons)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(30)
        ink = "#04121C" if c.lightnessF() > 0.55 else "#FFFFFF"
        btn.setStyleSheet(f"""
            QPushButton {{ background:{c.name()}; color:{ink};
                border:0; border-radius:8px; padding:4px 10px;
                font-size:11px; font-weight:600; }}
            QPushButton:hover {{ background:{c.lighter(115).name()}; }}
        """)
        btn.clicked.connect(lambda: self._call("light", "turn_on", {
            "rgb_color": [c.red(), c.green(), c.blue()]}))
        self.button_row.addWidget(btn)

    # -- sending ----------------------------------------------------------
    def _slider_moved(self, value: int) -> None:
        self.value.setText(f"{value}{self._unit}")
        if self._suppress or not self.entity_id:
            return
        domain = domains.domain_of(self.entity_id)
        payload = {
            "light": ("light", "turn_on", {"brightness_pct": value}),
            "fan": ("fan", "set_percentage", {"percentage": value}),
            "cover": ("cover", "set_cover_position", {"position": value}),
            "media_player": ("media_player", "volume_set",
                             {"volume_level": round(value / 100.0, 2)}),
            "climate": ("climate", "set_temperature",
                        {"temperature": value}),
        }.get(domain)
        if payload is None:
            return
        self._pending = payload
        # dragging emits on every pixel; without this the socket would take
        # sixty service calls a second
        self._send.start(SEND_DEBOUNCE_MS)

    def _flush(self) -> None:
        if not self._pending:
            return
        domain, service, data = self._pending
        self._pending = None
        self._last_sent = time.time()
        self.client.call_service(
            domain, service, target={"entity_id": self.entity_id}, data=data)

    def _call(self, domain: str, service: str, data: dict) -> None:
        self._last_sent = time.time()
        self.client.call_service(
            domain, service, target={"entity_id": self.entity_id}, data=data)

    def refresh(self, state: str, attributes: dict) -> None:
        """A state diff arrived. Ignored briefly after our own send, and
        while the handle is held, or the slider jumps under the finger."""
        if self.slider.isSliderDown():
            return
        if time.time() - self._last_sent < 1.5:
            return
        self.bind(self.entity_id, state, attributes, self.title.text(),
                  self.on_color)

    # -- placement --------------------------------------------------------
    def show_beside(self, anchor: QPoint, edge: str) -> None:
        """`anchor` is the tile's centre in screen coordinates."""
        self.adjustSize()
        w, h = self.width(), self.height()
        if edge == "right":
            pos = QPoint(anchor.x() - w - CARD_GAP, anchor.y() - h // 2)
            self._arrow_side = "right"
        elif edge == "left":
            pos = QPoint(anchor.x() + CARD_GAP, anchor.y() - h // 2)
            self._arrow_side = "left"
        elif edge == "top":
            pos = QPoint(anchor.x() - w // 2, anchor.y() + 30 + CARD_GAP)
            self._arrow_side = "none"
        else:
            pos = QPoint(anchor.x() - w // 2,
                         anchor.y() - h - 30 - CARD_GAP)
            self._arrow_side = "none"
        self._arrow_y = h / 2
        self.move(pos)
        self.show()
        self.raise_()
        self._apply_no_activate()

    def _apply_no_activate(self) -> None:
        if win32 is None:
            return
        try:
            win32.make_tool_window(int(self.winId()))
        except Exception:
            pass

    # -- painting ---------------------------------------------------------
    def paintEvent(self, _ev):
        q = QPainter(self)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(ARROW, 0, self.width() - ARROW * 2, self.height())

        path = QPainterPath()
        path.addRoundedRect(body, CARD_RADIUS, CARD_RADIUS)

        if self._arrow_side in ("right", "left"):
            nib = QPainterPath()
            if self._arrow_side == "right":
                x0, x1 = body.right(), body.right() + ARROW
            else:
                x0, x1 = body.left(), body.left() - ARROW
            nib.moveTo(x0, self._arrow_y - ARROW)
            nib.lineTo(x1, self._arrow_y)
            nib.lineTo(x0, self._arrow_y + ARROW)
            nib.closeSubpath()
            path = path.united(nib)

        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(QColor(theme.CARD_BG))
        q.drawPath(path)
