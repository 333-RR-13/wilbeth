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


def _get_kategorien(db: Session) -> list[DepartmentKategorie]:
    return db.exec(select(DepartmentKategorie).order_by(DepartmentKategorie.name)).all()


# ──────────────────────────────────────────────────────────────────────────────
# Kategorie-CRUD  (MUSS vor /{dept_id}-Routen stehen!)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/kategorien", response_class=HTMLResponse)
def list_kategorien(request: Request, db: DB):
    kategorien = _get_kategorien(db)
    return templates.TemplateResponse(request, "departments/kategorien.html", {
        "kategorien": kategorien, "active_nav": "abteilungen",
    })


@router.post("/kategorien", response_class=RedirectResponse)
def create_kategorie(
    db: DB,
    name: Annotated[str, Form()],
):
    name = name.strip()
    if name:
        db.add(DepartmentKategorie(name=name))
        db.commit()
    return RedirectResponse("/abteilungen/kategorien?msg=created", status_code=303)


@router.post("/kategorien/{kat_id}", response_class=RedirectResponse)
def update_kategorie(
    kat_id: int,
    db: DB,
    name: Annotated[str, Form()],
):
    kat = db.get(DepartmentKategorie, kat_id)
    if kat and name.strip():
        kat.name = name.strip()
        db.commit()
    return RedirectResponse("/abteilungen/kategorien?msg=updated", status_code=303)


@router.post("/kategorien/{kat_id}/loeschen", response_class=RedirectResponse)
def delete_kategorie(kat_id: int, db: DB):
    kat = db.get(DepartmentKategorie, kat_id)
    if kat is None:
        return RedirectResponse("/abteilungen/kategorien?err=notfound", status_code=303)
    # Sicherheitscheck: Kategorie darf nur gelöscht werden, wenn keine Abteilung sie nutzt
    in_use = db.exec(
        select(Department).where(Department.kategorie_id == kat_id)
    ).first()
    if in_use is not None:
        return RedirectResponse(
            f"/abteilungen/kategorien?err=inuse&kat={kat.name}", status_code=303
        )
    db.delete(kat)
    db.commit()
    return RedirectResponse("/abteilungen/kategorien?msg=deleted", status_code=303)


# ──────────────────────────────────────────────────────────────────────────────
# Abteilungen-CRUD
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def list_departments(request: Request, db: DB):
    deps = db.exec(select(Department).order_by(Department.code)).all()
    return templates.TemplateResponse(request, "departments/list.html", {
        "departments": deps, "active_nav": "abteilungen",
    })


@router.get("/neu", response_class=HTMLResponse)
def new_department(request: Request, db: DB):
    return templates.TemplateResponse(request, "departments/form.html", {
        "department": None, "kategorien": _get_kategorien(db), "active_nav": "abteilungen",
    })


@router.post("/", response_class=RedirectResponse)
def create_department(
    db: DB,
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    kategorie_id: Annotated[int | None, Form()] = None,
    ansprechpartner: Annotated[str, Form()] = "",
    info_text: Annotated[str, Form()] = "",
    erlaubt_mehrfachbelegung: Annotated[str, Form()] = "",
    farbe: Annotated[str, Form()] = "#9CA3AF",
):
    db.add(Department(
        code=code.strip().upper(),
        name=name,
        kategorie_id=kategorie_id,
        ansprechpartner=ansprechpartner,
        info_text=info_text,
        erlaubt_mehrfachbelegung=bool(erlaubt_mehrfachbelegung),
        farbe=farbe,
    ))
    db.commit()
    return RedirectResponse("/abteilungen/?msg=created", status_code=303)


@router.get("/{dept_id:int}/bearbeiten", response_class=HTMLResponse)
def edit_department(request: Request, dept_id: int, db: DB):
    dept = db.get(Department, dept_id)
    return templates.TemplateResponse(request, "departments/form.html", {
        "department": dept, "kategorien": _get_kategorien(db), "active_nav": "abteilungen",
    })


@router.post("/{dept_id:int}", response_class=RedirectResponse)
def update_department(
    dept_id: int, db: DB,
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    kategorie_id: Annotated[int | None, Form()] = None,
    ansprechpartner: Annotated[str, Form()] = "",
    info_text: Annotated[str, Form()] = "",
    erlaubt_mehrfachbelegung: Annotated[str, Form()] = "",
    farbe: Annotated[str, Form()] = "#9CA3AF",
):
    dept = db.get(Department, dept_id)
    dept.code = code.strip().upper()
    dept.name = name
    dept.kategorie_id = kategorie_id
    dept.ansprechpartner = ansprechpartner
    dept.info_text = info_text
    dept.erlaubt_mehrfachbelegung = bool(erlaubt_mehrfachbelegung)
    dept.farbe = farbe
    db.commit()
    return RedirectResponse("/abteilungen/?msg=updated", status_code=303)


@router.delete("/{dept_id:int}")
def delete_department(dept_id: int, db: DB):
    dept = db.get(Department, dept_id)
    db.delete(dept)
    db.commit()
    return HTMLResponse("")
