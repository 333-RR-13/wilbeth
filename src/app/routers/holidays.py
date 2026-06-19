from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import SchoolHoliday, Schoolyear

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
