import urllib.parse
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    Assignment,
    Department,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeClassMembership,
    TraineeRolle,
    TraineeWish,
)
from app.models.trainee_wish import prioritaet_label
from app.services.auth_service import CurrentUser, require_roles
from app.services.conflict_checker import find_conflicts
from app.services.membership_utils import (
    beruf_langname,
    beruf_optionen,
    beruf_und_lehrjahr,
    einstiegsklasse_fuer_beruf,
    klasse_fuer,
    semester_label,
    upsert_membership,
)
from app.services.school_sync import sync_trainee
from app.utils.colors import department_color_map
from app.utils.kw import iter_schoolyear_weeks

router = APIRouter(prefix="/trainees", tags=["trainees"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
templates.env.globals["prioritaet_label"] = prioritaet_label
DB = Annotated[Session, Depends(get_session)]


def _parse_ausbildungsbeginn(raw: str) -> tuple[date | None, str | None]:
    """Parst das Pflichtfeld Ausbildungsbeginn.

    Rueckgabe (wert, fehlertext); bei Erfolg ist fehlertext None.
    """
    if not raw:
        return None, "Ausbildungsbeginn ist Pflicht"
    try:
        return date.fromisoformat(raw), None
    except ValueError:
        return None, "Ausbildungsbeginn ist ungueltig"


def _resolve_einstiegsklasse_id(
    db: Session, sonderfall: str, klasse_id: str, beruf: str,
) -> tuple[int | None, str | None]:
    """Ermittelt die Einstiegsklasse (Anker) aus Sonderfall- oder Beruf-Eingabe.

    Sonderfall gesetzt -> klasse_id ist Pflicht (direkte Klassenwahl).
    Sonst -> beruf ist Pflicht; die Einstiegsklasse wird ueber
    einstiegsklasse_fuer_beruf() abgeleitet ("<Beruf> 1. LJ" bzw. DH-Kohorte).

    Rueckgabe (klasse_id, fehlertext); bei Erfolg ist fehlertext None.
    """
    if sonderfall:
        if not klasse_id:
            return None, "Bei Sonderfall ist eine Klasse Pflicht"
        return int(klasse_id), None
    if not beruf:
        return None, "Ausbildungsberuf ist Pflicht"
    all_classes = list(db.exec(select(TraineeClass)).all())
    klasse = einstiegsklasse_fuer_beruf(all_classes, beruf)
    if klasse is None:
        return None, f"Keine Klasse '{beruf} 1. LJ' vorhanden"
    return klasse.id, None


def _aktuelles_schuljahr_id(db: Session) -> str:
    """Nicht-archiviertes Schuljahr, in dem HEUTE liegt; Fallback: neuestes."""
    years = db.exec(
        select(Schoolyear)
        .where(Schoolyear.archiviert == False)  # noqa: E712
        .order_by(Schoolyear.start_year.desc())
    ).all()
    if not years:
        return ""
    iso = date.today().isocalendar()
    today_key = (iso[1], iso[0])
    for y in years:
        if today_key in iter_schoolyear_weeks(y.start_kw, y.start_year, y.end_kw, y.end_year):
            return y.id
    return years[0].id


@router.get("/", response_class=HTMLResponse)
def list_trainees(request: Request, db: DB, status: str = "aktiv"):
    """Liste der Trainees mit Status-Filter: aktiv | archiviert | alle."""
    q = select(Trainee).order_by(Trainee.nachname, Trainee.vorname)
    if status == "aktiv":
        q = q.where(Trainee.aktiv == True)  # noqa: E712
    elif status == "archiviert":
        q = q.where(Trainee.aktiv == False)  # noqa: E712
    # status == "alle": kein Filter
    trainees = db.exec(q).all()
    classes = {c.id: c for c in db.exec(select(TraineeClass)).all()}

    # BERECHNETE Klasse fuers laufende Jahr anzeigen (konsistent mit Uebersicht
    # und Jahresabschluss) - die rohe Einstiegsklasse ist nur der Anker und
    # wuerde falsche Anker-Daten verstecken.
    anzeige_jahr = _aktuelles_schuljahr_id(db)
    klasse_map: dict[int, TraineeClass | None] = {}
    for t in trainees:
        kid = klasse_fuer(db, t, anzeige_jahr) if anzeige_jahr else t.klasse_id
        klasse_map[t.id] = classes.get(kid) if kid else None

    return templates.TemplateResponse(request, "trainees/list.html", {
        "trainees": trainees,
        "classes": classes,
        "klasse_map": klasse_map,
        "anzeige_jahr": anzeige_jahr,
        "active_nav": "trainees",
        "status": status,
    })


@router.get("/upn-pflege", response_class=HTMLResponse)
def upn_pflege(request: Request, db: DB):
    """Sammel-Pflege der UPN (Entra-Anmeldename) fuer alle aktiven Trainees."""
    trainees = db.exec(
        select(Trainee)
        .where(Trainee.aktiv == True)  # noqa: E712
        .order_by(Trainee.nachname, Trainee.vorname)
    ).all()
    return templates.TemplateResponse(request, "trainees/upn_pflege.html", {
        "trainees": trainees,
        "active_nav": "trainees",
    })


@router.post("/upn-pflege", response_class=RedirectResponse)
async def upn_pflege_speichern(
    request: Request, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """Speichert die je Zeile eingetragenen UPN-Werte fuer alle aktiven Trainees."""
    form = await request.form()
    trainees = db.exec(
        select(Trainee).where(Trainee.aktiv == True)  # noqa: E712
    ).all()
    for t in trainees:
        field_name = f"upn_{t.id}"
        if field_name not in form:
            continue
        neuer_wert = (form[field_name] or "").strip() or None
        if neuer_wert != t.upn:
            t.upn = neuer_wert
            db.add(t)
    db.commit()
    return RedirectResponse("/trainees/upn-pflege?msg=updated", status_code=303)


@router.get("/neu", response_class=HTMLResponse)
def new_trainee(request: Request, db: DB):
    classes = db.exec(select(TraineeClass).order_by(TraineeClass.name)).all()
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    default_year_id = years[0].id if years else ""
    return templates.TemplateResponse(request, "trainees/form.html", {
        "trainee": None,
        "classes": classes,
        "rollen": list(TraineeRolle),
        "years": years,
        "selected_year_id": default_year_id,
        "memberships": {},
        "beruf_optionen": beruf_optionen(classes),
        "beruf_selected": "",
        "sonderfall_checked": False,
        "active_nav": "trainees",
    })


@router.post("/", response_class=RedirectResponse)
def create_trainee(
    db: DB,
    vorname: Annotated[str, Form()],
    nachname: Annotated[str, Form()],
    rolle: Annotated[TraineeRolle, Form()],
    klasse_id: Annotated[str, Form()] = "",
    beruf: Annotated[str, Form()] = "",
    sonderfall: Annotated[str, Form()] = "",
    membership_year_id: Annotated[str, Form()] = "",
    membership_klasse_id: Annotated[str, Form()] = "",
    notizen: Annotated[str, Form()] = "",
    steckbrief: Annotated[str, Form()] = "",
    aktiv: Annotated[str, Form()] = "",
    ausbildungsbeginn: Annotated[str, Form()] = "",
    upn: Annotated[str, Form()] = "",
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    ausbildungsbeginn_parsed, err = _parse_ausbildungsbeginn(ausbildungsbeginn)
    if err:
        return RedirectResponse(
            f"/trainees/neu?msg=error&detail={urllib.parse.quote(err)}", status_code=303
        )

    klasse_id_int, err = _resolve_einstiegsklasse_id(db, sonderfall, klasse_id, beruf)
    if err:
        return RedirectResponse(
            f"/trainees/neu?msg=error&detail={urllib.parse.quote(err)}", status_code=303
        )

    t = Trainee(
        vorname=vorname,
        nachname=nachname,
        rolle=rolle,
        klasse_id=klasse_id_int,
        notizen=notizen,
        steckbrief=steckbrief,
        aktiv=bool(aktiv),
        ausbildungsbeginn=ausbildungsbeginn_parsed,
        upn=upn.strip() or None,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    # Optionaler Membership-Override fuer ein bestimmtes Schuljahr
    mem_klasse_int = int(membership_klasse_id) if membership_klasse_id else None
    if membership_year_id and mem_klasse_int:
        upsert_membership(db, t.id, membership_year_id, mem_klasse_int)
        db.commit()
    sync_trainee(db, t.id)
    return RedirectResponse(f"/trainees/{t.id}?msg=created", status_code=303)


@router.get("/{trainee_id:int}", response_class=HTMLResponse)
def trainee_detail(request: Request, trainee_id: int, db: DB):
    trainee = db.get(Trainee, trainee_id)
    years_list = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    years = {y.id: y for y in years_list}
    all_depts = db.exec(select(Department)).all()
    depts = {d.id: d for d in all_depts}
    dept_colors = department_color_map(all_depts)
    assignments = db.exec(
        select(Assignment)
        .where(Assignment.trainee_id == trainee_id)
        .order_by(Assignment.jahr, Assignment.kw)
    ).all()

    conflict_cells: set[str] = set()
    for year_id in years:
        for c in find_conflicts(db, year_id):
            if c.trainee_id == trainee_id:
                conflict_cells.add(f"{c.kw}~{c.jahr}")

    _today = date.today().isocalendar()
    today_key = f"{_today.week}~{_today.year}"

    # Wuensche des Trainees (fuer die Planerin sichtbar), nach Prioritaet sortiert
    wishes = db.exec(
        select(TraineeWish)
        .where(TraineeWish.trainee_id == trainee_id)
        .order_by(TraineeWish.prioritaet)
    ).all()

    # ── Visitenkarte ────────────────────────────────────────────────
    # Klasse ueber klasse_fuer ermitteln (neuestes Schuljahr = berechneter Anker)
    schoolyear_id = years_list[0].id if years_list else None
    klasse_id = klasse_fuer(db, trainee, schoolyear_id) if schoolyear_id else trainee.klasse_id
    klasse = db.get(TraineeClass, klasse_id) if klasse_id else None
    # Ausbildungsberuf ausgeschrieben
    beruf_token, lehrjahr = beruf_und_lehrjahr(klasse.name if klasse else None)
    beruf_lang = beruf_langname(beruf_token)
    # Fuer DH-Studenten: Semester-Label ermitteln
    sem_label: str | None = None
    if schoolyear_id and trainee.rolle != TraineeRolle.AZUBI:
        sem_label = semester_label(db, trainee, schoolyear_id, "")

    return templates.TemplateResponse(request, "trainees/detail.html", {
        "trainee": trainee,
        "klasse": klasse,
        "sem_label": sem_label,
        "years": years,
        "depts": depts,
        "dept_colors": dept_colors,
        "assignments": assignments,
        "conflict_cells": conflict_cells,
        "today_key": today_key,
        "wishes": wishes,
        "beruf_lang": beruf_lang,
        "ausbildungsbeginn": trainee.ausbildungsbeginn,
        "active_nav": "trainees",
    })


@router.post("/{trainee_id:int}/share-token", response_class=RedirectResponse)
def generate_share_token(
    trainee_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    t = db.get(Trainee, trainee_id)
    t.share_token = str(uuid.uuid4())
    db.commit()
    return RedirectResponse(f"/trainees/{trainee_id}?msg=updated", status_code=303)


@router.post("/{trainee_id:int}/share-token/deaktivieren", response_class=RedirectResponse)
def revoke_share_token(
    trainee_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    t = db.get(Trainee, trainee_id)
    t.share_token = None
    db.commit()
    return RedirectResponse(f"/trainees/{trainee_id}?msg=updated", status_code=303)


@router.get("/{trainee_id:int}/bearbeiten", response_class=HTMLResponse)
def edit_trainee(request: Request, trainee_id: int, db: DB):
    from app.models.trainee_class_membership import TraineeClassMembership
    trainee = db.get(Trainee, trainee_id)
    classes = db.exec(select(TraineeClass).order_by(TraineeClass.name)).all()
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    # Bestehende Memberships: year_id -> klasse_id
    memberships = {
        m.schoolyear_id: m.klasse_id
        for m in db.exec(
            select(TraineeClassMembership).where(
                TraineeClassMembership.trainee_id == trainee_id
            )
        ).all()
    }
    # Default Lehrjahr: neuestes Jahr oder erstes mit Membership
    default_year_id = years[0].id if years else ""
    selected_year_id = request.query_params.get("year_id", default_year_id)
    # Bug A: wenn fuer selected_year_id keine Membership, aber trainee.klasse_id gesetzt ->
    # Klasse als Default vorwaehlen
    if selected_year_id and selected_year_id not in memberships and trainee.klasse_id:
        memberships[selected_year_id] = trainee.klasse_id

    # Beruf-Vorbelegung + Sonderfall-Erkennung aus der aktuellen Einstiegsklasse
    beruf_selected = ""
    sonderfall_checked = False
    if trainee.klasse_id:
        aktuelle_klasse = next((c for c in classes if c.id == trainee.klasse_id), None)
        if aktuelle_klasse is not None:
            token, lehrjahr = beruf_und_lehrjahr(aktuelle_klasse.name)
            beruf_selected = token
            sonderfall_checked = lehrjahr != 1

    return templates.TemplateResponse(request, "trainees/form.html", {
        "trainee": trainee,
        "classes": classes,
        "rollen": list(TraineeRolle),
        "years": years,
        "selected_year_id": selected_year_id,
        "memberships": memberships,
        "beruf_optionen": beruf_optionen(classes),
        "beruf_selected": beruf_selected,
        "sonderfall_checked": sonderfall_checked,
        "active_nav": "trainees",
    })


@router.post("/{trainee_id:int}", response_class=RedirectResponse)
def update_trainee(
    trainee_id: int, db: DB,
    vorname: Annotated[str, Form()],
    nachname: Annotated[str, Form()],
    rolle: Annotated[TraineeRolle, Form()],
    klasse_id: Annotated[str, Form()] = "",
    beruf: Annotated[str, Form()] = "",
    sonderfall: Annotated[str, Form()] = "",
    membership_year_id: Annotated[str, Form()] = "",
    membership_klasse_id: Annotated[str, Form()] = "",
    notizen: Annotated[str, Form()] = "",
    steckbrief: Annotated[str, Form()] = "",
    aktiv: Annotated[str, Form()] = "",
    ausbildungsbeginn: Annotated[str, Form()] = "",
    upn: Annotated[str, Form()] = "",
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    ausbildungsbeginn_parsed, err = _parse_ausbildungsbeginn(ausbildungsbeginn)
    if err:
        return RedirectResponse(
            f"/trainees/{trainee_id}/bearbeiten?msg=error&detail={urllib.parse.quote(err)}",
            status_code=303,
        )

    klasse_id_int, err = _resolve_einstiegsklasse_id(db, sonderfall, klasse_id, beruf)
    if err:
        return RedirectResponse(
            f"/trainees/{trainee_id}/bearbeiten?msg=error&detail={urllib.parse.quote(err)}",
            status_code=303,
        )

    t = db.get(Trainee, trainee_id)
    t.vorname = vorname
    t.nachname = nachname
    t.rolle = rolle
    t.notizen = notizen
    t.steckbrief = steckbrief
    t.aktiv = bool(aktiv)
    t.upn = upn.strip() or None
    t.ausbildungsbeginn = ausbildungsbeginn_parsed
    # Einstiegsklasse (Anker) ueber Sonderfall/Beruf ermittelt
    t.klasse_id = klasse_id_int
    # Optionaler Membership-Override fuer ein bestimmtes Schuljahr
    mem_klasse_int = int(membership_klasse_id) if membership_klasse_id else None
    if membership_year_id and mem_klasse_int:
        upsert_membership(db, trainee_id, membership_year_id, mem_klasse_int)
    db.add(t)
    db.commit()
    sync_trainee(db, trainee_id)
    return RedirectResponse(f"/trainees/{trainee_id}?msg=updated", status_code=303)


@router.post("/{trainee_id:int}/reaktivieren", response_class=RedirectResponse)
def reaktivieren_trainee(
    trainee_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """Archivierter Azubi wird reaktiviert (aktiv=True)."""
    t = db.get(Trainee, trainee_id)
    t.aktiv = True
    db.add(t)
    db.commit()
    return RedirectResponse("/trainees/?status=archiviert&msg=updated", status_code=303)


@router.post("/{trainee_id:int}/loeschen", response_class=RedirectResponse)
def loeschen_trainee(
    trainee_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("admin")),
):
    """Endgueltiges Loeschen eines Trainees inkl. aller abhaengigen Zeilen.

    Explizites Vorab-Loeschen von Assignment, TraineeWish, TraineeClassMembership
    stellt korrekte Funktion sowohl unter SQLite (FK-Enforcement evtl. inaktiv)
    als auch unter PostgreSQL (FK-Enforcement aktiv) sicher.
    """
    # Abhaengige Zeilen explizit loeschen (robust fuer SQLite + Postgres)
    assignments = db.exec(
        select(Assignment).where(Assignment.trainee_id == trainee_id)
    ).all()
    for a in assignments:
        db.delete(a)

    wishes = db.exec(
        select(TraineeWish).where(TraineeWish.trainee_id == trainee_id)
    ).all()
    for w in wishes:
        db.delete(w)

    memberships = db.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.trainee_id == trainee_id
        )
    ).all()
    for m in memberships:
        db.delete(m)

    t = db.get(Trainee, trainee_id)
    db.delete(t)
    db.commit()
    return RedirectResponse("/trainees/?status=archiviert&msg=deleted", status_code=303)


@router.delete("/{trainee_id:int}")
def delete_trainee(
    trainee_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """HTMX-kompatibler DELETE-Endpoint fuer die Aktiv-Liste (direkte Aktion ohne Archiv)."""
    # Abhaengige Zeilen explizit loeschen
    for a in db.exec(select(Assignment).where(Assignment.trainee_id == trainee_id)).all():
        db.delete(a)
    for w in db.exec(select(TraineeWish).where(TraineeWish.trainee_id == trainee_id)).all():
        db.delete(w)
    for m in db.exec(select(TraineeClassMembership).where(TraineeClassMembership.trainee_id == trainee_id)).all():
        db.delete(m)
    t = db.get(Trainee, trainee_id)
    db.delete(t)
    db.commit()
    return HTMLResponse("")
