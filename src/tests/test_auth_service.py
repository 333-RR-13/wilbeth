"""Tests fuer app.services.auth_service: resolve_role(), ensure_share_token(),
require_roles() und allowed_dept_ids()."""

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.config import settings
from app.models import Department, Trainee, TraineeRolle
from app.services.auth_service import (
    CurrentUser,
    allowed_dept_ids,
    ensure_share_token,
    require_roles,
    resolve_role,
)


def _reset_groups(monkeypatch):
    """Alle OIDC-Gruppen-Settings explizit leeren (definierter Ausgangszustand)."""
    monkeypatch.setattr(settings, "oidc_group_admin", "")
    monkeypatch.setattr(settings, "oidc_group_orga", "")
    monkeypatch.setattr(settings, "oidc_group_ausbilder", "")


# ── Staff-Rollen ueber Gruppenzugehoerigkeit ────────────────────────────────

def test_resolve_role_admin_wins_over_ausbilder(session: Session, monkeypatch):
    _reset_groups(monkeypatch)
    monkeypatch.setattr(settings, "oidc_group_admin", "gid-admin")
    monkeypatch.setattr(settings, "oidc_group_ausbilder", "gid-ausbilder")

    user = resolve_role(session, ["gid-ausbilder", "gid-admin"], "user@firma.de", "User Name")

    assert user is not None
    assert user.rolle == "admin"
    assert user.trainee_id is None
    assert user.is_staff is True


def test_resolve_role_ausbilder(session: Session, monkeypatch):
    _reset_groups(monkeypatch)
    monkeypatch.setattr(settings, "oidc_group_ausbilder", "gid-ausbilder")

    user = resolve_role(session, ["gid-ausbilder"], "trainer@firma.de", "Trainer Name")

    assert user is not None
    assert user.rolle == "ausbilder"
    assert user.is_staff is True


def test_resolve_role_orga(session: Session, monkeypatch):
    _reset_groups(monkeypatch)
    monkeypatch.setattr(settings, "oidc_group_orga", "gid-orga")

    user = resolve_role(session, ["gid-orga"], "orga@firma.de", "Orga Name")

    assert user is not None
    assert user.rolle == "orga"
    assert user.is_staff is True


def test_resolve_role_empty_settings_groups_never_match(session: Session, monkeypatch):
    """Leere Settings-Gruppen matchen nie, selbst wenn die Claim-Gruppen zufaellig
    einen leeren String enthalten."""
    _reset_groups(monkeypatch)

    user = resolve_role(session, ["", "admin", "orga", "ausbilder"], "unknown@firma.de", "Unknown")

    assert user is None


# ── Azubi-Rolle ueber UPN-Match ─────────────────────────────────────────────

def test_resolve_role_azubi_case_insensitive_whitespace(session: Session, monkeypatch):
    _reset_groups(monkeypatch)
    trainee = Trainee(
        vorname="Anna", nachname="Azubi", rolle=TraineeRolle.AZUBI,
        aktiv=True, upn="anna.azubi@firma.de",
    )
    session.add(trainee)
    session.commit()

    user = resolve_role(session, [], "  ANNA.AZUBI@FIRMA.DE  ", "Anna Azubi")

    assert user is not None
    assert user.rolle == "azubi"
    assert user.trainee_id == trainee.id
    assert user.is_staff is False


def test_resolve_role_inactive_trainee_no_match(session: Session, monkeypatch):
    _reset_groups(monkeypatch)
    trainee = Trainee(
        vorname="Bob", nachname="Inaktiv", rolle=TraineeRolle.AZUBI,
        aktiv=False, upn="bob@firma.de",
    )
    session.add(trainee)
    session.commit()

    user = resolve_role(session, [], "bob@firma.de", "Bob Inaktiv")

    assert user is None


def test_resolve_role_unknown_returns_none(session: Session, monkeypatch):
    _reset_groups(monkeypatch)

    user = resolve_role(session, [], "nirgendwo@firma.de", "Niemand")

    assert user is None


# ── ensure_share_token ───────────────────────────────────────────────────────

def test_ensure_share_token_creates_new(session: Session):
    trainee = Trainee(vorname="Clara", nachname="Test", rolle=TraineeRolle.AZUBI)
    session.add(trainee)
    session.commit()
    assert trainee.share_token is None

    token = ensure_share_token(session, trainee.id)

    assert token
    session.expire_all()
    assert session.get(Trainee, trainee.id).share_token == token


def test_ensure_share_token_keeps_existing(session: Session):
    trainee = Trainee(
        vorname="Dora", nachname="Test", rolle=TraineeRolle.AZUBI,
        share_token="existing-token-123",
    )
    session.add(trainee)
    session.commit()

    token = ensure_share_token(session, trainee.id)

    assert token == "existing-token-123"


# ── require_roles ────────────────────────────────────────────────────────────

class _FakeState:
    """Leerer Platzhalter fuer request.state (kein current_user-Attribut)."""


class _FakeRequest:
    """Minimaler Request-Stand-in: nur request.state.current_user wird genutzt."""

    def __init__(self, current_user=None):
        self.state = _FakeState()
        if current_user is not None:
            self.state.current_user = current_user


def test_require_roles_allowed_role_passes():
    user = CurrentUser(upn="orga@firma.de", name="Orga", rolle="orga")
    dep = require_roles("orga", "admin")

    result = dep(_FakeRequest(current_user=user))

    assert result is user


def test_require_roles_foreign_role_raises_403():
    user = CurrentUser(upn="azubi@firma.de", name="Azubi", rolle="azubi")
    dep = require_roles("orga", "admin")

    with pytest.raises(HTTPException) as exc_info:
        dep(_FakeRequest(current_user=user))

    assert exc_info.value.status_code == 403


def test_require_roles_missing_current_user_raises_403():
    dep = require_roles("orga", "admin")

    with pytest.raises(HTTPException) as exc_info:
        dep(_FakeRequest())

    assert exc_info.value.status_code == 403


# ── allowed_dept_ids ─────────────────────────────────────────────────────────

def test_allowed_dept_ids_matches_case_insensitive_across_separators(session: Session):
    dept_comma = Department(
        code="D1", name="Dept Comma",
        verantwortliche="Anna.Azubi@Firma.de, other@firma.de",
    )
    dept_semicolon_newline = Department(
        code="D2", name="Dept Semi/Newline",
        verantwortliche="foo@firma.de;ANNA.AZUBI@FIRMA.DE\nbar@firma.de",
    )
    dept_no_match = Department(
        code="D3", name="Dept No Match",
        verantwortliche="jemand-anders@firma.de",
    )
    session.add_all([dept_comma, dept_semicolon_newline, dept_no_match])
    session.commit()

    user = CurrentUser(upn="  ANNA.AZUBI@FIRMA.DE  ", name="Anna", rolle="ausbilder")

    result = allowed_dept_ids(session, user)

    assert result == {dept_comma.id, dept_semicolon_newline.id}


def test_allowed_dept_ids_empty_field_never_matches(session: Session):
    dept_empty = Department(code="D4", name="Dept Empty", verantwortliche="")
    session.add(dept_empty)
    session.commit()

    user = CurrentUser(upn="anna.azubi@firma.de", name="Anna", rolle="ausbilder")

    result = allowed_dept_ids(session, user)

    assert result == set()
