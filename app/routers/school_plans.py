from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    SchoolPlan,
    SchoolPlanWeek,
    SchoolWeekTyp,
    Schoolyear,
    TraineeClass,
)

router = APIRouter(prefix="/schulplaene", tags=["schulplaene"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


@router.get("/", response_class=HTMLResponse)
def list_plans(request: Request, db: DB):
    plans = db.exec(select(SchoolPlan)).all()
    classes = {c.id: c for c in db.exec(select(TraineeClass)).all()}
    years = {y.id: y for y in db.exec(select(Schoolyear)).all()}
    week_counts = {
        p.id: len(db.exec(select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == p.id)).all())
        for p in plans
    }
    return templates.TemplateResponse(request, "school_plans/list.html", {
        "plans": plans,
        "classes": classes,
        "years": years,
        "week_counts": week_counts,
        "active_nav": "schulplaene",
    })


@router.get("/neu", response_class=HTMLResponse)
def new_plan(request: Request, db: DB):
    classes = db.exec(select(TraineeClass).order_by(TraineeClass.name)).all()
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    return templates.TemplateResponse(request, "school_plans/form.html", {
        "classes": classes,
        "years": years,
        "active_nav": "schulplaene",
    })


@router.post("/", response_class=RedirectResponse)
def create_plan(
    db: DB,
    klasse_id: Annotated[int, Form()],
    schoolyear_id: Annotated[str, Form()],
):
    existing = db.exec(
        select(SchoolPlan).where(
            SchoolPlan.klasse_id == klasse_id,
            SchoolPlan.schoolyear_id == schoolyear_id,
        )
    ).first()
    if existing:
        return RedirectResponse(f"/schulplaene/{existing.id}?msg=updated", status_code=303)

    plan = SchoolPlan(klasse_id=klasse_id, schoolyear_id=schoolyear_id)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return RedirectResponse(f"/schulplaene/{plan.id}?msg=created", status_code=303)


@router.get("/{plan_id}", response_class=HTMLResponse)
def plan_detail(request: Request, plan_id: int, db: DB):
    plan = db.get(SchoolPlan, plan_id)
    klasse = db.get(TraineeClass, plan.klasse_id)
    year = db.get(Schoolyear, plan.schoolyear_id)
    weeks = db.exec(
        select(SchoolPlanWeek)
        .where(SchoolPlanWeek.plan_id == plan_id)
        .order_by(SchoolPlanWeek.jahr, SchoolPlanWeek.kw)
    ).all()
    return templates.TemplateResponse(request, "school_plans/detail.html", {
        "plan": plan,
        "klasse": klasse,
        "year": year,
        "weeks": weeks,
        "typen": list(SchoolWeekTyp),
        "active_nav": "schulplaene",
    })


@router.post("/{plan_id}/wochen", response_class=RedirectResponse)
def add_week(
    plan_id: int,
    db: DB,
    kw: Annotated[int, Form()],
    jahr: Annotated[int, Form()],
    typ: Annotated[SchoolWeekTyp, Form()],
):
    existing = db.exec(
        select(SchoolPlanWeek).where(
            SchoolPlanWeek.plan_id == plan_id,
            SchoolPlanWeek.kw == kw,
            SchoolPlanWeek.jahr == jahr,
        )
    ).first()
    if existing:
        existing.typ = typ
    else:
        db.add(SchoolPlanWeek(plan_id=plan_id, kw=kw, jahr=jahr, typ=typ))
    db.commit()
    return RedirectResponse(f"/schulplaene/{plan_id}?msg=created", status_code=303)


@router.delete("/{plan_id}/wochen/{week_id}")
def delete_week(plan_id: int, week_id: int, db: DB):
    w = db.get(SchoolPlanWeek, week_id)
    db.delete(w)
    db.commit()
    return HTMLResponse("")


@router.delete("/{plan_id}")
def delete_plan(plan_id: int, db: DB):
    for w in db.exec(select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan_id)).all():
        db.delete(w)
    db.delete(db.get(SchoolPlan, plan_id))
    db.commit()
    return HTMLResponse("")
