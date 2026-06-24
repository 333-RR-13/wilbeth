"""Globaler Jahreswechsel: Memberships vom Quell- ins Ziel-Lehrjahr uebertragen.

Logik:
- Fuer jede Membership im Quell-Lehrjahr, deren Klasse ein next_class_id hat,
  wird eine neue Membership (trainee, Ziel-Jahr, next_class) angelegt.
- Klassen ohne next_class_id (Abschluss) werden nicht uebernommen.
- Bereits vorhandene Memberships fuer (trainee, Ziel-Jahr) werden uebersprungen.
- Nach dem Uebernehmen: trainee.klasse_id = neue Klasse + resync_all.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import Schoolyear, Trainee, TraineeClass
from app.models.trainee_class_membership import TraineeClassMembership
from app.services.school_sync import resync_all

router = APIRouter(prefix="/jahreswechsel", tags=["jahreswechsel"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


def _build_preview(
    db: Session,
    source_year_id: str,
    target_year_id: str,
) -> tuple[list[dict], list[dict]]:
    """Berechnet Vorschau: (zu_uebertragen, abschluss).

    Gibt zwei Listen zurueck:
    - zu_uebertragen: Dicts mit trainee/alte Klasse/neue Klasse
    - abschluss: Dicts mit trainee/Klasse (kein next_class_id)
    """
    memberships = db.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.schoolyear_id == source_year_id
        )
    ).all()

    trainees_by_id: dict[int, Trainee] = {
        t.id: t for t in db.exec(select(Trainee)).all()
    }
    classes_by_id: dict[int, TraineeClass] = {
        c.id: c for c in db.exec(select(TraineeClass)).all()
    }

    # Bestehende Memberships im Ziel-Jahr
    existing_targets: set[int] = {
        m.trainee_id
        for m in db.exec(
            select(TraineeClassMembership).where(
                TraineeClassMembership.schoolyear_id == target_year_id
            )
        ).all()
    }

    zu_uebertragen: list[dict] = []
    abschluss: list[dict] = []

    for m in memberships:
        trainee = trainees_by_id.get(m.trainee_id)
        klasse = classes_by_id.get(m.klasse_id)
        if trainee is None or klasse is None:
            continue

        if klasse.next_class_id is not None:
            next_klasse = classes_by_id.get(klasse.next_class_id)
            zu_uebertragen.append({
                "trainee": trainee,
                "alte_klasse": klasse,
                "neue_klasse": next_klasse,
                "already_exists": m.trainee_id in existing_targets,
            })
        else:
            abschluss.append({
                "trainee": trainee,
                "klasse": klasse,
            })

    return zu_uebertragen, abschluss


@router.get("/", response_class=HTMLResponse)
def jahreswechsel_form(request: Request, db: DB):
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    source_year_id = request.query_params.get("source_year_id", "")
    target_year_id = request.query_params.get("target_year_id", "")

    preview_transfer: list[dict] = []
    preview_abschluss: list[dict] = []

    if source_year_id and target_year_id and source_year_id != target_year_id:
        preview_transfer, preview_abschluss = _build_preview(db, source_year_id, target_year_id)

    return templates.TemplateResponse(request, "jahreswechsel/form.html", {
        "years": years,
        "source_year_id": source_year_id,
        "target_year_id": target_year_id,
        "preview_transfer": preview_transfer,
        "preview_abschluss": preview_abschluss,
        "active_nav": "jahreswechsel",
    })


@router.post("/uebernehmen", response_class=RedirectResponse)
def jahreswechsel_uebernehmen(
    db: DB,
    source_year_id: Annotated[str, Form()],
    target_year_id: Annotated[str, Form()],
):
    if not source_year_id or not target_year_id or source_year_id == target_year_id:
        return RedirectResponse("/jahreswechsel/?msg=error&detail=Ungültige+Jahresauswahl", status_code=303)

    memberships = db.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.schoolyear_id == source_year_id
        )
    ).all()

    classes_by_id: dict[int, TraineeClass] = {
        c.id: c for c in db.exec(select(TraineeClass)).all()
    }

    # Bestehende Memberships im Ziel-Jahr
    existing_targets: set[int] = {
        m.trainee_id
        for m in db.exec(
            select(TraineeClassMembership).where(
                TraineeClassMembership.schoolyear_id == target_year_id
            )
        ).all()
    }

    count_new = 0
    count_skipped = 0

    for m in memberships:
        klasse = classes_by_id.get(m.klasse_id)
        if klasse is None or klasse.next_class_id is None:
            # Abschluss – nicht uebernehmen
            continue

        if m.trainee_id in existing_targets:
            count_skipped += 1
            continue

        # Neue Membership anlegen
        db.add(TraineeClassMembership(
            trainee_id=m.trainee_id,
            schoolyear_id=target_year_id,
            klasse_id=klasse.next_class_id,
        ))
        # trainee.klasse_id auf neue Klasse setzen
        trainee = db.get(Trainee, m.trainee_id)
        if trainee:
            trainee.klasse_id = klasse.next_class_id
            db.add(trainee)
        count_new += 1

    db.commit()

    # Schulwochen fuer das Ziel-Jahr materialisieren
    resync_all(db)

    detail = f"{count_new}+neue,{count_skipped}+übersprungen"
    return RedirectResponse(
        f"/jahreswechsel/?msg=created&detail={detail}&source_year_id={source_year_id}&target_year_id={target_year_id}",
        status_code=303,
    )
