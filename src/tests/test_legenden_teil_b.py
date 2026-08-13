"""Tests fuer TEIL B (Legenden aufraeumen und gleichmaessig setzen):
- "BS Berufsschule" + "HS Hochschule/Uni" -> EIN Eintrag "BS/HS Schule" in
  allen fuenf Matrix-Legenden (Planer-Matrix + vier Azubi-Seiten).
- Der Eintrag "du" entfaellt in share/jahrgang.html und share/uebersicht.html.
- .matrix-legend ist ein CSS-Grid mit 6/3/2 Spalten je nach Breakpoint.
"""
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "app" / "templates"
STYLE_CSS = (Path(__file__).resolve().parents[1] / "app" / "static" / "style.css").read_text(
    encoding="utf-8"
)

ALLE_LEGENDEN_TEMPLATES = [
    "overview/matrix.html",
    "share/plan.html",
    "share/klasse.html",
    "share/jahrgang.html",
    "share/uebersicht.html",
]


@pytest.mark.parametrize("template_name", ALLE_LEGENDEN_TEMPLATES)
def test_legende_fasst_bs_und_hs_zusammen(template_name):
    """Alle fuenf Legenden zeigen EINEN zusammengefassten Eintrag "BS/HS
    Schule" statt zwei getrennter Eintraege "BS Berufsschule" / "HS
    Hochschule/Uni". Die Chips in den Tabellenzellen selbst (BS bzw. HS)
    sind davon nicht betroffen -- nur die Legenden-Erklaerung wird kuerzer."""
    src = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
    assert "BS/HS" in src
    assert "Berufsschule</span>" not in src
    assert "Hochschule/Uni</span>" not in src


@pytest.mark.parametrize("template_name", ALLE_LEGENDEN_TEMPLATES)
def test_legende_hat_genau_sechs_eintraege(template_name):
    """Jede Legende hat nach dem Zusammenlegen (BS+HS) und dem Entfernen von
    "du" (nur jahrgang/uebersicht) genau sechs <span class="legend-item">."""
    src = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
    idx = src.find('class="matrix-legend"')
    assert idx != -1
    end = src.find("</div>", idx)
    legend_block = src[idx:end]
    assert legend_block.count('class="legend-item"') == 6


@pytest.mark.parametrize("template_name", ["share/jahrgang.html", "share/uebersicht.html"])
def test_legende_ohne_du_eintrag(template_name):
    """"du" entfaellt als Legenden-Eintrag auf den Seiten, die Trainees in
    einer Liste zeigen (selbsterklaerend) -- der "du"-Chip selbst (Markierung
    der eigenen Zeile in _partials/week_matrix*.html) bleibt unveraendert."""
    src = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
    idx = src.find('class="matrix-legend"')
    assert idx != -1
    end = src.find("</div>", idx)
    legend_block = src[idx:end]
    assert "self-tag" not in legend_block
    assert ">Du<" not in legend_block


def test_matrix_legend_ist_ein_grid_mit_drei_breakpoints():
    """.matrix-legend nutzt CSS-Grid mit 6 Spalten (volle Breite), die beim
    Umbruch auf 3 (>=6 Eintraege -> 3+3) und dann 2 (2+2+2) Spalten
    umschaltet -- statt flex-wrap, das je nach Textlaenge eine haengende
    letzte Zeile mit einem einzelnen Eintrag erzeugen wuerde."""
    idx = STYLE_CSS.find(".matrix-legend {")
    assert idx != -1
    end = STYLE_CSS.find("}", idx)
    rule = STYLE_CSS[idx:end]
    assert "display: grid" in rule
    assert "repeat(6, 1fr)" in rule

    assert "repeat(3, 1fr)" in STYLE_CSS
    assert "repeat(2, 1fr)" in STYLE_CSS
