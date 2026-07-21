"""Tests fuer /meine-abteilung/ (Ausbilder-Selbstbedienung: Bloecke bestaetigen
+ Einsatz vorschlagen) sowie den differenzierten Login-Redirect fuer Ausbilder.

Dev-Login setzt fuer Staff-Rollen upn="dev@local" (siehe app/routers/auth.py).
allowed_dept_ids() matcht Department.verantwortliche gegen die UPN.
"""
from sqlmodel import Session, select

from app.config import settings
from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    EinsatzVorschlag,
    Schoolyear,
    Trainee,
    TraineeRolle,
)

SY = "2025-2026"
DEV_UPN = "dev@local"


def _dev_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "dev")


def _login(client, rolle: str, trainee_id: str = ""):
    data = {"rolle": rolle}
    if trainee_id:
        data["trainee_id"] = trainee_id
    r = client.post("/auth/dev-login", data=data, follow_redirects=False)
    assert r.status_code == 303
    return r


def _setup(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    own_dept = Department(code="CP", name="Cloud Platform", verantwortliche=DEV_UPN)
    foreign_dept = Department(code="NW", name="Netzwerk", verantwortliche="jemand-anders@firma.de")
    session.add_all([own_dept, foreign_dept])
    session.flush()
    t = Trainee(vorname="Jonas", nachname="Jäger", rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.flush()
    session.commit()
    return {"trainee": t.id, "own": own_dept.id, "foreign": foreign_dept.id}


def _make_assignment(session: Session, trainee_id: int, dept_id: int, kw: int, jahr: int = 2025) -> Assignment:
    a = Assignment(
        trainee_id=trainee_id, schoolyear_id=SY, kw=kw, jahr=jahr,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept_id, source=AssignmentSource.MANUAL,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


# ── (a) Ausbilder mit verantworteter Abteilung sieht Bloecke ────────────────

def test_ausbilder_sees_blocks_of_own_department(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _make_assignment(session, ids["trainee"], ids["own"], 40)
    _make_assignment(session, ids["trainee"], ids["own"], 41)

    _login(client, "ausbilder")

    r = client.get(f"/meine-abteilung/?schoolyear_id={SY}")
    assert r.status_code == 200
    assert "CP" in r.text
    assert "Cloud Platform" in r.text
    assert "Jäger" in r.text
    assert "KW 40/2025" in r.text
    assert "KW 41/2025" in r.text


# ── (b) POST /block bestaetigt alle Zellen des Blocks ───────────────────────

def test_post_block_bestaetigt_all_cells(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    a1 = _make_assignment(session, ids["trainee"], ids["own"], 40)
    a2 = _make_assignment(session, ids["trainee"], ids["own"], 41)

    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/block", data={
        "assignment_ids": f"{a1.id},{a2.id}",
        "aktion": "bestaetigt",
        "notiz": "Passt",
        "feedback": "",
        "schoolyear_id": SY,
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    updated1 = session.get(Assignment, a1.id)
    updated2 = session.get(Assignment, a2.id)
    assert updated1.bestaetigung == "bestaetigt"
    assert updated2.bestaetigung == "bestaetigt"
    assert updated1.notiz == "Passt"


# ── (c) fremde Abteilung -> 403 ──────────────────────────────────────────────

def test_post_block_foreign_department_forbidden(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    a = _make_assignment(session, ids["trainee"], ids["foreign"], 40)

    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/block", data={
        "assignment_ids": str(a.id),
        "aktion": "bestaetigt",
        "notiz": "",
        "feedback": "",
        "schoolyear_id": SY,
    })
    assert r.status_code == 403

    session.expire_all()
    unchanged = session.get(Assignment, a.id)
    assert unchanged.bestaetigung == "offen"


# ── (d) ohne Zuordnung -> Hinweis ────────────────────────────────────────────

def test_ausbilder_without_department_sees_hint(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    session.add(Department(code="NW", name="Netzwerk", verantwortliche="jemand-anders@firma.de"))
    session.commit()

    _login(client, "ausbilder")

    r = client.get("/meine-abteilung/")
    assert r.status_code == 200
    assert "keine Abteilung zugeordnet" in r.text
    assert DEV_UPN in r.text


# ── (e) POST /vorschlag legt Vorschlag an ────────────────────────────────────

def test_post_vorschlag_creates_einsatz_vorschlag(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)

    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/vorschlag", data={
        "trainee_id": ids["trainee"],
        "department_id": ids["own"],
        "schoolyear_id": SY,
        "kw_von": 10,
        "jahr_von": 2026,
        "kw_bis": 12,
        "jahr_bis": 2026,
        "kommentar": "Bitte einplanen",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/meine-abteilung/?msg=created")

    rows = session.exec(select(EinsatzVorschlag)).all()
    assert len(rows) == 1
    v = rows[0]
    assert v.trainee_id == ids["trainee"]
    assert v.department_id == ids["own"]
    assert v.status == "offen"
    assert v.eingereicht_von_upn == DEV_UPN
    assert v.kommentar == "Bitte einplanen"


def test_post_vorschlag_foreign_department_forbidden(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)

    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/vorschlag", data={
        "trainee_id": ids["trainee"],
        "department_id": ids["foreign"],
        "schoolyear_id": SY,
        "kw_von": 10,
        "jahr_von": 2026,
        "kw_bis": 12,
        "jahr_bis": 2026,
        "kommentar": "",
    })
    assert r.status_code == 403
    assert session.exec(select(EinsatzVorschlag)).first() is None


# ── (f) azubi-Rolle kommt nicht auf die Seite ────────────────────────────────

def test_azubi_cannot_reach_meine_abteilung(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    t = Trainee(vorname="Anna", nachname="Azubi", rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.commit()
    session.refresh(t)

    _login(client, "azubi", trainee_id=str(t.id))

    r = client.get("/meine-abteilung/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/mein-plan/")


# ── (g) Login-Redirect: dev-login ausbilder -> /meine-abteilung/ ────────────

def test_dev_login_ausbilder_redirects_to_meine_abteilung(client, monkeypatch):
    _dev_mode(monkeypatch)

    r = client.post("/auth/dev-login", data={"rolle": "ausbilder"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/meine-abteilung/"
