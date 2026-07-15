"""Tests fuer app.services.auth_service: resolve_role() + ensure_share_token()."""

from sqlmodel import Session

from app.config import settings
from app.models import Trainee, TraineeRolle
from app.services.auth_service import ensure_share_token, resolve_role


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
