from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import Trainee, TraineeClass, UnterrichtsTyp
from app.utils.kw import WEEKDAY_LABELS, format_weekdays, parse_weekdays

router = APIRouter(prefix="/klassen", tags=["klassen"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


def _weekday_fields(
    unterrichts_typ: UnterrichtsTyp,
    wochentage: list[str],
    halbtag: str,
) -> tuple[str, int | None]:
    """Nur fuer TAGE_FEST werden Schultage gespeichert, sonst geleert."""
    if unterrichts_typ != UnterrichtsTyp.TAGE_FEST:
        return "", None
    days = sorted(int(w) for w in wochentage if w.isdigit())
    schul_wochentage = ",".join(str(d) for d in days)
    halbtag_wochentag = int(halbtag) if halbtag.isdigit() else None
    return schul_wochentage, halbtag_wochentag


@router.get("/", response_class=HTMLResponse)
def list_classes(request: Request, db: DB):
    classes = db.exec(select(TraineeClass).order_by(TraineeClass.name)).all()
    schul_labels = {
        c.id: format_weekdays(c.schul_wochentage, halbtag=c.halbtag_wochentag)
        for c in classes
    }
    return templates.TemplateResponse(request, "trainee_classes/list.html", {
        "classes": classes, "schul_labels": schul_labels, "active_nav": "klassen",
    })


@router.get("/neu", response_class=HTMLResponse)
def new_class(request: Request):
    return templates.TemplateResponse(request, "trainee_classes/form.html", {
        "cls": None, "typen": list(UnterrichtsTyp), "active_nav": "klassen",
        "weekday_labels": WEEKDAY_LABELS, "selected_weekdays": [],
    })


@router.post("/", response_class=RedirectResponse)
def create_class(
    db: DB,
    name: Annotated[str, Form()],
    berufsschule: Annotated[str, Form()],
    unterrichts_typ: Annotated[UnterrichtsTyp, Form()],
    wochentag: Annotated[list[str], Form()] = [],
    halbtag_wochentag: Annotated[str, Form()] = "",
):
    schul_wochentage, halbtag = _weekday_fields(unterrichts_typ, wochentag, halbtag_wochentag)
    db.add(TraineeClass(
        name=name,
        berufsschule=berufsschule,
        unterrichts_typ=unterrichts_typ,
        schul_wochentage=schul_wochentage,
        halbtag_wochentag=halbtag,
    ))
    db.commit()
    return RedirectResponse("/klassen/?msg=created", status_code=303)


@router.get("/{class_id:int}", response_class=HTMLResponse)
def detail_class(request: Request, class_id: int, db: DB):
    cls = db.get(TraineeClass, class_id)
    trainees = db.exec(select(Trainee).order_by(Trainee.nachname, Trainee.vorname)).all()
    all_classes = db.exec(select(TraineeClass)).all()
    class_names = {c.id: c.name for c in all_classes}
    schul_label = (
        format_weekdays(cls.schul_wochentage, halbtag=cls.halbtag_wochentag)
        if cls and cls.unterrichts_typ == UnterrichtsTyp.TAGE_FEST
        else None
    )
    return templates.TemplateResponse(request, "trainee_classes/detail.html", {
        "cls": cls,
        "trainees": trainees,
        "class_names": class_names,
        "schul_label": schul_label,
        "active_nav": "klassen",
    })


@router.post("/{class_id:int}/mitglieder", response_class=RedirectResponse)
def update_members(
    class_id: int,
    db: DB,
    mitglied: Annotated[list[str], Form()] = [],
):
    checked_ids = {int(i) for i in mitglied if i.isdigit()}
    trainees = db.exec(select(Trainee)).all()
    for t in trainees:
        if t.id in checked_ids:
            t.klasse_id = class_id
        elif t.klasse_id == class_id:
            t.klasse_id = None
    db.commit()
    return RedirectResponse(f"/klassen/{class_id}?msg=updated", status_code=303)


@router.get("/{class_id:int}/bearbeiten", response_class=HTMLResponse)
def edit_class(request: Request, class_id: int, db: DB):
    cls = db.get(TraineeClass, class_id)
    return templates.TemplateResponse(request, "trainee_classes/form.html", {
        "cls": cls, "typen": list(UnterrichtsTyp), "active_nav": "klassen",
        "weekday_labels": WEEKDAY_LABELS,
        "selected_weekdays": parse_weekdays(cls.schul_wochentage) if cls else [],
    })


@router.post("/{class_id:int}", response_class=RedirectResponse)
def update_class(
    class_id: int, db: DB,
    name: Annotated[str, Form()],
    berufsschule: Annotated[str, Form()],
    unterrichts_typ: Annotated[UnterrichtsTyp, Form()],
    wochentag: Annotated[list[str], Form()] = [],
    halbtag_wochentag: Annotated[str, Form()] = "",
):
    schul_wochentage, halbtag = _weekday_fields(unterrichts_typ, wochentag, halbtag_wochentag)
    cls = db.get(TraineeClass, class_id)
    cls.name = name
    cls.berufsschule = berufsschule
    cls.unterrichts_typ = unterrichts_typ
    cls.schul_wochentage = schul_wochentage
    cls.halbtag_wochentag = halbtag
    db.commit()
    return RedirectResponse("/klassen/?msg=updated", status_code=303)


@router.delete("/{class_id:int}")
def delete_class(class_id: int, db: DB):
    cls = db.get(TraineeClass, class_id)
    db.delete(cls)
    db.commit()
    return HTMLResponse("")
