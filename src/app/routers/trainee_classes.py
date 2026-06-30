from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import Schoolyear, Trainee, TraineeClass, UnterrichtsTyp
from app.models.trainee_class_membership import TraineeClassMembership
from app.services.membership_utils import beruf_und_lehrjahr, upsert_membership
from app.services.school_sync import sync_trainee
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
        result.append((beruf, sorted_classes))
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
        "trainees": [], "class_names": {},
        "years": years, "selected_year_id": years[0].id if years else "",
        "members_for_year": set(), "all_classes": [],
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
    trainees = db.exec(select(Trainee).order_by(Trainee.nachname, Trainee.vorname)).all()
    all_classes = db.exec(select(TraineeClass)).all()
    class_names = {c.id: c.name for c in all_classes}
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    # Ausgewaehltes Lehrjahr fuer Mitglieder-Anzeige
    default_year_id = years[0].id if years else ""
    selected_year_id = request.query_params.get("year_id", default_year_id)
    # Mitglieder dieser Klasse fuer das gewaehlte Lehrjahr
    members_for_year: set[int] = {
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
        "trainees": trainees,
        "class_names": class_names,
        "years": years,
        "selected_year_id": selected_year_id,
        "members_for_year": members_for_year,
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
    membership_year_id: Annotated[str, Form()] = "",
    mitglied: Annotated[list[str], Form()] = [],
):
    schul_wochentage, halbtag = _weekday_fields(unterrichts_typ, wochentag, halbtag_wochentag)
    cls = db.get(TraineeClass, class_id)
    cls.name = name
    cls.berufsschule = berufsschule
    cls.unterrichts_typ = unterrichts_typ
    cls.schul_wochentage = schul_wochentage
    cls.halbtag_wochentag = halbtag
    cls.next_class_id = int(next_class_id) if next_class_id else None
    db.add(cls)

    checked_ids = {int(i) for i in mitglied if i.isdigit()}
    trainees = db.exec(select(Trainee)).all()
    affected_ids: set[int] = set()

    if membership_year_id:
        # Membership-basierte Verwaltung fuer das gewaehlte Lehrjahr
        # Bestehende Memberships fuer (diese Klasse, dieses Jahr) laden
        existing_memberships = db.exec(
            select(TraineeClassMembership).where(
                TraineeClassMembership.klasse_id == class_id,
                TraineeClassMembership.schoolyear_id == membership_year_id,
            )
        ).all()
        existing_member_ids = {m.trainee_id for m in existing_memberships}

        # Neu hinzugekommen
        for tid in checked_ids - existing_member_ids:
            upsert_membership(db, tid, membership_year_id, class_id)
            affected_ids.add(tid)
            # klasse_id als Fallback setzen
            t = db.get(Trainee, tid)
            if t:
                t.klasse_id = class_id
                db.add(t)

        # Entfernt
        for m in existing_memberships:
            if m.trainee_id not in checked_ids:
                db.delete(m)
                affected_ids.add(m.trainee_id)

        # Unveraendert gebliebene Mitglieder: immer syncen (Schulplan koennte sich geaendert haben)
        affected_ids |= checked_ids
    else:
        # Kein Jahr gewaehlt: altes Verhalten (klasse_id direkt setzen)
        for t in trainees:
            if t.id in checked_ids:
                if t.klasse_id != class_id:
                    affected_ids.add(t.id)
                t.klasse_id = class_id
            elif t.klasse_id == class_id:
                affected_ids.add(t.id)
                t.klasse_id = None
        affected_ids |= checked_ids

    db.commit()

    for tid in affected_ids:
        sync_trainee(db, tid, commit=False)
    db.commit()

    return RedirectResponse("/klassen/?msg=updated", status_code=303)


@router.delete("/{class_id:int}")
def delete_class(class_id: int, db: DB):
    cls = db.get(TraineeClass, class_id)
    db.delete(cls)
    db.commit()
    return HTMLResponse("")
