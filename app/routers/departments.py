from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import Department, DepartmentKategorie

router = APIRouter(prefix="/abteilungen", tags=["abteilungen"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


@router.get("/", response_class=HTMLResponse)
def list_departments(request: Request, db: DB):
    deps = db.exec(select(Department).order_by(Department.code)).all()
    return templates.TemplateResponse(request, "departments/list.html", {
        "departments": deps, "active_nav": "abteilungen",
    })


@router.get("/neu", response_class=HTMLResponse)
def new_department(request: Request):
    return templates.TemplateResponse(request, "departments/form.html", {
        "department": None, "kategorien": list(DepartmentKategorie), "active_nav": "abteilungen",
    })


@router.post("/", response_class=RedirectResponse)
def create_department(
    db: DB,
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    kategorie: Annotated[DepartmentKategorie, Form()],
    ansprechpartner: Annotated[str, Form()] = "",
    erlaubt_mehrfachbelegung: Annotated[str, Form()] = "",
):
    db.add(Department(
        code=code.strip().upper(),
        name=name,
        kategorie=kategorie,
        ansprechpartner=ansprechpartner,
        erlaubt_mehrfachbelegung=bool(erlaubt_mehrfachbelegung),
    ))
    db.commit()
    return RedirectResponse("/abteilungen/?msg=created", status_code=303)


@router.get("/{dept_id}/bearbeiten", response_class=HTMLResponse)
def edit_department(request: Request, dept_id: int, db: DB):
    dept = db.get(Department, dept_id)
    return templates.TemplateResponse(request, "departments/form.html", {
        "department": dept, "kategorien": list(DepartmentKategorie), "active_nav": "abteilungen",
    })


@router.post("/{dept_id}", response_class=RedirectResponse)
def update_department(
    dept_id: int, db: DB,
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    kategorie: Annotated[DepartmentKategorie, Form()],
    ansprechpartner: Annotated[str, Form()] = "",
    erlaubt_mehrfachbelegung: Annotated[str, Form()] = "",
):
    dept = db.get(Department, dept_id)
    dept.code = code.strip().upper()
    dept.name = name
    dept.kategorie = kategorie
    dept.ansprechpartner = ansprechpartner
    dept.erlaubt_mehrfachbelegung = bool(erlaubt_mehrfachbelegung)
    db.commit()
    return RedirectResponse("/abteilungen/?msg=updated", status_code=303)


@router.delete("/{dept_id}")
def delete_department(dept_id: int, db: DB):
    dept = db.get(Department, dept_id)
    db.delete(dept)
    db.commit()
    return HTMLResponse("")
