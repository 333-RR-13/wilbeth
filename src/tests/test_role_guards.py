"""Tests fuer rollenbasierte Zugriffsguards (Paket A).

Rollen-Modell: admin = alles. orga = alles ausser Jahresabschluss und
endgueltigem Loeschen. ausbilder = nur lesen (+ Einsaetze bestaetigen, nicht
Teil dieses Pakets). azubi landet nie in der Planer-UI (Middleware sperrt
schon, siehe test_auth_flow.py).

Login-Muster: settings.auth_mode per monkeypatch auf "dev" umschalten, dann
POST /auth/dev-login mit rolle=ausbilder/orga/admin (siehe app/routers/auth.py).
"""
from sqlmodel import Session

from app.config import settings
from app.models import Department, Schoolyear, Trainee, TraineeRolle


def _login(client, monkeypatch, rolle: str) -> None:
    monkeypatch.setattr(settings, "auth_mode", "dev")
    r = client.post("/auth/dev-login", data={"rolle": rolle}, follow_redirects=False)
    assert r.status_code == 303


def _add_year(session: Session, sy_id: str, start_year: int) -> Schoolyear:
    y = Schoolyear(id=sy_id, start_kw=36, start_year=start_year, end_kw=35, end_year=start_year + 1)
    session.add(y)
    session.commit()
    return y


def _add_trainee(session: Session, vorname: str, nachname: str = "Test") -> Trainee:
    t = Trainee(vorname=vorname, nachname=nachname, rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.commit()
    return t


# ── Ausbilder: nur lesen ──────────────────────────────────────────────────

def test_ausbilder_post_trainees_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.post(
        "/trainees/",
        data={"vorname": "Neu", "nachname": "Azubi", "rolle": "AZUBI"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_ausbilder_post_upn_pflege_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.post("/trainees/upn-pflege", data={}, follow_redirects=False)
    assert r.status_code == 403


def test_ausbilder_post_abteilungen_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.post(
        "/abteilungen/",
        data={"code": "IT", "name": "IT-Abteilung"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_ausbilder_get_jahresabschluss_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/jahresabschluss/", follow_redirects=False)
    assert r.status_code == 403


def test_ausbilder_post_auto_plan_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.post("/auto-plan/apply", data={"schoolyear_id": "2025-2026"}, follow_redirects=False)
    assert r.status_code == 403


def test_ausbilder_get_trainees_erlaubt(client, session: Session, monkeypatch):
    """Lesen bleibt fuer Ausbilder erlaubt."""
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/trainees/")
    assert r.status_code == 200


def test_ausbilder_nav_ohne_auto_plan_import_jahresabschluss(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/trainees/")
    assert r.status_code == 200
    assert 'href="/jahresabschluss/"' not in r.text
    assert 'href="/auto-plan"' not in r.text
    assert 'href="/import"' not in r.text


# ── Orga: alles ausser Jahresabschluss + endgueltigem Loeschen ────────────

def test_orga_post_trainees_erlaubt(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "orga")
    r = client.post(
        "/trainees/",
        data={"vorname": "Orga", "nachname": "Erstellt", "rolle": "AZUBI"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_orga_get_jahresabschluss_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "orga")
    r = client.get("/jahresabschluss/", follow_redirects=False)
    assert r.status_code == 403


def test_orga_post_jahresabschluss_abschliessen_verboten(client, session: Session, monkeypatch):
    _add_year(session, "2025-2026", 2025)
    _login(client, monkeypatch, "orga")
    r = client.post(
        "/jahresabschluss/abschliessen",
        data={"schoolyear_id": "2025-2026"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_orga_post_trainee_loeschen_verboten(client, session: Session, monkeypatch):
    t = _add_trainee(session, "Loesch", "Mich")
    tid = t.id

    _login(client, monkeypatch, "orga")
    r = client.post(f"/trainees/{tid}/loeschen", follow_redirects=False)
    assert r.status_code == 403


def test_orga_delete_department_verboten(client, session: Session, monkeypatch):
    """Endgueltiges Loeschen (DELETE) bleibt Admin vorbehalten."""
    d = Department(code="ORG", name="Orga-Test-Abteilung")
    session.add(d)
    session.commit()
    did = d.id

    _login(client, monkeypatch, "orga")
    r = client.delete(f"/abteilungen/{did}")
    assert r.status_code == 403


def test_orga_nav_zeigt_auto_plan_und_import_aber_nicht_jahresabschluss(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "orga")
    r = client.get("/trainees/")
    assert r.status_code == 200
    assert 'href="/auto-plan"' in r.text
    assert 'href="/import"' in r.text
    assert 'href="/jahresabschluss/"' not in r.text


# ── Admin: alles ──────────────────────────────────────────────────────────

def test_admin_get_jahresabschluss_erlaubt(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "admin")
    r = client.get("/jahresabschluss/")
    assert r.status_code == 200


def test_admin_post_trainee_loeschen_erlaubt(client, session: Session, monkeypatch):
    t = _add_trainee(session, "AdminLoescht", "Mich")
    tid = t.id

    _login(client, monkeypatch, "admin")
    r = client.post(f"/trainees/{tid}/loeschen", follow_redirects=False)
    assert r.status_code == 303


def test_admin_delete_department_erlaubt(client, session: Session, monkeypatch):
    d = Department(code="ADM", name="Admin-Test-Abteilung")
    session.add(d)
    session.commit()
    did = d.id

    _login(client, monkeypatch, "admin")
    r = client.delete(f"/abteilungen/{did}")
    assert r.status_code == 200


def test_admin_nav_zeigt_jahresabschluss_link(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "admin")
    r = client.get("/trainees/")
    assert r.status_code == 200
    assert 'href="/jahresabschluss/"' in r.text


def test_admin_jahresabschluss_waehlt_aeltestes_jahr_vor(client, session: Session, monkeypatch):
    """GET /jahresabschluss/ ohne ?schoolyear_id waehlt das AELTESTE nicht-
    archivierte Jahr vor (chronologischer Abschluss), nicht das juengste."""
    _add_year(session, "2026-2027", 2026)  # juenger, zuerst angelegt
    _add_year(session, "2025-2026", 2025)  # aelter

    _login(client, monkeypatch, "admin")
    r = client.get("/jahresabschluss/")
    assert r.status_code == 200
    assert '<option value="2025-2026" selected>' in r.text
    assert '<option value="2026-2027" selected>' not in r.text
