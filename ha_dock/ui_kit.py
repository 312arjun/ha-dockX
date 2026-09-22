"""Reusable pieces for the settings window.

Qt's stock widgets carry a lot of platform chrome that fights the design,
so the parts that need to look exactly right — the title bar, the toggle,
the primary button, the status pill — are painted here instead.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRectF,
                            QSize, Qt, Property, Signal, QTimer)
from PySide6.QtGui import (QColor, QFont, QIcon, QImage, QPainter, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect,
                               QGraphicsOpacityEffect, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QSizePolicy,
                               QStyle, QStyleOption, QTableWidget,
                               QVBoxLayout, QWidget)

from . import glyph, theme


class Styled(QWidget):
    """Qt ignores stylesheet backgrounds on plain QWidget subclasses unless
    they paint the style primitive themselves. Every custom widget here that
    carries a background inherits this."""

    def paintEvent(self, _ev):
        opt = QStyleOption()
        opt.initFrom(self)
        q = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, q,
                                   self)


# --- small helpers --------------------------------------------------------
def icon_pixmap(name: str, size: int, color: str) -> QPixmap:
    pm = QPixmap(QSize(size, size))
    pm.setDevicePixelRatio(1.0)
    pm.fill(Qt.GlobalColor.transparent)
    q = QPainter(pm)
    q.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    q.setFont(glyph.font(name, size))
    q.setPen(QColor(color))
    q.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, glyph.char_for(name))
    q.end()
    return pm


ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _keyed(pm: QPixmap, threshold: int = 26) -> QPixmap:
    """Drop a flat near-black background to transparency.

    Artwork exported as RGB carries no alpha, so on a light button it lands
    as a black tile. Anything darker than `threshold` becomes transparent,
    and pixels just above it fade in, which keeps the edges smooth.
    """
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            lum = max(c.red(), c.green(), c.blue())
            if lum <= threshold:
                c.setAlpha(0)
                img.setPixelColor(x, y, c)
            elif lum < threshold * 3:
                c.setAlpha(int(255 * (lum - threshold) / (threshold * 2)))
                img.setPixelColor(x, y, c)
    return QPixmap.fromImage(img)


def button_icon(name: str, size: int, color: str) -> QIcon:
    """Accepts a qtawesome name or a file in assets/. A supplied image is
    used as-is — recolouring someone's artwork would defeat the point."""
    if name.lower().endswith((".png", ".svg", ".ico", ".jpg")):
        path = Path(name)
        if not path.is_absolute():
            path = ASSETS / path.name
        if path.exists():
            pm = QPixmap(str(path))
            if not pm.isNull():
                pm = pm.scaled(size * 2, size * 2,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                if not pm.hasAlphaChannel():
                    pm = _keyed(pm)
                return QIcon(pm.scaled(
                    size, size, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
        name = "mdi6.image-off-outline"
    return QIcon(icon_pixmap(name, size, color))


def icon_label(name: str, size: int, color: str, parent=None) -> QLabel:
    lab = QLabel(parent)
    lab.setPixmap(icon_pixmap(name, size, color))
    lab.setFixedSize(size + 2, size + 2)
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lab.setStyleSheet("background: transparent;")
    return lab


def text_label(text: str, size: int, color: str, weight=QFont.Weight.Normal,
               parent=None) -> QLabel:
    lab = QLabel(text, parent)
    f = lab.font()
    f.setPixelSize(size)
    f.setWeight(weight)
    lab.setFont(f)
    lab.setStyleSheet(f"color: {color}; background: transparent;")
    return lab


def glow(widget: QWidget, color: str, blur: int = 28, alpha: int = 150,
         dy: int = 4) -> None:
    eff = QGraphicsDropShadowEffect(widget)
    c = QColor(color)
    c.setAlpha(alpha)
    eff.setColor(c)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    widget.setGraphicsEffect(eff)


# --- containers -----------------------------------------------------------
class Card(QFrame):
    """A rounded panel with a hairline border and a faint top-down lift."""

    def __init__(self, parent=None, radius: int = theme.CARD_RADIUS):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(f"""
            QFrame#card {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.PANEL_HI}, stop:1 {theme.PANEL});
                border: 1px solid {theme.HAIRLINE};
                border-radius: {radius}px;
            }}
        """)


class SectionHeading(QWidget):
    """Cyan tick, title, subtitle. The tick encodes 'you are here'."""

    def __init__(self, title: str, subtitle: str = "", big: bool = True,
                 parent=None):
        super().__init__(parent)
        tick = QFrame(self)
        tick.setFixedWidth(3)
        tick.setStyleSheet(
            f"background: {theme.SIGNAL}; border-radius: 1px;")

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4 if big else 2)
        col.addWidget(text_label(title, 26 if big else 16, theme.TEXT,
                                 QFont.Weight.DemiBold, self))
        if subtitle:
            col.addWidget(text_label(subtitle, 13, theme.MUTED,
                                     parent=self))

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(tick)
        row.addLayout(col, 1)
        tick.setFixedHeight(46 if big else 22)


class StatusPill(QFrame):
    """Dot, state word, and a quiet timestamp — one glanceable unit."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pill")
        self.setStyleSheet(f"""
            QFrame#pill {{ background: {theme.RAISED};
                           border: 1px solid {theme.HAIRLINE};
                           border-radius: 18px; }}
        """)
        self.dot = QLabel(self)
        self.dot.setFixedSize(9, 9)
        self.state = text_label("Not connected", 13, theme.MUTED,
                                QFont.Weight.DemiBold, self)
        self.detail = text_label("", 12, theme.MUTED, parent=self)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 8, 18, 8)
        row.setSpacing(10)
        row.addWidget(self.dot)
        row.addWidget(self.state)
        row.addWidget(self.detail)
        self.set_state(False, "Not connected", "")

    def set_state(self, ok: bool, text: str, detail: str = "") -> None:
        colour = theme.GOOD if ok else theme.MUTED
        self.dot.setStyleSheet(
            f"background: {colour}; border-radius: 4px;")
        self.state.setText(text)
        self.state.setStyleSheet(f"color: {colour}; background: transparent;")
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))


class FieldRow(QWidget):
    """Icon + label + hint on the left, the control on the right."""

    def __init__(self, icon: str, label: str, hint: str, control: QWidget,
                 parent=None, label_width: int = 340):
        super().__init__(parent)
        left = QWidget(self)
        left.setFixedWidth(label_width)
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(14)
        ll.addWidget(icon_label(icon, 21, theme.SIGNAL, left),
                     0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        col.addWidget(text_label(label, 15, theme.TEXT,
                                 QFont.Weight.DemiBold, left))
        col.addWidget(text_label(hint, 12, theme.MUTED, parent=left))
        ll.addLayout(col, 1)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(24)
        row.addWidget(left, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(control, 1, Qt.AlignmentFlag.AlignVCenter)
        # the row must be at least as tall as its control, or a 46px field
        # gets clipped by the layout's idea of the label column's height
        self.setMinimumHeight(max(control.minimumHeight(), 48))


class Stat(QWidget):
    """One reading in the footer strip: icon, name, value, qualifier."""

    def __init__(self, icon: str, name: str, value: str, note: str,
                 parent=None):
        super().__init__(parent)
        self.value_label = text_label(value, 16, theme.TEXT,
                                      QFont.Weight.DemiBold, self)
        self.note_label = text_label(note, 12, theme.MUTED, parent=self)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(text_label(name, 12, theme.MUTED, parent=self))
        col.addWidget(self.value_label)
        col.addWidget(self.note_label)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(icon_label(icon, 22, theme.SIGNAL, self),
                      0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(col, 1)

    def set(self, value: str, note: str) -> None:
        self.value_label.setText(value)
        self.note_label.setText(note)


def divider(vertical: bool = False, parent=None) -> QFrame:
    f = QFrame(parent)
    if vertical:
        f.setFixedWidth(1)
    else:
        f.setFixedHeight(1)
    f.setStyleSheet(f"background: {theme.HAIRLINE}; border: 0;")
    return f


# --- controls -------------------------------------------------------------
class Toggle(QWidget):
    """An iOS-style switch. Qt's checkbox indicator can't be made to slide,
    and the slide is what tells you the state changed."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = checked
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, v: float) -> None:
        self._pos = float(v)
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, on: bool, animate: bool = True) -> None:
        on = bool(on)
        if on == self._checked:
            return
        self._checked = on
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(1.0 if on else 0.0)
            self._anim.start()
        else:
            self._set_knob(1.0 if on else 0.0)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)

    def paintEvent(self, _ev):
        q = QPainter(self)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(0, 0, self.width(), self.height())

        track_on = QColor(theme.SIGNAL)
        track_off = QColor(theme.HAIRLINE)
        track = QColor(
            int(track_off.red() + (track_on.red() - track_off.red()) * self._pos),
            int(track_off.green() + (track_on.green() - track_off.green()) * self._pos),
            int(track_off.blue() + (track_on.blue() - track_off.blue()) * self._pos),
        )
        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(track)
        q.drawRoundedRect(r, r.height() / 2, r.height() / 2)

        pad = 3.0
        d = r.height() - pad * 2
        x = pad + (r.width() - d - pad * 2) * self._pos
        q.setBrush(QColor("#FFFFFF"))
        q.drawEllipse(QRectF(x, pad, d, d))


class PrimaryButton(QPushButton):
    """The one loud control on a page. Gradient plus its own glow.

    `icon` is either a qtawesome name or a path to an image in assets/.
    """

    def __init__(self, text: str, icon: str = "", parent=None,
                 icon_size: int = 20):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)
        if icon:
            self.setIcon(button_icon(icon, icon_size, "#04121C"))
            self.setIconSize(QSize(icon_size, icon_size))
        f = self.font()
        f.setPixelSize(16)
        f.setWeight(QFont.Weight.DemiBold)
        self.setFont(f)
        self.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {theme.SIGNAL}, stop:1 {theme.SIGNAL_DEEP});
                color: #04121C; border: 0; border-radius: 11px;
                padding: 0 26px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #5CE2FF, stop:1 #3BA8FF);
            }}
            QPushButton:pressed {{ background: {theme.SIGNAL_DEEP}; }}
            QPushButton:disabled {{ background: {theme.HAIRLINE};
                                    color: {theme.MUTED}; }}
        """)
        glow(self, theme.SIGNAL, blur=34, alpha=120, dy=6)


class GhostButton(QPushButton):
    """Everything that isn't the one loud control."""

    def __init__(self, text: str, icon: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(40)
        if icon:
            self.setIcon(QIcon(icon_pixmap(icon, 17, theme.SIGNAL)))
            self.setIconSize(QSize(17, 17))
        self.setStyleSheet(f"""
            QPushButton {{ background: {theme.RAISED}; color: {theme.TEXT};
                           border: 1px solid {theme.HAIRLINE};
                           border-radius: 10px; padding: 0 18px;
                           font-size: 13px; }}
            QPushButton:hover {{ border: 1px solid {theme.SIGNAL};
                                 color: {theme.SIGNAL}; }}
            QPushButton:pressed {{ background: {theme.PANEL}; }}
        """)


class DangerButton(QPushButton):
    """Destructive actions. Red gradient with its own glow, so it never
    gets clicked by accident in a row of quiet ghost buttons."""

    def __init__(self, text: str, icon: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(48)
        if icon:
            self.setIcon(button_icon(icon, 18, "#FFFFFF"))
            self.setIconSize(QSize(18, 18))
        f = self.font()
        f.setPixelSize(15)
        f.setWeight(QFont.Weight.DemiBold)
        self.setFont(f)
        self.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {theme.DANGER}, stop:1 {theme.DANGER_DEEP});
                color: #FFFFFF; border: 0; border-radius: 11px;
                padding: 0 26px; }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #FF5C77, stop:1 #F02D5E); }}
            QPushButton:pressed {{ background: {theme.DANGER_DEEP}; }}
        """)
        glow(self, theme.DANGER, blur=30, alpha=130, dy=5)


class OutlineButton(QPushButton):
    """The quiet half of a two-button footer."""

    def __init__(self, text: str, icon: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(48)
        if icon:
            self.setIcon(button_icon(icon, 18, theme.SIGNAL))
            self.setIconSize(QSize(18, 18))
        f = self.font()
        f.setPixelSize(15)
        f.setWeight(QFont.Weight.DemiBold)
        self.setFont(f)
        self.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {theme.TEXT};
                border: 1px solid {theme.SIGNAL}; border-radius: 11px;
                padding: 0 26px; }}
            QPushButton:hover {{ background: rgba(56,214,245,22); }}
            QPushButton:pressed {{ background: rgba(56,214,245,40); }}
        """)


class RailEntry(Styled):
    """A destination in the left rail. Selected state gets the cyan tick
    and a tinted ground; nothing else moves."""

    def __init__(self, icon: str, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(66)
        self._selected = False
        self._icon_name = icon

        self.icon = icon_label(icon, 20, theme.MUTED, self)
        self.title = text_label(title, 15, theme.TEXT_DIM,
                                QFont.Weight.DemiBold, self)
        self.subtitle = text_label(subtitle, 12, theme.MUTED, parent=self)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        col.addStretch(1)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        col.addStretch(1)

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 14, 0)
        row.setSpacing(16)
        row.addWidget(self.icon)
        row.addLayout(col, 1)
        self._restyle()

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self._restyle()

    def _restyle(self) -> None:
        if self._selected:
            self.setStyleSheet(f"""
                RailEntry {{ background: qlineargradient(x1:0, y1:0, x2:1,
                    y2:0, stop:0 rgba(56,214,245,26),
                    stop:1 rgba(56,214,245,6));
                    border-left: 3px solid {theme.SIGNAL};
                    border-top: 1px solid {theme.HAIRLINE};
                    border-right: 1px solid {theme.HAIRLINE};
                    border-bottom: 1px solid {theme.HAIRLINE};
                    border-radius: 12px; }}
            """)
            self.icon.setPixmap(icon_pixmap(self._icon_name, 20, theme.SIGNAL))
            self.title.setStyleSheet(
                f"color: {theme.TEXT}; background: transparent;")
        else:
            self.setStyleSheet("RailEntry { background: transparent;"
                               " border: 0; }")
            self.icon.setPixmap(icon_pixmap(self._icon_name, 20, theme.MUTED))
            self.title.setStyleSheet(
                f"color: {theme.TEXT_DIM}; background: transparent;")


class AppBadge(QLabel):
    """The rounded-square home mark used in the title bar and the rail."""

    def __init__(self, size: int = 40, parent=None, colour: str = ""):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setStyleSheet("background: transparent;")
        self._size = size
        self._colour = colour or theme.BRAND
        self.setPixmap(self._render())

    def _render(self) -> QPixmap:
        s = self._size
        pm = QPixmap(QSize(s, s))
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        q.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(0.5, 0.5, s - 1, s - 1)
        q.setPen(QPen(QColor(theme.HAIRLINE_HI), 1))
        q.setBrush(QColor(theme.RAISED))
        q.drawRoundedRect(r, s * 0.28, s * 0.28)
        q.setFont(glyph.font("mdi6.home-assistant", int(s * 0.56)))
        q.setPen(QColor(self._colour))
        q.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter,
                   glyph.char_for("mdi6.home-assistant"))
        q.end()
        return pm


def app_icon(size: int = 256, colour: str = "") -> QPixmap:
    """The bare mark, no plate — for the tray, the taskbar and the .ico."""
    pm = QPixmap(QSize(size, size))
    pm.fill(Qt.GlobalColor.transparent)
    q = QPainter(pm)
    q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    q.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    q.setFont(glyph.font("mdi6.home-assistant", int(size * 0.86)))
    q.setPen(QColor(colour or theme.BRAND))
    q.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter,
               glyph.char_for("mdi6.home-assistant"))
    q.end()
    return pm


class WindowButton(QPushButton):
    def __init__(self, icon: str, danger: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedSize(42, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(QIcon(icon_pixmap(icon, 15, theme.TEXT_DIM)))
        self.setIconSize(QSize(15, 15))
        hover = theme.ALERT if danger else theme.HAIRLINE
        self.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: 0;
                           border-radius: 7px; }}
            QPushButton:hover {{ background: {hover}; }}
        """)


class TitleBar(Styled):
    """Frameless chrome. Drag anywhere on the bar, double-click to maximise."""

    def __init__(self, window: QWidget, tagline: str = "", parent=None):
        super().__init__(parent)
        self.window_ref = window
        self.setFixedHeight(72)
        self._drag_from: QPoint | None = None

        name = text_label("HA Dock", 19, theme.TEXT, QFont.Weight.DemiBold,
                          self)
        sub = text_label("Your Home Assistant Companion", 12, theme.MUTED,
                         parent=self)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(name)
        col.addWidget(sub)

        self.tagline = text_label(tagline, 12, theme.MUTED, parent=self)

        self.btn_min = WindowButton("mdi6.window-minimize", parent=self)
        self.btn_max = WindowButton("mdi6.window-maximize", parent=self)
        self.btn_close = WindowButton("mdi6.window-close", danger=True,
                                      parent=self)
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max.clicked.connect(self._toggle_max)
        self.btn_close.clicked.connect(window.close)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(4)
        controls.addWidget(self.btn_min)
        controls.addWidget(self.btn_max)
        controls.addWidget(self.btn_close)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
        right.addLayout(controls)
        right.addWidget(self.tagline, 0, Qt.AlignmentFlag.AlignRight)

        row = QHBoxLayout(self)
        row.setContentsMargins(22, 14, 16, 12)
        row.setSpacing(16)
        row.addWidget(AppBadge(40, self))
        row.addLayout(col)
        row.addStretch(1)
        row.addLayout(right)

        self.setStyleSheet(
            f"TitleBar {{ background: transparent;"
            f" border-bottom: 1px solid {theme.HAIRLINE}; }}")

    def _toggle_max(self) -> None:
        w = self.window_ref
        if w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_from = ev.globalPosition().toPoint() \
                - self.window_ref.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        if self._drag_from and not self.window_ref.isMaximized():
            self.window_ref.move(
                ev.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, _ev):
        self._drag_from = None

    def mouseDoubleClickEvent(self, _ev):
        self._toggle_max()


class RailFooter(QWidget):
    """Identity block at the foot of the rail."""

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        badge = AppBadge(52, self)
        name = text_label("HA Dock", 20, theme.TEXT, QFont.Weight.DemiBold,
                          self)
        ver = text_label(f"v{version}", 12, theme.MUTED, parent=self)
        tag = text_label("A smaller window\nfor a smarter home", 12,
                         theme.MUTED, parent=self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 18, 24)
        lay.setSpacing(6)
        lay.addWidget(badge)
        lay.addSpacing(6)
        lay.addWidget(name)
        lay.addWidget(ver)
        lay.addSpacing(4)
        lay.addWidget(tag)
        self.setStyleSheet("background: transparent;")


class ReorderTable(QTableWidget):
    """A table whose rows are dragged to reorder and whose columns keep
    their proportions at any window width.

    Qt's own InternalMove drag is no use here: the rows carry cell widgets
    (combo boxes, spin boxes, buttons) and those do not travel with a moved
    row, so the move leaves the controls behind. Instead the drag is
    tracked by hand and the reorder is applied to the store, which then
    rebuilds the rows — widgets and all.
    """

    reordered = Signal(int, int)        # from_row, to_row

    def __init__(self, rows: int, cols: int, parent=None):
        super().__init__(rows, cols, parent)
        self._drag_row = -1
        self._drop_row = -1
        self._weights: dict[int, float] = {}
        self._minimums: dict[int, int] = {}
        self.setMouseTracking(True)

    # -- proportional columns --------------------------------------------
    def set_weights(self, weights: dict[int, float],
                    minimums: dict[int, int] | None = None) -> None:
        self._weights = dict(weights)
        self._minimums = dict(minimums or {})
        self._apply_weights()

    def _apply_weights(self) -> None:
        if not self._weights:
            return
        total = self.viewport().width()
        if total <= 0:
            return
        cols = sorted(self._weights)
        weight_sum = sum(self._weights.values()) or 1.0
        floor = {c: self._minimums.get(c, 30) for c in cols}

        # Start from the weighted share, then lift anything under its floor.
        widths = {c: max(floor[c], int(total * self._weights[c] / weight_sum))
                  for c in cols}

        # Lifting can overshoot the viewport, which is what pushed the last
        # column off the edge. Claw the excess back from whichever columns
        # still have headroom above their own floor.
        excess = sum(widths.values()) - total
        while excess > 0:
            donors = [c for c in cols if widths[c] > floor[c]]
            headroom = sum(widths[c] - floor[c] for c in donors)
            if not donors or headroom <= 0:
                break
            for c in donors:
                if excess <= 0:
                    break
                take = min(widths[c] - floor[c],
                           max(1, round(excess * (widths[c] - floor[c])
                                        / headroom)))
                widths[c] -= take
                excess -= take

        # any rounding slack goes to the widest column, where it shows least
        slack = total - sum(widths.values())
        if slack:
            widest = max(cols, key=lambda c: self._weights[c])
            widths[widest] = max(floor[widest], widths[widest] + slack)

        hh = self.horizontalHeader()
        for col in cols:
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(col, widths[col])

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._apply_weights()

    # -- drag to reorder --------------------------------------------------
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_row = self.rowAt(int(ev.position().y()))
            self._drop_row = -1
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_row >= 0 and (ev.buttons() & Qt.MouseButton.LeftButton):
            y = int(ev.position().y())
            row = self.rowAt(y)
            if row < 0:
                row = self.rowCount() - 1 if y > 0 else 0
            if row != self._drop_row:
                self._drop_row = row
                self.viewport().update()
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        src, dst = self._drag_row, self._drop_row
        self._drag_row = -1
        self._drop_row = -1
        self.viewport().update()
        super().mouseReleaseEvent(ev)
        if src >= 0 and dst >= 0 and src != dst:
            self.reordered.emit(src, dst)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self._drag_row < 0 or self._drop_row < 0:
            return
        y = self.rowViewportPosition(self._drop_row)
        if self._drop_row > self._drag_row:
            y += self.rowHeight(self._drop_row)
        q = QPainter(self.viewport())
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        q.setPen(QPen(QColor(theme.SIGNAL), 2))
        q.drawLine(6, y, self.viewport().width() - 6, y)
        q.end()


class Toast(Styled):
    """A brief confirmation that fades itself out.

    A modal dialog for 'saved' would need dismissing every time, which
    turns a reassurance into an obstacle. This floats over the bottom of
    the window, says what happened, and leaves.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          True)
        self.icon = icon_label("mdi6.check-circle", 18, theme.GOOD, self)
        self.text = text_label("", 13, theme.TEXT, QFont.Weight.DemiBold,
                               self)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 11, 20, 11)
        row.setSpacing(11)
        row.addWidget(self.icon)
        row.addWidget(self.text)

        self.setStyleSheet(f"""
            Toast#toast {{ background: {theme.RAISED};
                border: 1px solid {theme.HAIRLINE_HI};
                border-radius: 10px; }}
        """)
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._fade = QPropertyAnimation(self._fx, b"opacity", self)
        self._fade.setDuration(180)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, message: str, ok: bool = True,
                     hold_ms: int = 2400) -> None:
        self.text.setText(message)
        self.icon.setPixmap(icon_pixmap(
            "mdi6.check-circle" if ok else "mdi6.alert-circle",
            18, theme.GOOD if ok else theme.ALERT))
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(self._fx.opacity())
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._hold.start(hold_ms)

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._fx.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()
        QTimer.singleShot(220, self.hide)

    def _reposition(self) -> None:
        p = self.parentWidget()
        if p is None:
            return
        self.move(max(12, (p.width() - self.width()) // 2),
                  max(12, p.height() - self.height() - 28))


class EdgeResizer:
    """Edge and corner resizing for a frameless window.

    The work is handed to the platform with startSystemResize rather than
    recomputing geometry on every mouse move. That buys native resize
    cursors, Aero Snap and correct behaviour on a multi-monitor desktop —
    all of which a hand-rolled version gets subtly wrong.

    The window needs a transparent margin at least MARGIN wide, or there is
    nowhere to grab: child widgets consume the events everywhere else.
    """

    MARGIN = 7

    def __init__(self, window: QWidget):
        self.w = window
        window.setMouseTracking(True)

    def edge_at(self, pos: QPoint) -> Qt.Edge:
        m = self.MARGIN
        w, h = self.w.width(), self.w.height()
        edges = Qt.Edge(0)
        if pos.x() <= m:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= w - m:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= m:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= h - m:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def cursor_for(edges: Qt.Edge) -> Qt.CursorShape:
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        if top or bottom:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def update_cursor(self, pos: QPoint) -> None:
        if self.w.isMaximized():
            self.w.unsetCursor()
            return
        self.w.setCursor(self.cursor_for(self.edge_at(pos)))

    def begin(self, pos: QPoint) -> bool:
        """True if a resize was started, so the caller can stop there."""
        if self.w.isMaximized():
            return False
        edges = self.edge_at(pos)
        if not edges:
            return False
        handle = self.w.windowHandle()
        if handle is None:
            return False
        return bool(handle.startSystemResize(edges))
