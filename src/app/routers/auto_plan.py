"""Auto-Plan Router.

Endpunkte:
  GET  /auto-plan          -> rendert die Auto-Plan-Seite
  POST /auto-plan/preview  -> Vorschau-Partial (kein DB-Write)
  POST /auto-plan/apply    -> schreibt Assignments, PRG-Redirect
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import Department, Schoolyear, Trainee, TraineeClass
from app.services.auth_service import CurrentUser, require_roles
from app.services.auto_plan import apply_auto_plan, plan_assignments

router = APIRouter(tags=["auto_plan"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


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


@router.get("/auto-plan", response_class=HTMLResponse)
def auto_plan_index(
    request: Request, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """Zeigt die Auto-Plan-Seite mit Lehrjahr-Auswahl, Azubi-Liste und Block-Länge."""
    schoolyear_id = request.query_params.get("schoolyear_id", "")
    msg = request.query_params.get("msg", "")

    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    classes = db.exec(select(TraineeClass).order_by(TraineeClass.name)).all()

    if not schoolyear_id and years:
        schoolyear_id = years[0].id

    trainees = db.exec(
        select(Trainee)
        .where(Trainee.aktiv == True)  # noqa: E712
        .order_by(Trainee.nachname, Trainee.vorname)
    ).all()

    return templates.TemplateResponse(request, "auto_plan/index.html", {
        "years": years,
        "classes": classes,
        "trainees": trainees,
        "selected_year": schoolyear_id,
        "msg": msg,
        "active_nav": "auto_plan",
    })


@router.post("/auto-plan/preview", response_class=HTMLResponse)
async def auto_plan_preview(
    request: Request, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
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
        "auto_plan/_preview.html",
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


@router.post("/auto-plan/apply", response_class=RedirectResponse)
async def auto_plan_apply(
    request: Request, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """Berechnet Auto-Plan und schreibt ihn als Assignment(source=AUTO) in die DB.

    Danach PRG-Redirect auf /auto-plan mit ?msg=... .
    """
    await request.form()
    schoolyear_id, trainee_ids, block_length = _parse_auto_plan_params(request)

    plan_result = apply_auto_plan(db, schoolyear_id, trainee_ids, block_length)

    n = len(plan_result.planned)
    msg = f"Auto-Plan: {n} Einsatz{'e' if n != 1 else ''} angelegt."

    redirect_url = f"/auto-plan?schoolyear_id={schoolyear_id}&msg={msg}"
    return RedirectResponse(redirect_url, status_code=303)
