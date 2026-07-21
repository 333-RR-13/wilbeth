"""Orga/Admin-Verwaltung der von Ausbildern eingereichten Einsatz-Vorschlaege.

- GET  /vorschlaege/            -> alle EinsatzVorschlag, offene zuerst.
- POST /vorschlaege/{id}/annehmen  -> legt Assignments fuer jede noch freie
  Woche des vorgeschlagenen Zeitraums an (typ=ABTEILUNG, source=MANUAL,
  bestaetigung=bestaetigt -- der vorschlagende Ausbilder hat den Einsatz
  bereits selbst gewollt); bereits belegte Wochen werden uebersprungen und im
  antwort_kommentar aufgelistet.
- POST /vorschlaege/{id}/ablehnen -> setzt status=abgelehnt + Kommentar.
"""
import urllib.parse
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
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
    EinsatzVorschlag,
    Schoolyear,
    Trainee,
)
from app.services.auth_service import CurrentUser, require_roles
from app.utils.kw import iter_schoolyear_weeks

router = APIRouter(prefix="/vorschlaege", tags=["vorschlaege"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


# ── Liste ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def list_vorschlaege(
    request: Request,
    db: DB,
    user: Annotated[CurrentUser, Depends(require_roles("orga", "admin"))],
):
    rows = db.exec(select(EinsatzVorschlag)).all()

    def _sort_key(v: EinsatzVorschlag) -> tuple:
        offen_rang = 0 if v.status == "offen" else 1
        return (offen_rang, -(v.erstellt_am or date.min).toordinal(), -(v.id or 0))

    rows_sorted = sorted(rows, key=_sort_key)

    trainee_map = {t.id: t for t in db.exec(select(Trainee)).all()}
    dept_map = {d.id: d for d in db.exec(select(Department)).all()}

    return templates.TemplateResponse(request, "vorschlaege/list.html", {
        "vorschlaege": rows_sorted,
        "trainee_map": trainee_map,
        "dept_map": dept_map,
        "active_nav": "vorschlaege",
    })


# ── Annehmen ─────────────────────────────────────────────────────────────

@router.post("/{vorschlag_id:int}/annehmen", response_class=RedirectResponse)
def annehmen(
    vorschlag_id: int,
    db: DB,
    user: Annotated[CurrentUser, Depends(require_roles("orga", "admin"))],
):
    v = db.get(EinsatzVorschlag, vorschlag_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Vorschlag nicht gefunden")

    sy = db.get(Schoolyear, v.schoolyear_id)
    if sy is None:
        raise HTTPException(status_code=400, detail="Schuljahr nicht gefunden")

    weeks = list(iter_schoolyear_weeks(sy.start_kw, sy.start_year, sy.end_kw, sy.end_year))
    week_idx = {wk: i for i, wk in enumerate(weeks)}

    idx_von = week_idx.get((v.kw_von, v.jahr_von))
    idx_bis = week_idx.get((v.kw_bis, v.jahr_bis))
    if idx_von is None or idx_bis is None or idx_von > idx_bis:
        raise HTTPException(status_code=400, detail="Ungueltiger Zeitraum")

    target_weeks = weeks[idx_von : idx_bis + 1]

    created = 0
    skipped: list[str] = []
    for kw, jahr in target_weeks:
        existing = db.exec(
            select(Assignment).where(
                Assignment.trainee_id == v.trainee_id,
                Assignment.kw == kw,
                Assignment.jahr == jahr,
            )
        ).first()
        if existing is not None:
            skipped.append(f"KW {kw}/{jahr}")
            continue
        db.add(Assignment(
            trainee_id=v.trainee_id,
            schoolyear_id=v.schoolyear_id,
            kw=kw,
            jahr=jahr,
            typ=AssignmentTyp.ABTEILUNG,
            abteilung_id=v.department_id,
            source=AssignmentSource.MANUAL,
            bestaetigung="bestaetigt",
        ))
        created += 1

    detail = f"{created} Wochen angelegt"
    if skipped:
        detail += f"; belegt uebersprungen: {', '.join(skipped)}"
    else:
        detail += "; keine uebersprungen"

    v.status = "angenommen"
    v.antwort_kommentar = detail
    db.add(v)
    db.commit()

    enc = urllib.parse.quote(detail)
    return RedirectResponse(f"/vorschlaege/?msg=updated&detail={enc}", status_code=303)


# ── Ablehnen ─────────────────────────────────────────────────────────────

@router.post("/{vorschlag_id:int}/ablehnen", response_class=RedirectResponse)
def ablehnen(
    vorschlag_id: int,
    db: DB,
    user: Annotated[CurrentUser, Depends(require_roles("orga", "admin"))],
    kommentar: Annotated[str, Form()] = "",
):
    v = db.get(EinsatzVorschlag, vorschlag_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Vorschlag nicht gefunden")

    v.status = "abgelehnt"
    v.antwort_kommentar = kommentar
    db.add(v)
    db.commit()

    return RedirectResponse("/vorschlaege/?msg=updated", status_code=303)
