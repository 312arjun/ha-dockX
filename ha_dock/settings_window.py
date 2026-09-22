"""Settings GUI.

Frameless, with its own chrome — the stock Windows title bar fights the
palette and there is no way to tint it. Three destinations in a left rail,
one card-based page each.

Hidden at launch; the tray icon brings it up. Closing hides rather than
quits, same pattern as iPhone Companion.
"""

from __future__ import annotations

import asyncio
import threading
import time

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog,
                               QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QSizeGrip, QSpinBox,
                               QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import (__version__, db, dialogs, domains, glyph, ha_client, theme,
               ui_kit)
from .tile_popup import supports_popup
from .ui_kit import (Card, DangerButton, FieldRow, GhostButton, PrimaryButton,
                     RailEntry, RailFooter, ReorderTable, SectionHeading,
                     Stat, StatusPill, TitleBar, Toggle, divider, icon_label,
                     text_label)

RING_MODES = ["none", "flat", "value", "ramp"]
RING_HELP = {
    "none": "Icon only — no ring drawn",
    "flat": "Full ring when on, track when off",
    "value": "Ring fills between min and max",
    "ramp": "Ring fills and takes the green/yellow/orange ramp",
}


class _Probe(QObject):
    done = Signal(bool, str, list, float)

    def run(self, url: str, token: str) -> None:
        def worker():
            started = time.perf_counter()
            try:
                res = asyncio.run(ha_client.probe(url, token))
                ms = (time.perf_counter() - started) * 1000
                ids = sorted(s.get("entity_id", "") for s in res["states"])
                self.done.emit(True, res["ha_version"], ids, ms)
            except Exception as exc:
                ms = (time.perf_counter() - started) * 1000
                self.done.emit(False, str(exc) or exc.__class__.__name__,
                               [], ms)

        threading.Thread(target=worker, daemon=True, name="ha-probe").start()


class IconPicker(QDialog):
    def __init__(self, current: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose an icon")
        self.resize(380, 480)
        self.selected = current

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search Material Design Icons")
        self.list = QListWidget(self)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)
        lay.addWidget(buttons)

        self.search.textChanged.connect(self._refresh)
        self.list.itemSelectionChanged.connect(self._pick)
        self.search.setText(glyph.split(current)[1] if current else "light")

    def _refresh(self, term: str) -> None:
        self.list.clear()
        for name in glyph.search(term, limit=200):
            item = QListWidgetItem(f"  {glyph.char_for(name)}   {name}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFont(glyph.font(name, 16))
            self.list.addItem(item)

    def _pick(self) -> None:
        items = self.list.selectedItems()
        if items:
            self.selected = items[0].data(Qt.ItemDataRole.UserRole)


class AddEntityDialog(QDialog):
    def __init__(self, known: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add entity")
        self.resize(460, 130)
        self.combo = QComboBox(self)
        self.combo.setEditable(True)
        self.combo.addItems(known)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.combo.setCurrentText("")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        hint = QLabel("Entity ID — type to filter, e.g. light.bedroom", self)
        hint.setStyleSheet(f"color: {theme.MUTED};")
        lay.addWidget(hint)
        lay.addWidget(self.combo)
        lay.addWidget(buttons)

    def entity_id(self) -> str:
        return self.combo.currentText().strip()


class SettingsWindow(QWidget):
    config_changed = Signal()
    reconnect_requested = Signal()
    disconnect_requested = Signal()
    quit_requested = Signal()

    COLS = ["", "Shown", "Entity", "Label", "Icon", "Ring", "Min", "Max",
            "Tile", "On colour", "Card"]
    C_PICK, C_ON, C_ENTITY, C_LABEL, C_ICON, C_RING, C_MIN, C_MAX, \
        C_COLOR, C_ONCOLOR, C_POPUP = range(11)
    PAGES = (
        ("mdi6.link-variant", "Connection", "Home Assistant"),
        ("mdi6.format-list-bulleted", "Entities", "What the notch shows"),
        ("mdi6.monitor", "Appearance", "Where it sits"),
    )

    def __init__(self, store: db.Store, client, parent=None):
        super().__init__(parent)
        self.store = store
        self.client = client
        self.known_ids: list[str] = []
        self._last_check = 0.0
        self._loading = False

        self.setWindowTitle("HA Dock")
        self.resize(1180, 780)
        self.setMinimumSize(980, 660)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.root = QFrame(self)
        self.root.setObjectName("root")

        self.title_bar = TitleBar(self, "Minimal  ·  Smart  ·  Always at hand",
                                  self.root)

        self.rail_entries: list[RailEntry] = []
        self.stack = QStackedWidget(self.root)
        rail = QWidget(self.root)
        rail.setObjectName("rail")
        rail.setFixedWidth(300)
        rail_lay = QVBoxLayout(rail)
        rail_lay.setContentsMargins(14, 18, 14, 0)
        rail_lay.setSpacing(6)

        builders = (self._connection_page, self._entities_page,
                    self._appearance_page)
        for i, ((icon, title, subtitle), build) in enumerate(
                zip(self.PAGES, builders)):
            entry = RailEntry(icon, title, subtitle, rail)
            entry.mousePressEvent = (
                lambda _ev, idx=i: self.set_page(idx))
            entry.setCursor(Qt.CursorShape.PointingHandCursor)
            self.rail_entries.append(entry)
            rail_lay.addWidget(entry)
            self.stack.addWidget(build())
        rail_lay.addStretch(1)
        rail_lay.addWidget(RailFooter(__version__, rail))

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(rail)
        body.addWidget(self.stack, 1)

        shell = QVBoxLayout(self.root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self.title_bar)
        shell.addLayout(body, 1)

        outer = QVBoxLayout(self)
        # a transparent border wide enough to grab for resizing; without it
        # the child widgets take every mouse event and the edges are dead
        outer.setContentsMargins(*([ui_kit.EdgeResizer.MARGIN] * 4))
        outer.addWidget(self.root)

        self.resizer = ui_kit.EdgeResizer(self)
        self.toast = ui_kit.Toast(self.root)

        self._apply_style()
        self.set_page(0)
        self._load()

        self._age_timer = QTimer(self)
        self._age_timer.timeout.connect(self._refresh_age)
        self._age_timer.start(20000)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if getattr(self, "toast", None) is not None:
            self.toast._reposition()

    # -- frameless window resizing ----------------------------------------
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and \
                self.resizer.begin(ev.position().toPoint()):
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        self.resizer.update_cursor(ev.position().toPoint())
        super().mouseMoveEvent(ev)

    def leaveEvent(self, ev):
        self.unsetCursor()
        super().leaveEvent(ev)

    def set_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, entry in enumerate(self.rail_entries):
            entry.set_selected(i == index)

    # -- page scaffolding -------------------------------------------------
    def _page(self, heading: str, subtitle: str,
              right: QWidget | None = None) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(SectionHeading(heading, subtitle, True, page))
        head.addStretch(1)
        if right is not None:
            head.addWidget(right, 0, Qt.AlignmentFlag.AlignVCenter)

        lay = QVBoxLayout(page)
        lay.setContentsMargins(30, 26, 34, 28)
        lay.setSpacing(22)
        lay.addLayout(head)
        return page, lay

    # -- Connection -------------------------------------------------------
    def _connection_page(self) -> QWidget:
        self.pill = StatusPill()
        self.menu_btn = GhostButton("", "mdi6.dots-horizontal")
        self.menu_btn.setFixedSize(46, 44)
        self.menu_btn.clicked.connect(self._connection_menu)

        head_right = QWidget()
        hr = QHBoxLayout(head_right)
        hr.setContentsMargins(0, 0, 0, 0)
        hr.setSpacing(10)
        hr.addWidget(self.pill)
        hr.addWidget(self.menu_btn)

        page, lay = self._page(
            "Connection", "Connect to your Home Assistant instance",
            head_right)

        # --- credentials card
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("http://homeassistant.local:8123")
        self.url_edit.setMinimumHeight(46)
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("Long-Lived Access Token")
        self.token_edit.setMinimumHeight(46)

        self.show_token = Toggle(False)
        self.show_token.toggled.connect(
            lambda on: self.token_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on
                else QLineEdit.EchoMode.Password))

        show_row = QHBoxLayout()
        show_row.setContentsMargins(0, 0, 0, 0)
        show_row.setSpacing(12)
        show_row.addSpacing(364)          # aligns under the fields above
        show_row.addWidget(self.show_token)
        show_row.addWidget(text_label("Show token", 14, theme.TEXT))
        show_row.addStretch(1)

        self.test_btn = PrimaryButton("Test && Save", "mdi6.power-plug")
        self.test_btn.clicked.connect(self._test_connection)
        self.disconnect_btn = DangerButton("Disconnect",
                                           "mdi6.lan-disconnect")
        self.disconnect_btn.setMinimumHeight(52)
        self.disconnect_btn.clicked.connect(self._disconnect)

        note = text_label(
            "The token is stored in Windows Credential Manager,\n"
            "not in the database. Create one in Home Assistant under\n"
            "your profile → Security → Long-Lived Access Tokens.",
            12, theme.MUTED)
        note_row = QHBoxLayout()
        note_row.setContentsMargins(0, 0, 0, 0)
        note_row.setSpacing(14)
        note_row.addWidget(icon_label("mdi6.information-outline", 18,
                                      theme.MUTED),
                           0, Qt.AlignmentFlag.AlignTop)
        note_row.addWidget(note, 1, Qt.AlignmentFlag.AlignTop)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(14)
        action_row.addWidget(self.test_btn, 4)
        action_row.addWidget(self.disconnect_btn, 3)
        action_row.addSpacing(14)
        action_row.addWidget(divider(vertical=True))
        action_row.addLayout(note_row, 6)

        creds = Card()
        cl = QVBoxLayout(creds)
        cl.setContentsMargins(28, 26, 28, 26)
        cl.setSpacing(22)
        cl.addWidget(FieldRow("mdi6.link-variant", "Home Assistant URL",
                              "The address of your Home Assistant instance",
                              self.url_edit))
        cl.addWidget(FieldRow("mdi6.key-variant", "Access token",
                              "Long-Lived Access Token", self.token_edit))
        cl.addLayout(show_row)
        cl.addLayout(action_row)
        lay.addWidget(creds)

        lay.addWidget(self._status_card())
        lay.addStretch(1)
        return page

    def _status_card(self) -> QWidget:
        card = Card()
        self.status_icon = icon_label("mdi6.check-circle-outline", 34,
                                      theme.MUTED)
        self.status_title = text_label("Not connected yet", 17, theme.TEXT,
                                       QFont.Weight.DemiBold)
        self.status_body = text_label(
            "Enter your URL and token above, then press Test & Save.",
            13, theme.MUTED)
        self.recheck_btn = GhostButton("Check again", "mdi6.refresh")
        self.recheck_btn.clicked.connect(self._test_connection)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(4)
        titles.addWidget(self.status_title)
        titles.addWidget(self.status_body)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(18)
        top.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addLayout(titles, 1)
        top.addWidget(self.recheck_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.stat_instance = Stat("mdi6.server", "Instance",
                                  "Home Assistant", "not reached")
        self.stat_version = Stat("mdi6.package-variant-closed", "Version",
                                 "—", "")
        self.stat_latency = Stat("mdi6.clock-outline", "Response time",
                                 "—", "")

        stats = QHBoxLayout()
        stats.setContentsMargins(0, 0, 0, 0)
        stats.setSpacing(26)
        stats.addWidget(self.stat_instance, 1)
        stats.addWidget(divider(vertical=True))
        stats.addWidget(self.stat_version, 1)
        stats.addWidget(divider(vertical=True))
        stats.addWidget(self.stat_latency, 1)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(20)
        lay.addWidget(SectionHeading("Connection Status", "", False, card))
        lay.addLayout(top)
        lay.addWidget(divider())
        lay.addLayout(stats)
        return card

    def _connection_menu(self) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addAction("Reconnect now", self.reconnect_requested.emit)
        menu.addAction("Forget saved token", self._forget_token)
        menu.exec(self.menu_btn.mapToGlobal(
            self.menu_btn.rect().bottomLeft()))

    def _forget_token(self) -> None:
        db.save_token("")
        self.token_edit.clear()
        self.pill.set_state(False, "Not connected")
        self._set_status(False, "Token cleared",
                         "Enter a new token and press Test & Save.")

    def _disconnect(self) -> None:
        if not dialogs.confirm(
                self, "Disconnect", "Disconnect from Home Assistant",
                "and forget the token?",
                note="The notch will stop updating until you enter a token "
                     "again.\nNothing in Home Assistant is changed.",
                confirm_text="Disconnect",
                confirm_icon="mdi6.lan-disconnect"):
            return
        self.disconnect_requested.emit()
        db.save_token("")
        self.token_edit.clear()
        self._last_check = 0.0
        self.pill.set_state(False, "Disconnected")
        self._set_status(False, "Disconnected",
                         "Enter a token and press Test & Save to reconnect.")
        self.stat_instance.set("Home Assistant", "not connected")
        self.stat_version.set("—", "")
        self.stat_latency.set("—", "")

    def _test_connection(self) -> None:
        url = self.url_edit.text().strip()
        token = self.token_edit.text().strip()
        if not url or not token:
            self._set_status(False, "Missing details",
                             "Both the URL and a token are required.")
            return
        self.pill.set_state(False, "Checking…")
        self.test_btn.setEnabled(False)
        probe = _Probe(self)
        probe.done.connect(
            lambda ok, msg, ids, ms: self._probe_done(ok, msg, ids, ms,
                                                      url, token))
        probe.run(url, token)

    def _probe_done(self, ok: bool, msg: str, ids: list, ms: float,
                    url: str, token: str) -> None:
        self.test_btn.setEnabled(True)
        if not ok:
            self.pill.set_state(False, "Not connected")
            self._set_status(False, "Could not reach Home Assistant", msg)
            self.stat_instance.set("Home Assistant", "not reached")
            self.stat_version.set("—", "")
            self.stat_latency.set("—", "")
            return

        self._last_check = time.time()
        self.known_ids = ids
        self.store.set("ha_url", url)
        host = url.split("://", 1)[-1].rstrip("/")

        self.pill.set_state(True, "Connected", "Last checked: just now")
        self._set_status(
            True, "Successfully connected",
            "Home Assistant is reachable and responding.")
        self.stat_instance.set("Home Assistant", host)
        self.stat_version.set(msg, f"{len(ids)} entities")
        self.stat_latency.set(f"{ms:.0f} ms", self._latency_word(ms))
        self.toast.show_message(
            f"Connected to Home Assistant {msg} — token saved")

        if not db.save_token(token):
            QMessageBox.warning(
                self, "Credential Manager",
                "Could not write the token to Windows Credential Manager. "
                "The connection will work this session but not after a "
                "restart.")
        self.reconnect_requested.emit()

    @staticmethod
    def _latency_word(ms: float) -> str:
        if ms < 120:
            return "Excellent"
        if ms < 400:
            return "Good"
        if ms < 1200:
            return "Slow"
        return "Very slow"

    def _set_status(self, ok: bool, title: str, body: str) -> None:
        colour = theme.GOOD if ok else theme.MUTED
        name = ("mdi6.check-circle-outline" if ok
                else "mdi6.alert-circle-outline")
        self.status_icon.setPixmap(ui_kit.icon_pixmap(name, 34, colour))
        self.status_title.setText(title)
        self.status_body.setText(body)

    def _refresh_age(self) -> None:
        if not self._last_check:
            return
        mins = int((time.time() - self._last_check) // 60)
        if mins < 1:
            detail = "Last checked: just now"
        elif mins == 1:
            detail = "Last checked: 1 minute ago"
        elif mins < 60:
            detail = f"Last checked: {mins} minutes ago"
        else:
            detail = f"Last checked: {mins // 60}h ago"
        if self.client.is_connected:
            self.pill.set_state(True, "Connected", detail)

    def set_status(self, text: str) -> None:
        """Called by the app when the live socket changes state."""
        ok = self.client.is_connected
        if ok and not self._last_check:
            self._last_check = time.time()
        self.pill.set_state(ok, "Connected" if ok else "Not connected",
                            text if not ok else "Last checked: just now")

    # -- Entities ---------------------------------------------------------
    def _entities_page(self) -> QWidget:
        self.add_btn = PrimaryButton("Add entity", "mdi6.plus")
        self.add_btn.setMinimumHeight(44)
        self.add_btn.clicked.connect(self._add_entity)

        page, lay = self._page("Entities", "What the notch shows",
                               self.add_btn)

        self.table = ReorderTable(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.reordered.connect(self._drag_reorder)

        # select-all rides on the header's first section
        self.select_all = QCheckBox(self.table.horizontalHeader())
        self.select_all.setToolTip("Select every row")
        self.select_all.toggled.connect(self._toggle_all)
        self.table.horizontalHeader().sectionResized.connect(
            lambda *_: self._place_select_all())
        self._size_columns()

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search entities…")
        self.search.setMinimumHeight(42)
        self.search.setMaximumWidth(380)
        self.search.addAction(
            ui_kit.button_icon("mdi6.magnify", 16, theme.MUTED),
            QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._filter_rows)

        self.empty_hint = text_label(
            "Drag rows to reorder entities", 14, theme.MUTED)
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = Card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 20, 22, 20)
        cl.setSpacing(16)
        cl.addWidget(self.search)
        cl.addWidget(self.table, 1)
        cl.addWidget(self.empty_hint)
        lay.addWidget(card, 1)

        self.sel_label = text_label("No rows selected", 12, theme.MUTED)
        enable = GhostButton("Enable", "mdi6.eye-outline")
        disable = GhostButton("Disable", "mdi6.eye-off-outline")
        rem = GhostButton("Delete", "mdi6.trash-can-outline")
        apply = GhostButton("Apply changes", "mdi6.content-save-outline")
        enable.clicked.connect(lambda: self._set_enabled_selected(True))
        disable.clicked.connect(lambda: self._set_enabled_selected(False))
        rem.clicked.connect(self._delete_selected)
        apply.clicked.connect(lambda: self._save_entities(announce=True))

        hint = text_label(
            "Drag a row by its entity name to change the order. Double-click "
            "any cell to edit it. Ring modes — none: icon only, the usual "
            "choice for a lamp or switch. flat: full ring when on. value: "
            "fills between min and max. ramp: green to orange as the value "
            "climbs.", 12, theme.MUTED)
        hint.setWordWrap(True)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(10)
        bar.addWidget(self.sel_label)
        bar.addSpacing(8)
        for b in (enable, disable, rem):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(apply)

        lay.addWidget(hint)
        lay.addLayout(bar)
        return page

    def _filter_rows(self, term: str) -> None:
        term = (term or "").strip().lower()
        shown = 0
        for r in range(self.table.rowCount()):
            eid = self.table.item(r, self.C_ENTITY)
            lab = self.table.item(r, self.C_LABEL)
            haystack = " ".join(filter(None, [
                eid.text() if eid else "", lab.text() if lab else ""])).lower()
            hide = bool(term) and term not in haystack
            self.table.setRowHidden(r, hide)
            shown += 0 if hide else 1
        if self.table.rowCount() == 0:
            self.empty_hint.setText("No entities yet — add one to begin")
        elif shown == 0:
            self.empty_hint.setText(f"Nothing matches “{term}”")
        else:
            self.empty_hint.setText("Drag rows to reorder entities")
        self.empty_hint.setVisible(shown == 0 or self.table.rowCount() == 0)

    def _drag_reorder(self, src: int, dst: int) -> None:
        self._save_entities()
        ids = [e.row_id for e in self.store.entities()]
        if not (0 <= src < len(ids) and 0 <= dst < len(ids)):
            return
        ids.insert(dst, ids.pop(src))
        self.store.reorder(ids)
        self._load_entities()
        self.table.selectRow(dst)
        self.config_changed.emit()

    def _place_select_all(self) -> None:
        hh = self.table.horizontalHeader()
        w = self.table.columnWidth(self.C_PICK)
        self.select_all.setGeometry(
            max(0, (w - 17) // 2), (hh.height() - 17) // 2, 17, 17)

    def _checkbox_cell(self, checked: bool) -> tuple[QWidget, QCheckBox]:
        chk = QCheckBox()
        chk.setChecked(checked)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(chk, 0, Qt.AlignmentFlag.AlignCenter)
        return holder, chk

    def _row_widgets(self, r: int, e: db.EntityRow) -> None:
        pick_cell, pick = self._checkbox_cell(False)
        pick.toggled.connect(self._update_selection_label)
        self.table.setCellWidget(r, self.C_PICK, pick_cell)

        on_cell, _on = self._checkbox_cell(bool(e.enabled))
        self.table.setCellWidget(r, self.C_ON, on_cell)

        eid = QTableWidgetItem(e.entity_id)
        eid.setData(Qt.ItemDataRole.UserRole, e.row_id)
        self.table.setItem(r, self.C_ENTITY, eid)
        self.table.setItem(r, self.C_LABEL, QTableWidgetItem(e.label))

        icon_btn = QPushButton(self._icon_caption(e))
        icon_btn.setProperty("icon_name", e.icon)
        icon_btn.clicked.connect(
            lambda _=False, b=icon_btn: self._pick_icon(b))
        self.table.setCellWidget(r, self.C_ICON, icon_btn)

        combo = QComboBox()
        combo.addItems(RING_MODES)
        combo.setCurrentText(e.ring_mode if e.ring_mode in RING_MODES
                             else "none")
        for i, mode in enumerate(RING_MODES):
            combo.setItemData(i, RING_HELP[mode], Qt.ItemDataRole.ToolTipRole)
        self.table.setCellWidget(r, self.C_RING, combo)

        for col, val in ((self.C_MIN, e.ring_min), (self.C_MAX, e.ring_max)):
            spin = QDoubleSpinBox()
            spin.setRange(-100000, 100000)
            spin.setDecimals(1)
            spin.setValue(val)
            self.table.setCellWidget(r, col, spin)

        col_btn = QPushButton(e.color or "auto")
        col_btn.setProperty("hex", e.color)
        col_btn.clicked.connect(
            lambda _=False, b=col_btn: self._pick_colour(b))
        self.table.setCellWidget(r, self.C_COLOR, col_btn)

        # The colour the light comes on at. Lights only — a switch has no
        # colour to set, and offering it would be a control that lies.
        is_light = domains.domain_of(e.entity_id) == "light"
        on_btn = QPushButton(e.on_color if is_light else "n/a")
        on_btn.setProperty("hex", e.on_color if is_light else "")
        on_btn.setEnabled(is_light)
        if is_light:
            on_btn.setToolTip("Click to set, right-click to clear. The light "
                              "turns on at this colour.")
            self._tint_swatch(on_btn, e.on_color)
            on_btn.clicked.connect(
                lambda _=False, b=on_btn: self._pick_on_colour(b))
            on_btn.setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu)
            on_btn.customContextMenuRequested.connect(
                lambda _p, b=on_btn: self._clear_on_colour(b))
        self.table.setCellWidget(r, self.C_ONCOLOR, on_btn)

        # The detail card only has controls for a few domains. Offering it
        # on a sensor would be a checkbox that does nothing.
        can_pop = supports_popup(e.entity_id)
        pop_cell, pop = self._checkbox_cell(bool(e.popup) and can_pop)
        pop.setEnabled(can_pop)
        pop.setToolTip(
            "Hover this tile to open a slider card"
            if can_pop else
            f"No card for {domains.domain_of(e.entity_id)} entities")
        self.table.setCellWidget(r, self.C_POPUP, pop_cell)

    def _tint_swatch(self, btn: QPushButton, hex_colour: str) -> None:
        """Show the chosen colour in the button itself — a hex string alone
        tells you nothing about what the light will look like."""
        c = QColor(hex_colour) if hex_colour else QColor()
        if not hex_colour or not c.isValid():
            btn.setText("none")
            btn.setStyleSheet("")
            return
        btn.setText(c.name())
        ink = "#04121C" if c.lightnessF() > 0.55 else "#FFFFFF"
        # every line here must be an f-string: a plain one leaves the
        # doubled braces in place and Qt rejects the whole sheet
        btn.setStyleSheet(
            f"QPushButton {{ background:{c.name()}; color:{ink};"
            f" border:1px solid {theme.HAIRLINE_HI}; border-radius:8px;"
            f" padding:6px 8px; font-size:11px; font-weight:600; }}")

    def _pick_on_colour(self, btn: QPushButton) -> None:
        start = QColor(btn.property("hex") or "#FF3B30")
        col = QColorDialog.getColor(start, self, "Colour to turn the light on at")
        if col.isValid():
            btn.setProperty("hex", col.name())
            self._tint_swatch(btn, col.name())

    def _clear_on_colour(self, btn: QPushButton) -> None:
        btn.setProperty("hex", "")
        self._tint_swatch(btn, "")

    # -- selection --------------------------------------------------------
    def _row_checkbox(self, r: int, col: int) -> QCheckBox | None:
        holder = self.table.cellWidget(r, col)
        return holder.findChild(QCheckBox) if holder else None

    def _selected_rows(self) -> list[int]:
        return [r for r in range(self.table.rowCount())
                if (cb := self._row_checkbox(r, self.C_PICK))
                and cb.isChecked()]

    def _toggle_all(self, on: bool) -> None:
        for r in range(self.table.rowCount()):
            cb = self._row_checkbox(r, self.C_PICK)
            if cb:
                cb.blockSignals(True)
                cb.setChecked(on)
                cb.blockSignals(False)
        self._update_selection_label()

    def _update_selection_label(self) -> None:
        n = len(self._selected_rows())
        total = self.table.rowCount()
        if n == 0:
            self.sel_label.setText("No rows selected")
        elif n == 1:
            self.sel_label.setText("1 row selected")
        else:
            self.sel_label.setText(f"{n} of {total} rows selected")

    def _set_enabled_selected(self, on: bool) -> None:
        rows = self._selected_rows()
        if not rows:
            self._nothing_selected()
            return
        for r in rows:
            cb = self._row_checkbox(r, self.C_ON)
            if cb:
                cb.setChecked(on)
        self._save_entities()
        word = "Shown in" if on else "Hidden from"
        self.toast.show_message(
            f"{word} the notch: {len(rows)} "
            f"{'entity' if len(rows) == 1 else 'entities'}")

    def _nothing_selected(self) -> None:
        dialogs.notice(
            self, "Nothing selected", "No rows are ticked.",
            "Tick the box at the left of a row, or use the box in the "
            "header to take them all.")

    def _delete_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            self._nothing_selected()
            return
        names = [self.table.item(r, self.C_ENTITY).text() for r in rows
                 if self.table.item(r, self.C_ENTITY)]
        shown = names[:6]
        note = ("This only removes them from HA Dock.\n"
                "Nothing in Home Assistant is changed.")
        if len(names) > len(shown):
            note = f"…and {len(names) - len(shown)} more.\n\n" + note

        word = "entity" if len(names) == 1 else "entities"
        if not dialogs.confirm(
                self, "Delete Entities",
                f"Remove {len(names)} {word}", "from the notch?",
                items=shown, note=note, confirm_text="Delete",
                confirm_icon="mdi6.trash-can-outline"):
            return

        self._save_entities()
        for r in rows:
            item = self.table.item(r, self.C_ENTITY)
            if item:
                self.store.delete_entity(
                    int(item.data(Qt.ItemDataRole.UserRole)))
        self.select_all.setChecked(False)
        self._load_entities()
        self.config_changed.emit()
        self.toast.show_message(
            f"Removed {len(names)} "
            f"{'entity' if len(names) == 1 else 'entities'} from the notch")

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Entity IDs are editable, so they need validating as they change."""
        if self._loading or item.column() != self.C_ENTITY:
            return
        text = item.text().strip()
        row_id = item.data(Qt.ItemDataRole.UserRole)
        if "." in text and len(text.split(".", 1)[1]) > 0:
            return
        dialogs.notice(
            self, "Invalid entity ID", f"'{text}' is not an entity ID.",
            "IDs look like domain.name — for example light.bedroom.",
            icon="mdi6.alert-outline", colour=theme.DANGER)
        previous = next((e.entity_id for e in self.store.entities()
                         if e.row_id == row_id), text)
        self._loading = True
        item.setText(previous)
        self._loading = False

    def _icon_caption(self, e: db.EntityRow) -> str:
        name = e.icon or domains.default_icon(e.entity_id)
        return f"{glyph.char_for(name)}  {glyph.split(name)[1]}"

    def _pick_icon(self, btn: QPushButton) -> None:
        dlg = IconPicker(btn.property("icon_name") or "", self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected:
            btn.setProperty("icon_name", dlg.selected)
            btn.setText(f"{glyph.char_for(dlg.selected)}  "
                        f"{glyph.split(dlg.selected)[1]}")

    def _pick_colour(self, btn: QPushButton) -> None:
        start = QColor(btn.property("hex") or theme.SIGNAL)
        col = QColorDialog.getColor(start, self, "Tile colour")
        if col.isValid():
            btn.setProperty("hex", col.name())
            btn.setText(col.name())

    def _add_entity(self) -> None:
        known = self.known_ids or sorted(self.client.states.keys())
        dlg = AddEntityDialog(known, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        eid = dlg.entity_id()
        if not eid or "." not in eid:
            QMessageBox.warning(self, "Add entity",
                                "That does not look like an entity ID.")
            return
        attrs = (self.client.states.get(eid) or {}).get("attributes", {})
        self.store.add_entity(db.EntityRow(
            entity_id=eid, icon=domains.default_icon(eid, attrs),
            popup=1 if supports_popup(eid) else 0))
        self._load_entities()
        self.config_changed.emit()

    def _remove_entity(self) -> None:
        self._delete_selected()

    def _move(self, delta: int) -> None:
        r = self.table.currentRow()
        if r < 0:
            return
        new = r + delta
        if new < 0 or new >= self.table.rowCount():
            return
        self._save_entities()
        ids = [e.row_id for e in self.store.entities()]
        ids[r], ids[new] = ids[new], ids[r]
        self.store.reorder(ids)
        self._load_entities()
        self.table.selectRow(new)
        self.config_changed.emit()

    def _save_entities(self, announce: bool = False) -> None:
        if self._loading:
            return
        seen: set[str] = set()
        saved = 0
        for r in range(self.table.rowCount()):
            item = self.table.item(r, self.C_ENTITY)
            if item is None:
                continue
            entity_id = item.text().strip()
            if "." not in entity_id or entity_id in seen:
                continue
            seen.add(entity_id)
            on_cb = self._row_checkbox(r, self.C_ON)
            pop_cb = self._row_checkbox(r, self.C_POPUP)
            icon_btn = self.table.cellWidget(r, self.C_ICON)
            combo = self.table.cellWidget(r, self.C_RING)
            lo = self.table.cellWidget(r, self.C_MIN)
            hi = self.table.cellWidget(r, self.C_MAX)
            col_btn = self.table.cellWidget(r, self.C_COLOR)
            on_btn = self.table.cellWidget(r, self.C_ONCOLOR)
            label_item = self.table.item(r, self.C_LABEL)
            self.store.update_entity(db.EntityRow(
                entity_id=entity_id,
                label=label_item.text() if label_item else "",
                icon=(icon_btn.property("icon_name") or "") if icon_btn else "",
                color=(col_btn.property("hex") or "") if col_btn else "",
                on_color=(on_btn.property("hex") or "") if on_btn else "",
                ring_mode=combo.currentText() if combo else "none",
                ring_min=lo.value() if lo else 0.0,
                ring_max=hi.value() if hi else 100.0,
                enabled=1 if (on_cb and on_cb.isChecked()) else 0,
                popup=1 if (pop_cb and pop_cb.isChecked()) else 0,
                sort_index=r,
                row_id=int(item.data(Qt.ItemDataRole.UserRole)),
            ))
            saved += 1
        self.config_changed.emit()
        if announce:
            self.toast.show_message(
                f"Saved {saved} {'entity' if saved == 1 else 'entities'} "
                "— the notch is updated")

    def _size_columns(self) -> None:
        # Proportional, so the row and its header stay lined up at any
        # window width. Fixed pixel widths plus one stretch column is what
        # made everything bunch up once the window was maximised.
        self.table.set_weights(
            weights={
                self.C_PICK: 0.4, self.C_ON: 0.5, self.C_ENTITY: 2.4,
                self.C_LABEL: 1.4, self.C_ICON: 1.5, self.C_RING: 1.0,
                self.C_MIN: 1.1, self.C_MAX: 1.1, self.C_COLOR: 0.9,
                self.C_ONCOLOR: 1.0, self.C_POPUP: 0.55,
            },
            minimums={
                self.C_PICK: 36, self.C_ON: 40, self.C_ENTITY: 120,
                self.C_LABEL: 74, self.C_ICON: 96, self.C_RING: 68,
                self.C_MIN: 66, self.C_MAX: 66, self.C_COLOR: 60,
                self.C_ONCOLOR: 72, self.C_POPUP: 44,
            },
        )
        self.table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._place_select_all()

    def _load_entities(self) -> None:
        self._loading = True
        try:
            rows = self.store.entities()
            self.table.setRowCount(len(rows))
            for r, e in enumerate(rows):
                self._row_widgets(r, e)
            self._size_columns()
        finally:
            self._loading = False
        self._update_selection_label()
        self._filter_rows(self.search.text())

    # -- Appearance -------------------------------------------------------
    def _appearance_page(self) -> QWidget:
        from PySide6.QtGui import QGuiApplication

        self.save_look_btn = PrimaryButton("Apply", "mdi6.check")
        self.save_look_btn.setMinimumHeight(44)
        self.save_look_btn.clicked.connect(self._save_appearance)

        page, lay = self._page("Appearance", "Where it sits",
                               self.save_look_btn)

        self.edge_combo = QComboBox()
        # No bottom edge: the taskbar lives there, so a notch welded to it
        # is either hidden or fighting for the same pixels.
        self.edge_combo.addItems(["right", "left", "top"])
        self.screen_combo = QComboBox()
        self.screen_combo.addItem("Primary", "")
        for sc in QGuiApplication.screens():
            self.screen_combo.addItem(
                f"{sc.name()}  ({sc.geometry().width()}×"
                f"{sc.geometry().height()})", sc.name())
        self.size_combo = QComboBox()
        self.size_combo.addItems(["small", "medium", "large"])
        self.offset_spin = QSpinBox()
        self.offset_spin.setRange(-2000, 2000)
        self.offset_spin.setSuffix("  px")
        for c in (self.edge_combo, self.screen_combo, self.size_combo,
                  self.offset_spin):
            c.setMinimumHeight(44)

        placement = Card()
        pl = QVBoxLayout(placement)
        pl.setContentsMargins(28, 24, 28, 24)
        pl.setSpacing(20)
        pl.addWidget(SectionHeading("Placement", "", False, placement))
        pl.addWidget(FieldRow("mdi6.dock-right", "Screen edge",
                              "Which bezel the notch welds itself to",
                              self.edge_combo))
        pl.addWidget(FieldRow("mdi6.monitor-multiple", "Monitor",
                              "Which display it lives on",
                              self.screen_combo))
        pl.addWidget(FieldRow("mdi6.arrow-up-down", "Offset along edge",
                              "Zero keeps it centred", self.offset_spin))
        pl.addWidget(FieldRow("mdi6.resize", "Size",
                              "Scales rings, glyphs and labels together",
                              self.size_combo))
        lay.addWidget(placement)

        self.hover_tgl = Toggle(True)
        self.labels_tgl = Toggle(True)
        self.autostart_tgl = Toggle(False)
        self.desktop_tgl = Toggle(False)
        self.fullscreen_tgl = Toggle(True)
        self.autoclose_spin = QSpinBox()
        self.autoclose_spin.setRange(0, 600)
        self.autoclose_spin.setSuffix("  seconds")
        self.autoclose_spin.setMinimumHeight(44)
        self.autoclose_spin.setSpecialValueText("Never")

        behaviour = Card()
        bl = QVBoxLayout(behaviour)
        bl.setContentsMargins(28, 24, 28, 24)
        bl.setSpacing(20)
        bl.addWidget(SectionHeading("Behaviour", "", False, behaviour))
        bl.addWidget(FieldRow("mdi6.gesture-tap", "Expand on hover",
                              "Unfold as the pointer reaches the edge",
                              self._toggle_cell(self.hover_tgl)))
        bl.addWidget(FieldRow("mdi6.format-text", "Value labels",
                              "Show a reading under each icon",
                              self._toggle_cell(self.labels_tgl)))
        bl.addWidget(FieldRow("mdi6.timer-outline", "Auto-collapse after",
                              "How long a pinned notch stays open",
                              self.autoclose_spin))
        bl.addWidget(FieldRow("mdi6.fullscreen", "Hide on fullscreen",
                              "Step aside for games and video, but stay put "
                              "for a merely maximised window",
                              self._toggle_cell(self.fullscreen_tgl)))
        bl.addWidget(FieldRow("mdi6.rocket-launch-outline",
                              "Start with Windows",
                              "Launch HA Dock when you sign in",
                              self._toggle_cell(self.autostart_tgl)))
        bl.addWidget(FieldRow("mdi6.monitor-dashboard",
                              "Desktop shortcut",
                              "Put a HA Dock icon on your desktop",
                              self._toggle_cell(self.desktop_tgl)))
        lay.addWidget(behaviour)
        lay.addStretch(1)
        return page

    @staticmethod
    def _toggle_cell(toggle: Toggle) -> QWidget:
        cell = QWidget()
        row = QHBoxLayout(cell)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(toggle, 0, Qt.AlignmentFlag.AlignLeft)
        row.addStretch(1)
        return cell

    def _save_appearance(self) -> None:
        self.store.set("edge", self.edge_combo.currentText())
        self.store.set("screen_name", self.screen_combo.currentData() or "")
        self.store.set("size", self.size_combo.currentText())
        self.store.set("align_offset", self.offset_spin.value())
        self.store.set("hover_peek", 1 if self.hover_tgl.isChecked() else 0)
        self.store.set("show_labels", 1 if self.labels_tgl.isChecked() else 0)
        self.store.set("auto_collapse_s", self.autoclose_spin.value())
        self.store.set("hide_on_fullscreen",
                       1 if self.fullscreen_tgl.isChecked() else 0)

        want = self.autostart_tgl.isChecked()
        if want != self.store.get_bool("start_with_windows", False):
            from .shortcut import set_autostart

            ok, msg = set_autostart(want)
            if not ok:
                QMessageBox.warning(self, "Start with Windows", msg)
                self.autostart_tgl.setChecked(not want)
            else:
                self.store.set("start_with_windows", 1 if want else 0)

        want_desk = self.desktop_tgl.isChecked()
        if want_desk != self.store.get_bool("desktop_shortcut", False):
            from .shortcut import set_desktop_shortcut

            ok, msg = set_desktop_shortcut(want_desk)
            if not ok:
                QMessageBox.warning(self, "Desktop shortcut", msg)
                self.desktop_tgl.setChecked(not want_desk)
            else:
                self.store.set("desktop_shortcut", 1 if want_desk else 0)
        self.config_changed.emit()
        self.toast.show_message(
            f"Appearance saved — {self.size_combo.currentText()} notch on "
            f"the {self.edge_combo.currentText()} edge")

    # -- load -------------------------------------------------------------
    def _load(self) -> None:
        self.url_edit.setText(self.store.get("ha_url"))
        self.token_edit.setText(db.load_token())
        self.edge_combo.setCurrentText(
            self.store.get("edge", "right").replace("bottom", "right"))
        idx = self.screen_combo.findData(self.store.get("screen_name", ""))
        self.screen_combo.setCurrentIndex(max(idx, 0))
        self.size_combo.setCurrentText(self.store.get("size", "medium"))
        self.offset_spin.setValue(self.store.get_int("align_offset", 0))
        self.hover_tgl.setChecked(
            self.store.get_bool("hover_peek", True), animate=False)
        self.labels_tgl.setChecked(
            self.store.get_bool("show_labels", True), animate=False)
        self.autoclose_spin.setValue(self.store.get_int("auto_collapse_s", 6))
        self.autostart_tgl.setChecked(
            self.store.get_bool("start_with_windows", False), animate=False)
        self.desktop_tgl.setChecked(
            self.store.get_bool("desktop_shortcut", False), animate=False)
        self.fullscreen_tgl.setChecked(
            self.store.get_bool("hide_on_fullscreen", True), animate=False)
        self.known_ids = sorted(self.client.states.keys())
        self._load_entities()

    def closeEvent(self, ev):
        ev.ignore()
        self._save_entities()
        self.hide()

    # -- style ------------------------------------------------------------
    def _apply_style(self) -> None:
        t = theme
        self.setStyleSheet(f"""
        QWidget {{ color: {t.TEXT}; font-family: "{t.UI_FAMILY}";
                   font-size: 13px; background: transparent; }}

        QFrame#root {{
            background: qlineargradient(x1:0, y1:0, x2:0.8, y2:1,
                stop:0 #0C1B2B, stop:0.55 {t.SHELL}, stop:1 #050B13);
            border: 1px solid {t.HAIRLINE_HI};
            border-radius: {t.WINDOW_RADIUS}px;
        }}
        QWidget#rail {{ background: rgba(6,13,22,120);
                        border-right: 1px solid {t.HAIRLINE}; }}

        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background: {t.RAISED}; border: 1px solid {t.HAIRLINE};
            border-radius: {t.FIELD_RADIUS}px; padding: 8px 14px;
            font-size: 14px; color: {t.TEXT};
            selection-background-color: {t.SIGNAL};
            selection-color: #04121C; }}
        QLineEdit:hover, QComboBox:hover, QSpinBox:hover,
        QDoubleSpinBox:hover {{ border: 1px solid {t.HAIRLINE_HI}; }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
        QDoubleSpinBox:focus {{ border: 1px solid {t.SIGNAL}; }}
        QComboBox::drop-down {{ border: 0; width: 26px; }}
        QComboBox QAbstractItemView {{
            background: {t.PANEL}; border: 1px solid {t.HAIRLINE};
            border-radius: 8px; padding: 4px; outline: 0;
            selection-background-color: {t.RAISED};
            selection-color: {t.SIGNAL}; }}

        QCheckBox::indicator {{ width: 17px; height: 17px;
            border-radius: 5px; border: 1px solid {t.HAIRLINE};
            background: {t.RAISED}; }}
        QCheckBox::indicator:checked {{ background: {t.SIGNAL};
            border: 1px solid {t.SIGNAL}; }}

        QTableWidget {{ background: transparent; border: 0;
            gridline-color: transparent;
            selection-background-color: rgba(56,214,245,22);
            font-family: "{t.MONO_FAMILY}"; font-size: 12px; }}
        QTableWidget::item {{ padding: 6px; border-bottom: 1px solid
            {t.HAIRLINE}; }}
        QTableWidget::item:selected {{ color: {t.SIGNAL}; }}
        QHeaderView::section {{ background: transparent; border: 0;
            border-bottom: 1px solid {t.HAIRLINE_HI}; padding: 10px 8px;
            color: {t.MUTED}; font-family: "{t.UI_FAMILY}";
            font-size: 11px; }}
        QTableWidget QPushButton {{ background: {t.RAISED};
            border: 1px solid {t.HAIRLINE}; border-radius: 8px;
            padding: 6px 8px; color: {t.TEXT}; font-size: 12px; }}
        QTableWidget QPushButton:hover {{ border: 1px solid {t.SIGNAL};
            color: {t.SIGNAL}; }}
        QTableWidget QComboBox, QTableWidget QDoubleSpinBox {{
            padding: 5px 6px; font-size: 12px; border-radius: 8px; }}
        QTableWidget QComboBox::drop-down {{ width: 16px; }}

        QScrollBar:vertical {{ background: transparent; width: 10px;
            margin: 4px; }}
        QScrollBar::handle:vertical {{ background: {t.HAIRLINE_HI};
            border-radius: 5px; min-height: 36px; }}
        QScrollBar::handle:vertical:hover {{ background: {t.SIGNAL}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

        QMenu {{ background: {t.PANEL}; border: 1px solid {t.HAIRLINE};
            border-radius: 10px; padding: 6px; }}
        QMenu::item {{ padding: 8px 18px; border-radius: 6px; }}
        QMenu::item:selected {{ background: {t.RAISED};
            color: {t.SIGNAL}; }}

        QSizeGrip {{ background: transparent; }}
        QToolTip {{ background: {t.PANEL}; color: {t.TEXT};
            border: 1px solid {t.HAIRLINE}; padding: 6px; }}
        """)
