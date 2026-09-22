"""Single-instance guard.

Two notches on the same edge look like one misbehaving notch: they fight
over z-order, both poll the cursor, both answer clicks, and both hold the
same SQLite file open. Easy to do by accident — launch from the terminal,
forget, then click the desktop shortcut.

A named mutex is the check. Unlike a pidfile it cannot go stale, because
Windows releases it when the process dies however it dies. A local socket
then lets the second launch hand over to the first instead of just
refusing: pressing the shortcut again pops the settings window, which is
what you actually wanted.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

MUTEX_NAME = "Local\\HADock.SingleInstance.v1"
SOCKET_NAME = "HADock.SingleInstance.v1"
ERROR_ALREADY_EXISTS = 183
WAKE = b"show"

try:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
except Exception:  # pragma: no cover - non-Windows dev
    _kernel32 = None


class SingleInstance(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = None
        self._server: QLocalServer | None = None
        self._on_activate: Callable[[], None] | None = None

    # -- the check --------------------------------------------------------
    def acquire(self) -> bool:
        """True if we are the only instance. Keeps the handle for the
        process lifetime; letting it be garbage collected would release the
        mutex and defeat the guard."""
        if _kernel32 is None:
            return self._acquire_by_socket()
        self._mutex = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not self._mutex:
            return self._acquire_by_socket()
        return ctypes.get_last_error() != ERROR_ALREADY_EXISTS

    def _acquire_by_socket(self) -> bool:
        """Fallback when the mutex is unavailable: if something is already
        listening on our socket name, that something is us."""
        probe = QLocalSocket()
        probe.connectToServer(SOCKET_NAME)
        taken = probe.waitForConnected(150)
        probe.abort()
        return not taken

    # -- handing over -----------------------------------------------------
    def listen(self, on_activate: Callable[[], None]) -> None:
        """Answer later launches by waking this instance instead."""
        self._on_activate = on_activate
        # A hard kill leaves the socket name behind; the mutex has already
        # proved we are alone, so reclaiming it is safe.
        QLocalServer.removeServer(SOCKET_NAME)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._greet)
        self._server.listen(SOCKET_NAME)

    def _greet(self) -> None:
        conn = self._server.nextPendingConnection() if self._server else None
        if conn is None:
            return
        conn.readyRead.connect(lambda: self._wake(conn))
        conn.disconnected.connect(conn.deleteLater)

    def _wake(self, conn: QLocalSocket) -> None:
        if conn.readAll().data().strip() == WAKE and self._on_activate:
            self._on_activate()
        conn.disconnectFromServer()

    def wake_existing(self) -> bool:
        """Ask the running instance to surface. False if it did not answer."""
        sock = QLocalSocket()
        sock.connectToServer(SOCKET_NAME)
        if not sock.waitForConnected(400):
            return False
        sock.write(WAKE)
        sock.flush()
        sock.waitForBytesWritten(400)
        sock.disconnectFromServer()
        return True
