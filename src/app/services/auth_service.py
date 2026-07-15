"""Auth-Basisbausteine: Rollenherleitung aus OIDC-Gruppen + Session-Handling.

resolve_role() bildet OIDC-Gruppen-IDs (aus dem ID-Token/Claims) auf eine
Wilbeth-Rolle ab. Staff-Rollen (admin/orga/ausbilder) kommen ausschliesslich
ueber Gruppenmitgliedschaft; Azubis werden stattdessen ueber ihre UPN auf
einen aktiven Trainee-Datensatz gematcht (case-insensitive, whitespace-tolerant).

login_session()/user_from_session()/clear_session() kapseln die
Session-Ablage (Starlette SessionMiddleware) defensiv: fehlt die Middleware
oder ist der Session-Inhalt kaputt/veraltet, wird None zurueckgegeben statt
eine Exception hochzureichen.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func
from sqlmodel import Session, select

from app.config import settings
from app.models.trainee import Trainee

SESSION_KEY = "wilbeth_user"

_STAFF_ROLES = {"admin", "orga", "ausbilder"}


@dataclass
class CurrentUser:
    upn: str
    name: str
    rolle: str
    trainee_id: int | None = None

    @property
    def is_staff(self) -> bool:
        return self.rolle in _STAFF_ROLES


def resolve_role(db: Session, groups: list[str], upn: str, name: str) -> CurrentUser | None:
    """Leitet die Wilbeth-Rolle eines eingeloggten SSO-Users her.

    Reihenfolge: admin vor orga vor ausbilder (Gruppenzugehoerigkeit ueber
    settings.oidc_group_*, nur wenn die jeweilige Settings-Gruppe nicht leer
    ist). Ohne Staff-Gruppentreffer wird per UPN nach einem aktiven Trainee
    gesucht. Kein Treffer -> None.
    """
    if settings.oidc_group_admin and settings.oidc_group_admin in groups:
        return CurrentUser(upn=upn, name=name, rolle="admin")
    if settings.oidc_group_orga and settings.oidc_group_orga in groups:
        return CurrentUser(upn=upn, name=name, rolle="orga")
    if settings.oidc_group_ausbilder and settings.oidc_group_ausbilder in groups:
        return CurrentUser(upn=upn, name=name, rolle="ausbilder")

    normalized_upn = upn.strip().lower()
    trainee = db.exec(
        select(Trainee).where(
            Trainee.upn.is_not(None),
            func.lower(Trainee.upn) == normalized_upn,
            Trainee.aktiv == True,  # noqa: E712
        )
    ).first()
    if trainee is not None:
        return CurrentUser(upn=upn, name=name, rolle="azubi", trainee_id=trainee.id)

    return None


def login_session(request, user: CurrentUser) -> None:
    request.session[SESSION_KEY] = {
        "upn": user.upn,
        "name": user.name,
        "rolle": user.rolle,
        "trainee_id": user.trainee_id,
    }


def user_from_session(request) -> CurrentUser | None:
    try:
        data = request.session.get(SESSION_KEY)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    try:
        upn = data["upn"]
        name = data["name"]
        rolle = data["rolle"]
    except KeyError:
        return None

    return CurrentUser(upn=upn, name=name, rolle=rolle, trainee_id=data.get("trainee_id"))


def clear_session(request) -> None:
    try:
        request.session.pop(SESSION_KEY, None)
    except Exception:
        pass


def ensure_share_token(db: Session, trainee_id: int) -> str | None:
    """Stellt sicher, dass der Trainee einen share_token hat; gibt ihn zurueck.

    Existiert der Trainee nicht -> None. Ist share_token bereits gesetzt,
    bleibt er unveraendert (kein Rotieren).
    """
    trainee = db.get(Trainee, trainee_id)
    if trainee is None:
        return None

    if not trainee.share_token:
        trainee.share_token = str(uuid.uuid4())
        db.add(trainee)
        db.commit()

    return trainee.share_token
