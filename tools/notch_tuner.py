"""Notch tuning harness — the real notch, live dials, nothing functional.

Runs the actual NotchWindow against a stub store and a stub Home Assistant
client, so what you see is exactly what the app paints. Hover, clicking and
auto-hide are all switched off: expansion is a slider, so the notch stays
wherever you put it while you measure it.

    .venv\\Scripts\\python.exe tools\\notch_tuner.py

Drag the dials until it looks right, then press Copy to get a block you can
paste straight over the matching lines in ha_dock/theme.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,  # noqa: E402
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from ha_dock import theme  # noqa: E402
from ha_dock.db import EntityRow  # noqa: E402
from ha_dock.notch_window import NotchWindow  # noqa: E402

DEMO = [
    ("light.tube_light", "mdi6.lightbulb", "TubeLight", "on", "none"),
    ("switch.desk_plug", "mdi6.power-socket-eu", "Desk", "off", "flat"),
    ("sensor.battery", "mdi6.battery", "Battery", "64", "ramp"),
    ("fan.study", "mdi6.fan", "Fan", "on", "value"),
    ("cover.blind", "mdi6.window-shutter", "Blind", "open", "value"),
    ("media_player.tv", "mdi6.television", "TV", "playing", "none"),
]

# name -> (min, max) for the integer dials
DIALS = {
    "NUB_THICKNESS": (4, 90),
    "NUB_LENGTH": (30, 500),
    "PILL_THICKNESS": (50, 220),
    "PILL_PADDING": (0, 60),
    "CELL_SPACING": (0, 60),
    "CELL_DIAMETER": (20, 90),
    "LABEL_WIDTH_PAD": (0, 90),
    "BODY_RADIUS": (0, 60),
    "EDGE_RADIUS": (0, 80),
    "EDGE_SWEEP": (0, 220),
    "BAR_WIDTH": (0, 20),
    "LABEL_SIZE": (6, 20),
}


class StubStore:
    """Only the handful of keys NotchWindow actually reads."""

    def __init__(self):
        self.values = {
            "size": "medium", "edge": "right", "align_offset": 0,
            "show_labels": 1, "hover_peek": 0, "auto_collapse_s": 0,
            "screen_name": "",
        }
        self.count = 3

    def get(self, key, default=""):
        return str(self.values.get(key, default))

    def get_int(self, key, default=0):
        try:
            return int(self.values.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key, default=False):
        return str(self.values.get(key, int(default))) in ("1", "True", "true")

    def set(self, key, value):
        self.values[key] = value

    def entities(self, only_enabled: bool = False):
        rows = []
        for i, (eid, icon, label, _state, ring) in enumerate(
                DEMO[:self.count]):
            rows.append(EntityRow(entity_id=eid, icon=icon, label="",
                                  ring_mode=ring, ring_min=0, ring_max=100,
                                  enabled=1, sort_index=i, row_id=i + 1))
        return rows


class StubClient(QObject):
    connected = Signal(dict)
    disconnected = Signal(str)
    status = Signal(str)
    states_reset = Signal()
    entity_updated = Signal(str, dict)
    auth_failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.is_connected = True
        self.states = {
            eid: {"state": state,
                  "attributes": {"friendly_name": label,
                                 "brightness": 180 if state == "on" else 0,
                                 "percentage": 60, "current_position": 40,
                                 "unit_of_measurement": "%"}}
            for eid, _icon, label, state, _ring in DEMO
        }

    def call_service(self, *_a, **_k):
        return False        # nothing works here, by design


class Panel(QWidget):
    def __init__(self, notch: NotchWindow, store: StubStore,
                 client: StubClient):
        super().__init__()
        self.notch = notch
        self.store = store
        self.client = client
        self.sliders: dict[str, QSlider] = {}
        self.readouts: dict[str, QLabel] = {}

        self.setWindowTitle("Notch tuner")
        self.resize(430, 900)

        root = QVBoxLayout(self)
        root.addWidget(self._scene_box())
        root.addWidget(self._dial_box(), 1)
        root.addWidget(self._output_box())

    # -- scene ------------------------------------------------------------
    def _scene_box(self) -> QGroupBox:
        box = QGroupBox("Scene")
        grid = QGridLayout(box)

        self.edge = QComboBox()
        self.edge.addItems(["right", "left", "top", "bottom"])
        self.edge.currentTextChanged.connect(
            lambda v: self._set_store("edge", v))

        self.size = QComboBox()
        self.size.addItems(["small", "medium", "large"])
        self.size.setCurrentText("medium")
        self.size.currentTextChanged.connect(
            lambda v: self._set_store("size", v))

        self.count = QSlider(Qt.Orientation.Horizontal)
        self.count.setRange(1, len(DEMO))
        self.count.setValue(3)
        self.count_lbl = QLabel("3")
        self.count.valueChanged.connect(self._set_count)

        self.expansion = QSlider(Qt.Orientation.Horizontal)
        self.expansion.setRange(0, 100)
        self.expansion.setValue(0)
        self.exp_lbl = QLabel("0%")
        self.expansion.valueChanged.connect(self._set_expansion)

        self.bar_run = QSlider(Qt.Orientation.Horizontal)
        self.bar_run.setRange(0, 100)
        self.bar_run.setValue(int(theme.BAR_RUN_FRACTION * 100))
        self.bar_lbl = QLabel(f"{theme.BAR_RUN_FRACTION:.2f}")
        self.bar_run.valueChanged.connect(self._set_bar_run)

        self.labels = QCheckBox("Value labels")
        self.labels.setChecked(True)
        self.labels.toggled.connect(
            lambda v: self._set_store("show_labels", 1 if v else 0))

        self.online = QCheckBox("Connected (bar colour)")
        self.online.setChecked(True)
        self.online.toggled.connect(self._set_online)

        rows = [
            ("Edge", self.edge, None),
            ("Size", self.size, None),
            ("Tiles", self.count, self.count_lbl),
            ("Expansion", self.expansion, self.exp_lbl),
            ("BAR_RUN_FRACTION", self.bar_run, self.bar_lbl),
        ]
        for r, (name, widget, readout) in enumerate(rows):
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(widget, r, 1)
            if readout is not None:
                readout.setMinimumWidth(52)
                grid.addWidget(readout, r, 2)
        grid.addWidget(self.labels, len(rows), 1)
        grid.addWidget(self.online, len(rows) + 1, 1)
        return box

    # -- dials ------------------------------------------------------------
    def _dial_box(self) -> QGroupBox:
        box = QGroupBox("theme.py values")
        grid = QGridLayout(box)
        for r, (name, (lo, hi)) in enumerate(DIALS.items()):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(lo, hi)
            slider.setValue(int(getattr(theme, name)))
            readout = QLabel(str(int(getattr(theme, name))))
            readout.setMinimumWidth(52)
            slider.valueChanged.connect(
                lambda v, n=name: self._set_theme(n, v))
            self.sliders[name] = slider
            self.readouts[name] = readout
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(slider, r, 1)
            grid.addWidget(readout, r, 2)
        return box

    # -- output -----------------------------------------------------------
    def _output_box(self) -> QGroupBox:
        box = QGroupBox("Paste into ha_dock/theme.py")
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMaximumHeight(210)
        f = self.out.font()
        f.setFamily("Cascadia Mono")
        self.out.setFont(f)

        copy = QPushButton("Copy")
        copy.clicked.connect(self._copy)
        reset = QPushButton("Reset to file")
        reset.clicked.connect(self._reset)

        bar = QHBoxLayout()
        bar.addWidget(copy)
        bar.addWidget(reset)
        bar.addStretch(1)

        lay = QVBoxLayout(box)
        lay.addWidget(self.out)
        lay.addLayout(bar)
        self._refresh_output()
        return box

    # -- handlers ---------------------------------------------------------
    def _set_store(self, key, value):
        self.store.set(key, value)
        if key == "size":
            self._sync_sliders()
        self._reload()
        self._refresh_output()

    def _current_size(self) -> str:
        return self.store.get("size", "medium")

    def _sync_sliders(self):
        """Per-size values differ, so the dials follow the chosen size."""
        size = self._current_size()
        for name, slider in self.sliders.items():
            value = int(theme.shape(name, size))
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
            self.readouts[name].setText(str(value))

    def _set_count(self, n):
        self.count_lbl.setText(str(n))
        self.store.count = n
        self._reload()

    def _set_expansion(self, v):
        self.exp_lbl.setText(f"{v}%")
        self.notch.expansion = v / 100.0
        self.notch._sync_mask()

    def _set_bar_run(self, v):
        theme.BAR_RUN_FRACTION = v / 100.0
        self.bar_lbl.setText(f"{v / 100.0:.2f}")
        self.notch.update()
        self._refresh_output()

    def _set_online(self, on):
        self.client.is_connected = on
        self.notch._set_connected(on)

    def _set_theme(self, name, value):
        # The three shape values are tuned per size, so they go into that
        # size's override rather than stamping over the shared default.
        if name in theme.SIZE_OVERRIDES.get("medium", {}):
            theme.SIZE_OVERRIDES.setdefault(
                self._current_size(), {})[name] = value
        else:
            setattr(theme, name, value)
        self.readouts[name].setText(str(value))
        self._reload()
        self._refresh_output()

    def _reload(self):
        keep = self.notch.expansion
        self.notch.reload()
        self.notch.expansion = keep
        self.notch._apply_geometry()
        self.notch._sync_mask()
        self.notch.update()

    def _refresh_output(self):
        per_size = set(theme.SIZE_OVERRIDES.get("medium", {}))
        lines = [f"{name} = {int(getattr(theme, name))}"
                 for name in DIALS if name not in per_size]
        lines.append(f"BAR_RUN_FRACTION = {theme.BAR_RUN_FRACTION:.2f}")
        lines.append("")
        lines.append("SIZE_OVERRIDES = {")
        for size in ("small", "medium", "large"):
            body = ", ".join(
                f'"{k}": {int(theme.shape(k, size))}' for k in sorted(per_size))
            marker = "   # <- editing" if size == self._current_size() else ""
            lines.append(f'    "{size}": {{{body}}},{marker}')
        lines.append("}")
        self.out.setPlainText("\n".join(lines))

    def _copy(self):
        QApplication.clipboard().setText(self.out.toPlainText())

    def _reset(self):
        import importlib

        importlib.reload(theme)
        self._sync_sliders()
        self.bar_run.blockSignals(True)
        self.bar_run.setValue(int(theme.BAR_RUN_FRACTION * 100))
        self.bar_run.blockSignals(False)
        self._reload()
        self._refresh_output()


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    store = StubStore()
    client = StubClient()
    notch = NotchWindow(store, client)

    # Nothing works here on purpose: no cursor polling, no optimistic
    # updates, no clicking. Expansion comes from the slider alone.
    notch._poll.stop()
    notch._tick.stop()
    notch.mousePressEvent = lambda _ev: None
    notch._set_connected(True)
    notch.show()

    panel = Panel(notch, store, client)
    panel.show()

    code = app.exec()
    notch.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
