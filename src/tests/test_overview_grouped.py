"""Tests fuer (A) aktiv-Filter, (B) Gruppierung und (C) berechnete Klasse/DH-Label."""
from datetime import date

from sqlmodel import Session

from app.models import (
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)
from app.models.trainee_class_membership import TraineeClassMembership
from app.services.membership_utils import beruf_und_lehrjahr

SY = "2025-2026"


# ---------------------------------------------------------------------------
# Hilfsfunktion
# ---------------------------------------------------------------------------

def _make_year(session: Session) -> None:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    session.flush()


def _make_class(session: Session, name: str) -> TraineeClass:
    c = TraineeClass(name=name, berufsschule="BS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(c)
    session.flush()
    return c


def _add_membership(session: Session, trainee_id: int, klasse_id: int) -> None:
    session.add(TraineeClassMembership(
        trainee_id=trainee_id,
        schoolyear_id=SY,
        klasse_id=klasse_id,
    ))
    session.flush()


# ---------------------------------------------------------------------------
# (A) aktiv-Filter
# ---------------------------------------------------------------------------

def test_inaktiver_azubi_nicht_sichtbar(client, session):
    """Trainee mit aktiv=False darf in der Uebersicht nicht erscheinen."""
    _make_year(session)
    klasse = _make_class(session, "FISI 1. LJ")
    # klasse_id setzen, damit klasse_fuer() nicht None liefert (statischer Fallback)
    aktiv = Trainee(vorname="Anna", nachname="Aktiv", rolle=TraineeRolle.AZUBI,
                    aktiv=True, klasse_id=klasse.id)
    inaktiv = Trainee(vorname="Igor", nachname="Inaktiv", rolle=TraineeRolle.AZUBI,
                      aktiv=False, klasse_id=klasse.id)
    session.add_all([aktiv, inaktiv])
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Aktiv" in r.text
    assert "Inaktiv" not in r.text


def test_aktiver_azubi_sichtbar(client, session):
    """Trainee mit aktiv=True erscheint in der Uebersicht."""
    _make_year(session)
    klasse = _make_class(session, "FISI 1. LJ")
    # klasse_id setzen, damit klasse_fuer() nicht None liefert (statischer Fallback)
    aktiv = Trainee(vorname="Anna", nachname="Sichtbar", rolle=TraineeRolle.AZUBI,
                    aktiv=True, klasse_id=klasse.id)
    session.add(aktiv)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Sichtbar" in r.text


# ---------------------------------------------------------------------------
# (B) Gruppierung – Beruf- und Klassen-Header
# ---------------------------------------------------------------------------

def test_gruppierung_reihenfolge_beruf_klasse(client, session):
    """Ohne Header, aber die Azubi-Reihenfolge ist nach Beruf -> Lehrjahr gruppiert."""
    _make_year(session)
    fisi1 = _make_class(session, "FISI 1. LJ")
    fisi2 = _make_class(session, "FISI 2. LJ")
    fiae2 = _make_class(session, "FIAE 2. LJ")

    t1 = Trainee(vorname="Adam", nachname="Alpha", rolle=TraineeRolle.AZUBI)
    t2 = Trainee(vorname="Berta", nachname="Beta", rolle=TraineeRolle.AZUBI)
    t3 = Trainee(vorname="Carla", nachname="Ceta", rolle=TraineeRolle.AZUBI)
    session.add_all([t1, t2, t3])
    session.flush()

    _add_membership(session, t1.id, fisi1.id)
    _add_membership(session, t2.id, fisi2.id)
    _add_membership(session, t3.id, fiae2.id)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    # Keine sichtbaren Gruppen-Ueberschriften mehr
    assert "matrix-group-beruf" not in r.text
    assert "matrix-group-klasse" not in r.text
    # Reihenfolge: FIAE (Ceta) -> FISI 1. LJ (Alpha) -> FISI 2. LJ (Beta)
    ceta_pos = r.text.index("Ceta")
    alpha_pos = r.text.index("Alpha")
    beta_pos = r.text.index("Beta")
    assert ceta_pos < alpha_pos < beta_pos, "Reihenfolge FIAE -> FISI 1. LJ -> FISI 2. LJ"


def test_keine_gruppen_header(client, session):
    """Es werden KEINE Beruf-/Klassen-Ueberschriften gerendert (nur die Azubis)."""
    _make_year(session)
    fisi2 = _make_class(session, "FISI 2. LJ")

    t = Trainee(vorname="Dirk", nachname="Dorf", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()
    _add_membership(session, t.id, fisi2.id)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "matrix-group-beruf" not in r.text
    assert "matrix-group-klasse" not in r.text
    assert "Dorf" in r.text   # Azubi selbst erscheint weiterhin


def test_trainee_ohne_membership_aber_mit_klasse_wird_angezeigt(client, session):
    """Trainee mit klasse_id aber ohne explizite Membership erscheint via statischem Fallback."""
    _make_year(session)
    klasse = _make_class(session, "FISI 1. LJ")
    # Kein ausbildungsbeginn -> statischer Fallback: klasse_fuer liefert klasse_id
    t = Trainee(vorname="Emil", nachname="Einzel", rolle=TraineeRolle.AZUBI,
                klasse_id=klasse.id)
    session.add(t)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Einzel" in r.text


def test_trainee_ohne_klasse_id_unter_ohne_klasse_sichtbar(client, session):
    """Aktiver Trainee OHNE klasse_id (kein Anker) bleibt sichtbar und landet in der
    Gruppe 'Ohne Klasse'. Nur echte Absolventen (Anker vorhanden, berechnet -> None)
    werden ausgeblendet (siehe test_absolvent_nicht_im_naechsten_jahr_sichtbar)."""
    _make_year(session)
    t = Trainee(vorname="Kein", nachname="KeinKlasse", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "KeinKlasse" in r.text


def test_trainee_reihenfolge_innerhalb_klasse(client, session):
    """Trainees innerhalb einer Klasse sind nach (nachname, vorname) sortiert."""
    _make_year(session)
    fisi2 = _make_class(session, "FISI 2. LJ")

    t1 = Trainee(vorname="Zoe", nachname="Zahn", rolle=TraineeRolle.AZUBI)
    t2 = Trainee(vorname="Aaron", nachname="Abel", rolle=TraineeRolle.AZUBI)
    session.add_all([t1, t2])
    session.flush()
    _add_membership(session, t1.id, fisi2.id)
    _add_membership(session, t2.id, fisi2.id)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    abel_pos = r.text.index("Abel")
    zahn_pos = r.text.index("Zahn")
    assert abel_pos < zahn_pos, "Abel soll vor Zahn erscheinen (alphabetisch)"


# ---------------------------------------------------------------------------
# (C) Berechnete Klasse & Jahreswechsel
# ---------------------------------------------------------------------------

def test_kuenftiges_jahr_zeigt_hochgestufte_klasse(client, session):
    """Im naechsten Schuljahr erscheint ein Trainee in seiner hochgestuften Klasse.

    Setup: FISI 1. LJ und FISI 2. LJ existieren; Trainee startet in FISI 1. LJ (2025);
    fuer das Schuljahr 2026-2027 soll klasse_fuer() FISI 2. LJ zurueckgeben.
    """
    sy_aktuell = "2025-2026"
    sy_naechstes = "2026-2027"
    session.add(Schoolyear(id=sy_aktuell, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    session.add(Schoolyear(id=sy_naechstes, start_kw=36, start_year=2026, end_kw=35, end_year=2027))
    fisi1 = _make_class(session, "FISI 1. LJ")
    fisi2 = _make_class(session, "FISI 2. LJ")

    # Trainee startet August 2025 -> start_year = 2025 -> steps = 0 fuer 2025-2026
    t = Trainee(
        vorname="Franz", nachname="Fortschritt",
        rolle=TraineeRolle.AZUBI,
        klasse_id=fisi1.id,
        ausbildungsbeginn=date(2025, 9, 1),
    )
    session.add(t)
    session.commit()

    # Im aktuellen Jahr (2025-2026): FISI 1. LJ
    r_aktuell = client.get("/overview", params={"schoolyear_id": sy_aktuell, "halbjahr": ""})
    assert r_aktuell.status_code == 200
    assert "Fortschritt" in r_aktuell.text

    # Im naechsten Jahr (2026-2027): sollte in FISI 2. LJ erscheinen (hochgestuft)
    r_naechstes = client.get("/overview", params={"schoolyear_id": sy_naechstes, "halbjahr": ""})
    assert r_naechstes.status_code == 200
    assert "Fortschritt" in r_naechstes.text, (
        "Trainee soll im kuenftigen Jahr in hochgestufter Klasse sichtbar sein"
    )


def test_absolvent_nicht_im_naechsten_jahr_sichtbar(client, session):
    """Ein AZUBI der nach 3. LJ abgeschlossen hat, erscheint im Folgejahr NICHT."""
    sy_jetzt = "2025-2026"
    sy_naechst = "2026-2027"
    session.add(Schoolyear(id=sy_jetzt, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    session.add(Schoolyear(id=sy_naechst, start_kw=36, start_year=2026, end_kw=35, end_year=2027))
    fisi3 = _make_class(session, "FISI 3. LJ")
    # kein next_class_id und keine FISI 4. LJ -> Absolvent nach einem Schritt

    # Trainee in letztem Lehrjahr (3. LJ, start 2025) -> naechstes Jahr: None = Absolvent
    t = Trainee(
        vorname="Abby", nachname="Absolvent",
        rolle=TraineeRolle.AZUBI,
        klasse_id=fisi3.id,
        ausbildungsbeginn=date(2022, 9, 1),  # start_year=2022, steps=3 fuer 2025-2026
    )
    session.add(t)
    session.commit()

    # Im naechsten Jahr: klasse_fuer liefert None -> Trainee ausgeblendet
    r = client.get("/overview", params={"schoolyear_id": sy_naechst, "halbjahr": ""})
    assert r.status_code == 200
    assert "Absolvent" not in r.text, (
        "Absolvent soll im Folgejahr nicht mehr in der Ansicht erscheinen"
    )


def test_klasse_filter_basiert_auf_berechneter_klasse(client, session):
    """Klassen-Filter (klasse_id) arbeitet auf der berechneten Klasse.

    Im naechsten Jahr filtert klasse_id=FISI_2_ID den Trainee, dessen
    berechnete Klasse FISI 2. LJ ist.
    """
    sy_naechstes = "2026-2027"
    session.add(Schoolyear(id=sy_naechstes, start_kw=36, start_year=2026, end_kw=35, end_year=2027))
    fisi1 = _make_class(session, "FISI 1. LJ")
    fisi2 = _make_class(session, "FISI 2. LJ")

    t = Trainee(
        vorname="Klaus", nachname="Zieltrainee",
        rolle=TraineeRolle.AZUBI,
        klasse_id=fisi1.id,
        ausbildungsbeginn=date(2025, 9, 1),  # start_year=2025, steps=1 -> FISI 2. LJ
    )
    session.add(t)
    session.commit()

    # Filter auf FISI 2. LJ im naechsten Jahr -> Trainee sichtbar
    r = client.get("/overview", params={
        "schoolyear_id": sy_naechstes, "klasse_id": str(fisi2.id), "halbjahr": "",
    })
    assert r.status_code == 200
    assert "Zieltrainee" in r.text, "Trainee muss via berechneter Klasse FISI 2. LJ gefiltert werden"

    # Filter auf FISI 1. LJ im naechsten Jahr -> Trainee NICHT sichtbar
    r2 = client.get("/overview", params={
        "schoolyear_id": sy_naechstes, "klasse_id": str(fisi1.id), "halbjahr": "",
    })
    assert r2.status_code == 200
    assert "Zieltrainee" not in r2.text, "Trainee darf bei FISI 1. LJ-Filter im naechsten Jahr nicht erscheinen"


def test_vor_ausbildungsbeginn_nicht_sichtbar(client, session):
    """Trainee der noch nicht begonnen hat (steps < 0) erscheint nicht in aelterem Jahr."""
    sy_alt = "2024-2025"
    session.add(Schoolyear(id=sy_alt, start_kw=36, start_year=2024, end_kw=35, end_year=2025))
    fisi1 = _make_class(session, "FISI 1. LJ")

    # Trainee beginnt erst 2025 -> steps = 2024 - 2025 = -1 fuer sy_alt
    t = Trainee(
        vorname="Neu", nachname="Neuling",
        rolle=TraineeRolle.AZUBI,
        klasse_id=fisi1.id,
        ausbildungsbeginn=date(2025, 9, 1),
    )
    session.add(t)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": sy_alt, "halbjahr": ""})
    assert r.status_code == 200
    assert "Neuling" not in r.text, (
        "Trainee vor Ausbildungsbeginn darf nicht in aelterem Schuljahr erscheinen"
    )


# ---------------------------------------------------------------------------
# (D) DH-Studenten: semester_label in der Uebersicht
# ---------------------------------------------------------------------------

def test_dh_semester_label_wird_angezeigt(client, session):
    """DH-Student sieht sein Semester-Label (z. B. '1. Semester') in der Matrix."""
    _make_year(session)
    # DH-Klasse ohne LJ-Muster -> statischer Fallback
    dhbw = _make_class(session, "DHBW Cybersecurity")

    # DH-Student: start_year=2025 (August), Schuljahr 2025-2026 -> steps=0 -> H1 = 1. Semester
    dh = Trainee(
        vorname="Dana", nachname="DHStudent",
        rolle=TraineeRolle.DH_STUDENT,
        klasse_id=dhbw.id,
        ausbildungsbeginn=date(2025, 10, 1),
    )
    session.add(dh)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": "1"})
    assert r.status_code == 200
    assert "DHStudent" in r.text
    # 1. Semester fuer H1, steps=0 -> base=0 -> "1. Semester" als ov-semester-badge
    assert '<span class="ov-semester-badge"' in r.text, "DH-Student soll ein ov-semester-badge haben"
    assert "1. Semester" in r.text, (
        "DH-Student soll '1. Semester' Label in H1 des ersten Jahres sehen"
    )


def test_dh_semester_label_h2(client, session):
    """DH-Student sieht im 2. Halbjahr des ersten Jahres '2. Semester'."""
    _make_year(session)
    dhbw = _make_class(session, "DHBW Cybersecurity")

    dh = Trainee(
        vorname="Dora", nachname="DHZwei",
        rolle=TraineeRolle.DH_STUDENT,
        klasse_id=dhbw.id,
        ausbildungsbeginn=date(2025, 10, 1),
    )
    session.add(dh)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": "2"})
    assert r.status_code == 200
    assert "DHZwei" in r.text
    assert '<span class="ov-semester-badge"' in r.text, "DH-Student soll ein ov-semester-badge haben"
    assert "2. Semester" in r.text, "DH-Student soll '2. Semester' in H2 des ersten Jahres sehen"


def test_azubi_hat_kein_semester_label(client, session):
    """Regulaerer AZUBI bekommt kein Semester-Label angezeigt."""
    _make_year(session)
    fisi1 = _make_class(session, "FISI 1. LJ")

    az = Trainee(
        vorname="Adam", nachname="AzubiOhneSem",
        rolle=TraineeRolle.AZUBI,
        klasse_id=fisi1.id,
        ausbildungsbeginn=date(2025, 9, 1),
    )
    session.add(az)
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": "1"})
    assert r.status_code == 200
    assert "AzubiOhneSem" in r.text
    # AZUBI darf kein Semester-Label-Span im HTML haben (Span ist nur bei DH rendert)
    # Die CSS-Klasse .ov-semester-badge ist im Style-Block immer da – wir pruefen das Badge-Tag
    assert '<span class="ov-semester-badge"' not in r.text, (
        "AZUBI darf kein ov-semester-badge-Element haben"
    )


# ---------------------------------------------------------------------------
# beruf_und_lehrjahr Unit-Tests
# ---------------------------------------------------------------------------

def test_beruf_und_lehrjahr_fisi():
    assert beruf_und_lehrjahr("FISI 2. LJ") == ("FISI", 2)


def test_beruf_und_lehrjahr_buero():
    assert beruf_und_lehrjahr("Büro 3. LJ") == ("Büro", 3)


def test_beruf_und_lehrjahr_dhbw():
    assert beruf_und_lehrjahr("DHBW Cybersecurity") == ("DHBW Cybersecurity", None)


def test_beruf_und_lehrjahr_none():
    assert beruf_und_lehrjahr(None) == ("Ohne Klasse", None)
