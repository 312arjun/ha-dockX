"""Application wiring: tray icon, notch, settings window, HA client."""

from __future__ import annotations

import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import db, glyph, theme, ui_kit
from .ha_client import HaClient
from .notch_window import NotchWindow
from .settings_window import SettingsWindow
from .single_instance import SingleInstance


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
        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(self.quit)
        for a in (act_settings, act_toggle, act_reconnect):
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
        self.settings.quit_requested.connect(self.quit)

        self.client.status.connect(self._on_status)
        self.client.connected.connect(lambda _: self._set_tray(True))
        self.client.disconnected.connect(lambda _: self._set_tray(False))
        self.client.auth_failed.connect(self._on_auth_failed)
        self.client.states_reset.connect(self.notch.reload)

    def _config_changed(self) -> None:
        self.notch.reload()

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
        self.reconnect()
        if not db.load_token():
            self.show_settings()

    def quit(self) -> None:
        self.client.stop()
        self.tray.hide()
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
