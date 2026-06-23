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
    SchoolPlan,
    SchoolPlanWeek,
    Schoolyear,
    Trainee,
    TraineeClass,
    UnterrichtsTyp,
)
from app.services.auto_plan import apply_auto_plan, plan_assignments
from app.services.conflict_checker import describe_conflict, find_conflicts
from app.services.dept_history import visited_departments
from app.utils.colors import department_color_map
from app.utils.kw import format_weekdays, iter_schoolyear_weeks, kw_to_monday

router = APIRouter(tags=["overview"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


@router.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse("/overview", status_code=302)


@router.get("/overview/konflikte", response_class=HTMLResponse)
def overview_conflicts(request: Request, db: DB):
    """Liefert die Konfliktliste mit Begruendung als Partial (HTMX, on demand)."""
    schoolyear_id = request.query_params.get("schoolyear_id", "")
    raw = find_conflicts(db, schoolyear_id) if schoolyear_id else []
    depts = {d.id: d for d in db.exec(select(Department)).all()}
    names = {t.id: f"{t.nachname}, {t.vorname}" for t in db.exec(select(Trainee)).all()}
    details = [describe_conflict(c, names, depts) for c in raw]
    return templates.TemplateResponse(request, "_partials/conflict_list.html", {
        "conflicts": details,
    })


WOCHEN_OPTIONS = [4, 8, 12, 16, 26]


@router.get("/overview", response_class=HTMLResponse)
def overview(request: Request, db: DB):
    schoolyear_id = request.query_params.get("schoolyear_id", "")
    klasse_id_str = request.query_params.get("klasse_id", "")
    abteilung_id_str = request.query_params.get("abteilung_id", "")
    wochen_str = request.query_params.get("wochen", "")

    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    classes = db.exec(select(TraineeClass).order_by(TraineeClass.name)).all()
    all_depts = db.exec(select(Department).order_by(Department.code)).all()

    # Schultage-Hinweis je TAGE_FEST-Klasse (z. B. "Di, Mi (halbtags)")
    tage_fest_map = {
        c.id: format_weekdays(c.schul_wochentage, halbtag=c.halbtag_wochentag)
        for c in classes
        if c.unterrichts_typ == UnterrichtsTyp.TAGE_FEST and c.schul_wochentage
    }

    if not schoolyear_id and years:
        schoolyear_id = years[0].id

    year = db.get(Schoolyear, schoolyear_id) if schoolyear_id else None

    if not year:
        dept_colors = department_color_map(all_depts)
        return templates.TemplateResponse(request, "overview/matrix.html", {
            "trainees": [], "weeks": [], "cell_map": {}, "conflict_cells": set(),
            "conflict_count": 0, "years": years, "classes": classes,
            "depts": {}, "all_depts": all_depts, "school_week_map": {}, "trainee_klasse_map": {},
            "tage_fest_map": tage_fest_map,
            "visited_map": {},
            "dept_colors": dept_colors,
            "selected_year": schoolyear_id, "selected_klasse": klasse_id_str,
            "selected_abteilung": abteilung_id_str,
            "selected_wochen": wochen_str,
            "wochen_options": WOCHEN_OPTIONS,
            "active_nav": "overview",
        })

    _today = date.today().isocalendar()
    _today_key = (_today.week, _today.year)
    all_weeks = [
        {
            "kw": kw,
            "jahr": jahr,
            "monday": kw_to_monday(kw, jahr),
            "is_today": (kw, jahr) == _today_key,
        }
        for kw, jahr in iter_schoolyear_weeks(
            year.start_kw, year.start_year,
            year.end_kw, year.end_year,
        )
    ]

    # Wochen-Fenster: nur N Wochen ab heutiger KW anzeigen
    try:
        n_wochen = int(wochen_str) if wochen_str else 0
    except (ValueError, TypeError):
        n_wochen = 0

    if n_wochen > 0:
        # Anker: Index der heutigen ISO-Woche; falls nicht im Lehrjahr → Index 0
        anker = next(
            (i for i, w in enumerate(all_weeks) if (w["kw"], w["jahr"]) == _today_key),
            0,
        )
        weeks = all_weeks[anker: anker + n_wochen]
    else:
        weeks = all_weeks

    # Filter trainees by class if requested
    q = select(Trainee)
    if klasse_id_str:
        q = q.where(Trainee.klasse_id == int(klasse_id_str))
    if abteilung_id_str:
        trainee_ids_in_dept = db.exec(
            select(Assignment.trainee_id).where(
                Assignment.schoolyear_id == schoolyear_id,
                Assignment.abteilung_id == int(abteilung_id_str),
            )
        ).all()
        q = q.where(Trainee.id.in_(trainee_ids_in_dept))
    trainees = db.exec(q.order_by(Trainee.nachname, Trainee.vorname)).all()

    # Assignments for the selected trainees
    trainee_ids = [t.id for t in trainees]
    if trainee_ids:
        assignments = db.exec(
            select(Assignment).where(
                Assignment.schoolyear_id == schoolyear_id,
                Assignment.trainee_id.in_(trainee_ids),
            )
        ).all()
    else:
        assignments = []

    # cell_map[trainee_id]["kw,jahr"] = Assignment
    cell_map: dict[int, dict[str, Assignment]] = {}
    for a in assignments:
        cell_map.setdefault(a.trainee_id, {})[f"{a.kw},{a.jahr}"] = a

    # Conflict detection. Fuer Doppelbelegungen (trainee_id=None) werden alle
    # beteiligten Trainees markiert, damit auch sie in der Matrix rot erscheinen.
    raw_conflicts = find_conflicts(db, schoolyear_id)
    conflict_cells: set[str] = set()
    for c in raw_conflicts:
        ids = c.trainee_ids if c.trainee_ids else ((c.trainee_id,) if c.trainee_id is not None else ())
        for tid in ids:
            conflict_cells.add(f"{tid}~{c.kw}~{c.jahr}")

    depts = {d.id: d for d in db.exec(select(Department)).all()}
    dept_colors = department_color_map(depts.values())

    # school_week_map[klasse_id] = dict "kw,jahr" -> typ_value for highlighting + chip rendering
    school_week_map: dict[int, dict[str, str]] = {}
    for plan in db.exec(
        select(SchoolPlan).where(SchoolPlan.schoolyear_id == schoolyear_id)
    ).all():
        sw: dict[str, str] = {}
        for w in db.exec(
            select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan.id)
        ).all():
            sw[f"{w.kw},{w.jahr}"] = w.typ.value
        school_week_map[plan.klasse_id] = sw

    trainee_klasse_map = {t.id: t.klasse_id for t in trainees}

    # visited_map[trainee_id] = list of departments this trainee has already been in
    visited_map: dict[int, list] = {t.id: visited_departments(db, t.id) for t in trainees}

    return templates.TemplateResponse(request, "overview/matrix.html", {
        "trainees": trainees,
        "weeks": weeks,
        "cell_map": cell_map,
        "conflict_cells": conflict_cells,
        "conflict_count": len(raw_conflicts),
        "years": years,
        "classes": classes,
        "depts": depts,
        "all_depts": all_depts,
        "school_week_map": school_week_map,
        "trainee_klasse_map": trainee_klasse_map,
        "tage_fest_map": tage_fest_map,
        "visited_map": visited_map,
        "dept_colors": dept_colors,
        "selected_year": schoolyear_id,
        "selected_klasse": klasse_id_str,
        "selected_abteilung": abteilung_id_str,
        "selected_wochen": wochen_str,
        "wochen_options": WOCHEN_OPTIONS,
        "active_nav": "overview",
    })


# ── Auto-Plan Endpunkte ───────────────────────────────────────────────────────

def _parse_auto_plan_params(request: Request) -> tuple[str, list[int], int]:
    """Liest schoolyear_id, trainee_ids (Liste) und block_length aus Form-Daten."""
    form_data = request._form  # type: ignore[attr-defined]
    schoolyear_id = form_data.get("schoolyear_id", "")
    block_length_str = form_data.get("block_length", "4")
    try:
        block_length = max(1, int(block_length_str))
    except (ValueError, TypeError):
        block_length = 4
    raw_ids = form_data.getlist("trainee_ids")
    trainee_ids: list[int] = []
    for raw in raw_ids:
        try:
            trainee_ids.append(int(raw))
        except (ValueError, TypeError):
            pass
    return schoolyear_id, trainee_ids, block_length


@router.post("/overview/auto-plan/preview", response_class=HTMLResponse)
async def auto_plan_preview(request: Request, db: DB):
    """Berechnet Auto-Plan-Vorschlag und rendert das Vorschau-Partial.

    Kein DB-Write. Parameter: schoolyear_id, trainee_ids (mehrfach), block_length.
    """
    await request.form()  # Form-Daten einlesen (fuellt request._form)
    schoolyear_id, trainee_ids, block_length = _parse_auto_plan_params(request)

    plan_result = plan_assignments(db, schoolyear_id, trainee_ids, block_length)

    depts = {d.id: d for d in db.exec(select(Department)).all()}
    trainee_map = {t.id: t for t in db.exec(select(Trainee)).all()}

    # Geplante Eintraege je Trainee gruppieren
    planned_by_trainee: dict[int, list] = {}
    for entry in plan_result.planned:
        planned_by_trainee.setdefault(entry.trainee_id, []).append(entry)

    # Uebersprungene je Trainee gruppieren
    skipped_by_trainee: dict[int, list] = {}
    for s in plan_result.skipped:
        skipped_by_trainee.setdefault(s.trainee_id, []).append(s)

    return templates.TemplateResponse(
        request,
        "overview/_auto_plan_preview.html",
        {
            "planned_by_trainee": planned_by_trainee,
            "skipped_by_trainee": skipped_by_trainee,
            "depts": depts,
            "trainee_map": trainee_map,
            "schoolyear_id": schoolyear_id,
            "block_length": block_length,
            "trainee_ids": trainee_ids,
            "total_planned": len(plan_result.planned),
            "total_skipped": len(plan_result.skipped),
        },
    )


@router.post("/overview/auto-plan/apply", response_class=RedirectResponse)
async def auto_plan_apply(request: Request, db: DB):
    """Berechnet Auto-Plan und schreibt ihn als Assignment(source=AUTO) in die DB.

    Danach PRG-Redirect auf /overview mit ?msg=... .
    """
    await request.form()
    schoolyear_id, trainee_ids, block_length = _parse_auto_plan_params(request)

    plan_result = apply_auto_plan(db, schoolyear_id, trainee_ids, block_length)

    n = len(plan_result.planned)
    msg = f"Auto-Plan: {n} Einsatz{'e' if n != 1 else ''} angelegt."

    redirect_url = f"/overview?schoolyear_id={schoolyear_id}&msg={msg}"
    return RedirectResponse(redirect_url, status_code=303)
