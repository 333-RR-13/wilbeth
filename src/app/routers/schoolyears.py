from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import Schoolyear

router = APIRouter(prefix="/lehrjahre", tags=["lehrjahre"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


@router.get("/", response_class=HTMLResponse)
def list_schoolyears(request: Request, db: DB):
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    return templates.TemplateResponse(request, "schoolyears/list.html", {
        "years": years, "active_nav": "lehrjahre"
    })


@router.get("/neu", response_class=HTMLResponse)
def new_schoolyear(request: Request):
    return templates.TemplateResponse(request, "schoolyears/form.html", {
        "year": None, "active_nav": "lehrjahre"
    })


@router.post("/", response_class=RedirectResponse)
def create_schoolyear(
    db: DB,
    id: Annotated[str, Form()],
    start_kw: Annotated[int, Form()],
    start_year: Annotated[int, Form()],
    end_kw: Annotated[int, Form()],
    end_year: Annotated[int, Form()],
):
    db.add(Schoolyear(
        id=id, start_kw=start_kw, start_year=start_year,
        end_kw=end_kw, end_year=end_year,
    ))
    db.commit()
    return RedirectResponse("/lehrjahre/?msg=created", status_code=303)


@router.get("/{year_id}/bearbeiten", response_class=HTMLResponse)
def edit_schoolyear(request: Request, year_id: str, db: DB):
    year = db.get(Schoolyear, year_id)
    return templates.TemplateResponse(request, "schoolyears/form.html", {
        "year": year, "active_nav": "lehrjahre"
    })


@router.post("/{year_id}", response_class=RedirectResponse)
def update_schoolyear(
    year_id: str, db: DB,
    start_kw: Annotated[int, Form()],
    start_year: Annotated[int, Form()],
    end_kw: Annotated[int, Form()],
    end_year: Annotated[int, Form()],
):
    year = db.get(Schoolyear, year_id)
    year.start_kw = start_kw
    year.start_year = start_year
    year.end_kw = end_kw
    year.end_year = end_year
    db.commit()
    return RedirectResponse("/lehrjahre/?msg=updated", status_code=303)


@router.delete("/{year_id}")
def delete_schoolyear(year_id: str, db: DB):
    year = db.get(Schoolyear, year_id)
    db.delete(year)
    db.commit()
    return HTMLResponse("")
