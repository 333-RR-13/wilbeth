"""Tests fuer die Matrix-Uebersicht: Klassen- und Abteilungs-Filter (Variante A)."""
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

SY = "2025-2026"


def _base(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    fisi = TraineeClass(name="FISI 2. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    fiae = TraineeClass(name="FIAE 2. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    cp = Department(code="CP", name="Cloud Platform")
    ba = Department(code="BA", name="Business Applications", erlaubt_mehrfachbelegung=True)
    session.add_all([fisi, fiae, cp, ba])
    session.flush()

    anton = Trainee(vorname="Anton", nachname="Altmann", rolle=TraineeRolle.AZUBI, klasse_id=fisi.id)
    beate = Trainee(vorname="Beate", nachname="Bergmann", rolle=TraineeRolle.AZUBI, klasse_id=fiae.id)
    session.add_all([anton, beate])
    session.flush()

    # Anton in CP, Beate in BA
    session.add(Assignment(trainee_id=anton.id, schoolyear_id=SY, kw=40, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=cp.id, source=AssignmentSource.MANUAL))
    session.add(Assignment(trainee_id=beate.id, schoolyear_id=SY, kw=40, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=ba.id, source=AssignmentSource.MANUAL))
    session.commit()
    return {"fisi": fisi.id, "fiae": fiae.id, "cp": cp.id, "ba": ba.id}


def test_overview_renders(client, session):
    _base(session)
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Altmann" in r.text
    assert "Bergmann" in r.text


def test_klasse_filter(client, session):
    ids = _base(session)
    r = client.get("/overview", params={"schoolyear_id": SY, "klasse_id": ids["fisi"]})
    assert r.status_code == 200
    assert "Altmann" in r.text       # FISI
    assert "Bergmann" not in r.text  # FIAE ausgeblendet


def test_abteilung_filter_variante_a(client, session):
    ids = _base(session)
    # Nur Trainees mit Einsatz in CP
    r = client.get("/overview", params={"schoolyear_id": SY, "abteilung_id": ids["cp"]})
    assert r.status_code == 200
    assert "Altmann" in r.text       # hat CP-Einsatz
    assert "Bergmann" not in r.text  # nur BA


def test_abteilung_filter_other_dept(client, session):
    ids = _base(session)
    r = client.get("/overview", params={"schoolyear_id": SY, "abteilung_id": ids["ba"]})
    assert r.status_code == 200
    assert "Bergmann" in r.text
    assert "Altmann" not in r.text


def test_date_header_present(client, session):
    _base(session)
    r = client.get("/overview", params={"schoolyear_id": SY})
    # Zweizeiliger Header: KW-Nummer + Datum der Montagswoche
    assert "th-kw-num" in r.text
    assert "th-kw-date" in r.text


def test_wochen_filter_viewport_in_html(client, session):
    """wochen=4 rendert ALLE KW-Spalten, setzt aber max-width fuer den Viewport-Container.

    Seit der Umstellung auf scrollbaren Scope werden immer alle Wochen gerendert;
    die sichtbare Breite wird per CSS max-width gesteuert, nicht per Slicing.
    """
    _base(session)
    r = client.get("/overview", params={"schoolyear_id": SY, "wochen": "4"})
    assert r.status_code == 200
    # Alle ~52 Wochen des Lehrjahres sind im HTML (kein Slicing mehr)
    kw_headers = r.text.count("th-kw-num")
    assert kw_headers > 4, f"Erwartet alle KW-Spalten, gefunden: {kw_headers}"
    # Viewport-Begrenzung via max-width im matrix-scroll-Container
    assert "max-width" in r.text, "max-width muss im HTML stehen wenn wochen=4"
    assert "calc(180px + 4 * 38px)" in r.text, "Viewport-Formel fuer n_wochen=4 erwartet"
    # Dropdown muss mit '4' als selected gerendert sein
    assert 'value="4" selected' in r.text or "value=\"4\"  selected" in r.text or ">4 Wochen<" in r.text


def test_wochen_filter_default_shows_all(client, session):
    """Ohne wochen-Parameter werden alle Wochen des Lehrjahres angezeigt; keine max-width."""
    _base(session)
    r_all = client.get("/overview", params={"schoolyear_id": SY})
    r_filtered = client.get("/overview", params={"schoolyear_id": SY, "wochen": "4"})
    assert r_all.status_code == 200
    assert r_filtered.status_code == 200
    # Beide rendern dieselbe Anzahl KW-Spalten (kein Slicing mehr)
    all_cols = r_all.text.count("th-kw-num")
    filtered_cols = r_filtered.text.count("th-kw-num")
    assert all_cols == filtered_cols, (
        f"Beide Modi sollen alle Spalten rendern ({all_cols} vs {filtered_cols})"
    )
    # Ohne wochen-Parameter: kein max-width im Scroll-Container
    assert "max-width" not in r_all.text or "calc(180px" not in r_all.text


def test_wochen_filter_invalid_shows_all(client, session):
    """Ungueltige wochen-Werte (leer, Text) fallen auf alle Wochen zurueck."""
    _base(session)
    r_empty = client.get("/overview", params={"schoolyear_id": SY, "wochen": ""})
    r_text = client.get("/overview", params={"schoolyear_id": SY, "wochen": "abc"})
    r_all = client.get("/overview", params={"schoolyear_id": SY})
    assert r_empty.status_code == 200
    assert r_text.status_code == 200
    assert r_empty.text.count("th-kw-num") == r_all.text.count("th-kw-num")
    assert r_text.text.count("th-kw-num") == r_all.text.count("th-kw-num")
