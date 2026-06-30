from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import SchoolHoliday, Schoolyear
from app.services.importer import apply_holidays, parse_holidays

router = APIRouter(prefix="/schulferien", tags=["schulferien"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


@router.get("/", response_class=HTMLResponse)
def list_holidays(request: Request, db: DB):
    holidays = db.exec(
        select(SchoolHoliday).order_by(SchoolHoliday.start_year, SchoolHoliday.start_kw)
    ).all()
    years = db.exec(select(Schoolyear)).all()
    years_map = {y.id: y for y in years}
    return templates.TemplateResponse(request, "holidays/list.html", {
        "holidays": holidays, "years_map": years_map, "active_nav": "schulferien",
    })


@router.get("/neu", response_class=HTMLResponse)
def new_holiday(request: Request, db: DB):
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    return templates.TemplateResponse(request, "holidays/form.html", {
        "holiday": None, "years": years, "active_nav": "schulferien",
    })


@router.post("/", response_class=RedirectResponse)
def create_holiday(
    db: DB,
    schoolyear_id: Annotated[str, Form()],
    name: Annotated[str, Form()],
    start_kw: Annotated[int, Form()],
    start_year: Annotated[int, Form()],
    end_kw: Annotated[int, Form()],
    end_year: Annotated[int, Form()],
):
    db.add(SchoolHoliday(
        schoolyear_id=schoolyear_id, name=name,
        start_kw=start_kw, start_year=start_year,
        end_kw=end_kw, end_year=end_year,
    ))
    db.commit()
    return RedirectResponse("/schulferien/?msg=created", status_code=303)


@router.get("/{holiday_id}/bearbeiten", response_class=HTMLResponse)
def edit_holiday(request: Request, holiday_id: int, db: DB):
    holiday = db.get(SchoolHoliday, holiday_id)
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    return templates.TemplateResponse(request, "holidays/form.html", {
        "holiday": holiday, "years": years, "active_nav": "schulferien",
    })


@router.post("/{holiday_id}", response_class=RedirectResponse)
def update_holiday(
    holiday_id: int, db: DB,
    schoolyear_id: Annotated[str, Form()],
    name: Annotated[str, Form()],
    start_kw: Annotated[int, Form()],
    start_year: Annotated[int, Form()],
    end_kw: Annotated[int, Form()],
    end_year: Annotated[int, Form()],
):
    h = db.get(SchoolHoliday, holiday_id)
    h.schoolyear_id = schoolyear_id
    h.name = name
    h.start_kw = start_kw
    h.start_year = start_year
    h.end_kw = end_kw
    h.end_year = end_year
    db.commit()
    return RedirectResponse("/schulferien/?msg=updated", status_code=303)


@router.delete("/{holiday_id}")
def delete_holiday(holiday_id: int, db: DB):
    h = db.get(SchoolHoliday, holiday_id)
    db.delete(h)
    db.commit()
    return HTMLResponse("")


# ── Schulferien-Import ────────────────────────────────────────────────────────

async def _read_text(raw_text: str | None, csv_file: UploadFile | None) -> str:
    """Gibt den Import-Text zurueck. Prioritaet: Datei > Textarea."""
    if csv_file and csv_file.filename:
        raw_bytes = await csv_file.read()
        try:
            return raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            return raw_bytes.decode("latin-1", errors="replace")
    return raw_text or ""


@router.get("/import/dialog", response_class=HTMLResponse)
def holiday_import_dialog(request: Request, db: DB):
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    return templates.TemplateResponse(request, "holidays/_import_dialog.html", {
        "years": years,
    })


@router.post("/import/preview", response_class=HTMLResponse)
async def holiday_import_preview(
    request: Request,
    db: DB,
    schoolyear_id: Annotated[str, Form()],
    raw_text: Annotated[str | None, Form()] = None,
    csv_file: UploadFile | None = None,
):
    text = await _read_text(raw_text, csv_file)
    parse_result = parse_holidays(text)
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    return templates.TemplateResponse(request, "holidays/_import_preview.html", {
        "valid": parse_result.valid,
        "errors": parse_result.errors,
        "raw_text": text,
        "schoolyear_id": schoolyear_id,
        "years": years,
    })


@router.post("/import/apply", response_class=RedirectResponse)
async def holiday_import_apply(
    request: Request,
    db: DB,
    schoolyear_id: Annotated[str, Form()],
    raw_text: Annotated[str | None, Form()] = None,
    csv_file: UploadFile | None = None,
):
    text = await _read_text(raw_text, csv_file)
    parse_result = parse_holidays(text)
    written, skipped = apply_holidays(db, schoolyear_id, parse_result.valid)

    n = len(written)
    s = len(skipped)
    parts = []
    if n:
        parts.append(f"{n} Ferien{'eintrag' if n == 1 else 'eintraege'} importiert")
    if s:
        parts.append(f"{s} uebersprungen")
    msg = ", ".join(parts) if parts else "Keine neuen Eintraege"

    return RedirectResponse(f"/schulferien/?msg={msg}", status_code=303)
