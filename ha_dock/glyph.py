"""Material Design Icons via qtawesome, drawn as text so we own the colour.

qtawesome bundles MDI6, so no font asset has to ship with the project and
HA's own `mdi:` icon names map across with a prefix swap.
"""

from __future__ import annotations

import functools

from PySide6.QtGui import QFont

_FALLBACK = "mdi6.help-circle-outline"


@functools.lru_cache(maxsize=1)
def _charmaps() -> dict[str, dict[str, str]]:
    try:
        import qtawesome as qta

        # qta.charmap() takes a *prefixed* name; the per-prefix tables live
        # on the singleton, which is the only way to enumerate for search.
        return dict(qta._instance().charmap)
    except Exception:
        return {}


def split(name: str) -> tuple[str, str]:
    if "." in name:
        prefix, short = name.split(".", 1)
    else:
        prefix, short = "mdi6", name
    return prefix, short


def char_for(name: str) -> str:
    """Codepoint for an icon name like 'mdi6.lightbulb'. '' if unknown."""
    prefix, short = split(name or "")
    maps = _charmaps()
    cm = maps.get(prefix) or maps.get("mdi6") or {}
    if short in cm:
        return cm[short]
    try:  # let qtawesome resolve aliases we do not know about
        import qtawesome as qta

        return qta.charmap(f"{prefix}.{short}")
    except Exception:
        pass
    # HA sometimes uses names MDI6 dropped; try the legacy mdi set
    legacy = maps.get("mdi") or {}
    if short in legacy:
        return legacy[short]
    fb_prefix, fb_short = split(_FALLBACK)
    return (maps.get(fb_prefix) or {}).get(fb_short, "")


def exists(name: str) -> bool:
    prefix, short = split(name or "")
    maps = _charmaps()
    return short in (maps.get(prefix) or {}) or short in (maps.get("mdi") or {})


def font(name: str, pixel_size: int) -> QFont:
    import qtawesome as qta

    prefix, _ = split(name or "")
    if prefix not in _charmaps():
        prefix = "mdi6"
    f: QFont = qta.font(prefix, pixel_size)
    f.setPixelSize(pixel_size)
    return f


def search(term: str, limit: int = 60) -> list[str]:
    """Icon names containing `term`, MDI6 first."""
    term = (term or "").strip().lower().replace(" ", "-")
    out: list[str] = []
    for prefix in ("mdi6", "mdi"):
        cm = _charmaps().get(prefix) or {}
        for short in sorted(cm):
            if not term or term in short:
                out.append(f"{prefix}.{short}")
                if len(out) >= limit:
                    return out
        if out:
            break
    return out
