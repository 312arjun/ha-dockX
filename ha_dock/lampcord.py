"""A pull-chain light switch that hangs from the top edge of the screen.

Drag the chain down and release past the threshold to toggle. The chain
extends by *tiling* its bead band rather than stretching it, so the beads
keep their size however far you pull — stretching a 70px chain to 160px
would visibly distort them.

The artwork is two PNGs in assets/. Their internal layout was measured
rather than guessed; see CHAIN below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation,
                            QRect, QRectF, Qt, QTimer, Property, Signal)
from PySide6.QtGui import QImage, QPainter, QRegion
from PySide6.QtWidgets import QWidget

ASSETS = Path(__file__).resolve().parent.parent / "assets"

try:
    from . import win32
except Exception:  # pragma: no cover - non-Windows dev
    win32 = None


@dataclass(frozen=True)
class ChainArt:
    """Bands within chain.png, in source pixels.

    Measured from the image: the cap occupies the top and the beads repeat
    on a 71px period. The chain's own vertical axis is to the right of the
    cap's centre, because the cap is a mount that clips beside the fixture
    rather than under it.

    The pendant at the bottom is its own file, chain_end.png, drawn at a
    different resolution — its stem is a thin rod where chain.png's beads
    are fat, so the two cannot share a scale factor. The pendant is sized
    by display height instead.
    """

    cap: QRect = QRect(196, 0, 176, 146)
    bead: QRect = QRect(330, 300, 92, 71)          # one clean period
    axis_x: int = 376                              # chain centre in source
    end_aspect: float = 186 / 403                  # chain_end.png w/h


CHAIN = ChainArt()


@dataclass
class LampcordLayout:
    """Everything positional, so it can be tuned live in the harness."""

    bulb_height: int = 96       # display height of the whole fixture
    chain_scale: float = 0.080  # display scale applied to chain.png
    chain_dx: int = 18          # chain axis, relative to the bulb centre
    chain_dy: int = 26          # where the chain's cap starts, from the top
    rest_length: int = 99       # bead run at rest
    pull_max: int = 33          # furthest the chain can be pulled
    threshold: int = 22         # pull past this to fire
    offset_x: int = 620         # along the top edge, 0 = centred
    end_height: int = 36        # display height of the pendant
    end_overlap: int = 2        # tuck its stem under the last bead

    # --- dangle, once you let go ---
    # A real chain does not glide back: it snaps up past its rest point and
    # swings, both dying away. Two damped oscillators, one vertical and one
    # angular, driven by a fixed-step integrator.
    bounce_freq: float = 11.0   # rad/s, the vertical bob
    bounce_damp: float = 5.0    # 1/s
    swing_gravity: float = 2600.0   # px/s^2, sets the swing period via L
    swing_damp: float = 1.7     # 1/s, how quickly the sway dies
    swing_kick: float = 2.2     # rad/s of swing per unit of pull fraction
    max_swing: float = 0.42     # radians, clamp so it cannot fling sideways
    max_omega: float = 7.0      # rad/s ceiling on angular velocity

    def fire_threshold(self) -> float:
        """A threshold past pull_max could never be reached, so the pull
        would silently never fire. Clamp rather than trust the number."""
        return min(float(self.threshold), self.pull_max * 0.95)


class Lampcord(QWidget):
    """Frameless, non-activating, top-edge window holding the fixture."""

    toggled = Signal()          # the user completed a pull
    moved = Signal(int)         # dragged along the top edge, new offset_x

    def __init__(self, layout: LampcordLayout | None = None, parent=None):
        super().__init__(parent)
        self.layout_ = layout or LampcordLayout()
        self._pull = 0.0
        self._dragging = False
        self._moving = False
        self._move_dx = 0
        self._grab_dy = 0.0
        self._lit = False

        self.bulb = QImage(str(ASSETS / "bulb_off.png"))
        self.bulb_lit = QImage(str(ASSETS / "bulb_on.png"))
        self.chain = QImage(str(ASSETS / "chain.png"))
        self.end = QImage(str(ASSETS / "chain_end.png"))
        # a lit bulb is a nicety; without it the off frame is reused
        if self.bulb_lit.isNull():
            self.bulb_lit = self.bulb
        self._missing = (self.bulb.isNull() or self.chain.isNull()
                         or self.end.isNull())

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            # Deliberately *not* WindowStaysOnTopHint. Unlike the notch,
            # this is a desktop ornament: it lives on the wallpaper and
            # anything you open covers it. Z-order is managed by hand in
            # _watch_foreground rather than by a window flag.
            | Qt.WindowType.Window
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        self._spring = QPropertyAnimation(self, b"pull", self)
        self._spring.setDuration(420)
        self._spring.setEasingCurve(QEasingCurve.Type.OutBack)
        self._spring.valueChanged.connect(lambda _: self._sync_mask())

        # dangle state: vertical bob and angular sway, integrated together
        self._vel = 0.0         # px/s along the chain
        self._swing = 0.0       # radians from vertical
        self._omega = 0.0       # rad/s
        self._drag_x = 0.0      # cursor offset from the axis while dragging
        self._physics = QTimer(self)
        self._physics.setInterval(16)
        self._physics.timeout.connect(self._step)

        # Z-order is managed by hand. In desktop_only mode it is pushed to
        # the bottom of the stack, so it shows on the wallpaper and any
        # window covers it. Set it False and it behaves like the notch:
        # always on top, stepping aside only for true fullscreen.
        self.desktop_only = True
        self.hide_on_fullscreen = True
        self._fullscreen_hidden = False
        self._fg = QTimer(self)
        self._fg.timeout.connect(self._watch_foreground)
        self._fg.start(180)

    # -- staying in the right layer ---------------------------------------
    def _watch_foreground(self) -> None:
        if win32 is None:
            return
        hwnd = int(self.winId())
        try:
            if self.desktop_only:
                # Show Desktop minimises every top-level window, tool
                # windows included, so undo it: a desktop ornament should
                # be exactly what is left when you clear the screen.
                if win32.is_iconic(hwnd):
                    win32.unminimise(hwnd)
                if self.isVisible():
                    win32.place_above_desktop(hwnd)
                if self._fullscreen_hidden:
                    self._fullscreen_hidden = False
                    self.show()
                return                # a window on top hides us anyway
            if self.isVisible():
                win32.raise_topmost(hwnd)
        except Exception:
            pass
        if not self.hide_on_fullscreen:
            if self._fullscreen_hidden:
                self._fullscreen_hidden = False
                self.show()
            return
        covering = self._is_fullscreen_foreground()
        if covering and not self._fullscreen_hidden:
            self._fullscreen_hidden = True
            self.hide()
        elif not covering and self._fullscreen_hidden:
            self._fullscreen_hidden = False
            self.show()

    def _is_fullscreen_foreground(self) -> bool:
        """A game or a video, not merely a maximised window — which keeps
        its caption bar and reports IsZoomed."""
        if win32 is None:
            return False
        try:
            hwnd = win32.foreground_window()
            if not hwnd or hwnd == int(self.winId()):
                return False
            if win32.window_class(hwnd) in (
                    "Progman", "WorkerW", "Shell_TrayWnd",
                    "Windows.UI.Core.CoreWindow"):
                return False
            if win32.is_zoomed(hwnd) or win32.has_caption(hwnd):
                return False
            rect = win32.window_rect(hwnd)
            if rect is None:
                return False
            left, top, right, bottom = rect
            screen = self.screen()
            if screen is None:
                return False
            geo = screen.geometry()
            return (left <= geo.x() and top <= geo.y()
                    and right >= geo.x() + geo.width()
                    and bottom >= geo.y() + geo.height())
        except Exception:
            return False

    # -- animated property ------------------------------------------------
    def _get_pull(self) -> float:
        return self._pull

    def _set_pull(self, v: float) -> None:
        self._pull = max(0.0, min(float(self.layout_.pull_max), float(v)))
        self.update()

    pull = Property(float, _get_pull, _set_pull)

    # -- derived geometry -------------------------------------------------
    @property
    def bulb_size(self) -> tuple[int, int]:
        if self._missing:
            return 70, self.layout_.bulb_height
        h = self.layout_.bulb_height
        w = max(1, round(self.bulb.width() * h / self.bulb.height()))
        return w, h

    def _cs(self) -> float:
        return self.layout_.chain_scale

    @property
    def bead_step(self) -> float:
        return max(1.0, CHAIN.bead.height() * self._cs())

    @property
    def finial_size(self) -> tuple[float, float]:
        h = float(self.layout_.end_height)
        return CHAIN.end_aspect * h, h

    def window_size(self) -> tuple[int, int]:
        """Sized for the fully extended chain, so a pull never clips."""
        bw, bh = self.bulb_size
        s = self._cs()
        cap_h = CHAIN.cap.height() * s
        _, fin_h = self.finial_size
        reach = (self.layout_.chain_dy + cap_h + self.layout_.rest_length
                 + self.layout_.pull_max + fin_h)
        # the swing throws the finial sideways, so the window has to be
        # wide enough for the arc as well as the fixture
        swing_reach = math.sin(self.layout_.max_swing) * (
            self.layout_.rest_length + self.layout_.pull_max)
        fin_w, _ = self.finial_size
        chain_half = (max(fin_w, CHAIN.cap.width() * s) / 2 + swing_reach)
        width = max(bw, int(abs(self.layout_.chain_dx) + chain_half) * 2 + 8)
        return int(width), int(max(bh, reach) + 8)

    @property
    def axis_x(self) -> float:
        return self.width() / 2 + self.layout_.chain_dx

    def _bead_run(self) -> float:
        return self.layout_.rest_length + self._pull

    def _anchor(self) -> QPointF:
        """Where the chain pivots — just under the cap, which stays put."""
        return QPointF(self.axis_x,
                       self.layout_.chain_dy
                       + CHAIN.cap.height() * self._cs())

    def finial_rect(self) -> QRectF:
        """The finial follows the swing, so hit-testing has to rotate too."""
        s = self._cs()
        fw, fh = self.finial_size
        along = self._bead_run()
        a = self._anchor()
        cx = a.x() + math.sin(self._swing) * along
        cy = a.y() + math.cos(self._swing) * along
        return QRectF(cx - fw / 2, cy, fw, fh)

    def grab_rect(self) -> QRectF:
        """A generous target — the chain is only a few pixels wide."""
        r = self.finial_rect()
        pad = 10.0
        return r.adjusted(-pad, -pad, pad, pad)

    def bulb_rect(self) -> QRectF:
        """The fixture itself, which is the handle for sliding it along."""
        bw, bh = self.bulb_size
        return QRectF(self.width() / 2 - bw / 2, 0, bw, bh)

    # -- placement --------------------------------------------------------
    def place(self, screen, offset_x: int | None = None) -> None:
        """Park it on the top edge. The offset keeps it clear of whatever
        else lives up there — a browser's tab strip, or the notch."""
        if offset_x is None:
            offset_x = self.layout_.offset_x
        w, h = self.window_size()
        geo = screen.geometry()
        x = geo.x() + (geo.width() - w) // 2 + offset_x
        # never hang it off the side of the monitor
        x = max(geo.x(), min(x, geo.x() + geo.width() - w))
        self.setGeometry(QRect(x, geo.y(), w, h))
        self._sync_mask()

    def _sync_mask(self) -> None:
        """Only the fixture and the chain take clicks; the rest of the
        window is a transparent rectangle that must stay click-through.

        The region has to follow the swing, or a swinging chain becomes
        ungrabbable — and a mask wide enough to cover the whole arc at all
        times would eat clicks on whatever is behind it.
        """
        bw, _ = self.bulb_size
        s = self._cs()
        region = QRegion(QRect(int(self.width() / 2 - bw / 2), 0, bw,
                               self.layout_.bulb_height))
        corridor = max(CHAIN.cap.width(), CHAIN.bead.width()) * s + 4
        a = self._anchor()
        tip = self.finial_rect().center()
        left = min(a.x(), tip.x()) - corridor / 2
        right = max(a.x(), tip.x()) + corridor / 2
        region = region.united(QRegion(QRect(
            int(left), self.layout_.chain_dy, int(right - left) + 1,
            int(tip.y() - self.layout_.chain_dy) + 2)))
        region = region.united(QRegion(self.grab_rect().toRect()))
        self.setMask(region)

    def showEvent(self, ev):
        super().showEvent(ev)
        if win32 is not None:
            try:
                win32.make_tool_window(
                    int(self.winId()), topmost=not self.desktop_only)
                if self.desktop_only:
                    win32.place_above_desktop(int(self.winId()))
            except Exception:
                pass
        self._sync_mask()

    # -- dangle physics ---------------------------------------------------
    def _chain_length(self) -> float:
        s = self._cs()
        _, fin_h = self.finial_size
        return max(8.0, CHAIN.cap.height() * s + self._bead_run() + fin_h / 2)

    def _step(self) -> None:
        """One fixed 16ms tick of two damped oscillators.

        Vertical is a spring pulling the chain back to its rest length.
        Angular is a pendulum whose period follows the chain's own length,
        so a longer chain sways more slowly — which is the detail that
        makes it read as a real object rather than an easing curve.
        """
        lay = self.layout_
        dt = 0.016

        # vertical bob
        accel = (-(lay.bounce_freq ** 2) * self._pull
                 - lay.bounce_damp * self._vel)
        self._vel += accel * dt
        self._pull = max(-lay.pull_max * 0.35,
                         min(lay.pull_max, self._pull + self._vel * dt))

        # angular sway
        omega_n2 = lay.swing_gravity / self._chain_length()
        ang_accel = (-omega_n2 * math.sin(self._swing)
                     - lay.swing_damp * self._omega)
        self._omega += ang_accel * dt
        self._omega = max(-lay.max_omega, min(lay.max_omega, self._omega))
        self._swing += self._omega * dt
        if self._swing >= lay.max_swing:
            # The chain has reached its limit. Without killing the outward
            # velocity here, a fast drag builds up far more omega than the
            # restoring force can undo in a reasonable time, and the chain
            # sits pinned at the clamp instead of settling.
            self._swing = lay.max_swing
            self._omega = min(self._omega, 0.0)
        elif self._swing <= -lay.max_swing:
            self._swing = -lay.max_swing
            self._omega = max(self._omega, 0.0)

        settled = (abs(self._pull) < 0.35 and abs(self._vel) < 2.0
                   and abs(self._swing) < 0.004 and abs(self._omega) < 0.05)
        if settled:
            self._pull = self._vel = self._swing = self._omega = 0.0
            self._physics.stop()
        self._sync_mask()
        self.update()

    # -- interaction ------------------------------------------------------
    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        # the chain is tested first: its grab box can overlap the fixture
        # when the chain is short, and pulling is the commoner action
        if self.grab_rect().contains(ev.position()):
            self._physics.stop()
            self._vel = self._omega = 0.0
            self._dragging = True
            self._grab_dy = ev.position().y() - self.finial_rect().top()
            self._drag_x = ev.position().x() - self.axis_x
            self.grabMouse()   # masked non-activating windows lose drags
            return
        if self.bulb_rect().contains(ev.position()):
            self._moving = True
            self._move_dx = ev.globalPosition().toPoint().x() - self.x()
            self.grabMouse()

    def mouseMoveEvent(self, ev):
        if self._moving:
            self._slide(ev.globalPosition().toPoint().x())
            return
        if not self._dragging:
            if self.grab_rect().contains(ev.position()):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif self.bulb_rect().contains(ev.position()):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        s = self._cs()
        base = self.layout_.chain_dy + CHAIN.cap.height() * s \
            + self.layout_.rest_length
        self.pull = ev.position().y() - self._grab_dy - base

        # dragging sideways tilts the chain, and the speed of that sideways
        # movement becomes the swing it carries into the release
        prev = self._drag_x
        self._drag_x = ev.position().x() - self.axis_x
        self._swing = max(-self.layout_.max_swing,
                          min(self.layout_.max_swing,
                              math.atan2(self._drag_x,
                                         self._chain_length())))
        self._omega = (self._drag_x - prev) * 0.25
        self._sync_mask()

    def _slide(self, global_x: int) -> None:
        """Move along the top edge only — it is a ceiling fixture."""
        screen = self.screen()
        geo = screen.geometry() if screen is not None else self.geometry()
        w = self.width()
        new_x = max(geo.x(), min(global_x - self._move_dx,
                                 geo.x() + geo.width() - w))
        dx = new_x - self.x()
        if dx:
            self.move(new_x, geo.y())
            # carry a real lamp sideways and the chain swings behind it,
            # but a fast flick must not bank unlimited momentum
            lay = self.layout_
            self._omega = max(-lay.max_omega,
                              min(lay.max_omega, self._omega - dx * 0.045))
            if not self._physics.isActive():
                self._physics.start()

    def mouseReleaseEvent(self, ev):
        if self._moving:
            self._moving = False
            self.releaseMouse()
            screen = self.screen()
            if screen is not None:
                geo = screen.geometry()
                centred = geo.x() + (geo.width() - self.width()) // 2
                self.layout_.offset_x = self.x() - centred
                self.moved.emit(self.layout_.offset_x)
            if not self._physics.isActive():
                self._physics.start()
            return
        if not self._dragging:
            return
        self._dragging = False
        self.releaseMouse()
        lay = self.layout_
        fired = self._pull >= lay.fire_threshold()

        # let go and it snaps upward, so the release velocity is negative;
        # scale it with how far it was pulled
        fraction = self._pull / max(1.0, lay.pull_max)
        self._vel = -lay.bounce_freq * self._pull * 0.55
        kick = lay.swing_kick * fraction
        self._omega += kick if self._swing >= 0 else -kick
        self._physics.start()

        if fired:
            self.toggled.emit()

    def set_lit(self, lit: bool) -> None:
        self._lit = bool(lit)
        self.update()

    def is_lit(self) -> bool:
        return self._lit

    # -- painting ---------------------------------------------------------
    def paintEvent(self, _ev):
        q = QPainter(self)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self._missing:
            return
        self._paint_chain(q)
        bw, bh = self.bulb_size
        art = self.bulb_lit if self._lit else self.bulb
        q.drawImage(QRectF(self.width() / 2 - bw / 2, 0, bw, bh), art)

    def _paint_chain(self, q: QPainter) -> None:
        s = self._cs()
        x = self.axis_x
        y = float(self.layout_.chain_dy)

        # the cap is a mount screwed to the fixture, so it never moves
        cap_w, cap_h = CHAIN.cap.width() * s, CHAIN.cap.height() * s
        cap_dx = (CHAIN.cap.center().x() - CHAIN.axis_x) * s
        q.drawImage(QRectF(x + cap_dx - cap_w / 2, y, cap_w, cap_h),
                    self.chain, QRectF(CHAIN.cap))

        # everything below it hangs, so it swings about the anchor
        a = self._anchor()
        q.save()
        q.translate(a)
        q.rotate(math.degrees(-self._swing))
        y = 0.0

        # tile whole beads, then clip the last partial one so the run ends
        # exactly where the finial begins
        bead_w = CHAIN.bead.width() * s
        step = self.bead_step
        remaining = self._bead_run()
        while remaining > 0.5:
            take = min(step, remaining)
            src = QRectF(CHAIN.bead)
            src.setHeight(CHAIN.bead.height() * take / step)
            q.drawImage(QRectF(-bead_w / 2, y, bead_w, take),
                        self.chain, src)
            y += take
            remaining -= take

        fw, fh = self.finial_size
        q.drawImage(QRectF(-fw / 2, y - self.layout_.end_overlap, fw, fh),
                    self.end)
        q.restore()
