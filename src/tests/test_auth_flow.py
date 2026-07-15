"""Tests fuer den Login-/Guard-Flow: Dev-Login, Auth-Middleware, Logout.

auth_mode wird pro Test zur Laufzeit via monkeypatch auf dem settings-Objekt
umgeschaltet (die Guard-Middleware liest settings.auth_mode bei jedem Request
neu, siehe app/main.py). Die Test-Suite laeuft ansonsten mit auth_mode "off"
(siehe tests/conftest.py: AUTH_MODE=off als Default), das deckt Test (g) ab.
"""
from sqlmodel import Session

from app.config import settings
from app.models import Trainee, TraineeRolle


def _dev_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "dev")


def _make_trainee(session: Session) -> Trainee:
    t = Trainee(vorname="Anna", nachname="Azubi", rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


# ── (a) dev-Modus: ohne Login gesperrt ──────────────────────────────────────

def test_overview_without_login_redirects_to_auth_login(client, monkeypatch):
    _dev_mode(monkeypatch)

    r = client.get("/overview", follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/auth/login"


# ── (b) /auth/login zeigt Dev-Login ──────────────────────────────────────────

def test_auth_login_shows_dev_login_form(client, monkeypatch):
    _dev_mode(monkeypatch)

    r = client.get("/auth/login")

    assert r.status_code == 200
    assert "Dev-Login" in r.text


# ── (c) Dev-Login als Admin ──────────────────────────────────────────────────

def test_dev_login_admin_then_overview_reachable(client, monkeypatch):
    _dev_mode(monkeypatch)

    r = client.post("/auth/dev-login", data={"rolle": "admin"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/overview"

    r2 = client.get("/overview")
    assert r2.status_code == 200


# ── (d) Dev-Login als Azubi ───────────────────────────────────────────────────

def test_dev_login_azubi_redirects_to_own_plan_and_locks_overview(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    trainee = _make_trainee(session)

    r = client.post(
        "/auth/dev-login",
        data={"rolle": "azubi", "trainee_id": str(trainee.id)},
        follow_redirects=False,
    )
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("/mein-plan/")
    token = location.removeprefix("/mein-plan/")
    assert token

    # Azubi darf nicht in den Staff-Bereich
    r_overview = client.get("/overview", follow_redirects=False)
    assert r_overview.status_code == 303
    assert r_overview.headers["location"] == f"/mein-plan/{token}"

    # Eigener Plan bleibt erreichbar
    r_plan = client.get(f"/mein-plan/{token}")
    assert r_plan.status_code == 200


# ── (e) /health und /static ohne Login erreichbar ────────────────────────────

def test_health_and_static_reachable_without_login(client, monkeypatch):
    _dev_mode(monkeypatch)

    r_health = client.get("/health")
    assert r_health.status_code == 200

    r_static = client.get("/static/style.css")
    assert r_static.status_code == 200


# ── (f) Capability-Link /mein-plan/{token} ohne Login erreichbar ────────────

def test_mein_plan_token_reachable_without_login(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    trainee = _make_trainee(session)
    trainee.share_token = "capability-token-xyz"
    session.add(trainee)
    session.commit()

    r = client.get(f"/mein-plan/{trainee.share_token}")

    assert r.status_code == 200


# ── (g) auth_mode off (Default der Suite): synthetischer Admin ─────────────

def test_overview_reachable_without_login_when_auth_off(client):
    # Kein monkeypatch noetig: conftest setzt AUTH_MODE=off als Suite-Default.
    assert settings.auth_mode == "off"

    r = client.get("/overview")

    assert r.status_code == 200


# ── (h) Logout loescht Session ───────────────────────────────────────────────

def test_logout_clears_session_and_locks_overview_again(client, monkeypatch):
    _dev_mode(monkeypatch)

    r = client.post("/auth/dev-login", data={"rolle": "admin"}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/overview").status_code == 200

    r_logout = client.get("/auth/logout", follow_redirects=False)
    assert r_logout.status_code == 303
    assert r_logout.headers["location"] == "/auth/login"

    r_after = client.get("/overview", follow_redirects=False)
    assert r_after.status_code == 303
    assert r_after.headers["location"] == "/auth/login"
