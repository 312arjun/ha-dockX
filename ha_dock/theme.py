"""Design tokens.

Two systems live here and they are deliberately different.

The *notch* keeps codenotch's structural values — pure black body, inverse
rounded corners, 44px cells on #2A2A2A, #3A3A3A ring track — because that
shape is the brief.

The *settings window* is its own thing: a cool instrument panel rather than
a terminal. Deep indigo-slate ground, hairlines in a blued grey, and two
accents that each carry meaning — cyan for anything interactive, violet for
state and selection. One accent on near-black would read as every other
dark app; the pair reads as an instrument.
"""

from PySide6.QtGui import QColor

# --- Notch body (codenotch) ----------------------------------------------
NOTCH_BG = QColor("#000000")
NOTCH_SHEEN = QColor(125, 226, 255, 26)   # 1px inner edge light
CARD_BG = QColor("#0A0A0A")

# --- Cell ----------------------------------------------------------------
CELL_DIAMETER = 44
CELL_FILL = QColor("#2A2A2A")
RING_TRACK = QColor("#3A3A3A")
RING_WIDTH = 3.0
GLYPH_COLOR = QColor("#FFFFFF")
GLYPH_COLOR_OFF = QColor("#7C8698")
LABEL_COLOR = QColor("#E6EDF7")
LABEL_SIZE = 11

# --- Ramp (codenotch: percent *used*) ------------------------------------
RAMP_GREEN = QColor("#28E07B")
RAMP_YELLOW = QColor("#F5E400")
RAMP_ORANGE = QColor("#FF4500")

# --- Instrument palette --------------------------------------------------
VOID = "#060D16"          # outside the window
SHELL = "#0A1420"         # window ground
PANEL = "#0C1826"         # card
PANEL_HI = "#112233"      # card, lighter end of its gradient
RAISED = "#0E1D2C"        # fields
HAIRLINE = "#16304A"      # borders
HAIRLINE_HI = "#1E415F"   # borders, hover
SIGNAL = "#38D6F5"        # interactive, primary accent
SIGNAL_DEEP = "#2E9BF0"   # far end of the primary gradient
FLUX = "#7DD3FC"          # secondary
GOOD = "#22C55E"          # healthy state
TEXT = "#E6F1F8"
TEXT_DIM = "#A9C0D4"
MUTED = "#6F899F"
ALERT = "#FF6B5B"

# The app mark. Orange against the cold instrument palette, so HA Dock is
# recognisable at 16px in a tray full of blue-grey icons.
BRAND = "#FF4500"
BRAND_DIM = "#8A3A1E"
DANGER = "#F43F5E"
DANGER_DEEP = "#E11D48"

ACCENT_ON = QColor(SIGNAL)
ACCENT_OFF = QColor("#16304A")
ACCENT_UNAVAILABLE = QColor("#3E556B")
ACCENT_ERROR = QColor(ALERT)
BLOOM_ALPHA = 64          # radial glow under an active tile

# --- Type ----------------------------------------------------------------
UI_FAMILY = "Segoe UI Variable Display, Segoe UI, sans-serif"
# monospace is reserved for entity IDs and numerics, where the alignment
# is doing real work rather than decorating a label
MONO_FAMILY = "Cascadia Mono, Consolas, monospace"

# --- Window chrome -------------------------------------------------------
WINDOW_RADIUS = 14
CARD_RADIUS = 14
FIELD_RADIUS = 9
SHADOW_BLUR = 40

# --- Geometry ------------------------------------------------------------
# The flare is an ellipse: EDGE_RADIUS is its depth and is limited by how
# thick the notch is, while EDGE_SWEEP is its reach along the bezel and is
# not. A long, shallow sweep is what makes a thin notch read as a curve
# rather than a straight line.
NUB_THICKNESS = 19
NUB_LENGTH = 108
PILL_THICKNESS = 76
PILL_PADDING = 16
CELL_SPACING = 12
LABEL_WIDTH_PAD = 34      # extra run per tile so side-by-side labels fit
BODY_RADIUS = 50
EDGE_RADIUS = 7           # how deep the flare cuts in — capped by depth
EDGE_SWEEP = 16           # how far it runs along the bezel — free
HOVER_MARGIN = 6          # how far outside the body still counts as hover

# --- Status bar -----------------------------------------------------------
BAR_WIDTH = 5             # the pill inside the notch
BAR_RUN_FRACTION = 0.42   # of the body's length, centred

# --- Motion --------------------------------------------------------------
ANIM_MS = 180
HOVER_IN_MS = 110
HOVER_OUT_MS = 320
POLL_MS = 50              # cursor poll; enter/leave is unreliable here
POPUP_DWELL_MS = 420      # hover this long over a tile to open its card
POPUP_CLOSE_MS = 400      # grace while the pointer crosses to the card
PIN_RELEASE_S = 4.0       # a pinned notch releases once the pointer is away

SIZE_SCALES = {"small": 0.85, "medium": 1.0, "large": 1.2}

# Per-size shape overrides. Tuned by eye in tools/notch_tuner.py and
# settled — treat these as fixed unless a tuning session says otherwise.
#
# Everything here is still multiplied by SIZE_SCALES afterwards, so these
# are base values, not final pixels. They exist because the flare does not
# survive uniform scaling: shrink the whole notch and a curve that read
# well at medium goes blunt.
#
# Anything absent from a size falls back to the module-level value above.
SIZE_OVERRIDES = {
    "small": {"BODY_RADIUS": 47, "EDGE_RADIUS": 9, "EDGE_SWEEP": 12},
    "medium": {"BODY_RADIUS": 50, "EDGE_RADIUS": 7, "EDGE_SWEEP": 16},
    "large": {"BODY_RADIUS": 50, "EDGE_RADIUS": 7, "EDGE_SWEEP": 16},
}


def shape(name: str, size: str = "medium") -> float:
    """A geometry value for a given size, falling back to the default."""
    return SIZE_OVERRIDES.get(size, {}).get(name, globals()[name])


def ramp_color(fraction: float) -> QColor:
    pct = max(0.0, min(1.0, fraction)) * 100.0
    if pct < 50:
        return RAMP_GREEN
    if pct < 80:
        return RAMP_YELLOW
    return RAMP_ORANGE
