"""Zentrale Personen-Verwaltung fuer betreuende/verantwortliche Personen.

Zwei UNABHAENGIGE Zustaendigkeiten, die hier NEBENEINANDER gepflegt werden:

1. Abteilungs-Zustaendigkeit ("Einsaetze bestaetigen"): kehrt
   Department.verantwortliche (bisher Abteilung -> UPN-Liste, gepflegt
   einzeln je Abteilung in app/routers/departments.py) zu Person -> ihre
   Abteilungen um. Reiner UPN-Freitext (siehe
   app/services/verantwortliche_utils.py), UNVERAENDERT seit der ersten
   Fassung dieser Seite -- app.services.auth_service.allowed_dept_ids()
   liest weiterhin ausschliesslich Department.verantwortliche und wird von
   diesem Umbau NICHT beruehrt.
2. Beruf-Zustaendigkeit ("Azubis ueber die Ausbildung begleiten", neu seit
   Migration 0017betreuung): die neue Betreuer-Tabelle mit Klarname,
   Funktion, Kontaktdaten, Notiz, aktiv/inaktiv und einer Liste zustaendiger
   Berufe (leer = KEINER -- fuer alle Berufe muessen alle Haken gesetzt
   werden, s. Schnellauswahl-Button "Alle"). Regel + Ausnahmen:
   app/services/betreuung_utils.py.

Seitenaufbau:
- GET  /ausbilder-verwaltung/                     -> Liste aller Personen
  (Betreuer-Tabelle) mit Funktion, Berufen, Abteilungen, aktiv/inaktiv.
- GET  /ausbilder-verwaltung/neu                  -> Anlegeformular.
- POST /ausbilder-verwaltung/neu                  -> legt eine Person an.
- GET  /ausbilder-verwaltung/{id}                 -> Profilseite (Kontakt,
  Zustaendigkeit, Liste "seiner" Azubis inkl. Ausnahmen-Pflege). Zusaetzlich
  zu orga/admin lesbar fuer die Person SELBST (UPN-Abgleich) -- bewusst OHNE
  require_roles(), da sonst die Rolle "ausbilder" hier grundsaetzlich
  ausgesperrt waere.
- GET/POST /ausbilder-verwaltung/{id}/bearbeiten  -> Stammdaten-Formular
  (dasselbe Template wie /neu).
- POST /ausbilder-verwaltung/{id}/entfernen       -> loescht die Person
  vollstaendig (inkl. Austragen aus Department.verantwortliche und ihrer
  Ausnahmen).
- POST /ausbilder-verwaltung/{id}/ausnahmen(...)  -> Ausnahmen pflegen
  (ZUSAETZLICH/AUSGENOMMEN je Trainee), nur orga/admin.

WICHTIGER HINWEIS (Kollision mit der Alt-Mechanik): Department.verantwortliche
bleibt AUCH ueber app/routers/departments.py (Freitext-Textarea im
Abteilungs-Formular) direkt editierbar. Wird dort eine UPN eingetragen, die
(noch) keinen Betreuer-Datensatz hat, taucht diese Person NICHT in dieser
Liste auf (sie hat weiterhin Abteilungs-Rechte ueber allowed_dept_ids(),
ist hier aber unsichtbar) -- diese Seite zeigt ausschliesslich Personen mit
einem Betreuer-Datensatz. Das ist eine bewusste Einschraenkung dieses
Umbaus, kein Bug: ein vollstaendiger Abgleich beider Datenquellen ist nicht
Teil dieser Aenderung.
"""
import urllib.parse
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import Betreuer, BetreuerTrainee, Department, Trainee, TraineeClass
from app.models.betreuer import FUNKTION_LABELS, MODUS_LABELS
from app.services.auth_service import CurrentUser, require_roles
from app.services.betreuung_utils import trainees_fuer_betreuer
from app.services.membership_utils import beruf_art_map, beruf_bereich_map, beruf_optionen, beruf_und_lehrjahr
from app.services.verantwortliche_utils import people_by_upn, sync_assignments

router = APIRouter(prefix="/ausbilder-verwaltung", tags=["ausbilder-verwaltung"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
templates.env.globals["FUNKTION_LABELS"] = FUNKTION_LABELS
templates.env.globals["MODUS_LABELS"] = MODUS_LABELS
DB = Annotated[Session, Depends(get_session)]


def _all_departments(db: Session) -> list[Department]:
    return db.exec(select(Department).order_by(Department.code)).all()


def _beruf_form_context(db: Session) -> dict:
    """Kontext fuer die Beruf-Checkbox-Liste (Schnellauswahl "Alle"/"Keine"/
    "Nur Ausbildungsberufe"/"Nur Studiengaenge") -- dasselbe Muster wie
    app/routers/departments.py: _beruf_form_context (bewusst hier dupliziert
    statt importiert, analog dem Duplikations-Stil migrationlokaler
    Hilfsfunktionen in diesem Projekt)."""
    classes = db.exec(select(TraineeClass)).all()
    return {
        "beruf_optionen": beruf_optionen(classes),
        "beruf_art_map": beruf_art_map(classes),
        "beruf_bereich_map": beruf_bereich_map(classes),
    }


def _parse_berufe(berufe: list[str]) -> list[str]:
    """Normalisiert die Beruf-Checkbox-Auswahl: leer bleibt leer (= fuer
    KEINEN Beruf zustaendig, s. app/services/betreuung_utils.py), Duplikate
    raus, Reihenfolge stabil."""
    gesehen: list[str] = []
    for b in berufe:
        b = (b or "").strip()
        if b and b not in gesehen:
            gesehen.append(b)
    return gesehen


def _dept_ids_for_upn(db: Session, upn: str) -> set[int]:
    depts = people_by_upn(db).get(upn.strip().lower(), [])
    return {d.id for d in depts}


def _sync_departments_on_rename(db: Session, old_upn: str, new_upn: str, dept_ids: set[int]) -> None:
    """Schreibt die Abteilungs-Checkbox-Auswahl nach Department.verantwortliche.

    Aendert sich die UPN dabei (Umbenennung), wird die ALTE Schreibweise
    zuerst ueberall ausgetragen -- sonst blieben Eintraege unter der alten
    UPN als Karteileichen stehen (sync_assignments() findet nur Eintraege,
    die zur UEBERGEBENEN UPN case-insensitiv passen)."""
    if old_upn.strip().lower() != new_upn.strip().lower():
        sync_assignments(db, old_upn, set())
    sync_assignments(db, new_upn, dept_ids)


# ── Liste ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def list_ausbilder(
    request: Request, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    all_betreuer = db.exec(select(Betreuer)).all()
    people = people_by_upn(db)
    rows = sorted(
        (
            {
                "betreuer": b,
                "departments": people.get(b.upn.strip().lower(), []),
            }
            for b in all_betreuer
        ),
        key=lambda r: (r["betreuer"].name or r["betreuer"].upn).lower(),
    )
    return templates.TemplateResponse(request, "ausbilder_verwaltung/list.html", {
        "rows": rows,
        "active_nav": "ausbilder_verwaltung",
    })


# ── Anlegen ──────────────────────────────────────────────────────────────

@router.get("/neu", response_class=HTMLResponse)
def new_betreuer_form(
    request: Request, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    return templates.TemplateResponse(request, "ausbilder_verwaltung/form.html", {
        "betreuer": None,
        "selected_dept_ids": set(),
        "departments": _all_departments(db),
        "active_nav": "ausbilder_verwaltung",
        **_beruf_form_context(db),
    })


@router.post("/neu", response_class=RedirectResponse)
def create_betreuer(
    db: DB,
    upn: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
    funktion: Annotated[str, Form()] = "SONSTIGES",
    email: Annotated[str, Form()] = "",
    telefon: Annotated[str, Form()] = "",
    notiz: Annotated[str, Form()] = "",
    aktiv: Annotated[str, Form()] = "",
    beruf: Annotated[list[str], Form()] = [],
    abteilung_ids: Annotated[list[int], Form()] = [],
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    upn_clean = upn.strip()
    if not upn_clean:
        return RedirectResponse(
            f"/ausbilder-verwaltung/?msg=error&detail={urllib.parse.quote('UPN ist Pflicht')}",
            status_code=303,
        )
    bestehend = db.exec(select(Betreuer)).all()
    if any(b.upn.strip().lower() == upn_clean.lower() for b in bestehend):
        return RedirectResponse(
            f"/ausbilder-verwaltung/?msg=error&detail={urllib.parse.quote('UPN bereits vorhanden -- bitte dort bearbeiten')}",
            status_code=303,
        )
    if funktion not in FUNKTION_LABELS:
        funktion = "SONSTIGES"

    betreuer = Betreuer(
        upn=upn_clean,
        name=name.strip(),
        funktion=funktion,
        email=email.strip(),
        telefon=telefon.strip(),
        notiz=notiz,
        aktiv=bool(aktiv),
        berufe=_parse_berufe(beruf),
    )
    db.add(betreuer)
    db.commit()

    sync_assignments(db, upn_clean, set(abteilung_ids))
    return RedirectResponse("/ausbilder-verwaltung/?msg=created", status_code=303)


# ── Profilseite ──────────────────────────────────────────────────────────

@router.get("/{betreuer_id:int}", response_class=HTMLResponse)
def betreuer_detail(request: Request, betreuer_id: int, db: DB):
    """Profilseite: orga/admin ODER die Person selbst (UPN-Abgleich).

    Bewusst OHNE require_roles()-Dependency: sonst waere die Rolle
    "ausbilder" hier immer ausgesperrt, auch wenn ihre eigene UPN zum
    Betreuer-Datensatz passt. Die Auth-Middleware (app/main.py) setzt
    request.state.current_user fuer jeden eingeloggten Staff-User bereits
    VOR dem Erreichen dieser Funktion -- ein azubi-Login wird dort schon
    umgeleitet.
    """
    user: CurrentUser = request.state.current_user
    betreuer = db.get(Betreuer, betreuer_id)
    if betreuer is None:
        raise HTTPException(status_code=404, detail="Person nicht gefunden")

    is_self = user.upn.strip().lower() == betreuer.upn.strip().lower()
    is_staff_admin = user.rolle in ("orga", "admin")
    if not is_staff_admin and not is_self:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    dept_ids = _dept_ids_for_upn(db, betreuer.upn)
    departments = [d for d in _all_departments(db) if d.id in dept_ids]

    trainees = trainees_fuer_betreuer(db, betreuer)
    trainee_rows = []
    all_classes = {c.id: c for c in db.exec(select(TraineeClass)).all()}
    for t in trainees:
        klasse = all_classes.get(t.klasse_id) if t.klasse_id else None
        beruf_token, lehrjahr = beruf_und_lehrjahr(klasse.name if klasse else None)
        trainee_rows.append({"trainee": t, "beruf": beruf_token, "lehrjahr": lehrjahr})

    ausnahmen = []
    if is_staff_admin:
        rows = db.exec(
            select(BetreuerTrainee).where(BetreuerTrainee.betreuer_id == betreuer_id)
        ).all()
        all_trainees_by_id = {t.id: t for t in db.exec(select(Trainee)).all()}
        ausnahmen = sorted(
            (
                {"ausnahme": a, "trainee": all_trainees_by_id.get(a.trainee_id)}
                for a in rows
                if a.trainee_id in all_trainees_by_id
            ),
            key=lambda r: (r["trainee"].nachname, r["trainee"].vorname),
        )
        alle_aktiven_trainees = sorted(
            db.exec(select(Trainee).where(Trainee.aktiv == True)).all(),  # noqa: E712
            key=lambda t: (t.nachname, t.vorname),
        )
    else:
        alle_aktiven_trainees = []

    return templates.TemplateResponse(request, "ausbilder_verwaltung/detail.html", {
        "betreuer": betreuer,
        "departments": departments,
        "trainee_rows": trainee_rows,
        "ausnahmen": ausnahmen,
        "alle_aktiven_trainees": alle_aktiven_trainees,
        "is_staff_admin": is_staff_admin,
        "active_nav": "ausbilder_verwaltung",
    })


# ── Bearbeiten ───────────────────────────────────────────────────────────

@router.get("/{betreuer_id:int}/bearbeiten", response_class=HTMLResponse)
def edit_betreuer_form(
    request: Request, betreuer_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    betreuer = db.get(Betreuer, betreuer_id)
    if betreuer is None:
        raise HTTPException(status_code=404, detail="Person nicht gefunden")
    return templates.TemplateResponse(request, "ausbilder_verwaltung/form.html", {
        "betreuer": betreuer,
        "selected_dept_ids": _dept_ids_for_upn(db, betreuer.upn),
        "departments": _all_departments(db),
        "active_nav": "ausbilder_verwaltung",
        **_beruf_form_context(db),
    })


@router.post("/{betreuer_id:int}/bearbeiten", response_class=RedirectResponse)
def update_betreuer(
    betreuer_id: int, db: DB,
    upn: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
    funktion: Annotated[str, Form()] = "SONSTIGES",
    email: Annotated[str, Form()] = "",
    telefon: Annotated[str, Form()] = "",
    notiz: Annotated[str, Form()] = "",
    aktiv: Annotated[str, Form()] = "",
    beruf: Annotated[list[str], Form()] = [],
    abteilung_ids: Annotated[list[int], Form()] = [],
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    betreuer = db.get(Betreuer, betreuer_id)
    if betreuer is None:
        raise HTTPException(status_code=404, detail="Person nicht gefunden")

    upn_clean = upn.strip()
    if not upn_clean:
        return RedirectResponse(
            f"/ausbilder-verwaltung/?msg=error&detail={urllib.parse.quote('UPN darf nicht leer sein')}",
            status_code=303,
        )
    andere = db.exec(select(Betreuer).where(Betreuer.id != betreuer_id)).all()
    if any(b.upn.strip().lower() == upn_clean.lower() for b in andere):
        return RedirectResponse(
            f"/ausbilder-verwaltung/?msg=error&detail={urllib.parse.quote('UPN bereits einer anderen Person zugeordnet')}",
            status_code=303,
        )
    if funktion not in FUNKTION_LABELS:
        funktion = "SONSTIGES"

    alte_upn = betreuer.upn
    betreuer.upn = upn_clean
    betreuer.name = name.strip()
    betreuer.funktion = funktion
    betreuer.email = email.strip()
    betreuer.telefon = telefon.strip()
    betreuer.notiz = notiz
    betreuer.aktiv = bool(aktiv)
    # JSON-Spalte: IMMER eine neue Liste zuweisen (siehe Kommentar in
    # app/models/feedback_bogen.py).
    betreuer.berufe = _parse_berufe(beruf)
    db.add(betreuer)
    db.commit()

    _sync_departments_on_rename(db, alte_upn, upn_clean, set(abteilung_ids))
    return RedirectResponse("/ausbilder-verwaltung/?msg=updated", status_code=303)


@router.post("/{betreuer_id:int}/entfernen", response_class=RedirectResponse)
def remove_betreuer(
    betreuer_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    betreuer = db.get(Betreuer, betreuer_id)
    if betreuer is None:
        return RedirectResponse("/ausbilder-verwaltung/?msg=error", status_code=303)

    # Abteilungs-Zustaendigkeit (Department.verantwortliche) austragen --
    # sonst bleibt die Person dort als Freitext-Karteileiche stehen, obwohl
    # ihr Betreuer-Datensatz geloescht wird.
    sync_assignments(db, betreuer.upn, set())

    # Ausnahmen explizit vorab loeschen (robust fuer SQLite + Postgres,
    # analog app/routers/trainees.py: loeschen_trainee).
    for a in db.exec(select(BetreuerTrainee).where(BetreuerTrainee.betreuer_id == betreuer_id)).all():
        db.delete(a)

    db.delete(betreuer)
    db.commit()
    return RedirectResponse("/ausbilder-verwaltung/?msg=deleted", status_code=303)


# ── Ausnahmen (ZUSAETZLICH/AUSGENOMMEN) ─────────────────────────────────

@router.post("/{betreuer_id:int}/ausnahmen", response_class=RedirectResponse)
def add_ausnahme(
    betreuer_id: int, db: DB,
    trainee_id: Annotated[int, Form()],
    modus: Annotated[str, Form()],
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    betreuer = db.get(Betreuer, betreuer_id)
    if betreuer is None:
        raise HTTPException(status_code=404, detail="Person nicht gefunden")
    if modus not in MODUS_LABELS:
        raise HTTPException(status_code=400, detail="Ungueltiger Modus")
    trainee = db.get(Trainee, trainee_id)
    if trainee is None:
        raise HTTPException(status_code=404, detail="Trainee nicht gefunden")

    bestehend = db.exec(
        select(BetreuerTrainee).where(
            BetreuerTrainee.betreuer_id == betreuer_id,
            BetreuerTrainee.trainee_id == trainee_id,
        )
    ).first()
    if bestehend is not None:
        bestehend.modus = modus
        db.add(bestehend)
    else:
        db.add(BetreuerTrainee(betreuer_id=betreuer_id, trainee_id=trainee_id, modus=modus))
    db.commit()
    return RedirectResponse(f"/ausbilder-verwaltung/{betreuer_id}?msg=updated", status_code=303)


@router.post("/{betreuer_id:int}/ausnahmen/{ausnahme_id:int}/entfernen", response_class=RedirectResponse)
def remove_ausnahme(
    betreuer_id: int, ausnahme_id: int, db: DB,
    user: CurrentUser = Depends(require_roles("orga", "admin")),
):
    ausnahme = db.get(BetreuerTrainee, ausnahme_id)
    if ausnahme is not None and ausnahme.betreuer_id == betreuer_id:
        db.delete(ausnahme)
        db.commit()
    return RedirectResponse(f"/ausbilder-verwaltung/{betreuer_id}?msg=deleted", status_code=303)
