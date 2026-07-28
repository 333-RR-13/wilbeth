"""Tests fuer die Matrix-Uebersicht: Beruf/Klassen-Baumfilter und Abteilungs-Filter
sowie Archiv-Dropdown.

Der Klassen-Filter arbeitet seit der Umstellung auf den Beruf/Klasse-Checkbaum mit
dem kommaseparierten Mehrfachauswahl-Param "klassen" (Query-Param + Cookie-Key).
Der alte Einzel-Param/Cookie-Key "klasse_id" bleibt als Fallback erhalten, damit
alte Links/Cookies nicht brechen.
"""
import json
from urllib.parse import unquote

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


def test_abteilungs_zelle_hat_tooltip(client, session):
    """Die ganze Matrix-Zelle eines Abteilungs-Einsatzes traegt den
    Abteilungsnamen als title-Tooltip (nicht nur der kleine Chip darin)."""
    _base(session)
    # halbjahr="" = ganzes Jahr, sonst laege KW40/2025 je nach heutigem
    # Datum ausserhalb des angezeigten Halbjahres
    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": ""})
    assert r.status_code == 200
    # td-Markup: title-Attribut direkt vor der class-Zeile (Chip-title allein
    # wuerde dieses Muster nicht erzeugen)
    import re
    assert re.search(r'title="Cloud Platform"\s+class="matrix-cell cell-clickable', r.text)


def test_klassen_filter_single_id(client, session):
    """klassen=<id> (neuer Mehrfachauswahl-Param, hier mit nur einer ID) filtert auf
    die berechnete Klasse des Trainees."""
    ids = _base(session)
    r = client.get("/overview", params={"schoolyear_id": SY, "klassen": str(ids["fisi"])})
    assert r.status_code == 200
    assert "Altmann" in r.text       # FISI
    assert "Bergmann" not in r.text  # FIAE ausgeblendet


def test_klassen_filter_leer_zeigt_alle(client, session):
    """klassen='' (bzw. gar kein Param) zeigt alle Trainees, kein Klassenfilter aktiv."""
    _base(session)
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Altmann" in r.text
    assert "Bergmann" in r.text


def test_klasse_id_alter_param_faellt_zurueck(client, session):
    """Der alte Einzel-Param 'klasse_id' wirkt weiterhin als Fallback fuer 'klassen',
    solange 'klassen' selbst weder als Query-Param noch im Cookie vorhanden ist."""
    ids = _base(session)
    r = client.get("/overview", params={"schoolyear_id": SY, "klasse_id": str(ids["fisi"])})
    assert r.status_code == 200
    assert "Altmann" in r.text       # FISI
    assert "Bergmann" not in r.text  # FIAE ausgeblendet


def test_klassen_filter_ganzer_beruf_alle_lj(client, session):
    """klassen=<id1>,<id2>,<id3> (alle LJ-Klassen eines Berufs) zeigt alle Trainees
    dieses Berufs unabhaengig vom Lehrjahr, aber keine Trainees anderer Berufe."""
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    fisi1 = TraineeClass(name="FISI 1. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    fisi2 = TraineeClass(name="FISI 2. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    fisi3 = TraineeClass(name="FISI 3. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    fiae1 = TraineeClass(name="FIAE 1. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add_all([fisi1, fisi2, fisi3, fiae1])
    session.flush()

    t1 = Trainee(vorname="Erik", nachname="Einserlj", rolle=TraineeRolle.AZUBI, klasse_id=fisi1.id)
    t2 = Trainee(vorname="Zora", nachname="Zweierlj", rolle=TraineeRolle.AZUBI, klasse_id=fisi2.id)
    t3 = Trainee(vorname="Dana", nachname="Dreierlj", rolle=TraineeRolle.AZUBI, klasse_id=fisi3.id)
    tf = Trainee(vorname="Finn", nachname="Fiaeler", rolle=TraineeRolle.AZUBI, klasse_id=fiae1.id)
    session.add_all([t1, t2, t3, tf])
    session.commit()

    klassen_param = f"{fisi1.id},{fisi2.id},{fisi3.id}"
    r = client.get("/overview", params={"schoolyear_id": SY, "klassen": klassen_param, "halbjahr": ""})
    assert r.status_code == 200
    assert "Einserlj" in r.text
    assert "Zweierlj" in r.text
    assert "Dreierlj" in r.text
    assert "Fiaeler" not in r.text  # anderer Beruf (FIAE) bleibt ausgeblendet


def test_klassen_cookie_persistenz(client, session):
    """klassen=<id> wird im ov_filters-Cookie unter dem Schluessel 'klassen' gespeichert
    und beim naechsten Request ohne Query-Param weiterverwendet."""
    ids = _base(session)
    r1 = client.get("/overview", params={"schoolyear_id": SY, "klassen": str(ids["fisi"])})
    assert r1.status_code == 200

    cookie_raw = client.cookies.get("ov_filters")
    assert cookie_raw is not None, "ov_filters-Cookie muss gesetzt sein"
    data = json.loads(unquote(cookie_raw))
    assert data["klassen"] == str(ids["fisi"]), (
        f"Cookie.klassen soll '{ids['fisi']}' sein, ist: {data.get('klassen')}"
    )

    # Folgerequest ohne klassen-Param: Cookie-Wert wird weiterhin angewendet
    r2 = client.get("/overview", params={"schoolyear_id": SY})
    assert r2.status_code == 200
    assert "Altmann" in r2.text
    assert "Bergmann" not in r2.text


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
    # halbjahr="" -> ganzes Jahr (sonst greift der Default-Halbjahr-Filter)
    r = client.get("/overview", params={"schoolyear_id": SY, "wochen": "4", "halbjahr": ""})
    assert r.status_code == 200
    # Alle ~52 Wochen des Lehrjahres sind im HTML (kein Slicing mehr)
    kw_headers = r.text.count("th-kw-num")
    assert kw_headers > 4, f"Erwartet alle KW-Spalten, gefunden: {kw_headers}"
    # Viewport-Begrenzung via max-width im matrix-scroll-Container
    assert "max-width" in r.text, "max-width muss im HTML stehen wenn wochen=4"
    assert "calc(180px + 132px + 4 * 44px)" in r.text, "Viewport-Formel fuer n_wochen=4 erwartet"
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


# ---------------------------------------------------------------------------
# Archiv-Dropdown: nur nicht-archivierte Schuljahre im Dropdown
# ---------------------------------------------------------------------------

def test_archiviertes_jahr_nicht_im_dropdown(client, session):
    """Archivierte Schuljahre (archiviert=True) erscheinen nicht im Jahres-Dropdown."""
    session.add(Schoolyear(id="2023-2024", start_kw=36, start_year=2023, end_kw=35, end_year=2024,
                           archiviert=True))
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026,
                           archiviert=False))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    # Das nicht-archivierte Jahr muss im Dropdown stehen
    assert SY in r.text
    # Das archivierte Jahr darf NICHT im Dropdown stehen (als option-Wert)
    assert '"2023-2024"' not in r.text and "value=\"2023-2024\"" not in r.text, (
        "Archiviertes Schuljahr darf nicht als Dropdown-Option erscheinen"
    )


def test_nicht_archiviertes_jahr_im_dropdown(client, session):
    """Nicht-archivierte Schuljahre erscheinen immer im Dropdown."""
    session.add(Schoolyear(id="2024-2025", start_kw=36, start_year=2024, end_kw=35, end_year=2025,
                           archiviert=False))
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026,
                           archiviert=False))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "2024-2025" in r.text, "Nicht-archiviertes Vorjahr muss im Dropdown erscheinen"
    assert SY in r.text


def test_default_jahr_ist_neuestes_nicht_archiviertes(client, session):
    """Ohne schoolyear_id-Parameter waehlt der Router das neueste nicht-archivierte Jahr."""
    session.add(Schoolyear(id="2023-2024", start_kw=36, start_year=2023, end_kw=35, end_year=2024,
                           archiviert=True))
    session.add(Schoolyear(id="2024-2025", start_kw=36, start_year=2024, end_kw=35, end_year=2025,
                           archiviert=False))
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026,
                           archiviert=False))
    session.commit()

    # Kein schoolyear_id-Parameter: Router soll neuestes nicht-archiviertes Jahr nehmen
    r = client.get("/overview")
    assert r.status_code == 200
    # Das neueste nicht-archivierte Jahr (SY = 2025-2026) muss als selected erscheinen
    assert f'value="{SY}" selected' in r.text or f'value="{SY}"  selected' in r.text or (
        SY in r.text
    ), "Neuestes nicht-archiviertes Jahr muss als Default gewaehlt sein"
    # Das archivierte Jahr soll nicht im Dropdown auftauchen
    assert "value=\"2023-2024\"" not in r.text
