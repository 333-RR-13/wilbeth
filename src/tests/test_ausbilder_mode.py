"""Tests fuer Paket B: Einsaetze-Guards + Ausbilder-Modus + Feedback.

Ausbilder darf im Matrix-Zellendialog NUR bestehende ABTEILUNG-Einsaetze der
eigenen (verantworteten) Abteilung(en) bestaetigen/mit Notiz/Feedback versehen
(kein Neuanlegen, kein Typ-/Abteilungs-/KW-Wechsel). Alle Voll-Schreib-Routen
(create/update/delete Einsatz, /copy, /copy-block) sind orga/admin
vorbehalten; /bulk-delete ist admin-only.

Dev-Login setzt fuer Staff-Rollen upn="dev@local" (siehe app/routers/auth.py).
"""
from sqlmodel import Session, select

from app.config import settings
from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    Schoolyear,
    Trainee,
    TraineeRolle,
)

SY = "2025-2026"
DEV_UPN = "dev@local"


def _dev_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "dev")


def _login(client, rolle: str):
    r = client.post("/auth/dev-login", data={"rolle": rolle}, follow_redirects=False)
    assert r.status_code == 303
    return r


def _setup(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    own_dept = Department(code="CP", name="Cloud Platform", verantwortliche=DEV_UPN)
    foreign_dept = Department(code="NW", name="Netzwerk", verantwortliche="jemand-anders@firma.de")
    session.add_all([own_dept, foreign_dept])
    session.flush()
    t = Trainee(vorname="Jonas", nachname="Jäger", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.flush()
    session.commit()
    return {"trainee": t.id, "own": own_dept.id, "foreign": foreign_dept.id}


def _make_assignment(session: Session, trainee_id: int, dept_id: int | None, kw: int = 40,
                      jahr: int = 2025, typ: AssignmentTyp = AssignmentTyp.ABTEILUNG) -> Assignment:
    a = Assignment(trainee_id=trainee_id, schoolyear_id=SY, kw=kw, jahr=jahr,
                   typ=typ, abteilung_id=dept_id, source=AssignmentSource.MANUAL)
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


# ── (a) Ausbilder + eigene Abteilung: bestaetigung/notiz/feedback erlaubt ────

def test_ausbilder_own_dept_cell_save_sets_confirm_notiz_feedback(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    a = _make_assignment(session, ids["trainee"], ids["own"])

    _login(client, "ausbilder")

    r = client.post("/einsaetze/cell-save", data={
        "trainee_id": ids["trainee"], "schoolyear_id": SY, "kw": 40, "jahr": 2025,
        # Versuchter Typ-/Abteilungswechsel muss ignoriert werden:
        "typ": "URLAUB", "abteilung_id": "",
        "bestaetigung": "bestaetigt", "notiz": "Läuft gut", "feedback": "Sehr engagiert",
    })
    assert r.status_code == 200

    session.expire_all()
    updated = session.get(Assignment, a.id)
    assert updated.typ == AssignmentTyp.ABTEILUNG          # unveraendert
    assert updated.abteilung_id == ids["own"]               # unveraendert
    assert updated.bestaetigung == "bestaetigt"
    assert updated.notiz == "Läuft gut"
    assert updated.feedback == "Sehr engagiert"


def test_ausbilder_cannot_create_new_assignment_via_cell_save(client, session, monkeypatch):
    """Kein existierendes Assignment -> 403 (kein Neuanlegen fuer Ausbilder)."""
    _dev_mode(monkeypatch)
    ids = _setup(session)

    _login(client, "ausbilder")

    r = client.post("/einsaetze/cell-save", data={
        "trainee_id": ids["trainee"], "schoolyear_id": SY, "kw": 41, "jahr": 2025,
        "typ": "ABTEILUNG", "abteilung_id": ids["own"],
        "bestaetigung": "bestaetigt", "notiz": "", "feedback": "",
    })
    assert r.status_code == 403

    row = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["trainee"], Assignment.kw == 41)
    ).first()
    assert row is None


# ── (b) Ausbilder + fremde Abteilung: 403 ────────────────────────────────────

def test_ausbilder_foreign_dept_cell_save_forbidden(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    a = _make_assignment(session, ids["trainee"], ids["foreign"])

    _login(client, "ausbilder")

    r = client.post("/einsaetze/cell-save", data={
        "trainee_id": ids["trainee"], "schoolyear_id": SY, "kw": 40, "jahr": 2025,
        "typ": "ABTEILUNG", "abteilung_id": ids["foreign"],
        "bestaetigung": "bestaetigt", "notiz": "", "feedback": "",
    })
    assert r.status_code == 403

    session.expire_all()
    unchanged = session.get(Assignment, a.id)
    assert unchanged.bestaetigung == "offen"


# ── (c) Ausbilder: Voll-Schreib-Endpunkte gesperrt ───────────────────────────

def test_ausbilder_create_assignment_forbidden(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _login(client, "ausbilder")

    r = client.post("/einsaetze/", data={
        "trainee_id": ids["trainee"], "schoolyear_id": SY, "kw": 45, "jahr": 2025,
        "typ": "ABTEILUNG", "abteilung_id": ids["own"],
    })
    assert r.status_code == 403


def test_ausbilder_copy_forbidden(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _make_assignment(session, ids["trainee"], ids["own"])
    _login(client, "ausbilder")

    r = client.post("/einsaetze/copy", data={
        "src_trainee_id": ids["trainee"], "src_kw": 40, "src_jahr": 2025,
        "dst_trainee_id": ids["trainee"], "dst_kw": 41, "dst_jahr": 2025,
        "schoolyear_id": SY,
    })
    assert r.status_code == 403


def test_ausbilder_bulk_delete_forbidden(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    a = _make_assignment(session, ids["trainee"], ids["own"])
    _login(client, "ausbilder")

    r = client.post("/einsaetze/bulk-delete", data={"ids": [a.id]})
    assert r.status_code == 403
    assert session.get(Assignment, a.id) is not None


# ── (d) Orga: cell-save mit feedback persistiert; bulk-delete 403 ───────────

def test_orga_cell_save_persists_feedback(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    a = _make_assignment(session, ids["trainee"], ids["own"])
    _login(client, "orga")

    r = client.post("/einsaetze/cell-save", data={
        "trainee_id": ids["trainee"], "schoolyear_id": SY, "kw": 40, "jahr": 2025,
        "typ": "ABTEILUNG", "abteilung_id": ids["own"],
        "notiz": "", "bestaetigung": "bestaetigt", "feedback": "Top Einsatz",
    })
    assert r.status_code == 200

    session.expire_all()
    updated = session.get(Assignment, a.id)
    assert updated.feedback == "Top Einsatz"


def test_orga_bulk_delete_forbidden(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    a = _make_assignment(session, ids["trainee"], ids["own"])
    _login(client, "orga")

    r = client.post("/einsaetze/bulk-delete", data={"ids": [a.id]})
    assert r.status_code == 403
    assert session.get(Assignment, a.id) is not None


# ── (e) Admin: bulk-delete erlaubt ────────────────────────────────────────────

def test_admin_bulk_delete_allowed(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    a = _make_assignment(session, ids["trainee"], ids["own"])
    _login(client, "admin")

    r = client.post("/einsaetze/bulk-delete", data={"ids": [a.id]}, follow_redirects=False)
    assert r.status_code == 303
    assert session.get(Assignment, a.id) is None


# ── (f) cell-edit-Dialog als Ausbilder: bestaetigung+feedback editierbar, ────
#        aber kein Abteilung-Select als editierbares Feld ───────────────────

def test_ausbilder_cell_edit_dialog_has_confirm_and_feedback_no_dept_select(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _make_assignment(session, ids["trainee"], ids["own"])
    _login(client, "ausbilder")

    r = client.get("/einsaetze/cell-edit", params={
        "trainee_id": ids["trainee"], "kw": 40, "jahr": 2025, "schoolyear_id": SY,
    })
    assert r.status_code == 200
    assert 'name="bestaetigung"' in r.text
    assert 'name="feedback"' in r.text
    # Abteilung darf nicht als editierbares Select-Feld erscheinen, nur als
    # verstecktes Feld (Wert wird vom Server ohnehin ignoriert).
    assert '<select id="cell-abt"' not in r.text
    assert 'type="hidden" name="abteilung_id"' in r.text


def test_ausbilder_cell_edit_dialog_foreign_dept_is_readonly(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _make_assignment(session, ids["trainee"], ids["foreign"])
    _login(client, "ausbilder")

    r = client.get("/einsaetze/cell-edit", params={
        "trainee_id": ids["trainee"], "kw": 40, "jahr": 2025, "schoolyear_id": SY,
    })
    assert r.status_code == 200
    assert "Nur die verantwortlichen Ausbilder dieser Abteilung können bestätigen" in r.text
    assert 'name="bestaetigung"' not in r.text


def test_ausbilder_cell_delete_forbidden(client, session, monkeypatch):
    """cell-delete ist orga/admin vorbehalten — auch per Direkt-POST (nicht nur UI-versteckt)."""
    _dev_mode(monkeypatch)
    ids = _setup(session)
    a = _make_assignment(session, ids["trainee"], ids["own"])
    _login(client, "ausbilder")

    r = client.post("/einsaetze/cell-delete", data={
        "assignment_id": a.id, "trainee_id": ids["trainee"],
        "schoolyear_id": SY, "kw": 40, "jahr": 2025,
    })
    assert r.status_code == 403

    session.expire_all()
    assert session.get(Assignment, a.id) is not None, "Einsatz darf nicht geloescht sein"
