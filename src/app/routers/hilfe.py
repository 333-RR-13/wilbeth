"""Hilfe-Seite ("How to Wilbeth"): rollenspezifische Kurzanleitung fuer Staff.

WICHTIG (Azubis): Diese Route liegt bewusst NICHT in PUBLIC_PREFIXES (app.main)
und ist damit Staff-only (admin/orga/ausbilder via require_roles). Azubi-
Sessions werden von der Auth-Middleware ohnehin auf /mein-plan/{token}
umgeleitet, bevor sie hier ankommen koennten. Die share-Sidebar
(templates/share/_base.html) bekommt deshalb bewusst KEINEN eigenen
"Hilfe"-Link -- die Azubi-Seiten gelten als selbsterklaerend, ein
ausfuehrliches Tutorial fuer Azubis liegt stattdessen in Confluence.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Annotated

from app.services.auth_service import CurrentUser, require_roles

router = APIRouter(prefix="/hilfe", tags=["hilfe"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")


@router.get("/", response_class=HTMLResponse)
def hilfe_index(
    request: Request,
    user: Annotated[CurrentUser, Depends(require_roles("ausbilder", "orga", "admin"))],
):
    return templates.TemplateResponse(request, "hilfe/index.html", {
        "user": user,
        "active_nav": "hilfe",
    })
