"""Jahresabschluss: Ein Ausbildungsjahr archivieren.

Logik:
- GET  /jahresabschluss     -> Formular: Auswahl eines nicht-archivierten Jahres,
                               Vorschau der Azubis die mit diesem Jahr ihren
                               Abschluss machen (klasse_fuer Folgejahr == None).
- POST /jahresabschluss/abschliessen -> setzt Schoolyear.archiviert = True (commit).

Klassen ruecken automatisch vor (berechnet via klasse_fuer) - kein manuelles
Materialisieren von Memberships noetig.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import Schoolyear, Trainee, TraineeClass, TraineeRolle
from app.services.membership_utils import klasse_fuer

router = APIRouter(prefix="/jahresabschluss", tags=["jahresabschluss"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


def _absolventen_vorschau(
    db: Session,
    schoolyear_id: str,
) -> list[dict]:
    """Gibt eine Liste von AZUBIs zurueck, die mit dem Abschluss dieses Jahres
    ihren Abschluss machen (klasse_fuer im Folgejahr == None).

    Das Folgejahr wird hier nicht benoetigt - es reicht zu pruefen ob
    klasse_fuer(db, trainee, schoolyear_id) eine Klasse liefert, die kein
    next_class_for hat (d.h. Absolvent im Sinne des berechneten Modells).

    Konkret: klasse_fuer fuer das abzuschliessende Jahr liefert eine Klasse,
    und die naechste Klasse existiert nicht -> Abschluss.
    Alternativ: klasse_fuer liefert None -> vor Beginn oder bereits Absolvent.

    Wir listen alle aktiven AZUBIs, bei denen klasse_fuer(year_id) nicht None
    ist, aber kein next_class existiert.
    """
    from app.services.membership_utils import next_class_for

    trainees = db.exec(
        select(Trainee)
        .where(Trainee.aktiv == True)  # noqa: E712
        .where(Trainee.rolle == TraineeRolle.AZUBI)
        .order_by(Trainee.nachname, Trainee.vorname)
    ).all()
    all_classes: list[TraineeClass] = list(db.exec(select(TraineeClass)).all())
    classes_by_id: dict[int, TraineeClass] = {c.id: c for c in all_classes}

    absolventen: list[dict] = []
    for trainee in trainees:
        klasse_id = klasse_fuer(db, trainee, schoolyear_id)
        if klasse_id is None:
            continue
        klasse = classes_by_id.get(klasse_id)
        if klasse is None:
            continue
        next_k = next_class_for(klasse, all_classes)
        if next_k is None:
            absolventen.append({"trainee": trainee, "klasse": klasse})

    return absolventen


@router.get("/", response_class=HTMLResponse)
def jahresabschluss_form(request: Request, db: DB):
    years = db.exec(
        select(Schoolyear)
        .where(Schoolyear.archiviert == False)  # noqa: E712
        .order_by(Schoolyear.start_year.desc())
    ).all()
    selected_year_id = request.query_params.get("schoolyear_id", "")

    absolventen: list[dict] = []
    if selected_year_id:
        absolventen = _absolventen_vorschau(db, selected_year_id)

    return templates.TemplateResponse(request, "jahreswechsel/form.html", {
        "years": years,
        "selected_year_id": selected_year_id,
        "absolventen": absolventen,
        "active_nav": "jahreswechsel",
    })


@router.post("/abschliessen", response_class=RedirectResponse)
def jahresabschluss_abschliessen(
    db: DB,
    schoolyear_id: Annotated[str, Form()],
):
    if not schoolyear_id:
        return RedirectResponse(
            "/jahresabschluss/?msg=error&detail=Kein+Ausbildungsjahr+angegeben",
            status_code=303,
        )

    year = db.get(Schoolyear, schoolyear_id)
    if year is None:
        return RedirectResponse(
            "/jahresabschluss/?msg=error&detail=Ausbildungsjahr+nicht+gefunden",
            status_code=303,
        )
    if year.archiviert:
        return RedirectResponse(
            f"/jahresabschluss/?msg=error&detail=Jahr+{schoolyear_id}+ist+bereits+archiviert",
            status_code=303,
        )

    year.archiviert = True
    db.add(year)
    db.commit()

    return RedirectResponse(
        f"/jahresabschluss/?msg=created&detail=Jahr+{schoolyear_id}+wurde+archiviert",
        status_code=303,
    )
