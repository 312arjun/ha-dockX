"""Per-domain behaviour: what a tile shows and what a click does."""

from __future__ import annotations

OFF_STATES = {"off", "closed", "idle", "unavailable", "unknown",
              "not_home", "standby", ""}
DEAD_STATES = {"unavailable", "unknown"}

# Fallback glyphs when the entity exposes no icon of its own.
DEFAULT_ICONS = {
    "light": "mdi6.lightbulb",
    "switch": "mdi6.toggle-switch",
    "input_boolean": "mdi6.toggle-switch-outline",
    "fan": "mdi6.fan",
    "cover": "mdi6.window-shutter",
    "lock": "mdi6.lock",
    "climate": "mdi6.thermostat",
    "media_player": "mdi6.speaker",
    "scene": "mdi6.palette",
    "script": "mdi6.script-text",
    "automation": "mdi6.robot",
    "vacuum": "mdi6.robot-vacuum",
    "sensor": "mdi6.gauge",
    "binary_sensor": "mdi6.circle-outline",
    "person": "mdi6.account",
    "device_tracker": "mdi6.cellphone",
    "button": "mdi6.gesture-tap-button",
    "humidifier": "mdi6.air-humidifier",
    "water_heater": "mdi6.water-boiler",
    "siren": "mdi6.bullhorn",
}

# domain -> (service, needs_toggle_semantics)
TOGGLE_SERVICES = {
    "light": "toggle",
    "switch": "toggle",
    "input_boolean": "toggle",
    "fan": "toggle",
    "media_player": "media_play_pause",
    "siren": "toggle",
    "humidifier": "toggle",
    "vacuum": "toggle",
}
# Domains where a press *does* something rather than flipping a state.
FIRE_SERVICES = {
    "scene": "turn_on",
    "script": "turn_on",
    "button": "press",
    "input_button": "press",
    # automation.toggle enables or disables the automation; it does not run
    # it. Pressing an automation tile plainly means "run this now".
    "automation": "trigger",
}
READ_ONLY = {"sensor", "binary_sensor", "person", "device_tracker",
             "sun", "weather", "device_automation"}


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else entity_id


def default_icon(entity_id: str, attributes: dict | None = None) -> str:
    """HA's own mdi: icon wins, then a per-domain fallback."""
    attributes = attributes or {}
    icon = attributes.get("icon") or ""
    if isinstance(icon, str) and icon.startswith("mdi:"):
        return "mdi6." + icon[4:]
    return DEFAULT_ICONS.get(domain_of(entity_id), "mdi6.help-circle-outline")


def friendly_name(entity_id: str, attributes: dict | None = None) -> str:
    attributes = attributes or {}
    return attributes.get("friendly_name") or entity_id.split(".", 1)[-1]


def is_dead(state: str) -> bool:
    return (state or "").lower() in DEAD_STATES


def is_on(state: str) -> bool:
    return (state or "").lower() not in OFF_STATES


def is_actionable(entity_id: str) -> bool:
    d = domain_of(entity_id)
    return d in TOGGLE_SERVICES or d in FIRE_SERVICES or d == "cover" \
        or d == "lock"


def click_action(entity_id: str, state: str) -> tuple[str, str, dict] | None:
    """Return (domain, service, data) for a click, or None if read-only."""
    d = domain_of(entity_id)
    if d in READ_ONLY:
        return None
    if d in FIRE_SERVICES:
        return d, FIRE_SERVICES[d], {}
    if d == "cover":
        return d, ("close_cover" if is_on(state) else "open_cover"), {}
    if d == "lock":
        return d, ("unlock" if is_on(state) else "lock"), {}
    if d in TOGGLE_SERVICES:
        return d, TOGGLE_SERVICES[d], {}
    return "homeassistant", "toggle", {}


def optimistic_state(entity_id: str, state: str) -> str | None:
    """What the tile should show immediately after a click."""
    d = domain_of(entity_id)
    if d in FIRE_SERVICES or d in READ_ONLY:
        return None
    if d == "cover":
        return "closed" if is_on(state) else "open"
    if d == "lock":
        return "unlocked" if is_on(state) else "locked"
    return "off" if is_on(state) else "on"


def auto_value(entity_id: str, state: str, attributes: dict) -> float | None:
    """A natural 0..1 fraction for the ring, when the domain has one."""
    d = domain_of(entity_id)
    attributes = attributes or {}
    if d == "light":
        b = attributes.get("brightness")
        if b is not None:
            return max(0.0, min(1.0, float(b) / 255.0))
        return 1.0 if is_on(state) else 0.0
    if d == "fan":
        p = attributes.get("percentage")
        if p is not None:
            return max(0.0, min(1.0, float(p) / 100.0))
    if d == "cover":
        p = attributes.get("current_position")
        if p is not None:
            return max(0.0, min(1.0, float(p) / 100.0))
    if d == "media_player":
        v = attributes.get("volume_level")
        if v is not None:
            return max(0.0, min(1.0, float(v)))
    if d == "sensor":
        try:
            return max(0.0, min(1.0, float(state) / 100.0))
        except (TypeError, ValueError):
            return None
    return None


def value_text(entity_id: str, state: str, attributes: dict) -> str:
    """Short label under the glyph when labels are on."""
    d = domain_of(entity_id)
    attributes = attributes or {}
    if is_dead(state):
        return "--"
    if d == "light" and is_on(state):
        b = attributes.get("brightness")
        if b is not None:
            return f"{round(float(b) / 255.0 * 100)}%"
        return "On"
    if d in ("sensor", "climate"):
        unit = attributes.get("unit_of_measurement") or ""
        if d == "climate":
            t = attributes.get("current_temperature")
            return f"{t}\u00b0" if t is not None else str(state)
        try:
            return f"{float(state):g}{unit}"
        except (TypeError, ValueError):
            return str(state)[:5]
    if d == "fan":
        p = attributes.get("percentage")
        if p is not None and is_on(state):
            return f"{int(p)}%"
    if d == "cover":
        p = attributes.get("current_position")
        if p is not None:
            return f"{int(p)}%"
    return "On" if is_on(state) else "Off"
