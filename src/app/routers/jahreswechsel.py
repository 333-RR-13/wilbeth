"""Jahresabschluss: Ein Ausbildungsjahr archivieren.

Logik:
- GET  /jahresabschluss     -> Formular: Auswahl eines nicht-archivierten Jahres,
                               Vorschau aller aktiven Trainees mit aktueller Klasse,
                               Sonderfall-Editor (wiederholt / wechselt / abbruch).
- POST /jahresabschluss/abschliessen -> wertet je Trainee die gewaehlte Aktion aus
                               (standard/absolvent/wiederholt/wechselt/abbruch),
                               setzt Schoolyear.archiviert = True (commit).

Klassen ruecken automatisch vor (berechnet via klasse_fuer) - kein manuelles
Materialisieren von Memberships noetig, ausser bei Override-Aktionen.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import Schoolyear, Trainee, TraineeClass, TraineeRolle
from app.services.membership_utils import klasse_fuer, next_class_for, upsert_membership

router = APIRouter(prefix="/jahresabschluss", tags=["jahresabschluss"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


def _get_folgejahr(db: Session, closing_start_year: int) -> Schoolyear | None:
    """Gibt das Schoolyear mit start_year == closing_start_year + 1 zurueck (oder None)."""
    return db.exec(
        select(Schoolyear).where(Schoolyear.start_year == closing_start_year + 1)
    ).first()


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


def _trainee_vorschau(
    db: Session,
    schoolyear_id: str,
) -> list[dict]:
    """Vorschau-Liste aller aktiven Trainees fuer den Sonderfall-Editor.

    Fuer jeden aktiven Trainee:
      - trainee
      - klasse (TraineeClass oder None)
      - klasse_id (int oder None)
      - folge_klasse_name (str: Name der Folgeklasse, "Abschluss/Archiv" wenn Absolvent, None wenn keine Klasse)
      - is_absolvent (bool)
    """
    trainees = db.exec(
        select(Trainee)
        .where(Trainee.aktiv == True)  # noqa: E712
        .order_by(Trainee.nachname, Trainee.vorname)
    ).all()
    all_classes: list[TraineeClass] = list(db.exec(select(TraineeClass)).all())
    classes_by_id: dict[int, TraineeClass] = {c.id: c for c in all_classes}

    rows: list[dict] = []
    for trainee in trainees:
        klasse_id = klasse_fuer(db, trainee, schoolyear_id)
        klasse = classes_by_id.get(klasse_id) if klasse_id is not None else None
        is_absolvent = False
        folge_klasse_name: str | None = None

        if klasse is not None:
            next_k = next_class_for(klasse, all_classes)
            if next_k is None and trainee.rolle == TraineeRolle.AZUBI:
                is_absolvent = True
                folge_klasse_name = "Abschluss/Archiv"
            elif next_k is not None:
                folge_klasse_name = next_k.name

        rows.append({
            "trainee": trainee,
            "klasse": klasse,
            "klasse_id": klasse_id,
            "folge_klasse_name": folge_klasse_name,
            "is_absolvent": is_absolvent,
        })

    return rows


@router.get("/", response_class=HTMLResponse)
def jahresabschluss_form(request: Request, db: DB):
    years = db.exec(
        select(Schoolyear)
        .where(Schoolyear.archiviert == False)  # noqa: E712
        .order_by(Schoolyear.start_year.desc())
    ).all()
    selected_year_id = request.query_params.get("schoolyear_id", "")

    absolventen: list[dict] = []
    trainee_rows: list[dict] = []
    folgejahr_fehlt = False
    closing_year: Schoolyear | None = None

    if selected_year_id:
        closing_year = db.get(Schoolyear, selected_year_id)
        if closing_year is not None:
            absolventen = _absolventen_vorschau(db, selected_year_id)
            trainee_rows = _trainee_vorschau(db, selected_year_id)
            folgejahr = _get_folgejahr(db, closing_year.start_year)
            folgejahr_fehlt = folgejahr is None

    all_classes: list[TraineeClass] = list(db.exec(select(TraineeClass)).all())

    return templates.TemplateResponse(request, "jahreswechsel/form.html", {
        "years": years,
        "selected_year_id": selected_year_id,
        "absolventen": absolventen,
        "trainee_rows": trainee_rows,
        "folgejahr_fehlt": folgejahr_fehlt,
        "all_classes": all_classes,
        "active_nav": "jahreswechsel",
    })


@router.post("/abschliessen", response_class=RedirectResponse)
async def jahresabschluss_abschliessen(
    request: Request,
    db: DB,
):
    form = await request.form()
    schoolyear_id = form.get("schoolyear_id", "")

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

    # (1) Closing year archivieren
    year.archiviert = True
    db.add(year)

    # (2) Folgejahr ermitteln
    folgejahr = _get_folgejahr(db, year.start_year)
    folgejahr_id: str | None = folgejahr.id if folgejahr is not None else None

    # (3) Alle aktiven Trainees verarbeiten
    trainees = db.exec(
        select(Trainee).where(Trainee.aktiv == True)  # noqa: E712
    ).all()

    all_classes: list[TraineeClass] = list(db.exec(select(TraineeClass)).all())
    classes_by_id: dict[int, TraineeClass] = {c.id: c for c in all_classes}

    count_archiviert = 0
    count_overrides = 0

    for trainee in trainees:
        aktion = str(form.get(f"aktion_{trainee.id}", "standard"))
        klasse_id = klasse_fuer(db, trainee, schoolyear_id)
        klasse = classes_by_id.get(klasse_id) if klasse_id is not None else None

        if aktion == "abbruch":
            trainee.aktiv = False
            db.add(trainee)
            count_archiviert += 1

        elif aktion == "wiederholt":
            if folgejahr_id is not None and klasse_id is not None:
                upsert_membership(db, trainee.id, folgejahr_id, klasse_id)
                count_overrides += 1

        elif aktion == "wechselt":
            wechsel_raw = form.get(f"wechsel_klasse_{trainee.id}", "")
            if folgejahr_id is not None and wechsel_raw:
                try:
                    wechsel_klasse_id = int(wechsel_raw)
                    upsert_membership(db, trainee.id, folgejahr_id, wechsel_klasse_id)
                    count_overrides += 1
                except (ValueError, TypeError):
                    pass  # ungueltige Klassen-ID ignorieren

        else:
            # "standard" oder leer
            if trainee.rolle == TraineeRolle.AZUBI and klasse is not None:
                next_k = next_class_for(klasse, all_classes)
                if next_k is None:
                    # Absolvent -> Auto-Archiv
                    trainee.aktiv = False
                    db.add(trainee)
                    count_archiviert += 1
            # Nicht-AZUBI und Nicht-Absolvent: nichts tun, rueckt automatisch auf

    db.commit()

    detail = f"{count_archiviert}+archiviert,+{count_overrides}+Overrides"
    return RedirectResponse(
        f"/jahresabschluss/?msg=created&detail={detail}",
        status_code=303,
    )
