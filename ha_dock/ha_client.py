"""Home Assistant WebSocket client.

Runs an asyncio loop on its own thread and talks to Qt via signals, which
avoids pulling in qasync. Uses `subscribe_entities` (the compressed diff
feed the HA frontend itself uses) rather than `subscribe_events`.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any

import websockets
from PySide6.QtCore import QObject, Signal

DEBUG = os.environ.get("HADOCK_DEBUG", "") not in ("", "0", "false")


def ws_url(base: str) -> str:
    base = base.strip().rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):] + "/api/websocket"
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):] + "/api/websocket"
    return "ws://" + base + "/api/websocket"


class HaClient(QObject):
    """Thread-safe front for a HA websocket connection."""

    connected = Signal(dict)              # ha_version payload
    disconnected = Signal(str)            # reason
    status = Signal(str)                  # human-readable connection status
    states_reset = Signal()               # a fresh full snapshot arrived
    entity_updated = Signal(str, dict)    # entity_id, {state, attributes}
    auth_failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ws = None
        self._msg_id = 1
        self._stop = threading.Event()
        self._url = ""
        self._token = ""
        self.states: dict[str, dict] = {}
        self.is_connected = False

    # -- lifecycle --------------------------------------------------------
    def start(self, url: str, token: str) -> None:
        self.stop()
        self._url, self._token = url, token
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="ha-ws")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        self._loop = None
        self.is_connected = False

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._supervise())
        except Exception:
            pass
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    # -- connection supervisor -------------------------------------------
    async def _supervise(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self.status.emit("Connecting…")
                await self._session()
                backoff = 1.0
            except _AuthError as exc:
                self.auth_failed.emit(str(exc))
                self.status.emit("Authentication failed")
                return
            except Exception as exc:
                self.is_connected = False
                self.disconnected.emit(str(exc) or exc.__class__.__name__)
                self.status.emit(f"Disconnected — retrying in {int(backoff)}s")
            if self._stop.is_set():
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    async def _session(self) -> None:
        async with websockets.connect(
            ws_url(self._url), ping_interval=20, ping_timeout=20,
            max_size=8 * 1024 * 1024, open_timeout=10,
        ) as ws:
            self._ws = ws
            hello = json.loads(await ws.recv())
            if hello.get("type") != "auth_required":
                raise RuntimeError(f"unexpected greeting: {hello.get('type')}")
            await ws.send(json.dumps({"type": "auth",
                                      "access_token": self._token}))
            reply = json.loads(await ws.recv())
            if reply.get("type") == "auth_invalid":
                raise _AuthError(reply.get("message", "invalid token"))
            if reply.get("type") != "auth_ok":
                raise RuntimeError(f"auth returned {reply.get('type')}")

            self.is_connected = True
            self.states = {}
            self.states_reset.emit()
            self.connected.emit(reply)
            self.status.emit(f"Connected — HA {reply.get('ha_version', '?')}")

            await self._send({"type": "subscribe_entities"})
            async for raw in ws:
                if self._stop.is_set():
                    return
                self._handle(json.loads(raw))
        self._ws = None
        self.is_connected = False

    async def _send(self, payload: dict) -> int:
        mid = self._msg_id
        self._msg_id += 1
        payload = {"id": mid, **payload}
        await self._ws.send(json.dumps(payload))
        return mid

    # -- inbound ----------------------------------------------------------
    def _handle(self, msg: dict) -> None:
        if msg.get("type") != "event":
            return
        ev = msg.get("event") or {}
        for eid, payload in (ev.get("a") or {}).items():
            self.states[eid] = {
                "state": payload.get("s", ""),
                "attributes": dict(payload.get("a") or {}),
            }
            self.entity_updated.emit(eid, self.states[eid])
        for eid, delta in (ev.get("c") or {}).items():
            cur = self.states.setdefault(eid, {"state": "", "attributes": {}})
            plus = delta.get("+") or {}
            minus = delta.get("-") or {}
            if "s" in plus:
                cur["state"] = plus["s"]
            if "a" in plus:
                cur["attributes"].update(plus["a"])
            for key in (minus.get("a") or []):
                cur["attributes"].pop(key, None)
            self.entity_updated.emit(eid, cur)
        for eid in (ev.get("r") or []):
            self.states.pop(eid, None)

    # -- outbound (callable from the Qt thread) --------------------------
    def call_service(self, domain: str, service: str,
                     target: dict[str, Any] | None = None,
                     data: dict[str, Any] | None = None) -> bool:
        payload: dict[str, Any] = {"type": "call_service",
                                   "domain": domain, "service": service}
        if data:
            payload["service_data"] = data
        if target:
            payload["target"] = target
        ok = self._dispatch(payload)
        if DEBUG:
            # Set HADOCK_DEBUG=1 to see exactly what goes to Home
            # Assistant. Guessing which service a tile sends is the slow
            # way to find out it was the wrong one.
            who = (target or {}).get("entity_id", "-")
            print(f"[ha] {domain}.{service} {who} {data or {}} "
                  f"{'sent' if ok else 'NOT SENT (no connection)'}",
                  flush=True)
        return ok

    def _dispatch(self, payload: dict) -> bool:
        loop, ws = self._loop, self._ws
        if not loop or not ws or not self.is_connected:
            return False
        try:
            asyncio.run_coroutine_threadsafe(self._send(payload), loop)
            return True
        except Exception:
            return False


class _AuthError(Exception):
    pass


async def probe(url: str, token: str, timeout: float = 8.0) -> dict:
    """One-shot connect + auth + get_states. Used by the Test button."""
    async with websockets.connect(ws_url(url), open_timeout=timeout,
                                  max_size=8 * 1024 * 1024) as ws:
        hello = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if hello.get("type") != "auth_required":
            raise RuntimeError("not a Home Assistant websocket endpoint")
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if reply.get("type") != "auth_ok":
            raise _AuthError(reply.get("message", "invalid access token"))
        await ws.send(json.dumps({"id": 1, "type": "get_states"}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            if msg.get("id") == 1 and msg.get("type") == "result":
                if not msg.get("success"):
                    raise RuntimeError("get_states failed")
                return {"ha_version": reply.get("ha_version", "?"),
                        "states": msg.get("result") or []}
