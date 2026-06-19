"""Tests fuer die Matrix-Chip-Overhaul-Features:
- Department.farbe defaults + persists
- Department form create/update with color round-trips
- text_color_for utility
- Overview matrix: chip rendering (BS/HS/BLK/ABTEILUNG/visited column)
"""
import pytest
from sqlmodel import Session

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    DepartmentKategorie,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)
from app.utils.colors import department_color_map, text_color_for

SY = "2025-2026"
SY2 = "2024-2025"


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
    d = Department(code="TEST", name="Test Dept", kategorie=DepartmentKategorie.ITO)
    session.add(d)
    session.flush()
    assert d.farbe == "#9CA3AF"


def test_department_farbe_persists(session: Session):
    """Custom farbe value is stored and retrieved."""
    d = Department(code="COL1", name="Colored Dept", kategorie=DepartmentKategorie.ITO, farbe="#A855F7")
    session.add(d)
    session.commit()
    fetched = session.get(Department, d.id)
    assert fetched.farbe == "#A855F7"


# ── department_color_map ──────────────────────────────────────────────────────

def test_department_color_map_structure(session: Session):
    """department_color_map returns correct bg/fg/code/name."""
    d = Department(code="MAP1", name="Map Test", kategorie=DepartmentKategorie.ITO, farbe="#000000")
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
        "kategorie": "ITO",
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
        "kategorie": "ITO",
    }, follow_redirects=False)
    assert r.status_code == 303

    from sqlmodel import select
    dept = session.exec(select(Department).where(Department.code == "DEF")).first()
    assert dept is not None
    assert dept.farbe == "#9CA3AF"


def test_dept_form_update_with_farbe(client, session: Session):
    """POST /abteilungen/{id} with new farbe updates the color."""
    d = Department(code="UPD", name="Update Test", kategorie=DepartmentKategorie.ITO, farbe="#111111")
    session.add(d)
    session.commit()

    r = client.post(f"/abteilungen/{d.id}", data={
        "code": "UPD",
        "name": "Update Test",
        "kategorie": "ITO",
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
    cp = Department(code="CP", name="Cloud Platform", kategorie=DepartmentKategorie.ITO, farbe="#9CA3AF")
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


def test_overview_urlaub_shows_u_with_cell_blocker(client, session: Session):
    """URLAUB assignment renders as 'U' with class cell-blocker."""
    ids = _setup_overview(session)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.URLAUB, abteilung_id=None, source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "cell-blocker" in r.text
    assert ">U<" in r.text


def test_overview_frei_shows_u_with_cell_blocker(client, session: Session):
    """FREI assignment renders as 'U' with class cell-blocker."""
    ids = _setup_overview(session)
    session.add(Assignment(
        trainee_id=ids["trainee_id"], schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.FREI, abteilung_id=None, source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "cell-blocker" in r.text
    assert ">U<" in r.text


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
