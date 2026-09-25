"""Application wiring: tray icon, notch, settings window, HA client."""

from __future__ import annotations

import sys

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import (QAction, QColor, QGuiApplication, QIcon, QPainter,
                           QPixmap)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import __version__, db, domains, glyph, theme, ui_kit
from .ha_client import HaClient
from .lampcord import Lampcord
from .notch_window import NotchWindow
from .settings_window import SettingsWindow
from .single_instance import SingleInstance
from .updater import (UpdateApplier, UpdateChecker, is_frozen,
                      open_release_page)


def _tray_pixmap(colour: QColor, size: int = 64) -> QPixmap:
    return ui_kit.app_icon(size, colour.name())


def app_qicon() -> QIcon:
    """One mark, several sizes, so Windows never has to scale it badly."""
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(ui_kit.app_icon(s))
    return icon


class Application:
    """Constructed by run.py and by smoke.py, so keep the ctor side-effect
    free beyond widget creation."""

    def __init__(self, store: db.Store | None = None):
        self.store = store or db.Store()
        self.client = HaClient()
        self.notch = NotchWindow(self.store, self.client)
        self.settings = SettingsWindow(self.store, self.client)
        self.tray = QSystemTrayIcon()
        self.cord: Lampcord | None = None
        self.update_checker = UpdateChecker()
        self.update_applier = UpdateApplier()
        self._update_info = None
        self._update_silent = False

        self._build_tray()
        self._wire()

    # -- tray -------------------------------------------------------------
    def _build_tray(self) -> None:
        # Orange is the app's mark, so the tray shows it in both states and
        # the connection is read from the tooltip and the notch's own bar.
        self.icon_ok = QIcon(_tray_pixmap(QColor(theme.BRAND)))
        self.icon_bad = QIcon(_tray_pixmap(QColor(theme.BRAND_DIM)))
        self.tray.setIcon(self.icon_bad)
        self.tray.setToolTip("HA Dock — disconnected")
        window_icon = app_qicon()
        self.settings.setWindowIcon(window_icon)
        QApplication.setWindowIcon(window_icon)

        menu = QMenu()
        act_settings = QAction("Settings…", menu)
        act_settings.triggered.connect(self.show_settings)
        act_toggle = QAction("Show / hide notch", menu)
        act_toggle.triggered.connect(self.toggle_notch)
        act_reconnect = QAction("Reconnect", menu)
        act_reconnect.triggered.connect(self.reconnect)
        act_update = QAction("Check for updates", menu)
        act_update.triggered.connect(self.check_for_updates)
        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(self.quit)
        for a in (act_settings, act_toggle, act_reconnect, act_update):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_settings()

    # -- wiring -----------------------------------------------------------
    def _wire(self) -> None:
        self.notch.settings_requested.connect(self.show_settings)
        self.notch.quit_requested.connect(self.quit)
        self.notch.reconnect_requested.connect(self.reconnect)

        self.settings.config_changed.connect(self._config_changed)
        self.settings.reconnect_requested.connect(self.reconnect)
        self.settings.disconnect_requested.connect(self.disconnect)
        self.settings.update_requested.connect(
            lambda: self.check_for_updates(silent=False))
        self.settings.quit_requested.connect(self.quit)

        self.client.status.connect(self._on_status)
        self.client.connected.connect(lambda _: self._set_tray(True))
        self.client.disconnected.connect(lambda _: self._set_tray(False))
        self.client.auth_failed.connect(self._on_auth_failed)
        self.client.states_reset.connect(self.notch.reload)
        self.client.states_reset.connect(self._refresh_cord_state)
        self.client.states_reset.connect(self.settings.refresh_entity_lists)

        self.client.entity_updated.connect(self._on_entity_update)

        self.update_checker.found.connect(self._on_update_found)
        self.update_checker.checked.connect(self._on_update_checked)
        self.update_applier.failed.connect(self._on_update_failed)
        self.update_applier.ready_to_restart.connect(self._on_update_ready)


    def _config_changed(self) -> None:
        self.notch.reload()
        self._sync_cord()

    # -- Lampcord ---------------------------------------------------------
    def _sync_cord(self) -> None:
        """Create, move or destroy the Lampcord to match the settings."""
        want = self.store.get_bool("cord_enabled", False)
        entity = self.store.get("cord_entity", "")
        if not want or not entity:
            if self.cord is not None:
                self.cord.close()
                self.cord.deleteLater()
                self.cord = None
            return

        if self.cord is None:
            self.cord = Lampcord()
            self.cord.toggled.connect(self._cord_pulled)
            self.cord.moved.connect(self._cord_moved)
        self.cord.layout_.offset_x = self.store.get_int("cord_offset_x", 620)
        self.cord.place(self._cord_screen())
        self.cord.show()
        self._refresh_cord_state()

    def _cord_screen(self):
        name = self.store.get("cord_screen", "")
        if name:
            for sc in QGuiApplication.screens():
                if sc.name() == name:
                    return sc
        return QGuiApplication.primaryScreen()

    def _cord_entity(self) -> str:
        return self.store.get("cord_entity", "")

    def _cord_pulled(self) -> None:
        entity = self._cord_entity()
        if not entity:
            return
        self.client.call_service("light", "toggle",
                                 target={"entity_id": entity})
        if self.cord is not None:
            # flip it straight away and let the real state correct us, the
            # same optimistic update the tiles use
            self.cord.set_lit(not self.cord.is_lit())

    def _cord_moved(self, offset_x: int) -> None:
        self.store.set("cord_offset_x", offset_x)
        try:
            self.settings.set_cord_offset(offset_x)
        except Exception:
            pass

    def _refresh_cord_state(self) -> None:
        if self.cord is None:
            return
        state = (self.client.states.get(self._cord_entity()) or {})
        self.cord.set_lit(domains.is_on(state.get("state", "")))

    def _on_entity_update(self, entity_id: str, payload: dict) -> None:
        if self.cord is not None and entity_id == self._cord_entity():
            self.cord.set_lit(domains.is_on(payload.get("state", "")))

    def _on_status(self, text: str) -> None:
        self.tray.setToolTip(f"HA Dock — {text}")
        try:
            self.settings.set_status(text)
        except Exception:
            pass

    def _set_tray(self, ok: bool) -> None:
        self.tray.setIcon(self.icon_ok if ok else self.icon_bad)

    def _on_auth_failed(self, msg: str) -> None:
        self._set_tray(False)
        self.tray.showMessage(
            "HA Dock", f"Home Assistant rejected the token: {msg}",
            QSystemTrayIcon.MessageIcon.Warning, 8000)
        self.show_settings()

    # -- updates ------------------------------------------------------
    def check_for_updates(self, silent: bool = False) -> None:
        self._update_silent = silent
        self.update_checker.check_async()

    def _on_update_found(self, info) -> None:
        self._update_info = info
        from . import dialogs

        do_update = dialogs.confirm(
            self.settings, "Update available",
            f"Version {info.version} is available "
            f"(you have {__version__}).",
            tail=info.notes[:600] if info.notes else "",
            confirm_text="Update now", confirm_icon="mdi6.arrow-up-circle",
            destructive=False)
        if not do_update:
            return
        if not is_frozen():
            open_release_page(info)
            return
        self.tray.setToolTip("HA Dock — updating…")
        self.update_applier.apply_async(info)

    def _on_update_checked(self) -> None:
        if self._update_info is None and not self._update_silent:
            from . import dialogs
            dialogs.notice(self.settings, "No updates",
                           f"You already have the latest version "
                           f"({__version__}).")

    def _on_update_failed(self, message: str) -> None:
        if self._update_info is not None:
            from . import dialogs

            dialogs.notice(
                self.settings, "Update failed",
                "The update could not be applied automatically.",
                detail=message, icon="mdi6.alert-circle-outline",
                colour=theme.ALERT)
            if self._update_info is not None:
                open_release_page(self._update_info)
        self._update_info = None

    def _on_update_ready(self) -> None:
        self.quit()

    # -- actions ----------------------------------------------------------
    def show_settings(self) -> None:
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def toggle_notch(self) -> None:
        self.notch.setVisible(not self.notch.isVisible())

    def reconnect(self) -> None:
        url = self.store.get("ha_url")
        token = db.load_token()
        if not url or not token:
            self._on_status("Not configured — open Settings")
            self.show_settings()
            return
        self.client.start(url, token)

    def disconnect(self) -> None:
        self.client.stop()
        self._set_tray(False)
        self._on_status("Disconnected")
        self.notch.reload()

    def start(self) -> None:
        self.tray.show()
        self.notch.show()
        self._sync_cord()
        self.reconnect()
        if not db.load_token():
            self.show_settings()
        QTimer.singleShot(6000, lambda: self.check_for_updates(silent=True))

    def quit(self) -> None:
        self.client.stop()
        self.tray.hide()
        if self.cord is not None:
            self.cord.close()
        self.notch.close()
        QApplication.instance().quit()


def main() -> int:
    QApplication.setAttribute(
        Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("HA Dock")

    # Two notches fight over z-order, both answer clicks, and both hold the
    # same database open. A second launch wakes the first instead.
    guard = SingleInstance()
    if not guard.acquire():
        if guard.wake_existing():
            print("HA Dock is already running; opened its settings window.")
        else:
            print("HA Dock is already running.")
        return 0

    ctl = Application()
    guard.listen(ctl.show_settings)
    ctl.guard = guard
    ctl.start()
    return app.exec()
