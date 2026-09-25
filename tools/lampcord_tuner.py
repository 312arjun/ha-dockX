"""Standalone lampcord harness — position it, feel the pull, nothing wired.

Nothing talks to Home Assistant here. Completing a pull just logs a line, so
you can settle the placement and the feel before any of it touches a real
light.

    .venv\\Scripts\\python.exe tools\\lampcord_tuner.py

Drag the finial at the bottom of the chain. Release past the threshold and
the chain springs back and reports a toggle; release short of it and it just
springs back.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,  # noqa: E402
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from ha_dock.lampcord import LampcordLayout, Lampcord  # noqa: E402

DIALS = {
    "bulb_height": (60, 320),
    "chain_dx": (-200, 200),
    "chain_dy": (0, 240),
    "rest_length": (0, 240),
    "pull_max": (20, 260),
    "threshold": (5, 200),
    "end_height": (10, 140),
    "end_overlap": (-10, 30),
}

# name -> (slider min, slider max, divisor) for the float physics values
FLOAT_DIALS = {
    "bounce_freq": (20, 260, 10.0),
    "bounce_damp": (5, 200, 10.0),
    "swing_gravity": (200, 8000, 1.0),
    "swing_damp": (2, 120, 10.0),
    "swing_kick": (0, 80, 10.0),
    "max_swing": (2, 120, 100.0),
}


class Panel(QWidget):
    def __init__(self, cord: Lampcord):
        super().__init__()
        self.cord = cord
        self.sliders: dict[str, QSlider] = {}
        self.readouts: dict[str, QLabel] = {}
        self.offset_x = 0

        self.setWindowTitle("Lampcord — position and feel")
        self.resize(450, 880)

        root = QVBoxLayout(self)
        root.addWidget(self._screen_box())
        root.addWidget(self._dial_box())
        root.addWidget(self._dangle_box())
        root.addWidget(self._log_box(), 1)

        cord.toggled.connect(self._on_toggle)
        cord.moved.connect(self._on_moved)

    def closeEvent(self, ev):
        """The Lampcord is a separate top-level window, so closing the
        panel alone would leave it on screen with no way to reach it."""
        self.cord.close()
        super().closeEvent(ev)

    def _on_moved(self, offset_x: int) -> None:
        """Dragging the fixture is another way of setting the offset, so
        the slider has to follow or the two disagree."""
        self.offset_x = offset_x
        self.offset.blockSignals(True)
        self.offset.setValue(offset_x)
        self.offset.blockSignals(False)
        self.offset_lbl.setText(f"{offset_x} px")
        self._refresh_output()
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.appendPlainText(f"{stamp}  moved -> offset_x {offset_x}")

    # -- placement --------------------------------------------------------
    def _screen_box(self) -> QGroupBox:
        box = QGroupBox("Placement")
        grid = QGridLayout(box)

        self.screen = QComboBox()
        for sc in QGuiApplication.screens():
            self.screen.addItem(
                f"{sc.name()} ({sc.geometry().width()}x"
                f"{sc.geometry().height()})", sc.name())
        self.screen.currentIndexChanged.connect(lambda _: self._replace())

        self.offset = QSlider(Qt.Orientation.Horizontal)
        self.offset.setRange(-1200, 1200)
        self.offset.setValue(self.cord.layout_.offset_x)
        self.offset_x = self.cord.layout_.offset_x
        self.offset_lbl = QLabel(f"{self.offset_x} px")
        self.offset.valueChanged.connect(self._set_offset)

        self.chain_scale = QSlider(Qt.Orientation.Horizontal)
        self.chain_scale.setRange(4, 40)
        self.chain_scale.setValue(int(self.cord.layout_.chain_scale * 100))
        self.scale_lbl = QLabel(f"{self.cord.layout_.chain_scale:.2f}")
        self.chain_scale.valueChanged.connect(self._set_scale)

        self.lit = QCheckBox("Pretend the light is on")
        self.lit.toggled.connect(self.cord.set_lit)

        rows = [("Monitor", self.screen, None),
                ("Offset along top", self.offset, self.offset_lbl),
                ("chain_scale", self.chain_scale, self.scale_lbl)]
        for r, (name, widget, readout) in enumerate(rows):
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(widget, r, 1)
            if readout is not None:
                readout.setMinimumWidth(56)
                grid.addWidget(readout, r, 2)
        grid.addWidget(self.lit, len(rows), 1)
        return box

    def _set_offset(self, v: int) -> None:
        self.offset_x = v
        self.cord.layout_.offset_x = v
        self.offset_lbl.setText(f"{v} px")
        self._replace()

    def _set_scale(self, v: int) -> None:
        self.cord.layout_.chain_scale = v / 100.0
        self.scale_lbl.setText(f"{v / 100.0:.2f}")
        self._replace()

    def _replace(self) -> None:
        name = self.screen.currentData()
        target = next((s for s in QGuiApplication.screens()
                       if s.name() == name), QGuiApplication.primaryScreen())
        self.cord.place(target, self.offset_x)
        self.cord.update()
        self._refresh_output()

    # -- dials ------------------------------------------------------------
    def _dial_box(self) -> QGroupBox:
        box = QGroupBox("Geometry")
        grid = QGridLayout(box)
        for r, (name, (lo, hi)) in enumerate(DIALS.items()):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(lo, hi)
            slider.setValue(int(getattr(self.cord.layout_, name)))
            readout = QLabel(str(int(getattr(self.cord.layout_, name))))
            readout.setMinimumWidth(56)
            slider.valueChanged.connect(
                lambda v, n=name: self._set_dial(n, v))
            self.sliders[name] = slider
            self.readouts[name] = readout
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(slider, r, 1)
            grid.addWidget(readout, r, 2)
        return box

    def _dangle_box(self) -> QGroupBox:
        box = QGroupBox("Dangle — how it behaves once you let go")
        grid = QGridLayout(box)
        for r, (name, (lo, hi, div)) in enumerate(FLOAT_DIALS.items()):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(lo, hi)
            cur = float(getattr(self.cord.layout_, name))
            slider.setValue(int(round(cur * div)))
            readout = QLabel(f"{cur:g}")
            readout.setMinimumWidth(56)
            slider.valueChanged.connect(
                lambda v, n=name, d=div: self._set_float(n, v, d))
            self.sliders[name] = slider
            self.readouts[name] = readout
            grid.addWidget(QLabel(name), r, 0)
            grid.addWidget(slider, r, 1)
            grid.addWidget(readout, r, 2)

        nudge = QPushButton("Nudge the chain")
        nudge.clicked.connect(self._nudge)
        grid.addWidget(nudge, len(FLOAT_DIALS), 1)
        return box

    def _set_float(self, name: str, value: int, div: float) -> None:
        v = value / div
        setattr(self.cord.layout_, name, v)
        self.readouts[name].setText(f"{v:g}")
        self._refresh_output()

    def _nudge(self) -> None:
        """Watch the dangle without having to drag it each time."""
        c = self.cord
        c._physics.stop()
        c._pull = c.layout_.pull_max * 0.8
        c._vel = -c.layout_.bounce_freq * c._pull * 0.55
        c._swing = 0.10
        c._omega = c.layout_.swing_kick * 0.8
        c._physics.start()

    def _set_dial(self, name: str, value: int) -> None:
        setattr(self.cord.layout_, name, value)
        self.readouts[name].setText(str(value))
        self._replace()

    # -- output -----------------------------------------------------------
    def _log_box(self) -> QGroupBox:
        box = QGroupBox("LampcordLayout — paste into ha_dock/lampcord.py")
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        f = self.out.font()
        f.setFamily("Cascadia Mono")
        self.out.setFont(f)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        self.log.setFont(f)

        copy = QPushButton("Copy")
        copy.clicked.connect(
            lambda: QApplication.clipboard().setText(self.out.toPlainText()))
        bar = QHBoxLayout()
        bar.addWidget(copy)
        bar.addStretch(1)

        lay = QVBoxLayout(box)
        lay.addWidget(self.out)
        lay.addLayout(bar)
        lay.addWidget(QLabel("Pull log"))
        lay.addWidget(self.log)
        self._refresh_output()
        return box

    def _refresh_output(self) -> None:
        lay = self.cord.layout_
        lines = [f"    bulb_height: int = {lay.bulb_height}",
                 f"    chain_scale: float = {lay.chain_scale:.3f}",
                 f"    chain_dx: int = {lay.chain_dx}",
                 f"    chain_dy: int = {lay.chain_dy}",
                 f"    rest_length: int = {lay.rest_length}",
                 f"    pull_max: int = {lay.pull_max}",
                 f"    threshold: int = {lay.threshold}",
                 f"    offset_x: int = {lay.offset_x}",
                 f"    end_height: int = {lay.end_height}",
                 f"    end_overlap: int = {lay.end_overlap}",
                 f"    bounce_freq: float = {lay.bounce_freq:g}",
                 f"    bounce_damp: float = {lay.bounce_damp:g}",
                 f"    swing_gravity: float = {lay.swing_gravity:g}",
                 f"    swing_damp: float = {lay.swing_damp:g}",
                 f"    swing_kick: float = {lay.swing_kick:g}",
                 f"    max_swing: float = {lay.max_swing:g}",
                 "",
                 f"# window {self.cord.window_size()}  "
                 f"offset_x {self.offset_x}"]
        if lay.threshold > lay.pull_max:
            lines.append(f"# threshold {lay.threshold} exceeds pull_max "
                         f"{lay.pull_max}; clamped to "
                         f"{lay.fire_threshold():.0f}")
        self.out.setPlainText("\n".join(lines))

    def _on_toggle(self) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.lit.setChecked(not self.lit.isChecked())
        self.log.appendPlainText(f"{stamp}  pull completed -> toggle")
        print(f"{stamp}  pull completed -> toggle", flush=True)


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    cord = Lampcord()
    if cord._missing:
        print("!! assets/bulb_off.png or assets/chain.png could not be "
              "loaded", file=sys.stderr)
        return 1
    cord.place(QGuiApplication.primaryScreen())
    cord.show()

    panel = Panel(cord)
    panel.show()

    code = app.exec()
    cord.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
