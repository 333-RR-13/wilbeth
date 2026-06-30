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
from app.models import Schoolyear, Trainee, TraineeClass, TraineeRolle
from app.models.trainee_class_membership import TraineeClassMembership
from app.services.membership_utils import klasse_fuer, next_class_for, upsert_membership
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
    trainees = db.exec(
        select(Trainee)
        .where(Trainee.aktiv == True)  # noqa: E712
        .order_by(Trainee.nachname, Trainee.vorname)
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

    all_classes = list(classes_by_id.values())
    zu_uebertragen: list[dict] = []
    abschluss: list[dict] = []

    for trainee in trainees:
        # Klasse im Quell-Lehrjahr: Membership oder Fallback trainee.klasse_id
        klasse_id = klasse_fuer(db, trainee, source_year_id)
        klasse = classes_by_id.get(klasse_id) if klasse_id is not None else None
        if klasse is None:
            continue

        next_klasse = next_class_for(klasse, all_classes)
        if next_klasse is not None:
            zu_uebertragen.append({
                "trainee": trainee,
                "alte_klasse": klasse,
                "neue_klasse": next_klasse,
                "already_exists": trainee.id in existing_targets,
            })
        elif trainee.rolle == TraineeRolle.AZUBI:
            # Nur Azubis ohne naechste Klasse gelten als Abschluss.
            # Studierende (DH_STUDENT) u. a. laufen einfach weiter -> nicht
            # archivieren, nicht transferieren.
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

    trainees = db.exec(
        select(Trainee).where(Trainee.aktiv == True)  # noqa: E712
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

    all_classes = list(classes_by_id.values())
    count_new = 0
    count_skipped = 0

    for trainee in trainees:
        # Klasse im Quell-Lehrjahr (Membership oder Fallback trainee.klasse_id)
        klasse_id = klasse_fuer(db, trainee, source_year_id)
        klasse = classes_by_id.get(klasse_id) if klasse_id is not None else None
        next_klasse = next_class_for(klasse, all_classes) if klasse is not None else None
        if klasse is None or next_klasse is None:
            # Keine Klasse oder Abschluss – nicht uebernehmen
            continue

        if trainee.id in existing_targets:
            count_skipped += 1
            continue

        # Quell-Lehrjahr festschreiben, damit es nach der klasse_id-Aenderung
        # korrekt bleibt (sonst lieferte der Fallback spaeter die neue Klasse).
        upsert_membership(db, trainee.id, source_year_id, klasse.id)
        # Neue Membership im Ziel-Lehrjahr anlegen
        db.add(TraineeClassMembership(
            trainee_id=trainee.id,
            schoolyear_id=target_year_id,
            klasse_id=next_klasse.id,
        ))
        # trainee.klasse_id auf neue Klasse setzen (= aktuelle Klasse)
        trainee.klasse_id = next_klasse.id
        db.add(trainee)
        count_new += 1

    db.commit()

    # Abschluss-Azubis deaktivieren: aktive Azubis, deren Quell-Klasse kein
    # next_class hat (= Abschluss) UND die nicht bereits promotet wurden.
    # Frisch promotete Azubis haben jetzt eine Membership im Ziel-Jahr, daher
    # reicht es, alle aktiven Azubis zu pruefen, deren Quell-Klasse None -> kein next.
    count_archived = 0
    trainees_after = db.exec(
        select(Trainee).where(Trainee.aktiv == True)  # noqa: E712
    ).all()
    classes_by_id_after: dict[int, TraineeClass] = {
        c.id: c for c in db.exec(select(TraineeClass)).all()
    }
    all_classes_after = list(classes_by_id_after.values())

    for trainee in trainees_after:
        # Nur Azubis duerfen automatisch archiviert werden. Studierende
        # (DH_STUDENT) und andere Nicht-Azubi-Rollen haben kein LJ-Muster und
        # wuerden sonst faelschlich als "Abschluss" deaktiviert.
        if trainee.rolle != TraineeRolle.AZUBI:
            continue
        klasse_id = klasse_fuer(db, trainee, source_year_id)
        klasse = classes_by_id_after.get(klasse_id) if klasse_id is not None else None
        if klasse is None:
            continue
        next_klasse = next_class_for(klasse, all_classes_after)
        if next_klasse is None:
            # Abschluss-Azubi → archivieren
            trainee.aktiv = False
            db.add(trainee)
            count_archived += 1

    db.commit()

    # Schulwochen fuer das Ziel-Jahr materialisieren
    resync_all(db)

    detail = f"{count_new}+neue,{count_skipped}+übersprungen,{count_archived}+archiviert"
    return RedirectResponse(
        f"/jahreswechsel/?msg=created&detail={detail}&source_year_id={source_year_id}&target_year_id={target_year_id}",
        status_code=303,
    )
