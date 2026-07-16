"""Login/Logout: OIDC (Entra) im Prod-Betrieb, simulierter Dev-Login lokal.

- GET  /auth/login     -> je nach auth_mode: Dev-Rollenwahl ODER Redirect zum IdP.
- GET  /auth/callback  -> OIDC-Rueckkehr vom IdP, Rollenherleitung, Session-Login.
- POST /auth/dev-login -> nur im Dev-Modus: direkter Login ohne echten IdP.
- GET  /auth/logout    -> Session loeschen, zurueck zum Login.

Der Entra-OIDC-Client wird lazy registriert (erst beim ersten echten Bedarf),
damit dev/off-Betrieb ohne gueltige OIDC-Einstellungen (Client-ID etc.)
funktioniert -- eager Registrierung wuerde bereits beim Modulimport gegen
die (im Dev leeren) Discovery-URL fehlschlagen.
"""
from pathlib import Path
from typing import Annotated

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import settings
from app.database import get_session
from app.models import Trainee
from app.services.auth_service import (
    SESSION_KEY,
    CurrentUser,
    clear_session,
    ensure_share_token,
    login_session,
    resolve_role,
)

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]

_ROLLEN_OHNE_TRAINEE = {"admin", "orga", "ausbilder"}

oauth = OAuth()
_oidc_registered = False


def _get_oidc_client():
    """Registriert den Entra-Client beim ersten Aufruf (lazy) und gibt ihn zurueck."""
    global _oidc_registered
    if not _oidc_registered:
        oauth.register(
            name="entra",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=settings.oidc_discovery_url,
            client_kwargs={"scope": "openid profile email"},
        )
        _oidc_registered = True
    return oauth.entra


# ── Login ────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login(request: Request, db: DB):
    if settings.auth_mode == "dev":
        trainees = db.exec(
            select(Trainee)
            .where(Trainee.aktiv == True)  # noqa: E712
            .order_by(Trainee.nachname, Trainee.vorname)
        ).all()
        return templates.TemplateResponse(request, "auth/dev_login.html", {"trainees": trainees})

    if settings.auth_mode == "oidc":
        client = _get_oidc_client()
        return await client.authorize_redirect(request, settings.oidc_redirect_uri)

    # auth_mode "off": Middleware laesst ohnehin alles durch, dieser Pfad
    # sollte praktisch nie erreicht werden -- einfach zur Startseite zurueck.
    return RedirectResponse("/", status_code=303)


# ── OIDC-Callback ────────────────────────────────────────────────────────────

@router.get("/callback")
async def callback(request: Request, db: DB):
    client = _get_oidc_client()
    token = await client.authorize_access_token(request)

    claims = token.get("userinfo") or {}
    if not claims and isinstance(token.get("id_token"), dict):
        claims = token["id_token"]

    upn = claims.get("preferred_username") or claims.get("upn") or claims.get("email") or ""
    name = claims.get("name", "")
    groups = claims.get("groups", []) or []

    user = resolve_role(db, groups, upn, name)
    if user is None:
        # Diagnose fuer "Kein Zugriff": im Pod-Log (kubectl logs) UND auf der
        # 403-Seite sichtbar. Haeufigste Ursachen: groups-Claim fehlt in der
        # Token-Konfiguration der App-Registration, oder die Objekt-IDs im
        # Token matchen nicht die OIDC_GROUP_*-Umgebungsvariablen.
        print(f"[auth] Zugriff verweigert: upn={upn!r} groups={groups!r}", flush=True)
        return templates.TemplateResponse(
            request,
            "auth/denied.html",
            {"upn": upn, "groups": groups, "groups_overage": "_claim_names" in claims},
            status_code=403,
        )

    login_session(request, user)

    if user.rolle == "azubi":
        token_str = ensure_share_token(db, user.trainee_id)
        request.session[SESSION_KEY]["share_token"] = token_str
        return RedirectResponse(f"/mein-plan/{token_str}", status_code=303)

    return RedirectResponse("/overview", status_code=303)


# ── Dev-Login (nur auth_mode == "dev") ───────────────────────────────────────

@router.post("/dev-login")
def dev_login(
    request: Request,
    db: DB,
    rolle: Annotated[str, Form()],
    trainee_id: Annotated[str, Form()] = "",
):
    if settings.auth_mode != "dev":
        raise HTTPException(status_code=404)

    if rolle == "azubi":
        if not trainee_id:
            raise HTTPException(status_code=400, detail="Trainee erforderlich fuer Azubi-Login")
        trainee = db.get(Trainee, int(trainee_id))
        if trainee is None:
            raise HTTPException(status_code=404, detail="Trainee nicht gefunden")

        user = CurrentUser(upn="dev@local", name="Dev azubi", rolle="azubi", trainee_id=trainee.id)
        login_session(request, user)
        token_str = ensure_share_token(db, trainee.id)
        request.session[SESSION_KEY]["share_token"] = token_str
        return RedirectResponse(f"/mein-plan/{token_str}", status_code=303)

    if rolle not in _ROLLEN_OHNE_TRAINEE:
        raise HTTPException(status_code=400, detail="Unbekannte Rolle")

    user = CurrentUser(upn="dev@local", name=f"Dev {rolle}", rolle=rolle)
    login_session(request, user)
    return RedirectResponse("/overview", status_code=303)


# ── Logout ───────────────────────────────────────────────────────────────────

@router.get("/logout")
def logout(request: Request):
    clear_session(request)
    return RedirectResponse("/auth/login", status_code=303)
