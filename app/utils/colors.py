"""Color utilities for per-department chip display."""
from __future__ import annotations


def text_color_for(hex_bg: str) -> str:
    """Return '#ffffff' for dark backgrounds or '#171717' for light ones.

    Uses a simplified luminance formula: 0.299*R + 0.587*G + 0.114*B.
    Threshold at ~150/255 (≈ 0.588 on a 0-255 scale).
    """
    try:
        h = hex_bg.lstrip("#")
        if len(h) != 6:
            return "#171717"
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        return "#ffffff" if luminance < 150 else "#171717"
    except (ValueError, AttributeError):
        return "#171717"


def department_color_map(departments) -> dict[int, dict]:
    """Build a mapping {dept_id: {bg, fg, code, name}} from an iterable of Department objects."""
    result: dict[int, dict] = {}
    for d in departments:
        if d.id is None:
            continue
        farbe = getattr(d, "farbe", "#9CA3AF") or "#9CA3AF"
        result[d.id] = {
            "bg": farbe,
            "fg": text_color_for(farbe),
            "code": d.code,
            "name": d.name,
        }
    return result
