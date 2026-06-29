import urllib.parse
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    SchoolPlan,
    SchoolPlanWeek,
    Schoolyear,
    Trainee,
)
from app.services.conflict_checker import ConflictKind, describe_conflict, find_conflicts
from app.services.dept_history import visited_department_ids
from app.utils.colors import department_color_map
from app.utils.kw import iter_kw_range

router = APIRouter(prefix="/einsaetze", tags=["einsaetze"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]

# Higher rank overrides lower rank; equal rank requires confirmation.
TYP_RANG: dict[AssignmentTyp, int] = {
    AssignmentTyp.BERUFSSCHULE: 3,
    AssignmentTyp.UNI: 3,
    AssignmentTyp.URLAUB: 2,
    AssignmentTyp.ABTEILUNG: 1,
    AssignmentTyp.FREI: 0,
}


def _is_school_week(db: Session, trainee_id: int, schoolyear_id: str, kw: int, jahr: int) -> bool:
    trainee = db.get(Trainee, trainee_id)
    if not trainee or not trainee.klasse_id:
        return False
    plan = db.exec(
        select(SchoolPlan).where(
            SchoolPlan.klasse_id == trainee.klasse_id,
            SchoolPlan.schoolyear_id == schoolyear_id,
        )
    ).first()
    if not plan:
        return False
    return bool(db.exec(
        select(SchoolPlanWeek).where(
            SchoolPlanWeek.plan_id == plan.id,
            SchoolPlanWeek.kw == kw,
            SchoolPlanWeek.jahr == jahr,
        )
    ).first())


def _resolve_range(
    db: Session,
    trainee_id: int,
    schoolyear_id: str,
    kw_list: list[tuple[int, int]],
    new_typ: AssignmentTyp,
    override_keys: frozenset[str],
) -> tuple[
    list[tuple[int, int]],
    list[tuple[int, int, Assignment]],
    list[tuple[int, int, str]],
    list[tuple[int, int, Assignment]],
]:
    """
    Returns (to_create, to_override, skipped, pending_confirm).
    skipped entries carry a reason string instead of an Assignment.
    """
    to_create: list[tuple[int, int]] = []
    to_override: list[tuple[int, int, Assignment]] = []
    skipped: list[tuple[int, int, str]] = []
    pending: list[tuple[int, int, Assignment]] = []

    new_rang = TYP_RANG[new_typ]

    for kw, jahr in kw_list:
        existing = db.exec(
            select(Assignment).where(
                Assignment.trainee_id == trainee_id,
                Assignment.kw == kw,
                Assignment.jahr == jahr,
            )
        ).first()

        if existing is None:
            # Implicit block: URLAUB cannot be placed on a school week
            if new_typ == AssignmentTyp.URLAUB and _is_school_week(db, trainee_id, schoolyear_id, kw, jahr):
                skipped.append((kw, jahr, "Schulwoche"))
            else:
                to_create.append((kw, jahr))
        else:
            old_rang = TYP_RANG[existing.typ]
            key = f"{kw}:{jahr}"
            if new_rang > old_rang:
                to_override.append((kw, jahr, existing))
            elif new_rang < old_rang:
                skipped.append((kw, jahr, existing.typ.value))
            else:
                if key in override_keys:
                    to_override.append((kw, jahr, existing))
                else:
                    pending.append((kw, jahr, existing))

    return to_create, to_override, skipped, pending


def _apply_assignments(
    db: Session,
    trainee_id: int,
    schoolyear_id: str,
    typ: AssignmentTyp,
    abteilung_id: int | None,
    notiz: str,
    to_create: list[tuple[int, int]],
    to_override: list[tuple[int, int, Assignment]],
    source: AssignmentSource = AssignmentSource.MANUAL,
) -> None:
    for kw, jahr in to_create:
        db.add(Assignment(
            trainee_id=trainee_id,
            schoolyear_id=schoolyear_id,
            kw=kw,
            jahr=jahr,
            typ=typ,
            abteilung_id=abteilung_id,
            notiz=notiz,
            source=source,
        ))
    for _, __, old in to_override:
        old.typ = typ
        old.abteilung_id = abteilung_id
        old.notiz = notiz
        old.source = source


def _build_detail(created: int, overwritten: int, skipped: int) -> str:
    if created + overwritten == 0:
        return ""
    parts = []
    if created:
        parts.append(f"{created} neu angelegt")
    if overwritten:
        parts.append(f"{overwritten} überschrieben")
    if skipped:
        parts.append(f"{skipped} übersprungen")
    return ", ".join(parts) + "."


def _redirect_created(detail: str) -> RedirectResponse:
    enc = urllib.parse.quote(detail) if detail else ""
    url = "/einsaetze/?msg=created" + (f"&detail={enc}" if enc else "")
    return RedirectResponse(url, status_code=303)


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def list_assignments(request: Request, db: DB):
    schoolyear_id = request.query_params.get("schoolyear_id", "")
    trainee_id_str = request.query_params.get("trainee_id", "")

    q = select(Assignment)
    if schoolyear_id:
        q = q.where(Assignment.schoolyear_id == schoolyear_id)
    if trainee_id_str:
        q = q.where(Assignment.trainee_id == int(trainee_id_str))
    assignments = db.exec(q.order_by(Assignment.jahr, Assignment.kw)).all()

    trainees = db.exec(select(Trainee).order_by(Trainee.nachname, Trainee.vorname)).all()
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    depts = {d.id: d for d in db.exec(select(Department)).all()}
    trainee_map = {t.id: t for t in trainees}

    return templates.TemplateResponse(request, "assignments/list.html", {
        "assignments": assignments,
        "trainees": trainees,
        "years": years,
        "depts": depts,
        "trainee_map": trainee_map,
        "selected_year": schoolyear_id,
        "selected_trainee": trainee_id_str,
        "active_nav": "einsaetze",
    })


# ── Create ────────────────────────────────────────────────────────────────────

@router.get("/neu", response_class=HTMLResponse)
def new_assignment(request: Request, db: DB):
    trainees = db.exec(
        select(Trainee).where(Trainee.aktiv == True).order_by(Trainee.nachname, Trainee.vorname)
    ).all()
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    depts = db.exec(select(Department).order_by(Department.code)).all()
    return templates.TemplateResponse(request, "assignments/form.html", {
        "assignment": None,
        "trainees": trainees,
        "years": years,
        "depts": depts,
        "typen": list(AssignmentTyp),
        "prefill_trainee_id": request.query_params.get("trainee_id", ""),
        "active_nav": "einsaetze",
    })


@router.post("/", response_class=HTMLResponse)
def create_assignment(
    request: Request,
    db: DB,
    trainee_id: Annotated[int, Form()],
    schoolyear_id: Annotated[str, Form()],
    kw: Annotated[int, Form()],
    jahr: Annotated[int, Form()],
    typ: Annotated[AssignmentTyp, Form()],
    kw_end: Annotated[str, Form()] = "",
    jahr_end: Annotated[str, Form()] = "",
    abteilung_id: Annotated[str, Form()] = "",
    notiz: Annotated[str, Form()] = "",
):
    _abt_id = int(abteilung_id) if typ == AssignmentTyp.ABTEILUNG and abteilung_id else None

    if kw_end and jahr_end:
        kw_list = list(iter_kw_range(kw, jahr, int(kw_end), int(jahr_end)))
    else:
        kw_list = [(kw, jahr)]

    to_create, to_override, skipped, pending = _resolve_range(
        db, trainee_id, schoolyear_id, kw_list, typ, frozenset()
    )

    if pending:
        trainees = db.exec(select(Trainee).order_by(Trainee.nachname, Trainee.vorname)).all()
        depts = db.exec(select(Department).order_by(Department.code)).all()
        return templates.TemplateResponse(request, "assignments/confirm.html", {
            "trainee_id": trainee_id,
            "schoolyear_id": schoolyear_id,
            "kw": kw,
            "jahr": jahr,
            "kw_end": kw_end,
            "jahr_end": jahr_end,
            "typ": typ.value,
            "abteilung_id": abteilung_id,
            "notiz": notiz,
            "pending": pending,
            "to_create_count": len(to_create),
            "to_override": to_override,
            "skipped": skipped,
            "depts": {d.id: d for d in depts},
            "active_nav": "einsaetze",
        })

    _apply_assignments(db, trainee_id, schoolyear_id, typ, _abt_id, notiz, to_create, to_override)
    db.commit()
    return _redirect_created(_build_detail(len(to_create), len(to_override), len(skipped)))


@router.post("/confirm", response_class=RedirectResponse)
def confirm_assignments(
    db: DB,
    trainee_id: Annotated[int, Form()],
    schoolyear_id: Annotated[str, Form()],
    kw: Annotated[int, Form()],
    jahr: Annotated[int, Form()],
    typ: Annotated[AssignmentTyp, Form()],
    kw_end: Annotated[str, Form()] = "",
    jahr_end: Annotated[str, Form()] = "",
    abteilung_id: Annotated[str, Form()] = "",
    notiz: Annotated[str, Form()] = "",
    override: Annotated[list[str], Form()] = [],
):
    _abt_id = int(abteilung_id) if typ == AssignmentTyp.ABTEILUNG and abteilung_id else None

    if kw_end and jahr_end:
        kw_list = list(iter_kw_range(kw, jahr, int(kw_end), int(jahr_end)))
    else:
        kw_list = [(kw, jahr)]

    override_keys = frozenset(override)
    to_create, to_override, skipped, still_pending = _resolve_range(
        db, trainee_id, schoolyear_id, kw_list, typ, override_keys
    )

    _apply_assignments(db, trainee_id, schoolyear_id, typ, _abt_id, notiz, to_create, to_override)
    db.commit()
    total_skipped = len(skipped) + len(still_pending)
    return _redirect_created(_build_detail(len(to_create), len(to_override), total_skipped))


# ── Edit ──────────────────────────────────────────────────────────────────────

@router.get("/{assignment_id:int}/bearbeiten", response_class=HTMLResponse)
def edit_assignment(request: Request, assignment_id: int, db: DB):
    assignment = db.get(Assignment, assignment_id)
    trainees = db.exec(select(Trainee).order_by(Trainee.nachname, Trainee.vorname)).all()
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    depts = db.exec(select(Department).order_by(Department.code)).all()
    return templates.TemplateResponse(request, "assignments/form.html", {
        "assignment": assignment,
        "trainees": trainees,
        "years": years,
        "depts": depts,
        "typen": list(AssignmentTyp),
        "prefill_trainee_id": "",
        "active_nav": "einsaetze",
    })


@router.post("/{assignment_id:int}", response_class=RedirectResponse)
def update_assignment(
    assignment_id: int,
    db: DB,
    trainee_id: Annotated[int, Form()],
    schoolyear_id: Annotated[str, Form()],
    kw: Annotated[int, Form()],
    jahr: Annotated[int, Form()],
    typ: Annotated[AssignmentTyp, Form()],
    abteilung_id: Annotated[str, Form()] = "",
    notiz: Annotated[str, Form()] = "",
):
    _abt_id = int(abteilung_id) if typ == AssignmentTyp.ABTEILUNG and abteilung_id else None
    a = db.get(Assignment, assignment_id)
    a.trainee_id = trainee_id
    a.schoolyear_id = schoolyear_id
    a.kw = kw
    a.jahr = jahr
    a.typ = typ
    a.abteilung_id = _abt_id
    a.notiz = notiz
    db.commit()
    return RedirectResponse("/einsaetze/?msg=updated", status_code=303)


@router.delete("/{assignment_id:int}")
def delete_assignment(assignment_id: int, db: DB):
    a = db.get(Assignment, assignment_id)
    db.delete(a)
    db.commit()
    return HTMLResponse("")


# ── Inline cell edit (matrix) ─────────────────────────────────────────────────

@router.get("/cell-edit", response_class=HTMLResponse)
def cell_edit(request: Request, db: DB):
    trainee_id = int(request.query_params["trainee_id"])
    kw = int(request.query_params["kw"])
    jahr = int(request.query_params["jahr"])
    schoolyear_id = request.query_params["schoolyear_id"]

    trainee = db.get(Trainee, trainee_id)
    existing = db.exec(
        select(Assignment).where(
            Assignment.trainee_id == trainee_id,
            Assignment.kw == kw,
            Assignment.jahr == jahr,
        )
    ).first()
    depts = db.exec(select(Department).order_by(Department.code)).all()

    # Konflikte, an denen genau diese Zelle beteiligt ist, mit Begruendung
    dept_map = {d.id: d for d in depts}
    names = {t.id: f"{t.nachname}, {t.vorname}" for t in db.exec(select(Trainee)).all()}
    cell_conflicts = [
        describe_conflict(c, names, dept_map)
        for c in find_conflicts(db, schoolyear_id)
        if c.kw == kw and c.jahr == jahr
        and (
            c.trainee_id == trainee_id
            or (c.kind == ConflictKind.DOPPELBELEGUNG and trainee_id in c.trainee_ids)
        )
    ]

    # Visited dept ids excluding the current cell so the warning reflects other stints
    visited_ids = visited_department_ids(db, trainee_id, exclude_kw=kw, exclude_jahr=jahr)

    return templates.TemplateResponse(request, "_partials/cell_form.html", {
        "trainee_id": trainee_id,
        "trainee_name": f"{trainee.nachname}, {trainee.vorname}" if trainee else "",
        "kw": kw,
        "jahr": jahr,
        "schoolyear_id": schoolyear_id,
        "existing": existing,
        "depts": depts,
        "typen": list(AssignmentTyp),
        "cell_conflicts": cell_conflicts,
        "visited_dept_ids": list(visited_ids),
    })


@router.post("/cell-save", response_class=HTMLResponse)
def cell_save(
    request: Request,
    db: DB,
    trainee_id: Annotated[int, Form()],
    schoolyear_id: Annotated[str, Form()],
    kw: Annotated[int, Form()],
    jahr: Annotated[int, Form()],
    typ: Annotated[AssignmentTyp, Form()],
    abteilung_id: Annotated[str, Form()] = "",
    notiz: Annotated[str, Form()] = "",
):
    _abt_id = int(abteilung_id) if typ == AssignmentTyp.ABTEILUNG and abteilung_id else None

    existing = db.exec(
        select(Assignment).where(
            Assignment.trainee_id == trainee_id,
            Assignment.kw == kw,
            Assignment.jahr == jahr,
        )
    ).first()

    if existing:
        existing.typ = typ
        existing.abteilung_id = _abt_id
        existing.notiz = notiz
        existing.source = AssignmentSource.MANUAL
    else:
        db.add(Assignment(
            trainee_id=trainee_id,
            schoolyear_id=schoolyear_id,
            kw=kw,
            jahr=jahr,
            typ=typ,
            abteilung_id=_abt_id,
            notiz=notiz,
            source=AssignmentSource.MANUAL,
        ))
    db.commit()

    return _render_cell_response(request, db, trainee_id, schoolyear_id, kw, jahr)


@router.post("/cell-delete", response_class=HTMLResponse)
def cell_delete(
    request: Request,
    db: DB,
    assignment_id: Annotated[int, Form()],
    trainee_id: Annotated[int, Form()],
    schoolyear_id: Annotated[str, Form()],
    kw: Annotated[int, Form()],
    jahr: Annotated[int, Form()],
):
    a = db.get(Assignment, assignment_id)
    if a:
        db.delete(a)
        db.commit()
    return _render_cell_response(request, db, trainee_id, schoolyear_id, kw, jahr)


# ── Copy (Drag & Drop) ────────────────────────────────────────────────────────

@router.post("/copy", response_class=HTMLResponse)
def copy_assignment(
    request: Request,
    db: DB,
    src_trainee_id: Annotated[int, Form()],
    src_kw: Annotated[int, Form()],
    src_jahr: Annotated[int, Form()],
    dst_trainee_id: Annotated[int, Form()],
    dst_kw: Annotated[int, Form()],
    dst_jahr: Annotated[int, Form()],
    schoolyear_id: Annotated[str, Form()],
):
    # no-op wenn Quelle == Ziel
    if (src_trainee_id == dst_trainee_id and src_kw == dst_kw and src_jahr == dst_jahr):
        return _render_cell_response(request, db, dst_trainee_id, schoolyear_id, dst_kw, dst_jahr)

    # Quelle laden
    src = db.exec(
        select(Assignment).where(
            Assignment.trainee_id == src_trainee_id,
            Assignment.kw == src_kw,
            Assignment.jahr == src_jahr,
            Assignment.schoolyear_id == schoolyear_id,
        )
    ).first()
    if not src:
        from fastapi.responses import Response
        return Response(status_code=400)

    # Ziel anlegen oder überschreiben
    dst = db.exec(
        select(Assignment).where(
            Assignment.trainee_id == dst_trainee_id,
            Assignment.kw == dst_kw,
            Assignment.jahr == dst_jahr,
            Assignment.schoolyear_id == schoolyear_id,
        )
    ).first()

    if dst:
        dst.typ = src.typ
        dst.abteilung_id = src.abteilung_id
        dst.source = AssignmentSource.MANUAL
        dst.notiz = ""
    else:
        db.add(Assignment(
            trainee_id=dst_trainee_id,
            schoolyear_id=schoolyear_id,
            kw=dst_kw,
            jahr=dst_jahr,
            typ=src.typ,
            abteilung_id=src.abteilung_id,
            source=AssignmentSource.MANUAL,
            notiz="",
        ))
    db.commit()

    return _render_cell_response(request, db, dst_trainee_id, schoolyear_id, dst_kw, dst_jahr)


def _render_cell_response(
    request: Request,
    db: Session,
    trainee_id: int,
    schoolyear_id: str,
    kw: int,
    jahr: int,
) -> HTMLResponse:
    assignment = db.exec(
        select(Assignment).where(
            Assignment.trainee_id == trainee_id,
            Assignment.kw == kw,
            Assignment.jahr == jahr,
        )
    ).first()

    trainee = db.get(Trainee, trainee_id)
    klasse_id = trainee.klasse_id if trainee else None

    school_week = False
    if klasse_id:
        plan = db.exec(
            select(SchoolPlan).where(
                SchoolPlan.klasse_id == klasse_id,
                SchoolPlan.schoolyear_id == schoolyear_id,
            )
        ).first()
        if plan:
            school_week = bool(db.exec(
                select(SchoolPlanWeek).where(
                    SchoolPlanWeek.plan_id == plan.id,
                    SchoolPlanWeek.kw == kw,
                    SchoolPlanWeek.jahr == jahr,
                )
            ).first())

    raw_conflicts = find_conflicts(db, schoolyear_id)
    is_conflict = any(
        c.kw == kw and c.jahr == jahr
        and (c.trainee_id == trainee_id or trainee_id in c.trainee_ids)
        for c in raw_conflicts
    )
    conflict_count = len(raw_conflicts)
    all_depts = db.exec(select(Department)).all()
    depts = {d.id: d for d in all_depts}
    dept_colors = department_color_map(all_depts)

    cell_html = templates.get_template("_partials/cell.html").render({
        "trainee_id": trainee_id,
        "kw": kw,
        "jahr": jahr,
        "schoolyear_id": schoolyear_id,
        "a": assignment,
        "is_school": school_week,
        "is_conflict": is_conflict,
        "depts": depts,
        "dept_colors": dept_colors,
    })

    counter_html = templates.get_template("_partials/conflict_counter.html").render({
        "conflict_count": conflict_count,
        "selected_year": schoolyear_id,
    })

    return HTMLResponse(cell_html + counter_html)
