"""Tests fuer den Azubi-Self-Service unter /mein-plan/{token}."""
from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    SchoolPlan,
    SchoolPlanWeek,
    SchoolWeekTyp,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    TraineeWish,
    UnterrichtsTyp,
)

SY = "2025-2026"
TOKEN = "test-token-1234"


def _setup(session: Session, with_class: bool = False) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    cp = Department(code="CP", name="Cloud Platform")
    ba = Department(code="BA", name="Business Applications", erlaubt_mehrfachbelegung=True)
    session.add_all([cp, ba])
    klasse_id = None
    if with_class:
        klasse = TraineeClass(name="FISI 2. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
        session.add(klasse)
        session.flush()
        klasse_id = klasse.id
        plan = SchoolPlan(klasse_id=klasse_id, schoolyear_id=SY)
        session.add(plan)
        session.flush()
        session.add(SchoolPlanWeek(plan_id=plan.id, kw=41, jahr=2025, typ=SchoolWeekTyp.BERUFSSCHULE))

    t = Trainee(vorname="Anton", nachname="Altmann", rolle=TraineeRolle.AZUBI,
                klasse_id=klasse_id, share_token=TOKEN)
    session.add(t)
    session.flush()
    session.commit()
    return {"trainee": t.id, "cp": cp.id, "ba": ba.id}


# ── Zugriff / Token ──────────────────────────────────────────────

def test_my_plan_valid_token(client, session):
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}")
    assert r.status_code == 200
    assert "Anton" in r.text
    assert "Meine Einsätze" in r.text


def test_my_plan_invalid_token(client, session):
    _setup(session)
    r = client.get("/mein-plan/gibt-es-nicht")
    assert r.status_code == 404


def test_my_plan_sidebar_links(client, session):
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}")
    assert r.status_code == 200
    # Linke Bar verlinkt alle Bereiche + Über Wilbeth
    for href in [
        f"/mein-plan/{TOKEN}/klasse",
        f"/mein-plan/{TOKEN}/urlaub",
        f"/mein-plan/{TOKEN}/wuensche",
        "/ueber-wilbeth",
    ]:
        assert href in r.text
    # Einzeilen-Matrix mit KW-Headern
    assert "th-kw-num" in r.text


def test_urlaub_page_renders(client, session):
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/urlaub")
    assert r.status_code == 200
    assert "Urlaub" in r.text


def test_wuensche_page_renders(client, session):
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/wuensche")
    assert r.status_code == 200
    assert "Wünsche" in r.text or "Priorität" in r.text


# ── Urlaub eintragen ─────────────────────────────────────────────

def test_urlaub_create(client, session):
    ids = _setup(session)
    r = client.post(f"/mein-plan/{TOKEN}/urlaub", data={"kw": 50, "jahr": 2025}, follow_redirects=False)
    assert r.status_code == 303

    a = session.exec(select(Assignment).where(Assignment.trainee_id == ids["trainee"])).first()
    assert a is not None
    assert a.typ == AssignmentTyp.URLAUB
    assert a.source == AssignmentSource.SELBST
    assert (a.kw, a.jahr) == (50, 2025)


def test_urlaub_range(client, session):
    ids = _setup(session)
    client.post(f"/mein-plan/{TOKEN}/urlaub",
                data={"kw": 50, "jahr": 2025, "kw_end": 1, "jahr_end": 2026},
                follow_redirects=False)
    rows = session.exec(select(Assignment).where(Assignment.trainee_id == ids["trainee"])).all()
    # KW50, 51, 52 (2025) + KW1 (2026) = 4 Wochen
    assert len(rows) == 4
    assert all(a.typ == AssignmentTyp.URLAUB for a in rows)


def test_urlaub_skips_school_week(client, session):
    ids = _setup(session, with_class=True)
    # KW41/2025 ist Schulwoche -> wird uebersprungen
    client.post(f"/mein-plan/{TOKEN}/urlaub", data={"kw": 41, "jahr": 2025}, follow_redirects=False)
    rows = session.exec(select(Assignment).where(Assignment.trainee_id == ids["trainee"])).all()
    assert len(rows) == 0


def test_urlaub_delete_own(client, session):
    ids = _setup(session)
    client.post(f"/mein-plan/{TOKEN}/urlaub", data={"kw": 50, "jahr": 2025}, follow_redirects=False)
    a = session.exec(select(Assignment).where(Assignment.trainee_id == ids["trainee"])).first()
    aid = a.id

    client.post(f"/mein-plan/{TOKEN}/urlaub/loeschen", data={"assignment_id": aid}, follow_redirects=False)
    assert session.get(Assignment, aid) is None


def test_urlaub_delete_only_self_entered(client, session):
    ids = _setup(session)
    # Von der Planerin gesetzter Urlaub (source=MANUAL) darf NICHT vom Azubi geloescht werden
    a = Assignment(trainee_id=ids["trainee"], schoolyear_id=SY, kw=50, jahr=2025,
                   typ=AssignmentTyp.URLAUB, source=AssignmentSource.MANUAL)
    session.add(a)
    session.commit()
    aid = a.id

    client.post(f"/mein-plan/{TOKEN}/urlaub/loeschen", data={"assignment_id": aid}, follow_redirects=False)
    assert session.get(Assignment, aid) is not None  # bleibt erhalten


# ── Wünsche ──────────────────────────────────────────────────────

def test_save_wishes(client, session):
    ids = _setup(session)
    r = client.post(f"/mein-plan/{TOKEN}/wuensche", data={
        f"prio_{ids['cp']}": "1",
        f"prio_{ids['ba']}": "3",
        "wunsch_notiz": "CP vor der Zwischenprüfung",
    }, follow_redirects=False)
    assert r.status_code == 303

    wishes = session.exec(select(TraineeWish).where(TraineeWish.trainee_id == ids["trainee"])).all()
    prios = {w.department_id: w.prioritaet for w in wishes}
    assert prios == {ids["cp"]: 1, ids["ba"]: 3}

    t = session.get(Trainee, ids["trainee"])
    assert "Zwischenprüfung" in t.wunsch_notiz


def test_save_wishes_replaces(client, session):
    ids = _setup(session)
    client.post(f"/mein-plan/{TOKEN}/wuensche", data={f"prio_{ids['cp']}": "1"}, follow_redirects=False)
    # Zweiter Speichervorgang ersetzt die alten Wuensche
    client.post(f"/mein-plan/{TOKEN}/wuensche", data={f"prio_{ids['ba']}": "2"}, follow_redirects=False)
    wishes = session.exec(select(TraineeWish).where(TraineeWish.trainee_id == ids["trainee"])).all()
    assert len(wishes) == 1
    assert wishes[0].department_id == ids["ba"]


# ── ICS-Export ───────────────────────────────────────────────────

def test_ics_export(client, session):
    ids = _setup(session)
    session.add(Assignment(trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
                           source=AssignmentSource.MANUAL))
    session.commit()

    r = client.get(f"/mein-plan/{TOKEN}/calendar.ics")
    assert r.status_code == 200
    assert "text/calendar" in r.headers["content-type"]
    body = r.text
    assert "BEGIN:VCALENDAR" in body
    assert "BEGIN:VEVENT" in body
    assert "CP" in body
    assert "DTSTART;VALUE=DATE:" in body


# ── Token-Rotation über Admin ────────────────────────────────────

def test_token_rotation_invalidates_old(client, session):
    ids = _setup(session)
    assert client.get(f"/mein-plan/{TOKEN}").status_code == 200

    # Admin erzeugt neuen Token
    client.post(f"/trainees/{ids['trainee']}/share-token", follow_redirects=False)
    session.expire_all()
    new_token = session.get(Trainee, ids["trainee"]).share_token
    assert new_token != TOKEN

    assert client.get(f"/mein-plan/{TOKEN}").status_code == 404      # alter Link tot
    assert client.get(f"/mein-plan/{new_token}").status_code == 200  # neuer Link lebt


def test_token_revoke(client, session):
    ids = _setup(session)
    client.post(f"/trainees/{ids['trainee']}/share-token/deaktivieren", follow_redirects=False)
    session.expire_all()
    assert session.get(Trainee, ids["trainee"]).share_token is None
    assert client.get(f"/mein-plan/{TOKEN}").status_code == 404
