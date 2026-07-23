"""Ausbilder-Selbstbedienung: eigene Abteilung(en) einsehen + Bloecke bestaetigen.

- GET  /meine-abteilung/          -> je verantworteter Abteilung die offenen
  Bloecke (assignment_blocks) + Formular zum Einsatz-Vorschlagen + eigene
  eingereichte Vorschlaege.
- POST /meine-abteilung/block     -> Block (mehrere Assignment-Zellen) auf
  einen Schlag bestaetigen/ablehnen (+ Notiz/Feedback). Nur fuer Bloecke der
  eigenen (verantworteten) Abteilungen.
- POST /meine-abteilung/vorschlag -> Einsatz fuer einen Trainee in der
  eigenen Abteilung vorschlagen (EinsatzVorschlag, status=offen); von
  Orga/Admin unter /vorschlaege/ anzunehmen oder abzulehnen.

Sicherheit: allowed_dept_ids(db, user) ist in beiden POST-Routen die alleinige
Quelle der Wahrheit fuer "eigene Abteilung" -- jede Abweichung ist ein 403.
"""
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
    AssignmentTyp,
    Department,
    EinsatzVorschlag,
    Schoolyear,
    Trainee,
)
from app.services.auth_service import CurrentUser, allowed_dept_ids, require_roles
from app.services.block_utils import apply_to_block, assignment_blocks
from app.services.membership_utils import aktuelles_schuljahr_id
from app.utils.kw import iter_schoolyear_weeks

router = APIRouter(prefix="/meine-abteilung", tags=["meine-abteilung"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


# ── Uebersicht ────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def meine_abteilung(
    request: Request,
    db: DB,
    user: Annotated[CurrentUser, Depends(require_roles("ausbilder", "orga", "admin"))],
):
    dept_ids = allowed_dept_ids(db, user)

    years = db.exec(
        select(Schoolyear)
        .where(Schoolyear.archiviert == False)  # noqa: E712
        .order_by(Schoolyear.start_year.desc())
    ).all()
    schoolyear_id = request.query_params.get("schoolyear_id", "")
    if not schoolyear_id:
        # Default = das Ausbildungsjahr, in dem HEUTE liegt (nicht das neueste --
        # ein bereits angelegtes Folgejahr hat noch keine Einsaetze und wuerde
        # eine leere Seite zeigen). Fallback: neuestes nicht-archiviertes Jahr.
        schoolyear_id = aktuelles_schuljahr_id(db)

    if not dept_ids:
        return templates.TemplateResponse(request, "ausbilder/meine_abteilung.html", {
            "no_dept": True,
            "user": user,
            "years": years,
            "selected_year": schoolyear_id,
            "active_nav": "meine_abteilung",
        })

    depts = db.exec(
        select(Department).where(Department.id.in_(list(dept_ids))).order_by(Department.code)
    ).all()

    dept_blocks = []
    offen_count = 0
    for d in depts:
        blocks = assignment_blocks(db, d.id, schoolyear_id) if schoolyear_id else []
        offen_count += sum(1 for b in blocks if b["status"] == "offen")
        dept_blocks.append({"dept": d, "blocks": blocks})

    trainees = db.exec(
        select(Trainee).where(Trainee.aktiv == True)  # noqa: E712
        .order_by(Trainee.nachname, Trainee.vorname)
    ).all()

    own_vorschlaege = db.exec(
        select(EinsatzVorschlag)
        .where(EinsatzVorschlag.eingereicht_von_upn == user.upn)
    ).all()
    own_vorschlaege = sorted(
        own_vorschlaege,
        key=lambda v: (v.erstellt_am or date.min, v.id or 0),
        reverse=True,
    )

    trainee_map = {t.id: t for t in db.exec(select(Trainee)).all()}
    dept_map = {d.id: d for d in db.exec(select(Department)).all()}

    return templates.TemplateResponse(request, "ausbilder/meine_abteilung.html", {
        "no_dept": False,
        "user": user,
        "dept_blocks": dept_blocks,
        "offen_count": offen_count,
        "trainees": trainees,
        "years": years,
        "selected_year": schoolyear_id,
        "own_vorschlaege": own_vorschlaege,
        "trainee_map": trainee_map,
        "dept_map": dept_map,
        "active_nav": "meine_abteilung",
    })


# ── Block bestaetigen/ablehnen ───────────────────────────────────────────

@router.post("/block", response_class=RedirectResponse)
def block_action(
    db: DB,
    user: Annotated[CurrentUser, Depends(require_roles("ausbilder", "orga", "admin"))],
    assignment_ids: Annotated[str, Form()],
    aktion: Annotated[str, Form()],
    notiz: Annotated[str, Form()] = "",
    feedback: Annotated[str, Form()] = "",
    schoolyear_id: Annotated[str, Form()] = "",
):
    if aktion not in ("bestaetigt", "abgelehnt"):
        raise HTTPException(status_code=400, detail="Unbekannte Aktion")

    ids = [int(x) for x in assignment_ids.split(",") if x.strip().isdigit()]
    if not ids:
        raise HTTPException(status_code=400, detail="Keine Assignment-IDs")

    allowed = allowed_dept_ids(db, user)
    rows = db.exec(
        select(Assignment).where(Assignment.id.in_(ids))  # type: ignore[union-attr]
    ).all()
    if len(rows) != len(ids):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")
    for a in rows:
        if a.typ != AssignmentTyp.ABTEILUNG or a.abteilung_id not in allowed:
            raise HTTPException(status_code=403, detail="Keine Berechtigung")

    apply_to_block(
        db,
        ids,
        bestaetigung=aktion,
        notiz=notiz if notiz.strip() else None,
        feedback=feedback if feedback.strip() else None,
    )

    url = "/meine-abteilung/"
    if schoolyear_id:
        url += f"?schoolyear_id={schoolyear_id}"
    return RedirectResponse(url, status_code=303)


# ── Einsatz vorschlagen ───────────────────────────────────────────────────

@router.post("/vorschlag", response_class=RedirectResponse)
def create_vorschlag(
    db: DB,
    user: Annotated[CurrentUser, Depends(require_roles("ausbilder", "orga", "admin"))],
    trainee_id: Annotated[int, Form()],
    department_id: Annotated[int, Form()],
    schoolyear_id: Annotated[str, Form()],
    kw_von: Annotated[int, Form()],
    jahr_von: Annotated[int, Form()],
    kw_bis: Annotated[int, Form()],
    jahr_bis: Annotated[int, Form()],
    kommentar: Annotated[str, Form()] = "",
):
    if department_id not in allowed_dept_ids(db, user):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    sy = db.get(Schoolyear, schoolyear_id)
    if sy is None:
        return RedirectResponse(
            f"/meine-abteilung/?msg=error&schoolyear_id={schoolyear_id}", status_code=303
        )

    week_idx = {
        wk: i
        for i, wk in enumerate(
            iter_schoolyear_weeks(sy.start_kw, sy.start_year, sy.end_kw, sy.end_year)
        )
    }
    idx_von = week_idx.get((kw_von, jahr_von))
    idx_bis = week_idx.get((kw_bis, jahr_bis))
    if idx_von is None or idx_bis is None or idx_von > idx_bis:
        return RedirectResponse(
            f"/meine-abteilung/?msg=error&schoolyear_id={schoolyear_id}", status_code=303
        )

    db.add(EinsatzVorschlag(
        trainee_id=trainee_id,
        department_id=department_id,
        schoolyear_id=schoolyear_id,
        kw_von=kw_von,
        jahr_von=jahr_von,
        kw_bis=kw_bis,
        jahr_bis=jahr_bis,
        kommentar=kommentar,
        eingereicht_von_upn=user.upn,
        eingereicht_von_name=user.name,
        status="offen",
        erstellt_am=date.today(),
    ))
    db.commit()

    return RedirectResponse(
        f"/meine-abteilung/?msg=created&schoolyear_id={schoolyear_id}", status_code=303
    )
