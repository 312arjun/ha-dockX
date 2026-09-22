"""Modal dialogs with the app's own chrome.

QMessageBox draws its own platform frame and icon, neither of which can be
restyled, so anything the person has to read carefully is built here.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QVBoxLayout, QWidget)

from . import glyph, theme
from .ui_kit import (AppBadge, DangerButton, OutlineButton, PrimaryButton,
                     Styled, WindowButton, icon_label, text_label)


def _emblem(icon: str, colour: str, size: int = 132) -> QPixmap:
    """A big glyph on a tinted rounded plate with a halo behind it."""
    pm = QPixmap(QSize(size, size))
    pm.fill(Qt.GlobalColor.transparent)
    q = QPainter(pm)
    q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    q.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    base = QColor(colour)
    for inset, alpha in ((0, 14), (10, 22), (20, 30)):
        ring = QColor(base)
        ring.setAlpha(alpha)
        q.setPen(QPen(ring, 1.5))
        q.setBrush(Qt.BrushStyle.NoBrush)
        r = QRectF(inset + 1, inset + 1, size - 2 * inset - 2,
                   size - 2 * inset - 2)
        q.drawRoundedRect(r, (size - 2 * inset) * 0.28,
                          (size - 2 * inset) * 0.28)

    plate = QColor(base)
    plate.setAlpha(26)
    q.setPen(Qt.PenStyle.NoPen)
    q.setBrush(plate)
    inner = QRectF(size * 0.16, size * 0.16, size * 0.68, size * 0.68)
    q.drawRoundedRect(inner, size * 0.19, size * 0.19)

    q.setFont(glyph.font(icon, int(size * 0.42)))
    q.setPen(QColor(colour))
    q.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, glyph.char_for(icon))
    q.end()
    return pm


class Dialog(QDialog):
    """Frameless shell: badge, title, close, content, footer."""

    def __init__(self, title: str, parent=None, width: int = 720):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self._drag_from: QPoint | None = None

        self.root = QFrame(self)
        self.root.setObjectName("dlgroot")

        head = QWidget(self.root)
        head.setObjectName("dlghead")
        head.setFixedHeight(76)
        close = WindowButton("mdi6.close", danger=True, parent=head)
        close.setFixedSize(46, 40)
        close.clicked.connect(self.reject)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(20, 14, 16, 14)
        hl.setSpacing(16)
        hl.addWidget(AppBadge(42, head))
        hl.addWidget(text_label(title, 19, theme.TEXT,
                                QFont.Weight.DemiBold, head))
        hl.addStretch(1)
        hl.addWidget(close)

        self.content = QWidget(self.root)
        self.body = QHBoxLayout(self.content)
        self.body.setContentsMargins(30, 26, 30, 26)
        self.body.setSpacing(26)

        self.footer = QWidget(self.root)
        self.footer.setObjectName("dlgfoot")
        self.buttons = QHBoxLayout(self.footer)
        self.buttons.setContentsMargins(24, 18, 24, 20)
        self.buttons.setSpacing(14)
        self.buttons.addStretch(1)

        shell = QVBoxLayout(self.root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(head)
        shell.addWidget(self.content, 1)
        shell.addWidget(self.footer)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.addWidget(self.root)
        self.setFixedWidth(width)
        self._style()

    def _style(self) -> None:
        t = theme
        self.setStyleSheet(f"""
        QWidget {{ color: {t.TEXT}; font-family: "{t.UI_FAMILY}";
                   background: transparent; font-size: 13px; }}
        QFrame#dlgroot {{
            background: qlineargradient(x1:0, y1:0, x2:0.7, y2:1,
                stop:0 #0C1B2B, stop:0.6 {t.SHELL}, stop:1 #050B13);
            border: 1px solid {t.SIGNAL}; border-radius: 16px; }}
        QWidget#dlghead {{ border-bottom: 1px solid {t.HAIRLINE}; }}
        QWidget#dlgfoot {{ border-top: 1px solid {t.HAIRLINE}; }}
        QFrame#itemlist {{ background: rgba(9,18,29,160);
            border: 1px solid {t.HAIRLINE}; border-radius: 12px; }}
        """)

    # drag by the head, same as the main window
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton \
                and ev.position().y() < 76:
            self._drag_from = ev.globalPosition().toPoint() \
                - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        if self._drag_from:
            self.move(ev.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, _ev):
        self._drag_from = None


class ConfirmDialog(Dialog):
    """Emblem on the left, the question and its consequences on the right."""

    def __init__(self, title: str, question: str, tail: str = "",
                 items: list[str] | None = None, note: str = "",
                 confirm: str = "Confirm", confirm_icon: str = "",
                 destructive: bool = True, parent=None):
        super().__init__(title, parent)
        colour = theme.DANGER if destructive else theme.SIGNAL

        emblem = QLabel(self.content)
        emblem.setPixmap(_emblem(
            "mdi6.alert-outline" if destructive
            else "mdi6.help-circle-outline", colour))
        emblem.setFixedSize(132, 132)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(18)

        head = QLabel(self.content)
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setWordWrap(True)
        head.setText(
            f'<span style="font-size:23px; font-weight:600; '
            f'color:{theme.TEXT};">{question}</span>'
            f'<span style="font-size:23px; color:{theme.MUTED};"> '
            f'{tail}</span>')
        right.addWidget(head)

        if items:
            box = QFrame(self.content)
            box.setObjectName("itemlist")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(18, 8, 18, 8)
            bl.setSpacing(0)
            for i, name in enumerate(items):
                if i:
                    rule = QFrame(box)
                    rule.setFixedHeight(1)
                    rule.setStyleSheet(f"background: {theme.HAIRLINE};")
                    bl.addWidget(rule)
                row = QHBoxLayout()
                row.setContentsMargins(0, 10, 0, 10)
                row.setSpacing(16)
                row.addWidget(icon_label("mdi6.cube-outline", 20,
                                         theme.SIGNAL, box))
                row.addWidget(text_label(name, 15, theme.TEXT, parent=box), 1)
                bl.addLayout(row)
            right.addWidget(box)

        if note:
            right.addWidget(text_label(note, 14, theme.MUTED,
                                       parent=self.content))
        right.addStretch(1)

        self.body.addWidget(emblem, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(right, 1)

        cancel = OutlineButton("Cancel", "mdi6.close")
        cancel.clicked.connect(self.reject)
        if destructive:
            go = DangerButton(confirm, confirm_icon or "mdi6.trash-can-outline")
        else:
            go = PrimaryButton(confirm, confirm_icon)
            go.setMinimumHeight(48)
        go.clicked.connect(self.accept)
        self.buttons.addWidget(cancel)
        self.buttons.addWidget(go)


def confirm(parent, title: str, question: str, tail: str = "",
            items: list[str] | None = None, note: str = "",
            confirm_text: str = "Confirm", confirm_icon: str = "",
            destructive: bool = True) -> bool:
    dlg = ConfirmDialog(title, question, tail, items, note, confirm_text,
                        confirm_icon, destructive, parent)
    return dlg.exec() == QDialog.DialogCode.Accepted


class Notice(Dialog):
    """A single message with one way out."""

    def __init__(self, title: str, message: str, detail: str = "",
                 icon: str = "mdi6.information-outline",
                 colour: str = "", parent=None):
        super().__init__(title, parent, width=560)
        colour = colour or theme.SIGNAL

        emblem = QLabel(self.content)
        emblem.setPixmap(_emblem(icon, colour, 104))
        emblem.setFixedSize(104, 104)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        msg = text_label(message, 17, theme.TEXT, QFont.Weight.DemiBold,
                         self.content)
        msg.setWordWrap(True)
        right.addWidget(msg)
        if detail:
            det = text_label(detail, 13, theme.MUTED, parent=self.content)
            det.setWordWrap(True)
            right.addWidget(det)
        right.addStretch(1)

        self.body.addWidget(emblem, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(right, 1)

        ok = OutlineButton("Close", "mdi6.check")
        ok.clicked.connect(self.accept)
        self.buttons.addWidget(ok)


def notice(parent, title: str, message: str, detail: str = "",
           icon: str = "mdi6.information-outline", colour: str = "") -> None:
    Notice(title, message, detail, icon, colour, parent).exec()
