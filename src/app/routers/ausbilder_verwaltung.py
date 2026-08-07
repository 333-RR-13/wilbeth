"""Zentrale Ausbilder-Verwaltung: kehrt Department.verantwortliche um
(bisher Abteilung -> UPN-Liste, gepflegt einzeln je Abteilung in
app/routers/departments.py) zu Person -> ihre Abteilungen.

- GET  /ausbilder-verwaltung/                 -> Liste aller Personen
  (dedupliziert case-insensitiv, alphabetisch sortiert) mit ihren
  betreuten Abteilungen, plus Formular "Person hinzufuegen".
- GET  /ausbilder-verwaltung/{upn}/bearbeiten -> Checkbox-Formular fuer
  eine einzelne Person (alle Abteilungen, vorausgewaehlt = aktuelle
  Zuordnung).
- POST /ausbilder-verwaltung/{upn}/bearbeiten -> speichert die Checkbox-
  Auswahl fuer diese Person.
- POST /ausbilder-verwaltung/hinzufuegen      -> legt eine neue Zuordnung
  an (UPN + Abteilungs-Checkboxen).
- POST /ausbilder-verwaltung/{upn}/entfernen  -> traegt die UPN aus ALLEN
  Abteilungen aus.

Rollen: wie alle anderen Stammdaten-Routen (Teil A) konsequent
orga/admin-only -- siehe app/services/auth_service.require_roles.
Ausbilder bekommt auf JEDER Route dieser Seite (GET wie POST) 403.

Kein Anzeigename: Department.verantwortliche ist reiner UPN-Freitext; ein
dauerhaft an die UPN gehaengter Klarname braeuchte ein eigenes Schema-Feld
samt Migration. Ein Formularfeld, das nur in der Flash-Message auftaucht
und danach verschwindet, waere irrefuehrend -- deshalb gibt es hier nur
die UPN.

"Schon einmal angemeldet"-Spalte bewusst WEGGELASSEN: login_session() in
auth_service.py schreibt ausschliesslich in die Starlette-Session
(verschluesseltes Browser-Cookie), es gibt keinerlei Login-/Audit-Tabelle
in der DB (siehe app/models/__init__.py) -- es existiert schlicht keine
Datenquelle dafuer.

UPNs enthalten "@"/"." -- Pfad-Parameter werden defensiv mit
urllib.parse.quote/unquote behandelt (Grundmuster wie in trainees.py
fuer generierte Links/Redirects ueblich).
"""
import urllib.parse
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import Department
from app.services.auth_service import CurrentUser, require_roles
from app.services.verantwortliche_utils import people_by_upn, sync_assignments

router = APIRouter(prefix="/ausbilder-verwaltung", tags=["ausbilder-verwaltung"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


def _all_departments(db: Session) -> list[Department]:
    return db.exec(select(Department).order_by(Department.code)).all()


# ── Liste + Hinzufuegen ──────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def list_ausbilder(
    request: Request, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    people = people_by_upn(db)
    rows = [
        {"upn": upn, "upn_encoded": urllib.parse.quote(upn, safe=""), "departments": depts}
        for upn, depts in people.items()
    ]
    return templates.TemplateResponse(request, "ausbilder_verwaltung/list.html", {
        "rows": rows,
        "departments": _all_departments(db),
        "active_nav": "ausbilder_verwaltung",
    })


@router.post("/hinzufuegen", response_class=RedirectResponse)
def add_ausbilder(
    db: DB,
    upn: Annotated[str, Form()],
    abteilung_ids: Annotated[list[int], Form()] = [],
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    upn_clean = upn.strip()
    if not upn_clean:
        return RedirectResponse(
            f"/ausbilder-verwaltung/?msg=error&detail={urllib.parse.quote('UPN ist Pflicht')}",
            status_code=303,
        )
    count = sync_assignments(db, upn_clean, set(abteilung_ids))
    detail = f"{upn_clean} wurde {count} Abteilung{'en' if count != 1 else ''} zugeordnet."
    return RedirectResponse(
        f"/ausbilder-verwaltung/?msg=created&detail={urllib.parse.quote(detail)}",
        status_code=303,
    )


# ── Einzelne Person bearbeiten ───────────────────────────────────────────

@router.get("/{upn}/bearbeiten", response_class=HTMLResponse)
def edit_ausbilder(
    request: Request, upn: str, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    decoded_upn = urllib.parse.unquote(upn)
    normalized_upn = decoded_upn.strip().lower()
    people = people_by_upn(db)
    selected_ids = {d.id for d in people.get(normalized_upn, [])}
    return templates.TemplateResponse(request, "ausbilder_verwaltung/form.html", {
        "upn": decoded_upn,
        "upn_encoded": urllib.parse.quote(decoded_upn, safe=""),
        "departments": _all_departments(db),
        "selected_ids": selected_ids,
        "active_nav": "ausbilder_verwaltung",
    })


@router.post("/{upn}/bearbeiten", response_class=RedirectResponse)
def update_ausbilder(
    upn: str, db: DB,
    abteilung_ids: Annotated[list[int], Form()] = [],
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    decoded_upn = urllib.parse.unquote(upn)
    if not decoded_upn.strip():
        return RedirectResponse(
            f"/ausbilder-verwaltung/?msg=error&detail={urllib.parse.quote('UPN darf nicht leer sein')}",
            status_code=303,
        )
    sync_assignments(db, decoded_upn, set(abteilung_ids))
    return RedirectResponse("/ausbilder-verwaltung/?msg=updated", status_code=303)


@router.post("/{upn}/entfernen", response_class=RedirectResponse)
def remove_ausbilder(
    upn: str, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    decoded_upn = urllib.parse.unquote(upn)
    sync_assignments(db, decoded_upn, set())
    return RedirectResponse("/ausbilder-verwaltung/?msg=deleted", status_code=303)
