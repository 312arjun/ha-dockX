"""The notch itself: a frameless, non-activating, click-through-except-here
window welded to a screen edge.

One window handles every state. The collapsed nub and the expanded pill are
the same painted body at two sizes, driven by a single animated `expansion`
property, so nothing can desync mid-animation.
"""

from __future__ import annotations

import time

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation,
                            QRect, QRectF, Qt, QTimer, Property, Signal)
from PySide6.QtGui import (QAction, QColor, QCursor, QFont, QGuiApplication,
                           QPainter, QPen, QRadialGradient, QRegion)
from PySide6.QtWidgets import QMenu, QWidget

from . import domains, glyph, theme
from .notch_path import notch_path
from .tile_popup import TilePopup, supports_popup

try:
    from . import win32
except Exception:  # pragma: no cover - non-Windows dev
    win32 = None


class Tile:
    """A configured entity plus whatever the socket last said about it."""

    __slots__ = ("row", "state", "attributes", "rect", "optimistic_until",
                 "pending", "failed_until")

    def __init__(self, row):
        self.row = row
        self.state = "unavailable"
        self.attributes: dict = {}
        self.rect = QRectF()
        self.optimistic_until = 0.0
        self.pending = False
        self.failed_until = 0.0

    @property
    def entity_id(self) -> str:
        return self.row.entity_id


class NotchWindow(QWidget):
    settings_requested = Signal()
    quit_requested = Signal()
    reconnect_requested = Signal()

    def __init__(self, store, client, parent=None):
        super().__init__(parent)
        self.store = store
        self.client = client
        self.tiles: list[Tile] = []
        self._expansion = 0.0
        self._pinned = False
        self._connected = False
        self._hidden_until = 0.0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            # Qt.Tool would be the obvious choice, but Qt owns a tool window
            # to the application's active window, and an owned window
            # follows its owner's z-order. WS_EX_TOOLWINDOW, applied
            # directly in win32.make_tool_window, keeps it out of the
            # taskbar and Alt-Tab without the ownership.
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        self._anim = QPropertyAnimation(self, b"expansion", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(lambda _: self._sync_mask())

        self._leave_timer = QTimer(self)
        self._leave_timer.setSingleShot(True)
        self._leave_timer.timeout.connect(self._collapse_if_unpinned)

        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._force_collapse)

        # Enter/leave events are unreliable on a masked, translucent,
        # non-activating tool window — the pointer can sit over a
        # transparent region and Qt never reports a leave. Poll instead.
        self._hover = False
        self._away_since = 0.0
        self._btn_was_down = False
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_cursor)
        self._poll.start(theme.POLL_MS)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._expire_optimistic)
        self._tick.start(500)

        self._fullscreen_hidden = False
        self._fg = QTimer(self)
        self._fg.timeout.connect(self._watch_foreground)
        self._fg.start(500)

        # detail card: opens on dwell over a tile that has it enabled
        self.popup = TilePopup(client)
        self._popup_tile: Tile | None = None
        self._dwell_tile: Tile | None = None
        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.timeout.connect(self._open_popup)
        self._popup_close = QTimer(self)
        self._popup_close.setSingleShot(True)
        self._popup_close.timeout.connect(self._close_popup)

        client.entity_updated.connect(self._on_entity)
        client.connected.connect(lambda _: self._set_connected(True))
        client.disconnected.connect(lambda _: self._set_connected(False))
        client.auth_failed.connect(lambda _: self._set_connected(False))

        self.reload()

    # -- animated property ------------------------------------------------
    def _get_expansion(self) -> float:
        return self._expansion

    def _set_expansion(self, v: float) -> None:
        self._expansion = float(v)
        self.update()

    expansion = Property(float, _get_expansion, _set_expansion)

    # -- configuration ----------------------------------------------------
    def reload(self) -> None:
        self.tiles = [Tile(r) for r in self.store.entities(only_enabled=True)]
        for t in self.tiles:
            cached = self.client.states.get(t.entity_id)
            if cached:
                t.state = cached.get("state", "")
                t.attributes = cached.get("attributes", {})
        self._apply_geometry()
        self._sync_mask()
        self.update()

    # -- metrics ----------------------------------------------------------
    @property
    def scale(self) -> float:
        return theme.SIZE_SCALES.get(self.store.get("size", "medium"), 1.0)

    @property
    def edge(self) -> str:
        return self.store.get("edge", "right")

    @property
    def show_labels(self) -> bool:
        return self.store.get_bool("show_labels", True)

    def _metrics(self) -> dict:
        s = self.scale
        size = self.store.get("size", "medium")
        n = max(len(self.tiles), 1)
        vertical = self.edge in ("left", "right")
        cell = theme.CELL_DIAMETER * s
        label_h = (theme.LABEL_SIZE + 4) * s if self.show_labels else 0.0
        spacing = theme.CELL_SPACING * s
        pad = theme.PILL_PADDING * s

        # A tile is a circle with its label *below* it, so the label adds to
        # the run when the notch is vertical but to its depth when the notch
        # is horizontal. Treating both the same left the cells off-centre on
        # the top and bottom edges.
        if vertical:
            tile_along = cell + label_h
            tile_across = cell
            thick = theme.PILL_THICKNESS * s
        else:
            tile_along = cell + (theme.LABEL_WIDTH_PAD * s
                                 if self.show_labels else 0.0)
            tile_across = cell + label_h
            thick = max(theme.PILL_THICKNESS * s, tile_across + 26 * s)

        run = pad * 2 + n * tile_along + (n - 1) * spacing
        return {
            "s": s, "cell": cell, "label_h": label_h,
            "tile_along": tile_along, "tile_across": tile_across,
            "spacing": spacing, "pad": pad, "vertical": vertical,
            "pill_thick": thick,
            "pill_run": run,
            "nub_thick": theme.NUB_THICKNESS * s,
            "nub_run": theme.NUB_LENGTH * s,
            "er": theme.shape("EDGE_RADIUS", size) * s,
            "es": theme.shape("EDGE_SWEEP", size) * s,
            "br": theme.shape("BODY_RADIUS", size) * s,
        }

    def _screen(self):
        name = self.store.get("screen_name", "")
        if name:
            for sc in QGuiApplication.screens():
                if sc.name() == name:
                    return sc
        return QGuiApplication.primaryScreen()

    def _apply_geometry(self) -> None:
        m = self._metrics()
        geo = self._screen().geometry()
        offset = self.store.get_int("align_offset", 0)
        # The window has to hold whichever state is largest. The resting nub
        # is longer than a one-tile pill, and when the window was sized to
        # the pill alone the nub's flares were clipped clean off — which is
        # what made it read as a plain rectangle.
        run = max(m["pill_run"], m["nub_run"])
        thick = max(m["pill_thick"], m["nub_thick"])
        # the flare bleeds EDGE_SWEEP past each end of the body, so that is
        # the slack the window has to carry
        slack = int(m["es"] * 2 + 10)

        if self.edge in ("left", "right"):
            w = int(thick)
            h = int(run) + slack
            y = geo.y() + (geo.height() - h) // 2 + offset
            x = geo.x() + geo.width() - w if self.edge == "right" else geo.x()
        else:
            h = int(thick)
            w = int(run) + slack
            x = geo.x() + (geo.width() - w) // 2 + offset
            y = geo.y() + geo.height() - h if self.edge == "bottom" else geo.y()
        self.setGeometry(QRect(x, y, w, h))

    def _body_rect(self) -> QRectF:
        m = self._metrics()
        e = self._expansion
        thick = m["nub_thick"] + (m["pill_thick"] - m["nub_thick"]) * e
        run = m["nub_run"] + (m["pill_run"] - m["nub_run"]) * e
        w, h = self.width(), self.height()
        if self.edge == "right":
            return QRectF(w - thick, (h - run) / 2, thick, run)
        if self.edge == "left":
            return QRectF(0, (h - run) / 2, thick, run)
        if self.edge == "top":
            return QRectF((w - run) / 2, 0, run, thick)
        return QRectF((w - run) / 2, h - thick, run, thick)

    def _sync_mask(self) -> None:
        m = self._metrics()
        b = self._body_rect()
        pad = int(max(m["er"], m["es"]) + 3)
        r = QRect(int(b.x()) - pad, int(b.y()) - pad,
                  int(b.width()) + pad * 2, int(b.height()) + pad * 2)
        self.setMask(QRegion(r.intersected(self.rect())))

    # -- expansion --------------------------------------------------------
    def _animate_to(self, target: float, ms: int) -> None:
        if abs(self._expansion - target) < 0.001:
            return
        self._anim.stop()
        self._anim.setDuration(ms)
        self._anim.setStartValue(self._expansion)
        self._anim.setEndValue(target)
        self._anim.start()

    def expand(self) -> None:
        if not self.tiles:
            return          # nothing to show; stay a sliver
        self._leave_timer.stop()
        self._animate_to(1.0, theme.ANIM_MS)

    def collapse(self) -> None:
        self._auto_timer.stop()
        self._close_popup()
        self._animate_to(0.0, theme.ANIM_MS)

    def _collapse_if_unpinned(self) -> None:
        if not self._pinned:
            self.collapse()

    def _force_collapse(self) -> None:
        self._pinned = False
        self.collapse()

    # -- hover by polling -------------------------------------------------
    def _hover_rect(self) -> QRect:
        """Screen-space rect that counts as 'pointer is on the notch'."""
        b = self._body_rect().toRect()
        m = int(theme.HOVER_MARGIN * self.scale)
        top_left = self.mapToGlobal(b.topLeft())
        return QRect(top_left.x() - m, top_left.y() - m,
                     b.width() + m * 2, b.height() + m * 2)

    def _collapse_delay_ms(self) -> int:
        """How long the notch stays open after the pointer leaves.

        This is what 'Auto-collapse after' means — the fixed grace period
        only exists so a pointer crossing a gap doesn't slam it shut.
        """
        secs = self.store.get_int("auto_collapse_s", 6)
        if secs <= 0:
            return 0          # 0 = never; only a click dismisses it
        return max(theme.HOVER_OUT_MS, secs * 1000)

    def _poll_cursor(self) -> None:
        if not self.isVisible():
            return
        cursor = QCursor.pos()
        on_popup = (self.popup.isVisible()
                    and self.popup.frameGeometry().contains(cursor))
        inside = self._hover_rect().contains(cursor) or on_popup

        self._track_dwell(cursor, on_popup)

        # A click anywhere else dismisses the notch. Qt never sees those
        # clicks — the window is non-activating and masked — so the button
        # state is read straight from Windows.
        if self._expansion > 0.05 and not inside and self._click_outside():
            self._force_collapse()
            return

        if inside:
            self._leave_timer.stop()
            if not self._hover:
                self._hover = True
                if self.store.get_bool("hover_peek", True) or self._pinned:
                    QTimer.singleShot(theme.HOVER_IN_MS, self._hover_expand)
            return

        if self._hover:
            self._hover = False
            # A pinned notch is one you asked to stay open, so it waits for
            # a click rather than a timer.
            if not self._pinned:
                delay = self._collapse_delay_ms()
                if delay:
                    self._leave_timer.start(delay)

    # -- detail card ------------------------------------------------------
    def _tile_at(self, local) -> "Tile | None":
        if self._expansion < 0.85:
            return None
        for t in self.tiles:
            if t.rect.contains(local):
                return t
        return None

    def _popup_enabled(self, tile) -> bool:
        return bool(getattr(tile.row, "popup", 0)) and \
            supports_popup(tile.entity_id)

    def _track_dwell(self, cursor, on_popup: bool) -> None:
        """Hovering a tile for a beat opens its card. Moving onto the card
        must not close it, which is why the popup counts as being inside."""
        if on_popup:
            self._popup_close.stop()
            return
        tile = self._tile_at(self.mapFromGlobal(cursor))
        if tile is not None and not self._popup_enabled(tile):
            tile = None
        if tile is not None:
            self._popup_close.stop()
        if tile is self._dwell_tile:
            return
        self._dwell_tile = tile
        if tile is None:
            self._dwell.stop()
            # There is a gap between the notch and the card, and the pointer
            # is over neither while it crosses. Closing immediately would
            # make the card unreachable, so it gets a grace period.
            if self._popup_tile is not None:
                self._popup_close.start(theme.POPUP_CLOSE_MS)
        else:
            self._dwell.start(theme.POPUP_DWELL_MS)

    def _open_popup(self) -> None:
        tile = self._dwell_tile
        if tile is None or self._expansion < 0.85:
            return
        self._popup_close.stop()
        self._popup_tile = tile
        self.popup.bind(tile.entity_id, tile.state, tile.attributes,
                        tile.row.label, getattr(tile.row, "on_color", ""))
        self.popup.show_beside(
            self.mapToGlobal(tile.rect.center().toPoint()), self.edge)

    def _close_popup(self) -> None:
        self._popup_tile = None
        self._dwell.stop()
        self._popup_close.stop()
        self.popup.hide()

    def _click_outside(self) -> bool:
        """True on the transition into a mouse-button press this tick."""
        if win32 is None:
            return False
        try:
            down = win32.mouse_button_down()
        except Exception:
            return False
        fired = down and not self._btn_was_down
        self._btn_was_down = down
        return fired

    def _hover_expand(self) -> None:
        if self._hover or self._pinned:
            self.expand()

    # -- events -----------------------------------------------------------
    def showEvent(self, ev):
        super().showEvent(ev)
        self._apply_no_activate()
        self._sync_mask()

    def _apply_no_activate(self) -> None:
        if win32 is None:
            return
        try:
            win32.make_tool_window(int(self.winId()))
        except Exception:
            pass

    def _ensure_topmost(self) -> None:
        """Re-assert topmost, unconditionally.

        Windows can leave WS_EX_TOPMOST set on the window while placing it
        down in the ordinary z-order band, so the style bit reads True
        while a maximised app sits on top of it. The previous version only
        re-asserted when is_topmost() was False, which meant it never
        fired — it was gated on a check that lies. SetWindowPos is a few
        microseconds and a no-op when the order is already right, so there
        is nothing to be gained by asking first.
        """
        if win32 is None or not self.isVisible():
            return
        try:
            win32.raise_topmost(int(self.winId()))
        except Exception:
            pass

    def _foreground_is_fullscreen(self) -> bool:
        """True only for a genuinely fullscreen window — a game, a video,
        a presentation.

        The window rectangle alone cannot tell you this. A maximised window
        is sized to the work area but its rect is inflated by the invisible
        resize border, so on this machine a maximised Chrome reports
        -8,-8 to 1928,1040 on a 1920x1080 screen. Two further tests settle
        it: a maximised window reports IsZoomed, and it keeps its caption
        bar in its style bits. Real fullscreen is neither.
        """
        if win32 is None:
            return False
        try:
            hwnd = win32.foreground_window()
            if not hwnd or hwnd == int(self.winId()):
                return False
            if win32.window_class(hwnd) in (
                    "Progman", "WorkerW", "Shell_TrayWnd",
                    "Windows.UI.Core.CoreWindow"):
                return False        # desktop, taskbar, shell surfaces
            if win32.is_zoomed(hwnd):
                return False        # maximised, not fullscreen
            if win32.has_caption(hwnd):
                return False        # still a normal framed window

            rect = win32.window_rect(hwnd)
            if rect is None:
                return False
            left, top, right, bottom = rect
            geo = self._screen().geometry()
            return (left <= geo.x() and top <= geo.y()
                    and right >= geo.x() + geo.width()
                    and bottom >= geo.y() + geo.height())
        except Exception:
            return False

    def _watch_foreground(self) -> None:
        self._ensure_topmost()
        if not self.store.get_bool("hide_on_fullscreen", True):
            if self._fullscreen_hidden:
                self._fullscreen_hidden = False
                self.show()
            return
        covering = self._foreground_is_fullscreen()
        if covering and not self._fullscreen_hidden:
            self._fullscreen_hidden = True
            self.hide()
        elif not covering and self._fullscreen_hidden:
            self._fullscreen_hidden = False
            self.show()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.RightButton:
            self._context_menu(ev.globalPosition().toPoint())
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        pos = ev.position()
        if self._expansion > 0.85:
            for t in self.tiles:
                if t.rect.contains(pos):
                    self._activate(t)
                    return
            # clicking the body toggles the pin, and unpinning always folds
            self._pinned = not self._pinned
            if self._pinned:
                self.expand()
            else:
                self.collapse()
        else:
            self._pinned = True
            self.expand()

    def _context_menu(self, at: QPoint) -> None:
        menu = QMenu()
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        act_settings = QAction("Settings\u2026", menu)
        act_settings.triggered.connect(self.settings_requested.emit)
        act_collapse = QAction("Collapse now", menu)
        act_collapse.triggered.connect(self._force_collapse)
        act_reconnect = QAction("Reconnect", menu)
        act_reconnect.triggered.connect(self.reconnect_requested.emit)
        act_hide = QAction("Hide for 1 hour", menu)
        act_hide.triggered.connect(self._hide_an_hour)
        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(self.quit_requested.emit)
        for a in (act_settings, act_collapse, act_reconnect, act_hide):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(act_quit)
        menu.exec(at)

    def _hide_an_hour(self) -> None:
        self._pinned = False
        self.collapse()
        self.hide()
        QTimer.singleShot(3600 * 1000, self.show)

    # -- state ------------------------------------------------------------
    def _set_connected(self, ok: bool) -> None:
        self._connected = ok
        self.update()

    def _on_entity(self, entity_id: str, payload: dict) -> None:
        touched = False
        for t in self.tiles:
            if t.entity_id == entity_id:
                t.state = payload.get("state", "")
                t.attributes = payload.get("attributes", {})
                t.optimistic_until = 0.0
                t.pending = False
                touched = True
        if touched:
            self.update()
            if (self._popup_tile is not None
                    and self._popup_tile.entity_id == entity_id
                    and self.popup.isVisible()):
                self.popup.refresh(payload.get("state", ""),
                                   payload.get("attributes", {}))

    @staticmethod
    def _turn_on_colour(t: Tile) -> tuple[str, str, dict] | None:
        """A light with a configured colour turns on *at* that colour.

        Only on the off-to-on transition: sending the colour again on every
        press would fight whatever you had just set on the wheel.
        """
        on_hex = getattr(t.row, "on_color", "") or ""
        if not on_hex or domains.domain_of(t.entity_id) != "light":
            return None
        if domains.is_on(t.state) and not domains.is_dead(t.state):
            return None
        colour = QColor(on_hex)
        if not colour.isValid():
            return None
        return "light", "turn_on", {
            "rgb_color": [colour.red(), colour.green(), colour.blue()]}

    def _activate(self, t: Tile) -> None:
        action = self._turn_on_colour(t) or domains.click_action(
            t.entity_id, t.state)
        if action is None:
            return
        domain, service, data = action
        ok = self.client.call_service(
            domain, service, target={"entity_id": t.entity_id}, data=data
        )
        if not ok:
            t.failed_until = time.time() + 1.5
            self.update()
            return
        guess = domains.optimistic_state(t.entity_id, t.state)
        if guess is not None:
            t.state = guess
            t.optimistic_until = time.time() + 3.0
            t.pending = True
        self.update()

    def _expire_optimistic(self) -> None:
        now = time.time()
        dirty = False
        for t in self.tiles:
            if t.optimistic_until and now > t.optimistic_until:
                t.optimistic_until = 0.0
                t.pending = False
                cached = self.client.states.get(t.entity_id)
                if cached:
                    t.state = cached.get("state", "")
                    t.attributes = cached.get("attributes", {})
                else:
                    t.failed_until = now + 1.5
                dirty = True
            if t.failed_until and now > t.failed_until:
                t.failed_until = 0.0
                dirty = True
        if dirty:
            self.update()

    # -- painting ---------------------------------------------------------
    def _accent(self, t: Tile) -> QColor:
        if domains.is_dead(t.state):
            return theme.ACCENT_UNAVAILABLE
        if t.failed_until:
            return theme.ACCENT_ERROR
        if t.row.color:
            c = QColor(t.row.color)
            if c.isValid():
                return c
        if t.row.ring_mode == "ramp":
            frac = self._fraction(t)
            return theme.ramp_color(frac if frac is not None else 0.0)
        return theme.ACCENT_ON if domains.is_on(t.state) else theme.ACCENT_OFF

    def _fraction(self, t: Tile) -> float | None:
        mode = t.row.ring_mode
        if mode == "flat":
            return 1.0 if domains.is_on(t.state) else 0.0
        if mode in ("value", "ramp"):
            try:
                raw = float(t.state)
            except (TypeError, ValueError):
                auto = domains.auto_value(t.entity_id, t.state, t.attributes)
                return auto
            lo, hi = t.row.ring_min, t.row.ring_max
            if hi == lo:
                return 0.0
            return max(0.0, min(1.0, (raw - lo) / (hi - lo)))
        return None

    def paintEvent(self, _ev):
        q = QPainter(self)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        q.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        m = self._metrics()
        body = self._body_rect()
        path = notch_path(body, self.edge, m["br"], m["er"], m["es"])

        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(theme.NOTCH_BG)
        q.drawPath(path)

        # a hairline of light along the inner face, so the body reads as a
        # machined edge rather than a flat cut-out
        q.setBrush(Qt.BrushStyle.NoBrush)
        q.setPen(QPen(theme.NOTCH_SHEEN, 1.0))
        q.drawPath(path)

        # The status bar along the bezel is always drawn — it is the one
        # thing visible when the notch is a sliver, so it carries state by
        # colour rather than by presence. It is a short centred pill, not a
        # rule running the whole length.
        bar = (theme.ACCENT_ERROR if not self._connected
               else QColor(theme.SIGNAL))
        bar_w = max(3.0, theme.BAR_WIDTH * m["s"])
        q.setBrush(Qt.BrushStyle.NoBrush)
        q.setPen(QPen(bar, bar_w, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        inset = bar_w / 2 + 4 * m["s"]
        if self.edge in ("left", "right"):
            half = body.height() * theme.BAR_RUN_FRACTION / 2
            half = min(half, max(0.0, body.height() / 2 - bar_w))
            bx = (body.right() - inset if self.edge == "right"
                  else body.left() + inset)
            q.drawLine(QPointF(bx, body.center().y() - half),
                       QPointF(bx, body.center().y() + half))
        else:
            half = body.width() * theme.BAR_RUN_FRACTION / 2
            half = min(half, max(0.0, body.width() / 2 - bar_w))
            by = (body.top() + inset if self.edge == "top"
                  else body.bottom() - inset)
            q.drawLine(QPointF(body.center().x() - half, by),
                       QPointF(body.center().x() + half, by))

        if self._expansion < 0.08 or not self.tiles:
            for t in self.tiles:
                t.rect = QRectF()
            return

        alpha = max(0.0, min(1.0, (self._expansion - 0.35) / 0.55))
        q.save()
        q.setClipPath(path)
        q.setOpacity(alpha)
        self._paint_cells(q, body, m)
        q.restore()

    def _paint_cells(self, q: QPainter, body: QRectF, m: dict) -> None:
        cell = m["cell"]
        step = m["tile_along"] + m["spacing"]
        vertical = m["vertical"]
        run = m["pill_run"]

        if vertical:
            start = body.center().y() - run / 2 + m["pad"]
        else:
            start = body.center().x() - run / 2 + m["pad"]

        for i, t in enumerate(self.tiles):
            off = start + i * step
            if vertical:
                cx = body.center().x()
                cy = off + cell / 2
            else:
                cx = off + m["tile_along"] / 2
                # the label hangs below the circle, so the circle must sit
                # above centre for the pair to read as centred
                cy = body.center().y() - m["label_h"] / 2
            circle = QRectF(cx - cell / 2, cy - cell / 2, cell, cell)
            half = m["tile_along"] / 2
            t.rect = QRectF(cx - half, circle.top() - 4,
                            m["tile_along"], cell + 8 + m["label_h"])
            self._paint_cell(q, t, circle, m)

    def _paint_cell(self, q: QPainter, t: Tile, circle: QRectF, m: dict) -> None:
        accent = self._accent(t)
        on = domains.is_on(t.state) and not domains.is_dead(t.state)

        fill = QColor(theme.CELL_FILL)
        if on:
            # the one indulgence in the whole design: an active tile blooms
            bloom = QRadialGradient(circle.center(), circle.width() * 0.95)
            c0 = QColor(accent)
            c0.setAlpha(theme.BLOOM_ALPHA)
            c1 = QColor(accent)
            c1.setAlpha(0)
            bloom.setColorAt(0.0, c0)
            bloom.setColorAt(1.0, c1)
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(bloom)
            q.drawEllipse(circle.adjusted(-14, -14, 14, 14))
            fill = QColor(accent)
            fill.setAlpha(52)
        q.setPen(Qt.PenStyle.NoPen)
        q.setBrush(fill)
        q.drawEllipse(circle)
        if on:
            edge = QColor(accent)
            edge.setAlpha(120)
            q.setBrush(Qt.BrushStyle.NoBrush)
            q.setPen(QPen(edge, 1.0))
            q.drawEllipse(circle.adjusted(0.5, 0.5, -0.5, -0.5))

        frac = self._fraction(t)
        if frac is not None:
            pen_w = theme.RING_WIDTH * m["s"]
            arc = circle.adjusted(pen_w / 2 + 1, pen_w / 2 + 1,
                                  -(pen_w / 2 + 1), -(pen_w / 2 + 1))
            q.setBrush(Qt.BrushStyle.NoBrush)
            q.setPen(QPen(theme.RING_TRACK, pen_w, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            q.drawArc(arc, 0, 360 * 16)
            if frac > 0.001:
                q.setPen(QPen(accent, pen_w, Qt.PenStyle.SolidLine,
                              Qt.PenCapStyle.RoundCap))
                q.drawArc(arc, 90 * 16, int(-360 * 16 * frac))

        if t.pending:
            pen_w = theme.RING_WIDTH * m["s"]
            arc = circle.adjusted(pen_w / 2 + 1, pen_w / 2 + 1,
                                  -(pen_w / 2 + 1), -(pen_w / 2 + 1))
            spin = int((time.time() * 240) % 360)
            q.setBrush(Qt.BrushStyle.NoBrush)
            q.setPen(QPen(QColor("#FFFFFF"), pen_w, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            q.drawArc(arc, -spin * 16, -70 * 16)

        name = t.row.icon or domains.default_icon(t.entity_id, t.attributes)
        ch = glyph.char_for(name)
        if ch:
            gf = glyph.font(name, int(circle.height() * 0.52))
            q.setFont(gf)
            q.setPen(QPen(accent if on else theme.GLYPH_COLOR_OFF))
            q.drawText(circle, Qt.AlignmentFlag.AlignCenter, ch)

        if m["label_h"] > 0:
            txt = t.row.label or domains.value_text(
                t.entity_id, t.state, t.attributes)
            f = QFont()
            f.setPixelSize(max(8, int(theme.LABEL_SIZE * m["s"])))
            f.setWeight(QFont.Weight.DemiBold)
            q.setFont(f)
            q.setPen(QPen(theme.LABEL_COLOR if on else theme.GLYPH_COLOR_OFF))
            width = max(m["tile_along"], circle.width() + 20)
            box = QRectF(circle.center().x() - width / 2, circle.bottom() + 1,
                         width, m["label_h"])
            q.drawText(box, Qt.AlignmentFlag.AlignHCenter
                       | Qt.AlignmentFlag.AlignTop, txt)
