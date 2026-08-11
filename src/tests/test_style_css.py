"""Tests fuer zwei CSS-Fixes in app/static/style.css:

(a) .flash darf kein Flex-Container mehr sein -- ein Flex-Container macht aus
    JEDEM in-flow-Kind (auch anonymen Textlaeufen um Inline-Markup wie
    <strong>) ein eigenes Flex-Item und reisst dadurch Fliesstext mit
    Inline-Markup in mehrere nebeneinander mit "gap" gesetzte Bloecke
    auseinander (sichtbar z. B. bei .flash-info in
    app/templates/ausbilder_verwaltung/list.html: Text vor/nach <strong>
    landet nebeneinander statt normal zu umbrechen).

(b) .content-inner darf die Seitenbreite nicht mehr auf 1100px begrenzen --
    alle Seiten sollen die volle Bildschirmbreite nutzen. .content-inner--wide
    bleibt als (nun wirkungsloser) Modifier bestehen.
"""
import re
from pathlib import Path

STYLE_CSS = (Path(__file__).resolve().parents[1] / "app" / "static" / "style.css").read_text(
    encoding="utf-8"
)


def _rule_body(css: str, selector: str) -> str:
    """Extrahiert den Deklarationsblock der ERSTEN Regel mit genau diesem
    Selektor (z. B. '.flash' matcht NICHT '.flash-success', '.content-inner'
    matcht NICHT '.content-inner--wide', da dort vor der '{' noch weitere
    Zeichen stehen)."""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"Regel {selector!r} nicht in style.css gefunden"
    return m.group(1)


# ── (a) .flash: kein Flex-Container mehr ─────────────────────────────────────

def test_flash_is_not_a_flex_container():
    body = _rule_body(STYLE_CSS, ".flash")
    assert "display: flex" not in body, (
        ".flash darf kein Flex-Container sein -- sonst wird Fliesstext mit "
        "Inline-Markup (<strong> etc.) in mehrere nebeneinander gesetzte "
        "Bloecke zerrissen statt normal zu umbrechen."
    )
    assert "display: block" in body


def test_flash_success_error_info_variants_unchanged():
    """Die Farbvarianten setzen nur background/color/box-shadow -- kein
    eigenes display, sonst koennten sie die Basis-Regel wieder ueberschreiben."""
    for variant in (".flash-success", ".flash-error", ".flash-info"):
        body = _rule_body(STYLE_CSS, variant)
        assert "display" not in body


# ── (b) .content-inner: keine 1100px-Breitenbegrenzung mehr ─────────────────

def test_content_inner_has_no_width_cap():
    body = _rule_body(STYLE_CSS, ".content-inner")
    assert "1100px" not in body
    assert "max-width: none" in body


def test_content_inner_wide_modifier_still_present_but_harmless():
    """content-inner--wide bleibt als Klasse bestehen (Templates muessen nicht
    angefasst werden), setzt aber denselben Wert wie die Basis-Regel."""
    body = _rule_body(STYLE_CSS, ".content-inner--wide")
    assert "max-width: none" in body
