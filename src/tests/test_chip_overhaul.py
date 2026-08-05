"""Tests fuer die Matrix-Chip-Overhaul-Features:
- Department.farbe defaults + persists
- Department form create/update with color round-trips
- text_color_for utility
- Overview matrix: chip rendering (BS/HS/BLK/ABTEILUNG/visited column)
"""
from pathlib import Path

import pytest
from sqlmodel import Session

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)
from app.utils.colors import department_color_map, text_color_for

SY = "2025-2026"
SY2 = "2024-2025"

STYLE_CSS = (Path(__file__).resolve().parents[1] / "app" / "static" / "style.css").read_text(
    encoding="utf-8"
)


# ── text_color_for ────────────────────────────────────────────────────────────

def test_text_color_dark_background():
    """Dark backgrounds (#374151) return white text."""
    assert text_color_for("#374151") == "#ffffff"


def test_text_color_light_background():
    """Light backgrounds (#FACC15 yellow) return dark text."""
    assert text_color_for("#FACC15") == "#171717"


def test_text_color_black():
    assert text_color_for("#000000") == "#ffffff"


def test_text_color_white():
    assert text_color_for("#ffffff") == "#171717"


def test_text_color_deep_blue():
    """Deep blue (#1E3A8A) should return white."""
    assert text_color_for("#1E3A8A") == "#ffffff"


def test_text_color_invalid_fallback():
    """Invalid color string returns dark text (safe fallback)."""
    assert text_color_for("not-a-color") == "#171717"


# ── Department.farbe model field ──────────────────────────────────────────────

def test_department_farbe_default(session: Session):
    """Department.farbe defaults to #9CA3AF."""
    d = Department(code="TEST", name="Test Dept")
    session.add(d)
    session.flush()
    assert d.farbe == "#9CA3AF"


def test_department_farbe_persists(session: Session):
    """Custom farbe value is stored and retrieved."""
    d = Department(code="COL1", name="Colored Dept", farbe="#A855F7")
    session.add(d)
    session.commit()
    fetched = session.get(Department, d.id)
    assert fetched.farbe == "#A855F7"


# ── department_color_map ──────────────────────────────────────────────────────

def test_department_color_map_structure(session: Session):
    """department_color_map returns correct bg/fg/code/name."""
    d = Department(code="MAP1", name="Map Test", farbe="#000000")
    session.add(d)
    session.flush()
    m = department_color_map([d])
    assert d.id in m
    entry = m[d.id]
    assert entry["bg"] == "#000000"
    assert entry["fg"] == "#ffffff"   # dark bg -> white text
    assert entry["code"] == "MAP1"
    assert entry["name"] == "Map Test"


# ── Department form: create with farbe ───────────────────────────────────────

def test_dept_form_create_with_farbe(client, session: Session):
    """POST /abteilungen/ with farbe stores the color."""
    r = client.post("/abteilungen/", data={
        "code": "XYZ",
        "name": "Test XYZ",
        "farbe": "#FF0000",
    }, follow_redirects=False)
    assert r.status_code == 303

    from sqlmodel import select
    dept = session.exec(select(Department).where(Department.code == "XYZ")).first()
    assert dept is not None
    assert dept.farbe == "#FF0000"


def test_dept_form_create_default_farbe(client, session: Session):
    """POST /abteilungen/ without farbe uses default #9CA3AF."""
    r = client.post("/abteilungen/", data={
        "code": "DEF",
        "name": "Default Color",
    }, follow_redirects=False)
    assert r.status_code == 303

    from sqlmodel import select
    dept = session.exec(select(Department).where(Department.code == "DEF")).first()
    assert dept is not None
    assert dept.farbe == "#9CA3AF"


def test_dept_form_update_with_farbe(client, session: Session):
    """POST /abteilungen/{id} with new farbe updates the color."""
    d = Department(code="UPD", name="Update Test", farbe="#111111")
    session.add(d)
    session.commit()

    r = client.post(f"/abteilungen/{d.id}", data={
        "code": "UPD",
        "name": "Update Test",
        "farbe": "#222222",
    }, follow_redirects=False)
    assert r.status_code == 303

    session.refresh(d)
    assert d.farbe == "#222222"


# ── Overview matrix chip rendering ───────────────────────────────────────────

def _setup_overview(session: Session) -> dict:
    """Set up schoolyear, class, departments, and a trainee."""
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    session.add(Schoolyear(id=SY2, start_kw=36, start_year=2024, end_kw=35, end_year=2025))
    klasse = TraineeClass(name="FISI 2. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    cp = Department(code="CP", name="Cloud Platform", farbe="#9CA3AF")
    session.add_all([klasse, cp])
    session.flush()
    trainee = Trainee(vorname="Test", nachname="Trainee", rolle=TraineeRolle.AZUBI, klasse_id=klasse.id)
    session.add(trainee)
    session.flush()
    session.commit()
    return {"trainee_id": trainee.id, "cp_id": cp.id, "klasse_id": klasse.id}


def test_overview_berufsschule_shows_bs_with_cell_school(client, session: Session):
    """BERUFSSCHULE assignment renders as 'BS' with class cell-school."""
    ids = _setup_overview(session)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.BERUFSSCHULE, abteilung_id=None, source=AssignmentSource.AUTO,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "cell-school" in r.text
    assert ">BS<" in r.text


def test_overview_uni_shows_hs_with_cell_school(client, session: Session):
    """UNI assignment renders as 'HS' with class cell-school."""
    ids = _setup_overview(session)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.UNI, abteilung_id=None, source=AssignmentSource.AUTO,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "cell-school" in r.text
    assert ">HS<" in r.text


# URLAUB als Assignment-Typ entfaellt (siehe Abwesenheiten-Overlay, project_
# computed_class_model): der frühere Test "URLAUB rendert als U" ist damit
# gegenstandslos geworden. FREI bleibt der einzige "Blocker"-Typ und wird
# unten mit dem neuen Buchstaben 'F' geprueft.

def test_overview_frei_shows_f_with_cell_blocker(client, session: Session):
    """FREI assignment renders as 'F' with class cell-blocker.

    halbjahr wird explizit auf '1' gesetzt (deckt KW36-KW10 ab, hier KW40/2025),
    damit die Zelle unabhaengig vom Default-Halbjahr (das sich am heutigen
    Datum orientiert, siehe overview._default_halbjahr) tatsaechlich im
    gerenderten Bereich liegt -- sonst wuerde die Assertion nur zufaellig
    ueber die (unabhaengige) Legende passen."""
    ids = _setup_overview(session)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.FREI, abteilung_id=None, source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": "1"})
    assert r.status_code == 200
    cell = _cell_html(r.text, ids["trainee_id"], 40, 2025)
    assert "cell-blocker" in cell
    assert ">F<" in cell


def test_overview_abteilung_chip_has_inline_style(client, session: Session):
    """ABTEILUNG assignment chip has inline background: style with dept color."""
    ids = _setup_overview(session)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp_id"], source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    # The dept chip uses inline style with background
    assert "background:" in r.text
    # CP code should appear in the chip
    assert ">CP<" in r.text


def test_overview_visited_column_header_present(client, session: Session):
    """The 'Bereits eingeplant' column header is rendered."""
    _setup_overview(session)
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Bereits eingeplant" in r.text
    assert "matrix-th-visited" in r.text


def test_overview_visited_dept_in_right_column(client, session: Session):
    """A previously visited department appears in the visited right column,
    not in the name cell."""
    ids = _setup_overview(session)
    # CP assignment in a different schoolyear (the "visited" history)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY2, kw=2, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp_id"], source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    # visited-col-chip should be present (right column chip)
    assert "visited-col-chip" in r.text
    assert "matrix-td-visited" in r.text
    # The old visited-depts block under the name should NOT contain CP
    # (i.e., visited chips are now in the right column, not in matrix-td-name)
    assert "visited-depts" not in r.text


def test_overview_no_visited_chip_when_no_history(client, session: Session):
    """Without prior ABTEILUNG assignments, visited column is empty."""
    _setup_overview(session)
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    # Column header still present
    assert "Bereits eingeplant" in r.text
    # No chips in it
    assert "visited-col-chip" not in r.text


# ── Bestaetigungsstatus-Marker (ABTEILUNG-Zellen) ────────────────────────────

def _cell_html(r_text: str, trainee_id: int, kw: int, jahr: int) -> str:
    """Extract the <td ...> snippet for one matrix cell from the response HTML."""
    marker = f'id="cell-{trainee_id}-{kw}-{jahr}"'
    idx = r_text.find(marker)
    assert idx != -1, "cell not found in response (check halbjahr filter / kw range)"
    end = r_text.find("</td>", idx)
    return r_text[idx:end]


def test_overview_abteilung_bestaetigt_shows_confirm_marker(client, session: Session):
    """ABTEILUNG assignment with bestaetigung='bestaetigt' gets mc-confirm-bestaetigt marker."""
    ids = _setup_overview(session)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp_id"], source=AssignmentSource.MANUAL,
        bestaetigung="bestaetigt",
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": "1"})
    assert r.status_code == 200
    cell = _cell_html(r.text, ids["trainee_id"], 40, 2025)
    assert "mc-confirm-bestaetigt" in cell


def test_overview_abteilung_default_offen_shows_offen_marker(client, session: Session):
    """ABTEILUNG assignment without explicit bestaetigung defaults to 'offen' marker."""
    ids = _setup_overview(session)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp_id"], source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": "1"})
    assert r.status_code == 200
    cell = _cell_html(r.text, ids["trainee_id"], 40, 2025)
    assert "mc-confirm-offen" in cell


def test_overview_abteilung_abgelehnt_shows_confirm_marker(client, session: Session):
    """ABTEILUNG assignment with bestaetigung='abgelehnt' gets mc-confirm-abgelehnt marker."""
    ids = _setup_overview(session)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp_id"], source=AssignmentSource.MANUAL,
        bestaetigung="abgelehnt",
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": "1"})
    assert r.status_code == 200
    cell = _cell_html(r.text, ids["trainee_id"], 40, 2025)
    assert "mc-confirm-abgelehnt" in cell


def test_overview_non_abteilung_has_no_confirm_marker(client, session: Session):
    """BERUFSSCHULE/FREI assignments never get a confirm marker class."""
    ids = _setup_overview(session)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.FREI, abteilung_id=None, source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": "1"})
    assert r.status_code == 200
    cell = _cell_html(r.text, ids["trainee_id"], 40, 2025)
    assert "mc-confirm-" not in cell


# ── Befund 8: veraltete Legenden (U/Urlaub statt F/Frei, fehlender Abwesend-
#    Eintrag in den share-Templates) ─────────────────────────────────────────

def _legend_html(r_text: str) -> str:
    """Extrahiert den <div class="matrix-legend">...</div>-Block."""
    idx = r_text.find('class="matrix-legend"')
    assert idx != -1, "matrix-legend nicht in der Antwort gefunden"
    end = r_text.find("</div>", idx)
    return r_text[idx:end]


def test_overview_legend_shows_f_frei_not_u_urlaub(client, session: Session):
    """Die Legende zeigt 'F' / 'Frei' (das Kuerzel, das chip.html fuer FREI
    tatsaechlich rendert). Das 'U' steht seit dem Abwesenheiten-Umbau nicht
    mehr fuer den alten Plan-Typ URLAUB, sondern fuer eine Abwesenheit in einer
    sonst leeren Woche -- es muss also mit 'Urlaub' beschriftet sein und darf
    nicht laenger als FREI-Kuerzel auftauchen."""
    _setup_overview(session)
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    legend = _legend_html(r.text)
    assert "cell-blocker\">F</span> Frei" in legend
    assert "cell-blocker\">U</span> Urlaub" in legend
    assert "cell-blocker\">A</span> sonstige Abwesenheit" in legend


def test_overview_legend_has_abwesend_sample(client, session: Session):
    """Die Legende der Voll-Matrix erklaert die Abwesend-Schraffur bereits
    (Referenz fuer die share-Templates unten)."""
    _setup_overview(session)
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    legend = _legend_html(r.text)
    assert "matrix-abwesend-sample" in legend
    assert "Abwesend in einer verplanten Woche" in legend


@pytest.mark.parametrize("template_name", [
    "share/plan.html",
    "share/klasse.html",
    "share/jahrgang.html",
    "share/uebersicht.html",
])
def test_share_legend_shows_f_frei_and_abwesend_sample(template_name):
    """Alle vier share-Legenden: 'F' / 'Frei' statt 'U' / 'Urlaub', UND der
    Abwesend-Sample-Eintrag (der vorher in den share-Templates komplett
    fehlte, obwohl die Zellen die Markierung schon anzeigen)."""
    src = (
        Path(__file__).resolve().parents[1] / "app" / "templates" / template_name
    ).read_text(encoding="utf-8")
    assert "cell-blocker\">F</span> Frei" in src
    assert "cell-blocker\">U</span> Urlaub" in src
    assert "matrix-abwesend-sample" in src
    assert "Abwesend in einer verplanten Woche" in src


# ── Befund 11: CSS-Spezifitaet der Abwesend-Schraffur ───────────────────────

def test_abwesend_voll_selector_matches_today_conflict_specificity():
    """.matrix-cell.mc-abwesend.mc-abwesend-voll (Spezifitaet 0-3-0) statt nur
    .matrix-cell.mc-abwesend-voll (0-2-0) -- sonst verliert eine Zelle, die
    gleichzeitig mc-today + mc-conflict UND ganze-Woche-abwesend ist, die
    background-image-Schraffur gegen die hoeher-spezifische
    .matrix-cell.mc-today.mc-conflict-Regel (setzt background-image implizit
    auf none)."""
    assert ".matrix-cell.mc-abwesend.mc-abwesend-voll {" in STYLE_CSS
    assert ".matrix-cell.mc-abwesend-voll {" not in STYLE_CSS


# ── Befund 14: tote CSS-Reste (.cell-URLAUB, veralteter Kommentar) ──────────

def test_cell_urlaub_dead_css_removed():
    """.cell-URLAUB hat keinen Nutzer mehr (AssignmentTyp.URLAUB entfaellt)
    und der Kommentar ueber 'Urlaub and Frei shown as dark U' ist veraltet."""
    assert ".cell-URLAUB" not in STYLE_CSS
    assert "Urlaub and Frei shown as dark" not in STYLE_CSS


def test_overview_zelle_zeigt_u_kuerzel_bei_abwesenheit(client, session: Session):
    """Eine Woche, in der der Trainee abwesend ist und sonst nichts geplant ist,
    zeigt das Kuerzel 'U' (Urlaub) bzw. 'A' (Sonstiges) -- vorher stand dort nur
    eine leere Zelle mit Schraffur (Wunsch aus dem Praxis-Feedback)."""
    from datetime import date

    from app.models import Abwesenheit, AbwesenheitQuelle, AbwesenheitTyp

    ids = _setup_overview(session)
    # KW 12/2026 = Mo 16.03. bis Fr 20.03.
    session.add(Abwesenheit(
        trainee_id=ids["trainee_id"], von_datum=date(2026, 3, 16), bis_datum=date(2026, 3, 20),
        typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.PLANER,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": ""})
    assert r.status_code == 200
    # Gezielt die Zelle pruefen -- die Legende enthaelt das Kuerzel ebenfalls
    cell = _cell_html(r.text, ids["trainee_id"], 12, 2026)
    assert 'class="cell-chip cell-blocker">U</span>' in cell
    assert "mc-abwesend" in cell

    # Liegt in derselben Woche ein Einsatz, bleibt dessen Chip stehen (kein U daneben)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY, kw=12, jahr=2026,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp_id"], source=AssignmentSource.MANUAL,
    ))
    session.commit()
    cell2 = _cell_html(
        client.get("/overview", params={"schoolyear_id": SY, "halbjahr": ""}).text,
        ids["trainee_id"], 12, 2026,
    )
    assert 'class="cell-chip cell-blocker">U</span>' not in cell2
    assert ">CP</span>" in cell2
    assert "mc-abwesend" in cell2


def test_bestaetigt_marker_hat_passende_css_regel(client, session: Session):
    """Regression: Das Template rendert die Klasse aus dem gespeicherten Status
    ('bestaetigt'), das scoped CSS definierte aber nur '.mc-confirm-ok' --
    bestaetigte Einsaetze hatten dadurch GAR KEINEN Punkt. Klassenname im
    Markup und im CSS muessen zusammenpassen."""
    ids = _setup_overview(session)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp_id"],
        source=AssignmentSource.MANUAL, bestaetigung="bestaetigt",
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": "1"})
    assert r.status_code == 200
    cell = _cell_html(r.text, ids["trainee_id"], 40, 2025)
    assert "mc-confirm-bestaetigt" in cell
    # ... und dafuer existiert auch eine CSS-Regel mit Farbe
    assert ".matrix-cell.mc-confirm-bestaetigt::after" in r.text
    assert "mc-confirm-ok" not in r.text
