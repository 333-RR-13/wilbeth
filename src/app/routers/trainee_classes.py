from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import Schoolyear, Trainee, TraineeClass, UnterrichtsTyp
from app.models.trainee_class_membership import TraineeClassMembership
from app.services.auth_service import CurrentUser, require_roles
from app.services.membership_utils import beruf_langname, beruf_und_lehrjahr, klasse_fuer
from app.services.school_sync import sync_class
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


def _group_by_beruf(
    classes: list[TraineeClass],
) -> list[tuple[str, list[TraineeClass]]]:
    """Gruppiert Klassen nach Beruf; innerhalb jedes Berufs nach Lehrjahr (None zuletzt)."""
    from collections import defaultdict

    buckets: dict[str, list[TraineeClass]] = defaultdict(list)
    for c in classes:
        beruf, _ = beruf_und_lehrjahr(c.name)
        buckets[beruf].append(c)

    def _lj_sort_key(c: TraineeClass) -> int:
        _, lj = beruf_und_lehrjahr(c.name)
        return lj if lj is not None else 99

    result = []
    for beruf in sorted(buckets.keys()):
        sorted_classes = sorted(buckets[beruf], key=_lj_sort_key)
        result.append((beruf_langname(beruf), sorted_classes))
    return result


@router.get("/", response_class=HTMLResponse)
def list_classes(request: Request, db: DB):
    classes = db.exec(select(TraineeClass).order_by(TraineeClass.name)).all()
    schul_labels = {
        c.id: format_weekdays(c.schul_wochentage, halbtag=c.halbtag_wochentag)
        for c in classes
    }
    grouped = _group_by_beruf(classes)
    return templates.TemplateResponse(request, "trainee_classes/list.html", {
        "classes": classes,
        "grouped": grouped,
        "schul_labels": schul_labels,
        "active_nav": "klassen",
    })


@router.get("/neu", response_class=HTMLResponse)
def new_class(request: Request, db: DB):
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    return templates.TemplateResponse(request, "trainee_classes/form.html", {
        "cls": None, "typen": list(UnterrichtsTyp), "active_nav": "klassen",
        "weekday_labels": WEEKDAY_LABELS, "selected_weekdays": [],
        "years": years, "selected_year_id": years[0].id if years else "",
        "members": [], "override_ids": set(), "all_classes": [],
    })


@router.post("/", response_class=RedirectResponse)
def create_class(
    db: DB,
    name: Annotated[str, Form()],
    berufsschule: Annotated[str, Form()],
    unterrichts_typ: Annotated[UnterrichtsTyp, Form()],
    wochentag: Annotated[list[str], Form()] = [],
    halbtag_wochentag: Annotated[str, Form()] = "",
    next_class_id: Annotated[str, Form()] = "",
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    schul_wochentage, halbtag = _weekday_fields(unterrichts_typ, wochentag, halbtag_wochentag)
    db.add(TraineeClass(
        name=name,
        berufsschule=berufsschule,
        unterrichts_typ=unterrichts_typ,
        schul_wochentage=schul_wochentage,
        halbtag_wochentag=halbtag,
        next_class_id=int(next_class_id) if next_class_id else None,
    ))
    db.commit()
    return RedirectResponse("/klassen/?msg=created", status_code=303)


@router.get("/{class_id:int}/bearbeiten", response_class=HTMLResponse)
def edit_class(request: Request, class_id: int, db: DB):
    cls = db.get(TraineeClass, class_id)
    all_classes = db.exec(select(TraineeClass)).all()
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    # Ausgewaehltes Lehrjahr fuer Mitglieder-Anzeige
    default_year_id = years[0].id if years else ""
    selected_year_id = request.query_params.get("year_id", default_year_id)

    # BERECHNETE Mitglieder fuers gewaehlte Lehrjahr: alle aktiven Trainees,
    # deren klasse_fuer(db, t, jahr) dieser Klasse entspricht. Keine eigene
    # Verwaltung mehr hier - Ausnahmen werden ausschliesslich am Trainee gepflegt.
    members: list[Trainee] = []
    override_ids: set[int] = set()
    if selected_year_id:
        aktive_trainees = db.exec(
            select(Trainee).where(Trainee.aktiv == True)  # noqa: E712
            .order_by(Trainee.nachname, Trainee.vorname)
        ).all()
        members = [
            t for t in aktive_trainees
            if klasse_fuer(db, t, selected_year_id) == class_id
        ]
        override_ids = {
            m.trainee_id
            for m in db.exec(
                select(TraineeClassMembership).where(
                    TraineeClassMembership.klasse_id == class_id,
                    TraineeClassMembership.schoolyear_id == selected_year_id,
                )
            ).all()
        }

    return templates.TemplateResponse(request, "trainee_classes/form.html", {
        "cls": cls, "typen": list(UnterrichtsTyp), "active_nav": "klassen",
        "weekday_labels": WEEKDAY_LABELS,
        "selected_weekdays": parse_weekdays(cls.schul_wochentage) if cls else [],
        "years": years,
        "selected_year_id": selected_year_id,
        "members": members,
        "override_ids": override_ids,
        "all_classes": all_classes,
    })


@router.post("/{class_id:int}", response_class=RedirectResponse)
def update_class(
    class_id: int, db: DB,
    name: Annotated[str, Form()],
    berufsschule: Annotated[str, Form()],
    unterrichts_typ: Annotated[UnterrichtsTyp, Form()],
    wochentag: Annotated[list[str], Form()] = [],
    halbtag_wochentag: Annotated[str, Form()] = "",
    next_class_id: Annotated[str, Form()] = "",
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """Speichert nur die Klassen-Stammdaten. Mitgliedschaften werden NICHT mehr
    hier gepflegt: sie ergeben sich ausschliesslich aus dem Trainee-Anker
    (Ausbildungsbeginn + Einstiegsklasse) bzw. expliziten Ausnahmen am Trainee.
    """
    schul_wochentage, halbtag = _weekday_fields(unterrichts_typ, wochentag, halbtag_wochentag)
    cls = db.get(TraineeClass, class_id)
    cls.name = name
    cls.berufsschule = berufsschule
    cls.unterrichts_typ = unterrichts_typ
    cls.schul_wochentage = schul_wochentage
    cls.halbtag_wochentag = halbtag
    cls.next_class_id = int(next_class_id) if next_class_id else None
    db.add(cls)
    db.commit()

    # Schulplan koennte sich geaendert haben (Wochentage/Halbtag) - alle
    # Mitglieder dieser Klasse (direkt + per Ausnahme) neu synchronisieren.
    sync_class(db, class_id)

    return RedirectResponse("/klassen/?msg=updated", status_code=303)


@router.delete("/{class_id:int}")
def delete_class(
    class_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("admin")),
):
    cls = db.get(TraineeClass, class_id)
    db.delete(cls)
    db.commit()
    return HTMLResponse("")
