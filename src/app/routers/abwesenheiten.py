"""Staff-UI fuer Abwesenheiten (Overlay-Modell, siehe app/models/abwesenheit.py +
app/services/abwesenheit_utils.py fuer die Fachlogik).

NUR orga/admin duerfen diesen Router ueberhaupt aufrufen -- Ausbilder haben
keinen Zugriff (weder Liste noch Anlegen/Aendern/Loeschen), anders als beim
Feedback-Router.

- GET  /abwesenheiten/                    -> Liste aller Abwesenheiten (Filter
  trainee_id, typ, Zeitraum-Jahr), neueste zuerst.
- GET  /abwesenheiten/neu                  -> Formular (Anlegen).
- POST /abwesenheiten/                     -> legt eine Abwesenheit an
  (quelle=PLANER). Ueberschneidet sich der Zeitraum mit einer bestehenden
  Abwesenheit desselben Trainees, wird trotzdem angelegt -- nur ein
  Hinweis-Flash, KEIN harter Block (siehe ueberlappende()).
- GET  /abwesenheiten/{id}/bearbeiten       -> Formular (Aendern).
- POST /abwesenheiten/{id}                 -> aendert alle Felder; prueft
  Ueberschneidungen GENAUSO wie beim Anlegen (exclude_id blendet den
  bearbeiteten Eintrag selbst aus), ebenfalls nur Hinweis-Flash, kein Block.
- POST /abwesenheiten/{id}/loeschen         -> loescht endgueltig.

Datums-Parsing ist defensiv: fehlende/kaputte Werte fuehren zu 400, nie zu
einem 500 (siehe _parse_date_or_none). Zeitraeume laenger als 366 Tage
werden mit 400 abgelehnt (Befund 3) -- sonst wuerde die Werktage-Zaehlung
in dieser Liste (_werktage) pro Zeile ueber zehntausende Tage laufen und ein
so eingetragener Trainee waere in JEDER Woche als voll abwesend markiert.
"""
from datetime import date, timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import Abwesenheit, AbwesenheitQuelle, AbwesenheitTyp, Trainee
from app.services.abwesenheit_utils import ueberlappende
from app.services.auth_service import CurrentUser, require_roles

router = APIRouter(prefix="/abwesenheiten", tags=["abwesenheiten"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]
CU = Annotated[CurrentUser, Depends(require_roles("orga", "admin"))]


# ── Kleine Helfer ─────────────────────────────────────────────────────────

def _parse_int_or_none(raw: str | None) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_date_or_none(raw: str | None) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _werktage(von_datum: date, bis_datum: date) -> int:
    """Anzahl Werktage (Mo-Fr) im Zeitraum [von_datum, bis_datum] (inklusive)."""
    tage = 0
    d = von_datum
    while d <= bis_datum:
        if d.isoweekday() <= 5:
            tage += 1
        d += timedelta(days=1)
    return tage


def _get_or_404(db: Session, abwesenheit_id: int) -> Abwesenheit:
    a = db.get(Abwesenheit, abwesenheit_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Abwesenheit nicht gefunden")
    return a


def _sorted_trainees(db: Session) -> list[Trainee]:
    return sorted(db.exec(select(Trainee)).all(), key=lambda t: (t.nachname, t.vorname))


def _parse_form(form) -> tuple[int | None, date | None, date | None, str, str]:
    """Liest die vier gemeinsamen Formularfelder aus (Anlegen + Aendern)."""
    trainee_id = _parse_int_or_none(form.get("trainee_id"))
    von = _parse_date_or_none(form.get("von_datum"))
    bis = _parse_date_or_none(form.get("bis_datum"))
    typ_raw = (form.get("typ") or "").strip()
    kommentar = (form.get("kommentar") or "").strip()
    return trainee_id, von, bis, typ_raw, kommentar


MAX_ZEITRAUM_TAGE = 366  # Befund 3: Plausibilitaetsgrenze (deckt jedes Schuljahr inkl. Schaltjahr ab)


def _validate(db: Session, trainee_id: int | None, von: date | None, bis: date | None, typ_raw: str) -> AbwesenheitTyp:
    """Prueft die Pflichtfelder; wirft 400 bei fehlenden/ungueltigen Werten,
    404 wenn der Trainee nicht existiert. Gibt den geparsten Typ zurueck.

    Befund 3: Ein Zeitraum von mehr als MAX_ZEITRAUM_TAGE Tagen (z. B. durch
    einen manipulierten POST mit von=0001-01-01/bis=9999-12-31) wird mit 400
    abgelehnt -- ohne diese Grenze wuerde der Trainee in JEDER Woche als voll
    abwesend gelten und die Staff-Liste muesste pro Zeile zehntausende Tage
    durchlaufen."""
    if trainee_id is None or von is None or bis is None:
        raise HTTPException(status_code=400, detail="Pflichtfelder fehlen oder Datum ungueltig")
    if bis < von:
        raise HTTPException(status_code=400, detail="Enddatum darf nicht vor dem Startdatum liegen")
    if (bis - von).days > MAX_ZEITRAUM_TAGE:
        raise HTTPException(
            status_code=400,
            detail=f"Zeitraum darf nicht laenger als {MAX_ZEITRAUM_TAGE} Tage sein",
        )
    try:
        typ = AbwesenheitTyp(typ_raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungueltiger Abwesenheitstyp")
    if db.get(Trainee, trainee_id) is None:
        raise HTTPException(status_code=404, detail="Trainee nicht gefunden")
    return typ


# ── Liste ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def list_abwesenheiten(request: Request, db: DB, user: CU):
    trainee_filter = request.query_params.get("trainee_id", "")
    typ_filter = request.query_params.get("typ", "")
    jahr_filter = request.query_params.get("jahr", "")

    query = select(Abwesenheit)
    if trainee_filter.isdigit():
        query = query.where(Abwesenheit.trainee_id == int(trainee_filter))
    if typ_filter:
        query = query.where(Abwesenheit.typ == typ_filter)
    if jahr_filter.isdigit():
        jahr = int(jahr_filter)
        jahr_start = date(jahr, 1, 1)
        jahr_end = date(jahr, 12, 31)
        query = query.where(
            Abwesenheit.von_datum <= jahr_end, Abwesenheit.bis_datum >= jahr_start
        )

    rows = db.exec(query).all()
    rows_sorted = sorted(
        rows, key=lambda a: (a.von_datum.toordinal(), a.id or 0), reverse=True
    )
    werktage_map = {a.id: _werktage(a.von_datum, a.bis_datum) for a in rows_sorted}

    trainee_map = {t.id: t for t in db.exec(select(Trainee)).all()}

    alle = db.exec(select(Abwesenheit)).all()
    jahre = sorted({a.von_datum.year for a in alle} | {a.bis_datum.year for a in alle}, reverse=True)

    return templates.TemplateResponse(request, "abwesenheiten/index.html", {
        "rows": rows_sorted,
        "trainee_map": trainee_map,
        "trainees_filter": _sorted_trainees(db),
        "werktage_map": werktage_map,
        "typen": list(AbwesenheitTyp),
        "jahre": jahre,
        "f_trainee_id": trainee_filter,
        "f_typ": typ_filter,
        "f_jahr": jahr_filter,
        "active_nav": "abwesenheiten",
    })


# ── Anlegen ───────────────────────────────────────────────────────────────

@router.get("/neu", response_class=HTMLResponse)
def neu_abwesenheit(request: Request, db: DB, user: CU):
    return templates.TemplateResponse(request, "abwesenheiten/form.html", {
        "abwesenheit": None,
        "trainees": _sorted_trainees(db),
        "typen": list(AbwesenheitTyp),
        "action_url": "/abwesenheiten/",
        "active_nav": "abwesenheiten",
    })


@router.post("/", response_class=RedirectResponse)
async def create_abwesenheit(request: Request, db: DB, user: CU):
    form = await request.form()
    trainee_id, von, bis, typ_raw, kommentar = _parse_form(form)
    typ = _validate(db, trainee_id, von, bis, typ_raw)

    ueberschneidungen = ueberlappende(db, trainee_id, von, bis)

    a = Abwesenheit(
        trainee_id=trainee_id, von_datum=von, bis_datum=bis, typ=typ,
        kommentar=kommentar, quelle=AbwesenheitQuelle.PLANER,
        erstellt_von_upn=user.upn, erstellt_am=date.today(),
    )
    db.add(a)
    db.commit()

    if ueberschneidungen:
        hinweis = quote(
            f"Hinweis: Zeitraum ueberschneidet sich mit {len(ueberschneidungen)} "
            "bestehender Abwesenheit desselben Trainees."
        )
        return RedirectResponse(f"/abwesenheiten/?msg=created&detail={hinweis}", status_code=303)
    return RedirectResponse("/abwesenheiten/?msg=created", status_code=303)


# ── Aendern ───────────────────────────────────────────────────────────────

@router.get("/{abwesenheit_id:int}/bearbeiten", response_class=HTMLResponse)
def edit_abwesenheit(request: Request, abwesenheit_id: int, db: DB, user: CU):
    a = _get_or_404(db, abwesenheit_id)
    return templates.TemplateResponse(request, "abwesenheiten/form.html", {
        "abwesenheit": a,
        "trainees": _sorted_trainees(db),
        "typen": list(AbwesenheitTyp),
        "action_url": f"/abwesenheiten/{a.id}",
        "active_nav": "abwesenheiten",
    })


@router.post("/{abwesenheit_id:int}", response_class=RedirectResponse)
async def update_abwesenheit(request: Request, abwesenheit_id: int, db: DB, user: CU):
    a = _get_or_404(db, abwesenheit_id)
    form = await request.form()
    trainee_id, von, bis, typ_raw, kommentar = _parse_form(form)
    typ = _validate(db, trainee_id, von, bis, typ_raw)

    # Befund 10: dieselbe Ueberschneidungspruefung wie beim Anlegen -- ohne
    # exclude_id wuerde jede unveraenderte Bearbeitung sich staendig selbst
    # als Ueberschneidung melden; verschiebt der Planer den Zeitraum exakt
    # auf eine bestehende Abwesenheit, entsteht sonst kommentarlos ein
    # Doppel-Eintrag. Weiterhin nur Hinweis-Flash, KEIN harter Block.
    ueberschneidungen = ueberlappende(db, trainee_id, von, bis, exclude_id=a.id)

    a.trainee_id = trainee_id
    a.von_datum = von
    a.bis_datum = bis
    a.typ = typ
    a.kommentar = kommentar
    db.add(a)
    db.commit()

    if ueberschneidungen:
        hinweis = quote(
            f"Hinweis: Zeitraum ueberschneidet sich mit {len(ueberschneidungen)} "
            "bestehender Abwesenheit desselben Trainees."
        )
        return RedirectResponse(f"/abwesenheiten/?msg=updated&detail={hinweis}", status_code=303)
    return RedirectResponse("/abwesenheiten/?msg=updated", status_code=303)


# ── Loeschen ──────────────────────────────────────────────────────────────

@router.post("/{abwesenheit_id:int}/loeschen", response_class=RedirectResponse)
def delete_abwesenheit(abwesenheit_id: int, db: DB, user: CU):
    a = _get_or_404(db, abwesenheit_id)
    db.delete(a)
    db.commit()
    return RedirectResponse("/abwesenheiten/?msg=deleted", status_code=303)
