"""Tests fuer Visitenkarte, Steckbrief, Rollen-Badge und Jahreswechsel-Fix
fuer Studierende (DH_STUDENT).

(1) Visitenkarte/Steckbrief: detail.html zeigt Steckbrief; Formular speichert ihn.
(2) Rollen-Badge: DH_STUDENT zeigt "DH-Student".
(3) Jahreswechsel: ein DH_STUDENT (Klasse ohne next_class) bleibt nach
    uebernehmen aktiv=True; ein AZUBI im Abschlussjahr wird weiterhin archiviert.
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
    r = client.post(
        "/trainees/",
        data={
            "vorname": "Nele",
            "nachname": "Neu",
            "rolle": "AZUBI",
            "steckbrief": "Liebt Backend-Entwicklung.",
            "aktiv": "1",
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


# ── (3) Jahreswechsel-Fix fuer Studierende ────────────────────────────────────

def test_jahreswechsel_dh_student_bleibt_aktiv(client, session: Session):
    """Ein DH_STUDENT in einer Klasse OHNE next_class wird beim Jahreswechsel
    NICHT archiviert (bleibt aktiv=True). Ein AZUBI im Abschlussjahr wird
    weiterhin archiviert."""
    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

    # DHBW-Klasse ohne LJ-Muster und ohne next_class_id -> kein next
    dh_klasse = _add_class(session, "DHBW Cybersecurity")
    # FISI 3. LJ -> Abschluss (kein next)
    fisi3 = _add_class(session, "FISI 3. LJ")

    student = Trainee(
        vorname="Sara", nachname="Student", rolle=TraineeRolle.DH_STUDENT,
        klasse_id=dh_klasse.id, aktiv=True,
    )
    session.add(student)
    session.flush()
    session.add(TraineeClassMembership(
        trainee_id=student.id, schoolyear_id=SY_A, klasse_id=dh_klasse.id
    ))

    azubi = Trainee(
        vorname="Abel", nachname="Abschluss", rolle=TraineeRolle.AZUBI,
        klasse_id=fisi3.id, aktiv=True,
    )
    session.add(azubi)
    session.flush()
    session.add(TraineeClassMembership(
        trainee_id=azubi.id, schoolyear_id=SY_A, klasse_id=fisi3.id
    ))
    session.commit()

    r = client.post(
        "/jahreswechsel/uebernehmen",
        data={"source_year_id": SY_A, "target_year_id": SY_B},
        follow_redirects=False,
    )
    assert r.status_code == 303
    session.expire_all()

    # DH_STUDENT bleibt aktiv (nicht archiviert)
    s = session.get(Trainee, student.id)
    assert s.aktiv is True, "DH_STUDENT darf beim Jahreswechsel nicht archiviert werden"

    # AZUBI im Abschlussjahr wird archiviert
    a = session.get(Trainee, azubi.id)
    assert a.aktiv is False, "AZUBI im Abschlussjahr muss weiterhin archiviert werden"


def test_jahreswechsel_preview_dh_student_nicht_abschluss(client, session: Session):
    """Die Vorschau listet einen DH_STUDENT ohne next_class NICHT als Abschluss."""
    _add_year(session, SY_A, 2025)
    _add_year(session, SY_B, 2026)

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

    from app.routers.jahreswechsel import _build_preview
    _transfer, abschluss = _build_preview(session, SY_A, SY_B)
    abschluss_ids = {row["trainee"].id for row in abschluss}
    assert student.id not in abschluss_ids, \
        "DH_STUDENT darf nicht in der Abschluss-Vorschau erscheinen"
