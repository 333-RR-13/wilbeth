"""Tests fuer Visitenkarte, Steckbrief, Rollen-Badge und Jahresabschluss.

(1) Visitenkarte/Steckbrief: detail.html zeigt Steckbrief; Formular speichert ihn.
(2) Rollen-Badge: DH_STUDENT zeigt "DH-Student".
(3) Jahresabschluss: POST /jahresabschluss/abschliessen setzt archiviert=True;
    Vorschau zeigt korrekte Absolventen.
"""
from sqlmodel import Session, select

from app.models import (
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeClassMembership,
    TraineeRolle,
    UnterrichtsTyp,
)

SY_A = "2025-2026"
SY_B = "2026-2027"


def _add_year(session: Session, sy_id: str, start_year: int) -> Schoolyear:
    y = Schoolyear(id=sy_id, start_kw=36, start_year=start_year, end_kw=35, end_year=start_year + 1)
    session.add(y)
    session.flush()
    return y


def _add_class(session: Session, name: str) -> TraineeClass:
    c = TraineeClass(name=name, berufsschule="JD Schule", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(c)
    session.flush()
    return c


# ── (1) Steckbrief: Anzeige in der Visitenkarte ───────────────────────────────

def test_detail_zeigt_steckbrief(client, session: Session):
    """Die Detailseite zeigt den hinterlegten Steckbrief-Text."""
    _add_year(session, SY_A, 2025)
    klasse = _add_class(session, "FISI 2. LJ")
    t = Trainee(
        vorname="Sina", nachname="Steck", rolle=TraineeRolle.AZUBI,
        klasse_id=klasse.id, steckbrief="Begeistert sich fuer Cloud und Automatisierung.",
    )
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "Begeistert sich fuer Cloud und Automatisierung." in r.text
    # Visitenkarten-Fakten (neu): ausgeschriebener Beruf + Klasse, KEIN Ausbildungsjahr mehr
    assert "Ausbildungsberuf" in r.text
    assert "Fachinformatiker" in r.text and "Systemintegration" in r.text
    assert "FISI 2. LJ" in r.text  # Klasse


def test_detail_steckbrief_leer_zeigt_platzhalter(client, session: Session):
    """Ohne Steckbrief erscheint der Platzhalter, kein Crash."""
    t = Trainee(vorname="Ohne", nachname="Steck", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "Noch kein Steckbrief hinterlegt." in r.text


# ── (1) Formular speichert Steckbrief ─────────────────────────────────────────

def test_create_speichert_steckbrief(client, session: Session):
    """POST /trainees/ speichert das Steckbrief-Feld."""
    _add_class(session, "FISI 1. LJ")
    r = client.post(
        "/trainees/",
        data={
            "vorname": "Nele",
            "nachname": "Neu",
            "rolle": "AZUBI",
            "steckbrief": "Liebt Backend-Entwicklung.",
            "aktiv": "1",
            "ausbildungsbeginn": "2025-09-01",
            "beruf": "FISI",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    session.expire_all()
    t = session.exec(select(Trainee).where(Trainee.vorname == "Nele")).first()
    assert t is not None
    assert t.steckbrief == "Liebt Backend-Entwicklung."


def test_update_speichert_steckbrief(client, session: Session):
    """POST /trainees/{id} aktualisiert das Steckbrief-Feld."""
    _add_class(session, "FISI 1. LJ")
    t = Trainee(vorname="Udo", nachname="Update", rolle=TraineeRolle.AZUBI, steckbrief="alt")
    session.add(t)
    session.commit()
    tid = t.id

    r = client.post(
        f"/trainees/{tid}",
        data={
            "vorname": "Udo",
            "nachname": "Update",
            "rolle": "AZUBI",
            "steckbrief": "neuer Steckbrief-Text",
            "aktiv": "1",
            "ausbildungsbeginn": "2025-09-01",
            "beruf": "FISI",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    session.expire_all()
    t2 = session.get(Trainee, tid)
    assert t2.steckbrief == "neuer Steckbrief-Text"


# ── (2) Rollen-Badge ──────────────────────────────────────────────────────────

def test_badge_dh_student(client, session: Session):
    """DH_STUDENT zeigt das Badge 'DH-Student' in der Visitenkarte."""
    t = Trainee(vorname="Dana", nachname="Dual", rolle=TraineeRolle.DH_STUDENT)
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "DH-Student" in r.text
    assert "badge-orange" in r.text


def test_badge_azubi(client, session: Session):
    """AZUBI zeigt das Badge 'Azubi' (badge-blue) in der Visitenkarte."""
    t = Trainee(vorname="Aron", nachname="Azubi", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert ">Azubi<" in r.text
    assert "badge-blue" in r.text


# ── (3) Jahresabschluss ───────────────────────────────────────────────────────

def test_jahresabschluss_setzt_archiviert(client, session: Session):
    """POST /jahresabschluss/abschliessen setzt Schoolyear.archiviert = True."""
    year = _add_year(session, SY_A, 2025)
    assert year.archiviert is False
    session.commit()

    r = client.post(
        "/jahresabschluss/abschliessen",
        data={"schoolyear_id": SY_A},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/jahresabschluss/" in r.headers["location"]

    session.expire_all()
    updated = session.get(Schoolyear, SY_A)
    assert updated is not None
    assert updated.archiviert is True, "Schoolyear.archiviert muss True sein nach Abschluss"


def test_jahresabschluss_nicht_archivierbares_jahr_liefert_fehler(client, session: Session):
    """POST /jahresabschluss/abschliessen mit unbekanntem Jahr -> Redirect mit Fehlermeldung."""
    r = client.post(
        "/jahresabschluss/abschliessen",
        data={"schoolyear_id": "9999-9999"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error" in r.headers["location"]


def test_jahresabschluss_formular_zeigt_nur_nicht_archivierte(client, session: Session):
    """GET /jahresabschluss/ zeigt nur nicht-archivierte Jahre in der Auswahl."""
    aktiv = _add_year(session, SY_A, 2025)
    archiv = _add_year(session, SY_B, 2026)
    archiv.archiviert = True
    session.add(archiv)
    session.commit()

    r = client.get("/jahresabschluss/")
    assert r.status_code == 200
    assert SY_A in r.text
    assert SY_B not in r.text


def test_jahresabschluss_vorschau_absolventen(client, session: Session):
    """Die Absolventen-Vorschau listet Azubis ohne Nachfolge-Klasse."""
    from app.routers.jahreswechsel import _absolventen_vorschau

    _add_year(session, SY_A, 2025)
    # FISI 3. LJ -> Abschluss (kein next)
    fisi3 = _add_class(session, "FISI 3. LJ")
    # FISI 1. LJ -> hat Nachfolger FISI 2. LJ, aber den legen wir nicht an -> kein next
    fisi1 = _add_class(session, "FISI 1. LJ")
    # Lege FISI 2. LJ an, damit fisi1 eine Nachfolge hat
    fisi2 = _add_class(session, "FISI 2. LJ")

    azubi_abschluss = Trainee(
        vorname="Abel", nachname="Abschluss", rolle=TraineeRolle.AZUBI,
        klasse_id=fisi3.id, aktiv=True,
    )
    session.add(azubi_abschluss)
    azubi_weiter = Trainee(
        vorname="Willi", nachname="Weiter", rolle=TraineeRolle.AZUBI,
        klasse_id=fisi1.id, aktiv=True,
    )
    session.add(azubi_weiter)
    session.flush()
    session.add(TraineeClassMembership(
        trainee_id=azubi_abschluss.id, schoolyear_id=SY_A, klasse_id=fisi3.id
    ))
    session.add(TraineeClassMembership(
        trainee_id=azubi_weiter.id, schoolyear_id=SY_A, klasse_id=fisi1.id
    ))
    session.commit()

    absolventen = _absolventen_vorschau(session, SY_A)
    ids = {row["trainee"].id for row in absolventen}
    assert azubi_abschluss.id in ids, "Azubi im 3. LJ muss als Absolvent erscheinen"
    assert azubi_weiter.id not in ids, "Azubi im 1. LJ darf nicht als Absolvent erscheinen"


def test_jahresabschluss_vorschau_dh_student_nicht_in_absolventen(client, session: Session):
    """DH_STUDENT ohne Nachfolge-Klasse erscheint NICHT in der Absolventen-Vorschau."""
    from app.routers.jahreswechsel import _absolventen_vorschau

    _add_year(session, SY_A, 2025)
    dh_klasse = _add_class(session, "DHBW Cybersecurity")
    student = Trainee(
        vorname="Paul", nachname="Preview", rolle=TraineeRolle.DH_STUDENT,
        klasse_id=dh_klasse.id, aktiv=True,
    )
    session.add(student)
    session.flush()
    session.add(TraineeClassMembership(
        trainee_id=student.id, schoolyear_id=SY_A, klasse_id=dh_klasse.id
    ))
    session.commit()

    absolventen = _absolventen_vorschau(session, SY_A)
    ids = {row["trainee"].id for row in absolventen}
    assert student.id not in ids, "DH_STUDENT darf nicht in der Absolventen-Vorschau erscheinen"
