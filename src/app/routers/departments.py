from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import Department, DepartmentKategorie, TraineeClass
from app.services.auth_service import CurrentUser, require_roles
from app.services.membership_utils import beruf_art_map, beruf_bereich_map, beruf_optionen
from app.utils.text import is_safe_http_url, linkify

router = APIRouter(prefix="/abteilungen", tags=["abteilungen"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


def _validate_info_link(info_link: str) -> str:
    """Trimmt info_link; leer bleibt erlaubt (kein Link), sonst MUSS es
    http/https sein -- sonst 400 (siehe app.utils.text.is_safe_http_url)."""
    info_link = (info_link or "").strip()
    if info_link and not is_safe_http_url(info_link):
        raise HTTPException(
            status_code=400, detail="Ungueltiger Link (nur http:// oder https:// erlaubt)"
        )
    return info_link


def _get_kategorien(db: Session) -> list[DepartmentKategorie]:
    return db.exec(select(DepartmentKategorie).order_by(DepartmentKategorie.name)).all()


def _beruf_form_context(db: Session) -> dict:
    """Kontext fuer die Beruf-Checkbox-Liste im Abteilungs-Formular: alle
    Beruf-Optionen (sortiert nach Langname) + die Beruf->Art- und
    Beruf->Bereich-Zuordnung fuer die Schnellauswahl-Buttons ("Nur
    Ausbildungsberufe"/"Nur Studiengaenge"/"Nur IT"/"Nur kaufmännisch",
    reines JS -- siehe departments/form.html). Die Buttons setzen dabei nur
    eine Vorauswahl -- eine Abteilung kann durchaus beide Bereiche fuehren,
    die manuelle Auswahl bleibt danach unveraendert moeglich."""
    classes = db.exec(select(TraineeClass)).all()
    return {
        "beruf_optionen": beruf_optionen(classes),
        "beruf_art_map": beruf_art_map(classes),
        "beruf_bereich_map": beruf_bereich_map(classes),
    }


def _parse_erlaubte_berufe(berufe: list[str]) -> list[str]:
    """Normalisiert die aus dem Formular kommende Checkbox-Auswahl.

    Leer bleibt leer (= alle Berufe erlaubt). Duplikate werden entfernt,
    Reihenfolge ist stabil (erstes Vorkommen zaehlt).
    """
    gesehen: list[str] = []
    for b in berufe:
        b = (b or "").strip()
        if b and b not in gesehen:
            gesehen.append(b)
    return gesehen


# ──────────────────────────────────────────────────────────────────────────────
# Kategorie-CRUD  (MUSS vor /{dept_id}-Routen stehen!)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/kategorien", response_class=HTMLResponse)
def list_kategorien(
    request: Request, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    kategorien = _get_kategorien(db)
    return templates.TemplateResponse(request, "departments/kategorien.html", {
        "kategorien": kategorien, "active_nav": "abteilungen",
    })


@router.post("/kategorien", response_class=RedirectResponse)
def create_kategorie(
    db: DB,
    name: Annotated[str, Form()],
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    name = name.strip()
    if name:
        db.add(DepartmentKategorie(name=name))
        db.commit()
    return RedirectResponse("/abteilungen/kategorien?msg=created", status_code=303)


@router.post("/kategorien/{kat_id}", response_class=RedirectResponse)
def update_kategorie(
    kat_id: int,
    db: DB,
    name: Annotated[str, Form()],
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    kat = db.get(DepartmentKategorie, kat_id)
    if kat and name.strip():
        kat.name = name.strip()
        db.commit()
    return RedirectResponse("/abteilungen/kategorien?msg=updated", status_code=303)


@router.post("/kategorien/{kat_id}/loeschen", response_class=RedirectResponse)
def delete_kategorie(
    kat_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    kat = db.get(DepartmentKategorie, kat_id)
    if kat is None:
        return RedirectResponse("/abteilungen/kategorien?err=notfound", status_code=303)
    # Sicherheitscheck: Kategorie darf nur gelöscht werden, wenn keine Abteilung sie nutzt
    in_use = db.exec(
        select(Department).where(Department.kategorie_id == kat_id)
    ).first()
    if in_use is not None:
        return RedirectResponse(
            f"/abteilungen/kategorien?err=inuse&kat={kat.name}", status_code=303
        )
    db.delete(kat)
    db.commit()
    return RedirectResponse("/abteilungen/kategorien?msg=deleted", status_code=303)


# ──────────────────────────────────────────────────────────────────────────────
# Abteilungen-CRUD
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def list_departments(
    request: Request, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    deps = db.exec(select(Department).order_by(Department.code)).all()
    return templates.TemplateResponse(request, "departments/list.html", {
        "departments": deps, "active_nav": "abteilungen",
    })


@router.get("/neu", response_class=HTMLResponse)
def new_department(
    request: Request, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    return templates.TemplateResponse(request, "departments/form.html", {
        "department": None, "kategorien": _get_kategorien(db), "active_nav": "abteilungen",
        **_beruf_form_context(db),
    })


@router.post("/", response_class=RedirectResponse)
def create_department(
    db: DB,
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    kategorie_id: Annotated[int | None, Form()] = None,
    ansprechpartner: Annotated[str, Form()] = "",
    info_text: Annotated[str, Form()] = "",
    info_link: Annotated[str, Form()] = "",
    erlaubt_mehrfachbelegung: Annotated[str, Form()] = "",
    farbe: Annotated[str, Form()] = "#9CA3AF",
    verantwortliche: Annotated[str, Form()] = "",
    beruf: Annotated[list[str], Form()] = [],
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    info_link = _validate_info_link(info_link)
    db.add(Department(
        code=code.strip().upper(),
        name=name,
        kategorie_id=kategorie_id,
        ansprechpartner=ansprechpartner,
        info_text=info_text,
        info_link=info_link,
        erlaubt_mehrfachbelegung=bool(erlaubt_mehrfachbelegung),
        farbe=farbe,
        verantwortliche=verantwortliche,
        erlaubte_berufe=_parse_erlaubte_berufe(beruf),
    ))
    db.commit()
    return RedirectResponse("/abteilungen/?msg=created", status_code=303)


@router.get("/{dept_id:int}/bearbeiten", response_class=HTMLResponse)
def edit_department(
    request: Request, dept_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    dept = db.get(Department, dept_id)
    return templates.TemplateResponse(request, "departments/form.html", {
        "department": dept, "kategorien": _get_kategorien(db), "active_nav": "abteilungen",
        **_beruf_form_context(db),
    })


@router.post("/{dept_id:int}", response_class=RedirectResponse)
def update_department(
    dept_id: int, db: DB,
    code: Annotated[str, Form()],
    name: Annotated[str, Form()],
    kategorie_id: Annotated[int | None, Form()] = None,
    ansprechpartner: Annotated[str, Form()] = "",
    info_text: Annotated[str, Form()] = "",
    info_link: Annotated[str, Form()] = "",
    erlaubt_mehrfachbelegung: Annotated[str, Form()] = "",
    farbe: Annotated[str, Form()] = "#9CA3AF",
    verantwortliche: Annotated[str, Form()] = "",
    beruf: Annotated[list[str], Form()] = [],
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    info_link = _validate_info_link(info_link)
    dept = db.get(Department, dept_id)
    dept.code = code.strip().upper()
    dept.name = name
    dept.kategorie_id = kategorie_id
    dept.ansprechpartner = ansprechpartner
    dept.info_text = info_text
    dept.info_link = info_link
    dept.erlaubt_mehrfachbelegung = bool(erlaubt_mehrfachbelegung)
    dept.farbe = farbe
    dept.verantwortliche = verantwortliche
    # JSON-Spalte: IMMER eine neue Liste zuweisen, nie in-place mutieren
    # (siehe Kommentar in app/models/feedback_bogen.py).
    dept.erlaubte_berufe = _parse_erlaubte_berufe(beruf)
    db.commit()
    return RedirectResponse("/abteilungen/?msg=updated", status_code=303)


# ──────────────────────────────────────────────────────────────────────────────
# Vorschau (Staff-Sicht auf die Azubi-Detailseite, read-only)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/{dept_id:int}/vorschau", response_class=HTMLResponse)
def preview_department(
    request: Request, dept_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    """Zeigt Orga/Admin read-only, wie die neue Abteilungs-Detailseite
    (app/routers/share.py: abteilung_detail) fuer Azubis aussieht -- selbes
    Markup (siehe _partials/abteilung_detail_content.html), nur im
    Staff-Layout (base.html) statt im Azubi-Layout (share/_base.html), das
    einen Trainee-Token voraussetzt."""
    dept = db.get(Department, dept_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="Abteilung nicht gefunden")
    return templates.TemplateResponse(request, "departments/vorschau.html", {
        "dept": dept,
        "info_html": linkify(dept.info_text),
        "back_url": "/abteilungen/",
        "active_nav": "abteilungen",
    })


@router.delete("/{dept_id:int}")
def delete_department(
    dept_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    dept = db.get(Department, dept_id)
    db.delete(dept)
    db.commit()
    return HTMLResponse("")
