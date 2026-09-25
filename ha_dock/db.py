"""SQLite persistence for settings and configured entities.

Everything except the access token lives here. The token goes to Windows
Credential Manager via keyring, so the db can be copied around safely.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 3
BACKUPS = 10              # rolling copies kept in HADock/backups

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "HADock"
DB_PATH = APP_DIR / "hadock.db"

KEYRING_SERVICE = "HADock"
KEYRING_USER = "ha_token"

DEFAULTS = {
    "schema_version": str(SCHEMA_VERSION),
    "ha_url": "http://homeassistant.local:8123",
    "edge": "right",
    "align_offset": "0",          # px along the edge, 0 = centred
    "size": "medium",
    "hover_peek": "1",
    "auto_collapse_s": "6",       # 0 = never
    "show_labels": "1",
    "theme": "dark",
    "start_with_windows": "0",
    "desktop_shortcut": "0",
    "hide_on_fullscreen": "1",
    "cord_enabled": "0",          # the Lampcord: a hanging bulb you pull
    "cord_entity": "",            # one light entity
    "cord_screen": "",            # empty = primary
    "cord_offset_x": "620",       # along the top edge, 0 = centred
    "screen_name": "",            # empty = primary
}


@dataclass
class EntityRow:
    entity_id: str
    label: str = ""
    icon: str = ""                # qtawesome name, e.g. "mdi6.lightbulb"
    color: str = ""               # tile hex override, empty = from state
    on_color: str = ""            # hex the light turns on at, empty = leave
    ring_mode: str = "none"       # none | flat | value | ramp
    ring_min: float = 0.0
    ring_max: float = 100.0
    enabled: int = 1
    popup: int = 0                # show the detail card on hover
    sort_index: int = 0
    row_id: int = field(default=0)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id   TEXT NOT NULL UNIQUE,
    label       TEXT NOT NULL DEFAULT '',
    icon        TEXT NOT NULL DEFAULT '',
    color       TEXT NOT NULL DEFAULT '',
    on_color    TEXT NOT NULL DEFAULT '',
    ring_mode   TEXT NOT NULL DEFAULT 'none',
    ring_min    REAL NOT NULL DEFAULT 0,
    ring_max    REAL NOT NULL DEFAULT 100,
    enabled     INTEGER NOT NULL DEFAULT 1,
    popup       INTEGER NOT NULL DEFAULT 0,
    sort_index  INTEGER NOT NULL DEFAULT 0
);
"""


class Store:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._backup()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self._seed_defaults()
        # INSERT OR IGNORE never updates, so seeding alone would leave this
        # reporting whatever version first created the file.
        self.set("schema_version", SCHEMA_VERSION)

    def _backup(self) -> None:
        """Keep a rolling copy from before each launch.

        Configuration that took a while to build up should not be one
        crash, one bad save or one stray delete away from gone. Cheap
        insurance: the file is tens of kilobytes.
        """
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        try:
            backups = self.path.parent / "backups"
            backups.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(self.path, backups / f"{self.path.stem}-{stamp}.db")
            keep = sorted(backups.glob(f"{self.path.stem}-*.db"))[:-BACKUPS]
            for old in keep:
                old.unlink(missing_ok=True)
        except Exception:
            pass        # a failed backup must never stop the app starting

    def _migrate(self) -> None:
        """CREATE TABLE IF NOT EXISTS leaves an existing table alone, so a
        database made before a column existed needs it added by hand."""
        have = {r["name"] for r in
                self.conn.execute("PRAGMA table_info(entities)")}
        for name, ddl in (
            ("popup", "INTEGER NOT NULL DEFAULT 0"),
            ("on_color", "TEXT NOT NULL DEFAULT ''"),
        ):
            if name not in have:
                self.conn.execute(
                    f"ALTER TABLE entities ADD COLUMN {name} {ddl}")
        self.conn.commit()

    # -- settings ---------------------------------------------------------
    def _seed_defaults(self) -> None:
        cur = self.conn.cursor()
        for k, v in DEFAULTS.items():
            cur.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v)
            )
        self.conn.commit()

    def get(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return DEFAULTS.get(key, default)
        return row["value"]

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, str(default)))
        except ValueError:
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        return self.get(key, "1" if default else "0") == "1"

    def set(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    # -- entities ---------------------------------------------------------
    def entities(self, only_enabled: bool = False) -> list[EntityRow]:
        sql = "SELECT * FROM entities"
        if only_enabled:
            sql += " WHERE enabled=1"
        sql += " ORDER BY sort_index ASC, id ASC"
        out = []
        for r in self.conn.execute(sql):
            out.append(
                EntityRow(
                    entity_id=r["entity_id"],
                    label=r["label"],
                    icon=r["icon"],
                    color=r["color"],
                    on_color=r["on_color"],
                    ring_mode=r["ring_mode"],
                    ring_min=r["ring_min"],
                    ring_max=r["ring_max"],
                    enabled=r["enabled"],
                    popup=r["popup"],
                    sort_index=r["sort_index"],
                    row_id=r["id"],
                )
            )
        return out

    def add_entity(self, e: EntityRow) -> int:
        nxt = self.conn.execute(
            "SELECT COALESCE(MAX(sort_index), -1) + 1 AS n FROM entities"
        ).fetchone()["n"]
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO entities"
            "(entity_id,label,icon,color,on_color,ring_mode,ring_min,"
            "ring_max,enabled,popup,sort_index)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (e.entity_id, e.label, e.icon, e.color, e.on_color, e.ring_mode,
             e.ring_min, e.ring_max, e.enabled, e.popup, nxt),
        )
        self.conn.commit()
        return cur.lastrowid or 0

    def update_entity(self, e: EntityRow) -> None:
        self.conn.execute(
            "UPDATE entities SET entity_id=?,label=?,icon=?,color=?,"
            "on_color=?,ring_mode=?,ring_min=?,ring_max=?,enabled=?,popup=?,"
            "sort_index=? WHERE id=?",
            (e.entity_id, e.label, e.icon, e.color, e.on_color, e.ring_mode,
             e.ring_min, e.ring_max, e.enabled, e.popup, e.sort_index,
             e.row_id),
        )
        self.conn.commit()

    def delete_entity(self, row_id: int) -> None:
        self.conn.execute("DELETE FROM entities WHERE id=?", (row_id,))
        self.conn.commit()

    def reorder(self, row_ids: list[int]) -> None:
        for i, rid in enumerate(row_ids):
            self.conn.execute("UPDATE entities SET sort_index=? WHERE id=?", (i, rid))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


# -- token -----------------------------------------------------------------
def load_token() -> str:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
    except Exception:
        return ""


def save_token(token: str) -> bool:
    try:
        import keyring

        if token:
            keyring.set_password(KEYRING_SERVICE, KEYRING_USER, token)
        else:
            try:
                keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            except Exception:
                pass
        return True
    except Exception:
        return False
