"""Datenexport/-import: Admin-Werkzeug zum vollstaendigen Sichern/Ersetzen aller Daten.

GET  /daten/        -> Erklaerseite mit Export-Button + Import-Formular
GET  /daten/export  -> ZIP-Download (eine CSV je Tabelle)
POST /daten/import  -> ersetzt ALLE Tabellen durch den Inhalt des hochgeladenen
                       ZIP (nur mit gesetzter Bestaetigungs-Checkbox)

Nur fuer admin (require_roles("admin")) - siehe app/services/auth_service.py.
Die eigentliche Export-/Import-Logik liegt in app/services/datenexport.py.
"""

import urllib.parse
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session

from app.database import get_session
from app.services.auth_service import CurrentUser, require_roles
from app.services.datenexport import export_zip, import_zip

router = APIRouter(prefix="/daten", tags=["daten"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


@router.get("/", response_class=HTMLResponse)
def daten_index(
    request: Request,
    user: CurrentUser = Depends(require_roles("admin")),
):
    return templates.TemplateResponse(request, "datenexport/index.html", {
        "active_nav": "daten",
    })


@router.get("/export")
def daten_export(
    db: DB,
    user: CurrentUser = Depends(require_roles("admin")),
):
    payload = export_zip(db)
    dateiname = f"wilbeth-export-{date.today().isoformat()}.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{dateiname}"'},
    )


@router.post("/import", response_class=RedirectResponse)
async def daten_import(
    db: DB,
    bestaetigt: Annotated[str, Form()] = "",
    zip_datei: UploadFile | None = None,
    user: CurrentUser = Depends(require_roles("admin")),
):
    if not bestaetigt:
        detail = urllib.parse.quote("Bestaetigung fehlt - Import abgebrochen")
        return RedirectResponse(f"/daten/?msg=error&detail={detail}", status_code=303)

    if zip_datei is None or not zip_datei.filename:
        detail = urllib.parse.quote("Keine ZIP-Datei ausgewaehlt")
        return RedirectResponse(f"/daten/?msg=error&detail={detail}", status_code=303)

    raw = await zip_datei.read()
    try:
        counts = import_zip(db, raw)
    except Exception as exc:
        detail = urllib.parse.quote(str(exc)[:200])
        return RedirectResponse(f"/daten/?msg=error&detail={detail}", status_code=303)

    summary = ", ".join(f"{name}: {n}" for name, n in counts.items())
    detail = urllib.parse.quote(summary)
    return RedirectResponse(f"/daten/?msg=created&detail={detail}", status_code=303)
