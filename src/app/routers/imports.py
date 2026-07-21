"""Import-Router: Vorschau + Uebernehmen fuer Schulplan-Wochen und Einsaetze.

Endpunkte:
  GET  /import                              -> Einstiegsseite Einsatz-Import (Sidebar)

  GET  /imports/schulplan/{plan_id}/dialog  -> Einfuege-/Upload-Formular als HTMX-Partial
  POST /imports/schulplan/{plan_id}/preview -> parst + validiert, rendert Vorschau
  POST /imports/schulplan/{plan_id}/apply   -> schreibt gueltige Wochen in die DB

  GET  /imports/einsaetze/dialog            -> Einfuege-/Upload-Formular als HTMX-Partial
  POST /imports/einsaetze/preview           -> parst + validiert, rendert Vorschau
  POST /imports/einsaetze/apply             -> schreibt gueltige Einsaetze in die DB
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import SchoolPlan, Schoolyear
from app.services.auth_service import CurrentUser, require_roles
from app.services.importer import (
    apply_assignments,
    apply_school_weeks,
    parse_assignments_auto,
    parse_school_weeks,
)

router = APIRouter(prefix="/imports", tags=["imports"])
# Separater Router ohne Prefix fuer die /import-Einstiegsseite
import_page_router = APIRouter(tags=["imports"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


# ── Import-Einstiegsseite ─────────────────────────────────────────────────────

@import_page_router.get("/import", response_class=HTMLResponse)
def import_index(
    request: Request,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """Einstiegsseite für den Einsatz-Import (eigener Sidebar-Reiter)."""
    schoolyear_id = request.query_params.get("schoolyear_id", "")
    return templates.TemplateResponse(request, "imports/index.html", {
        "schoolyear_id": schoolyear_id,
        "active_nav": "import",
    })


# ── Hilfs-Funktion: Text aus textarea ODER UploadFile ────────────────────────

async def _read_text(
    raw_text: str | None,
    csv_file: UploadFile | None,
) -> str:
    """Gibt den Import-Text zurueck.

    Prioritaet: hochgeladene Datei > eingefuegter Text.
    """
    if csv_file and csv_file.filename:
        raw_bytes = await csv_file.read()
        # UTF-8 mit BOM-Toleranz, Fallback auf latin-1
        try:
            return raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            return raw_bytes.decode("latin-1", errors="replace")
    return raw_text or ""


# ── Schulplan-Import ──────────────────────────────────────────────────────────

@router.get("/schulplan/{plan_id}/dialog", response_class=HTMLResponse)
def schulplan_import_dialog(
    request: Request, plan_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    plan = db.get(SchoolPlan, plan_id)
    return templates.TemplateResponse(request, "imports/_dialog.html", {
        "mode": "schulplan",
        "plan_id": plan_id,
        "plan": plan,
    })


@router.post("/schulplan/{plan_id}/preview", response_class=HTMLResponse)
async def schulplan_import_preview(
    request: Request,
    plan_id: int,
    db: DB,
    raw_text: Annotated[str | None, Form()] = None,
    csv_file: UploadFile | None = None,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    text = await _read_text(raw_text, csv_file)
    parse_result = parse_school_weeks(text)
    plan = db.get(SchoolPlan, plan_id)
    return templates.TemplateResponse(request, "imports/_preview.html", {
        "mode": "schulplan",
        "plan_id": plan_id,
        "plan": plan,
        "valid": parse_result.valid,
        "errors": parse_result.errors,
        "raw_text": text,
    })


@router.post("/schulplan/{plan_id}/apply", response_class=RedirectResponse)
async def schulplan_import_apply(
    request: Request,
    plan_id: int,
    db: DB,
    raw_text: Annotated[str | None, Form()] = None,
    csv_file: UploadFile | None = None,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    text = await _read_text(raw_text, csv_file)
    parse_result = parse_school_weeks(text)
    written, skipped = apply_school_weeks(db, plan_id, parse_result.valid)

    n = len(written)
    s = len(skipped)
    parts = []
    if n:
        parts.append(f"{n} Woche{'n' if n != 1 else ''} importiert")
    if s:
        parts.append(f"{s} uebersprungen")
    msg = ", ".join(parts) if parts else "Keine neuen Wochen"

    return RedirectResponse(f"/schulplaene/{plan_id}?msg={msg}", status_code=303)


# ── Einsatz-Import ────────────────────────────────────────────────────────────

@router.get("/einsaetze/dialog", response_class=HTMLResponse)
def einsaetze_import_dialog(
    request: Request,
    db: DB,
    schoolyear_id: str = "",
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    if not schoolyear_id and years:
        schoolyear_id = years[0].id
    schoolyear = db.get(Schoolyear, schoolyear_id) if schoolyear_id else None
    default_start_kw = schoolyear.start_kw if schoolyear else None
    return templates.TemplateResponse(request, "imports/_dialog.html", {
        "mode": "einsaetze",
        "schoolyear_id": schoolyear_id,
        "default_start_kw": default_start_kw,
        "years": years,
    })


@router.post("/einsaetze/preview", response_class=HTMLResponse)
async def einsaetze_import_preview(
    request: Request,
    db: DB,
    schoolyear_id: Annotated[str, Form()],
    raw_text: Annotated[str | None, Form()] = None,
    csv_file: UploadFile | None = None,
    start_kw: Annotated[str | None, Form()] = None,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    text = await _read_text(raw_text, csv_file)
    parsed_start_kw: int | None = None
    if start_kw and start_kw.strip().isdigit():
        parsed_start_kw = int(start_kw.strip())
    parse_result = parse_assignments_auto(text, db, schoolyear_id, start_kw=parsed_start_kw)
    return templates.TemplateResponse(request, "imports/_preview.html", {
        "mode": "einsaetze",
        "schoolyear_id": schoolyear_id,
        "valid": parse_result.valid,
        "errors": parse_result.errors,
        "raw_text": text,
    })


@router.post("/einsaetze/apply", response_class=RedirectResponse)
async def einsaetze_import_apply(
    request: Request,
    db: DB,
    schoolyear_id: Annotated[str, Form()],
    raw_text: Annotated[str | None, Form()] = None,
    csv_file: UploadFile | None = None,
    start_kw: Annotated[str | None, Form()] = None,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    text = await _read_text(raw_text, csv_file)
    parsed_start_kw: int | None = None
    if start_kw and start_kw.strip().isdigit():
        parsed_start_kw = int(start_kw.strip())
    parse_result = parse_assignments_auto(text, db, schoolyear_id, start_kw=parsed_start_kw)
    written, skipped = apply_assignments(db, schoolyear_id, parse_result.valid)

    n = len(written)
    s = len(skipped)
    parts = []
    if n:
        parts.append(f"{n} Einsatz{'e' if n != 1 else ''} importiert")
    if s:
        parts.append(f"{s} uebersprungen")
    msg = ", ".join(parts) if parts else "Keine neuen Einsaetze"

    return RedirectResponse(f"/overview?schoolyear_id={schoolyear_id}&msg={msg}", status_code=303)
