"""Tests fuer die Hilfe-Seite ("How to Wilbeth", Paket HILFE + NAV).

/hilfe ist Staff-only (admin/orga/ausbilder via require_roles) und liegt
NICHT in PUBLIC_PREFIXES -- Azubis werden von der Auth-Middleware ohnehin
vor Erreichen der Route auf /mein-plan/{token} umgeleitet (separat in
test_auth_flow.py abgedeckt).

Login-Muster: settings.auth_mode per monkeypatch auf "dev" umschalten, dann
POST /auth/dev-login mit rolle=ausbilder/orga/admin.
"""
from sqlmodel import Session

from app.config import settings
from app.models import Trainee, TraineeRolle


def _login(client, monkeypatch, rolle: str) -> None:
    monkeypatch.setattr(settings, "auth_mode", "dev")
    r = client.post("/auth/dev-login", data={"rolle": rolle}, follow_redirects=False)
    assert r.status_code == 303


def test_ausbilder_sieht_meine_abteilung_nicht_jahresabschluss(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/hilfe/")
    assert r.status_code == 200
    assert 'id="meine-abteilung"' in r.text
    assert 'id="jahresabschluss"' not in r.text
    assert 'id="datensicherung"' not in r.text
    assert 'id="stammdaten"' not in r.text


def test_orga_sieht_stammdaten_nicht_jahresabschluss(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "orga")
    r = client.get("/hilfe/")
    assert r.status_code == 200
    assert 'id="stammdaten"' in r.text
    assert 'id="trainee-anlegen"' in r.text
    assert 'id="planen"' in r.text
    assert 'id="jahresabschluss"' not in r.text
    assert 'id="datensicherung"' not in r.text


def test_admin_sieht_jahresabschluss_und_datensicherung(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "admin")
    r = client.get("/hilfe/")
    assert r.status_code == 200
    assert 'id="jahresabschluss"' in r.text
    assert 'id="datensicherung"' in r.text
    assert 'id="stammdaten"' in r.text
    assert 'id="meine-abteilung"' in r.text


def test_azubi_kommt_nicht_auf_hilfe(client, session: Session, monkeypatch):
    """Azubi-Sessions werden schon von der Auth-Middleware auf /mein-plan
    umgeleitet, bevor /hilfe ueberhaupt erreicht wird (kein Staff-only-403,
    /hilfe steht bewusst nicht in PUBLIC_PREFIXES)."""
    trainee = Trainee(vorname="Azubi", nachname="Test", rolle=TraineeRolle.AZUBI)
    session.add(trainee)
    session.commit()

    monkeypatch.setattr(settings, "auth_mode", "dev")
    r = client.post(
        "/auth/dev-login",
        data={"rolle": "azubi", "trainee_id": str(trainee.id)},
        follow_redirects=False,
    )
    assert r.status_code == 303
    token = r.headers["location"].removeprefix("/mein-plan/")

    r2 = client.get("/hilfe/", follow_redirects=False)
    assert r2.status_code == 303
    assert r2.headers["location"] == f"/mein-plan/{token}"


# ── Nav ────────────────────────────────────────────────────────────────

def test_nav_zeigt_how_to_wilbeth_fuer_alle_staff(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/trainees/")
    assert r.status_code == 200
    assert "How to Wilbeth" in r.text
    assert 'href="/hilfe/"' in r.text


def test_nav_zeigt_datensicherung_fuer_admin(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "admin")
    r = client.get("/trainees/")
    assert r.status_code == 200
    assert "Datensicherung" in r.text
    assert 'href="/daten/"' in r.text


def test_nav_zeigt_kein_datensicherung_fuer_ausbilder(client, session: Session, monkeypatch):
    """/daten/ ist admin-only, nur der Linktext wurde von 'Export / Import'
    auf 'Datensicherung' umbenannt -- fuer Ausbilder bleibt der Link ganz weg."""
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/trainees/")
    assert r.status_code == 200
    assert "Datensicherung" not in r.text
    assert 'href="/daten/"' not in r.text
