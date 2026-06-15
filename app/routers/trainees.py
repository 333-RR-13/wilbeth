import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    Assignment,
    Department,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    TraineeWish,
)
from app.services.conflict_checker import find_conflicts
from app.services.school_sync import sync_trainee

router = APIRouter(prefix="/trainees", tags=["trainees"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


@router.get("/", response_class=HTMLResponse)
def list_trainees(request: Request, db: DB):
    trainees = db.exec(
        select(Trainee).order_by(Trainee.nachname, Trainee.vorname)
    ).all()
    classes = {c.id: c for c in db.exec(select(TraineeClass)).all()}
    return templates.TemplateResponse(request, "trainees/list.html", {
        "trainees": trainees, "classes": classes, "active_nav": "trainees",
    })


@router.get("/neu", response_class=HTMLResponse)
def new_trainee(request: Request, db: DB):
    classes = db.exec(select(TraineeClass).order_by(TraineeClass.name)).all()
    return templates.TemplateResponse(request, "trainees/form.html", {
        "trainee": None, "classes": classes, "rollen": list(TraineeRolle), "active_nav": "trainees",
    })


@router.post("/", response_class=RedirectResponse)
def create_trainee(
    db: DB,
    vorname: Annotated[str, Form()],
    nachname: Annotated[str, Form()],
    rolle: Annotated[TraineeRolle, Form()],
    klasse_id: Annotated[str, Form()] = "",
    notizen: Annotated[str, Form()] = "",
    aktiv: Annotated[str, Form()] = "",
):
    t = Trainee(
        vorname=vorname,
        nachname=nachname,
        rolle=rolle,
        klasse_id=int(klasse_id) if klasse_id else None,
        notizen=notizen,
        aktiv=bool(aktiv),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    sync_trainee(db, t.id)
    return RedirectResponse("/trainees/?msg=created", status_code=303)


@router.get("/{trainee_id:int}", response_class=HTMLResponse)
def trainee_detail(request: Request, trainee_id: int, db: DB):
    trainee = db.get(Trainee, trainee_id)
    klasse = db.get(TraineeClass, trainee.klasse_id) if trainee.klasse_id else None
    years = {y.id: y for y in db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()}
    depts = {d.id: d for d in db.exec(select(Department)).all()}
    assignments = db.exec(
        select(Assignment)
        .where(Assignment.trainee_id == trainee_id)
        .order_by(Assignment.jahr, Assignment.kw)
    ).all()

    conflict_cells: set[str] = set()
    for year_id in years:
        for c in find_conflicts(db, year_id):
            if c.trainee_id == trainee_id:
                conflict_cells.add(f"{c.kw}~{c.jahr}")

    _today = date.today().isocalendar()
    today_key = f"{_today.week}~{_today.year}"

    # Wuensche des Trainees (fuer die Planerin sichtbar), nach Prioritaet sortiert
    wishes = db.exec(
        select(TraineeWish)
        .where(TraineeWish.trainee_id == trainee_id)
        .order_by(TraineeWish.prioritaet)
    ).all()

    return templates.TemplateResponse(request, "trainees/detail.html", {
        "trainee": trainee,
        "klasse": klasse,
        "years": years,
        "depts": depts,
        "assignments": assignments,
        "conflict_cells": conflict_cells,
        "today_key": today_key,
        "wishes": wishes,
        "active_nav": "trainees",
    })


@router.post("/{trainee_id:int}/share-token", response_class=RedirectResponse)
def generate_share_token(trainee_id: int, db: DB):
    t = db.get(Trainee, trainee_id)
    t.share_token = str(uuid.uuid4())
    db.commit()
    return RedirectResponse(f"/trainees/{trainee_id}?msg=updated", status_code=303)


@router.post("/{trainee_id:int}/share-token/deaktivieren", response_class=RedirectResponse)
def revoke_share_token(trainee_id: int, db: DB):
    t = db.get(Trainee, trainee_id)
    t.share_token = None
    db.commit()
    return RedirectResponse(f"/trainees/{trainee_id}?msg=updated", status_code=303)


@router.get("/{trainee_id:int}/bearbeiten", response_class=HTMLResponse)
def edit_trainee(request: Request, trainee_id: int, db: DB):
    trainee = db.get(Trainee, trainee_id)
    classes = db.exec(select(TraineeClass).order_by(TraineeClass.name)).all()
    return templates.TemplateResponse(request, "trainees/form.html", {
        "trainee": trainee, "classes": classes, "rollen": list(TraineeRolle), "active_nav": "trainees",
    })


@router.post("/{trainee_id:int}", response_class=RedirectResponse)
def update_trainee(
    trainee_id: int, db: DB,
    vorname: Annotated[str, Form()],
    nachname: Annotated[str, Form()],
    rolle: Annotated[TraineeRolle, Form()],
    klasse_id: Annotated[str, Form()] = "",
    notizen: Annotated[str, Form()] = "",
    aktiv: Annotated[str, Form()] = "",
):
    t = db.get(Trainee, trainee_id)
    t.vorname = vorname
    t.nachname = nachname
    t.rolle = rolle
    t.klasse_id = int(klasse_id) if klasse_id else None
    t.notizen = notizen
    t.aktiv = bool(aktiv)
    db.commit()
    sync_trainee(db, trainee_id)
    return RedirectResponse("/trainees/?msg=updated", status_code=303)


@router.delete("/{trainee_id:int}")
def delete_trainee(trainee_id: int, db: DB):
    t = db.get(Trainee, trainee_id)
    db.delete(t)
    db.commit()
    return HTMLResponse("")
