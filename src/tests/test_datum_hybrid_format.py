"""Tests fuer TEIL 3: Datumsfelder im Hybrid-Format TT.MM.JJJJ.

Deckt ab: Trainee-Anlage/-Bearbeitung (ausbildungsbeginn), Staff-Abwesenheiten
(von_datum/bis_datum), Azubi-Abwesenheit (von/bis) und Feedback (besprochen_am)
akzeptieren jetzt BEIDE Formate ueber den gemeinsamen Parser
app.utils.datum.parse_datum. Die bestehenden ISO-Regressionstests in
test_trainee_anlage.py, test_abwesenheiten.py, test_abwesenheit_share.py und
test_feedback.py bleiben UNVERAENDERT (sie posten weiterhin JJJJ-MM-TT) --
das wird hier durch den vollen Testlauf dieser Dateien zusaetzlich
abgesichert.

Ausserdem: die vier betroffenen Templates rendern jetzt das Hybrid-Makro
(templates/_partials/datum_feld.html) statt eines nativen
<input type="date">.
"""
from datetime import date

from sqlmodel import Session, select

from app.models import (
    Abwesenheit,
    AbwesenheitQuelle,
    AbwesenheitTyp,
    FeedbackBogen,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)

SY = "2025-2026"


def _add_class(session: Session, name: str) -> TraineeClass:
    c = TraineeClass(name=name, berufsschule="JD Schule", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(c)
    session.commit()
    return c


def _make_trainee(session: Session, vorname="Jonas", nachname="Jaeger") -> int:
    t = Trainee(vorname=vorname, nachname=nachname, rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.commit()
    session.refresh(t)
    return t.id


# ── Trainee-Anlage: deutsches Format, NICHT MM/DD verwechselt ──────────────

def test_trainee_anlage_mit_deutschem_datum_speichert_1_september(client, session: Session):
    """Der urspruengliche Datenfehler: 01.09.2024 wurde ueber ein englisches
    input[type=date] als 9. Januar gespeichert. Ueber das neue Textfeld ist
    TT.MM.JJJJ eindeutig -- date(2024, 9, 1), NICHT date(2024, 1, 9)."""
    _add_class(session, "FISI 1. LJ")

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Text", "nachname": "Feld", "rolle": "AZUBI",
            "beruf": "FISI", "ausbildungsbeginn": "01.09.2024",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" not in r.headers["location"]

    t = session.exec(select(Trainee).where(Trainee.nachname == "Feld")).first()
    assert t is not None
    assert t.ausbildungsbeginn == date(2024, 9, 1)
    assert t.ausbildungsbeginn != date(2024, 1, 9)


def test_trainee_anlage_mit_ungueltigem_datum_bleibt_error_redirect(client, session: Session):
    """Bestehendes Verhalten (Error-Redirect statt 400, s. _parse_ausbildungsbeginn
    in app/routers/trainees.py) bleibt unveraendert -- nur das Format-Spektrum
    wurde erweitert."""
    _add_class(session, "FISI 1. LJ")

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Kaputt", "nachname": "Datum", "rolle": "AZUBI",
            "beruf": "FISI", "ausbildungsbeginn": "32.13.2024",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" in r.headers["location"]
    assert session.exec(select(Trainee).where(Trainee.nachname == "Datum")).first() is None


def test_trainee_formular_rendert_hybrid_datumsfeld(client, session: Session):
    r = client.get("/trainees/neu")
    assert r.status_code == 200
    assert 'name="ausbildungsbeginn"' in r.text
    assert 'data-datum-feld-text' in r.text
    assert 'placeholder="TT.MM.JJJJ"' in r.text
    assert 'maxlength="10"' in r.text
    assert 'data-datum-feld-btn' in r.text
    # Kein natives Datumsfeld mit diesem name mehr im sichtbaren Markup
    assert 'type="date" id="ausbildungsbeginn"' not in r.text


# ── Staff-Abwesenheiten: deutsches Format ───────────────────────────────────

def test_staff_abwesenheit_anlegen_mit_deutschem_datum(client, session: Session):
    t_id = _make_trainee(session)

    r = client.post("/abwesenheiten/", data={
        "trainee_id": t_id,
        "von_datum": "02.03.2026",
        "bis_datum": "04.03.2026",
        "typ": "URLAUB",
        "kommentar": "Deutsches Format",
    }, follow_redirects=False)
    assert r.status_code == 303

    rows = session.exec(select(Abwesenheit).where(Abwesenheit.trainee_id == t_id)).all()
    assert len(rows) == 1
    assert rows[0].von_datum == date(2026, 3, 2)
    assert rows[0].bis_datum == date(2026, 3, 4)


def test_staff_abwesenheit_ungueltiges_deutsches_datum_gibt_400(client, session: Session):
    t_id = _make_trainee(session)

    r = client.post("/abwesenheiten/", data={
        "trainee_id": t_id,
        "von_datum": "32.01.2026",
        "bis_datum": "04.03.2026",
        "typ": "URLAUB",
        "kommentar": "",
    })
    assert r.status_code == 400
    assert session.exec(select(Abwesenheit)).first() is None


def test_abwesenheiten_formular_rendert_hybrid_datumsfelder(client, session: Session):
    r = client.get("/abwesenheiten/neu")
    assert r.status_code == 200
    assert 'name="von_datum"' in r.text
    assert 'name="bis_datum"' in r.text
    assert r.text.count('data-datum-feld-text') == 2


# ── Azubi-Abwesenheit (/mein-plan): deutsches Format ────────────────────────

def test_azubi_abwesenheit_mit_deutschem_datum(client, session: Session):
    if session.get(Schoolyear, SY) is None:
        session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    token = "test-token-hybrid-datum"
    t = Trainee(vorname="Anke", nachname="Azubi", rolle=TraineeRolle.AZUBI, share_token=token)
    session.add(t)
    session.commit()
    session.refresh(t)

    r = client.post(f"/mein-plan/{token}/abwesenheit",
                     data={"von": "01.09.2025", "bis": "03.09.2025", "typ": "URLAUB"},
                     follow_redirects=False)
    assert r.status_code == 303

    rows = session.exec(select(Abwesenheit).where(Abwesenheit.trainee_id == t.id)).all()
    assert len(rows) == 1
    assert rows[0].von_datum == date(2025, 9, 1)
    assert rows[0].bis_datum == date(2025, 9, 3)


def test_azubi_abwesenheit_ungueltiges_deutsches_datum_gibt_400(client, session: Session):
    token = "test-token-hybrid-datum-400"
    t = Trainee(vorname="Bo", nachname="Broken", rolle=TraineeRolle.AZUBI, share_token=token)
    session.add(t)
    session.commit()

    r = client.post(f"/mein-plan/{token}/abwesenheit",
                     data={"von": "31.02.2026", "bis": "03.03.2026"},
                     follow_redirects=False)
    assert r.status_code == 400


def test_azubi_abwesenheit_seite_rendert_hybrid_datumsfelder(client, session: Session):
    token = "test-token-hybrid-datum-form"
    t = Trainee(vorname="Cara", nachname="Card", rolle=TraineeRolle.AZUBI, share_token=token)
    session.add(t)
    session.commit()

    r = client.get(f"/mein-plan/{token}/abwesenheit")
    assert r.status_code == 200
    assert 'name="von"' in r.text
    assert 'name="bis"' in r.text
    assert r.text.count('data-datum-feld-text') == 2


# ── Feedback: besprochen_am akzeptiert deutsches Format ─────────────────────

def test_feedback_besprochen_am_deutsches_format(client, session: Session):
    if session.get(Schoolyear, SY) is None:
        session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    from app.models import Department
    dept = Department(code="CP", name="Cloud Platform")
    session.add(dept)
    session.flush()
    t = Trainee(vorname="Feli", nachname="Feedback", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()

    bogen = FeedbackBogen(
        typ="AZUBI", trainee_id=t.id, department_id=dept.id, schoolyear_id=SY,
        kw_von=10, jahr_von=2026, kw_bis=12, jahr_bis=2026,
        status="abgeschlossen", erstellt_am=date.today(),
    )
    session.add(bogen)
    session.commit()
    session.refresh(bogen)

    r = client.post(f"/feedback/{bogen.id}/besprochen",
                     data={"besprochen_am": "10.03.2026"}, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    updated = session.get(FeedbackBogen, bogen.id)
    assert updated.besprochen_am == date(2026, 3, 10)


def test_feedback_detail_rendert_hybrid_datumsfeld(client, session: Session):
    if session.get(Schoolyear, SY) is None:
        session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    from app.models import Department
    dept = Department(code="CP2", name="Cloud Platform 2")
    session.add(dept)
    session.flush()
    t = Trainee(vorname="Gero", nachname="Grafik", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()
    bogen = FeedbackBogen(
        typ="AZUBI", trainee_id=t.id, department_id=dept.id, schoolyear_id=SY,
        kw_von=10, jahr_von=2026, kw_bis=12, jahr_bis=2026,
        status="abgeschlossen", erstellt_am=date.today(),
    )
    session.add(bogen)
    session.commit()
    session.refresh(bogen)

    r = client.get(f"/feedback/{bogen.id}")
    assert r.status_code == 200
    assert 'name="besprochen_am"' in r.text
    assert 'data-datum-feld-text' in r.text
