"""Ausbilder-Selbstbedienung: eigene Abteilung(en) einsehen + Bloecke bestaetigen.

- GET  /meine-abteilung/          -> je verantworteter Abteilung die offenen
  Bloecke (assignment_blocks) + Formular zum Einsatz-Vorschlagen + eigene
  eingereichte Vorschlaege.
- POST /meine-abteilung/block     -> Block (mehrere Assignment-Zellen) auf
  einen Schlag bestaetigen/ablehnen (+ Notiz/Feedback). Nur fuer Bloecke der
  eigenen (verantworteten) Abteilungen.
- POST /meine-abteilung/vorschlag -> Einsatz fuer einen Trainee in der
  eigenen Abteilung vorschlagen (EinsatzVorschlag, status=offen); von
  Orga/Admin unter /vorschlaege/ anzunehmen oder abzulehnen.
- POST /meine-abteilung/notiz     -> TraineeNotiz (Notiz-Verlauf ueber den
  Azubi, NICHT das Assignment.notiz/feedback obiger Zeilen) aus einem
  Einsatz-Block heraus anlegen. Berechtigung siehe
  app.services.trainee_notiz_service.darf_notiz_anlegen -- bewusst NICHT
  dieselbe allowed_dept_ids-Regel wie block_action/create_vorschlag (dort
  sind auch orga/admin auf die eigene UPN beschraenkt, hier nicht).

Sicherheit: allowed_dept_ids(db, user) ist in block_action/create_vorschlag
die alleinige Quelle der Wahrheit fuer "eigene Abteilung" -- jede Abweichung
ist ein 403. Fuer /meine-abteilung/notiz gilt stattdessen darf_notiz_anlegen()
(siehe oben).
"""
import json
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    Assignment,
    AssignmentTyp,
    Department,
    EinsatzVorschlag,
    Schoolyear,
    Trainee,
)
from app.services.auth_service import CurrentUser, allowed_dept_ids, require_roles
from app.services.block_utils import apply_to_block, assignment_blocks
from app.services.feedback_utils import bogen_fuer_block
from app.services.membership_utils import aktuelles_schuljahr_id
from app.services.trainee_notiz_service import darf_notiz_anlegen, erstelle_notiz
from app.utils.kw import iter_schoolyear_weeks, kw_to_monday

router = APIRouter(prefix="/meine-abteilung", tags=["meine-abteilung"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]


# ── KW-Auswahl fuers Vorschlag-Formular ─────────────────────────────────────

def _week_options(sy: Schoolyear) -> list[dict]:
    """Baut die Wochen-Optionen (Wert 'kw,jahr' + Label) fuer die KW-Selects des
    Vorschlag-Formulars -- deckt den Jahreswechsel innerhalb eines Schuljahres
    ab (z. B. KW36/2025 .. KW35/2026)."""
    options = []
    for kw, jahr in iter_schoolyear_weeks(sy.start_kw, sy.start_year, sy.end_kw, sy.end_year):
        monday = kw_to_monday(kw, jahr)
        options.append({
            "value": f"{kw},{jahr}",
            "label": f"KW {kw} / {jahr} (ab {monday.strftime('%d.%m.')})",
        })
    return options


def _parse_kw_kombi(raw: str) -> tuple[int | None, int | None]:
    """Parst eine KW-Select-Option im Format 'kw,jahr' robust: alles
    Ungueltige/Leere ergibt (None, None) statt eines 500ers."""
    parts = (raw or "").split(",")
    if len(parts) != 2:
        return None, None
    kw_str, jahr_str = parts[0].strip(), parts[1].strip()
    if not kw_str.isdigit() or not jahr_str.isdigit():
        return None, None
    return int(kw_str), int(jahr_str)


# ── Uebersicht ────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def meine_abteilung(
    request: Request,
    db: DB,
    user: Annotated[CurrentUser, Depends(require_roles("ausbilder", "orga", "admin"))],
):
    dept_ids = allowed_dept_ids(db, user)

    years = db.exec(
        select(Schoolyear)
        .where(Schoolyear.archiviert == False)  # noqa: E712
        .order_by(Schoolyear.start_year.desc())
    ).all()
    schoolyear_id = request.query_params.get("schoolyear_id", "")
    if not schoolyear_id:
        # Default = das Ausbildungsjahr, in dem HEUTE liegt (nicht das neueste --
        # ein bereits angelegtes Folgejahr hat noch keine Einsaetze und wuerde
        # eine leere Seite zeigen). Fallback: neuestes nicht-archiviertes Jahr.
        schoolyear_id = aktuelles_schuljahr_id(db)

    # KW-Optionen je (nicht-archiviertem) Schuljahr fuers Vorschlag-Formular --
    # weeks_by_year fuer die serverseitige Vorbelegung (kein-JS-Fallback),
    # weeks_by_year_json fuers Nachladen der Wochen-Selects bei Jahreswechsel
    # im Formular (ohne Server-Roundtrip).
    weeks_by_year = {y.id: _week_options(y) for y in years}
    weeks_by_year_json = json.dumps(weeks_by_year)

    if not dept_ids:
        return templates.TemplateResponse(request, "ausbilder/meine_abteilung.html", {
            "no_dept": True,
            "user": user,
            "years": years,
            "selected_year": schoolyear_id,
            "weeks_by_year": weeks_by_year,
            "weeks_by_year_json": weeks_by_year_json,
            "active_nav": "meine_abteilung",
        })

    depts = db.exec(
        select(Department).where(Department.id.in_(list(dept_ids))).order_by(Department.code)
    ).all()

    dept_blocks = []
    offen_count = 0
    for d in depts:
        blocks = assignment_blocks(db, d.id, schoolyear_id) if schoolyear_id else []
        offen_count += sum(1 for b in blocks if b["status"] == "offen")
        for b in blocks:
            b["bogen"] = (
                bogen_fuer_block(
                    db, "AUSBILDER", b["trainee"].id, d.id, schoolyear_id,
                    b["kw_von"], b["jahr_von"], b["kw_bis"], b["jahr_bis"],
                )
                if b["trainee"] is not None else None
            )
        dept_blocks.append({"dept": d, "blocks": blocks})

    trainees = db.exec(
        select(Trainee).where(Trainee.aktiv == True)  # noqa: E712
        .order_by(Trainee.nachname, Trainee.vorname)
    ).all()

    own_vorschlaege = db.exec(
        select(EinsatzVorschlag)
        .where(EinsatzVorschlag.eingereicht_von_upn == user.upn)
    ).all()
    own_vorschlaege = sorted(
        own_vorschlaege,
        key=lambda v: (v.erstellt_am or date.min, v.id or 0),
        reverse=True,
    )

    trainee_map = {t.id: t for t in db.exec(select(Trainee)).all()}
    dept_map = {d.id: d for d in db.exec(select(Department)).all()}

    return templates.TemplateResponse(request, "ausbilder/meine_abteilung.html", {
        "no_dept": False,
        "user": user,
        "dept_blocks": dept_blocks,
        "offen_count": offen_count,
        "trainees": trainees,
        "years": years,
        "selected_year": schoolyear_id,
        "own_vorschlaege": own_vorschlaege,
        "trainee_map": trainee_map,
        "dept_map": dept_map,
        "weeks_by_year": weeks_by_year,
        "weeks_by_year_json": weeks_by_year_json,
        "active_nav": "meine_abteilung",
    })


# ── Block bestaetigen/ablehnen ───────────────────────────────────────────

@router.post("/block", response_class=RedirectResponse)
def block_action(
    db: DB,
    user: Annotated[CurrentUser, Depends(require_roles("ausbilder", "orga", "admin"))],
    assignment_ids: Annotated[str, Form()],
    aktion: Annotated[str, Form()],
    notiz: Annotated[str, Form()] = "",
    feedback: Annotated[str, Form()] = "",
    schoolyear_id: Annotated[str, Form()] = "",
):
    if aktion not in ("bestaetigt", "abgelehnt"):
        raise HTTPException(status_code=400, detail="Unbekannte Aktion")

    ids = [int(x) for x in assignment_ids.split(",") if x.strip().isdigit()]
    if not ids:
        raise HTTPException(status_code=400, detail="Keine Assignment-IDs")

    allowed = allowed_dept_ids(db, user)
    rows = db.exec(
        select(Assignment).where(Assignment.id.in_(ids))  # type: ignore[union-attr]
    ).all()
    if len(rows) != len(ids):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")
    for a in rows:
        if a.typ != AssignmentTyp.ABTEILUNG or a.abteilung_id not in allowed:
            raise HTTPException(status_code=403, detail="Keine Berechtigung")

    apply_to_block(
        db,
        ids,
        bestaetigung=aktion,
        notiz=notiz if notiz.strip() else None,
        feedback=feedback if feedback.strip() else None,
    )

    url = "/meine-abteilung/"
    if schoolyear_id:
        url += f"?schoolyear_id={schoolyear_id}"
    return RedirectResponse(url, status_code=303)


# ── Einsatz vorschlagen ───────────────────────────────────────────────────

@router.post("/vorschlag", response_class=RedirectResponse)
def create_vorschlag(
    db: DB,
    user: Annotated[CurrentUser, Depends(require_roles("ausbilder", "orga", "admin"))],
    trainee_id: Annotated[int, Form()],
    department_id: Annotated[int, Form()],
    schoolyear_id: Annotated[str, Form()],
    von: Annotated[str, Form()],
    bis: Annotated[str, Form()],
    kommentar: Annotated[str, Form()] = "",
):
    """`von`/`bis` kommen aus den KW-Selects im Format 'kw,jahr' (siehe
    _week_options) -- robust geparst, jede Ungueltigkeit ergibt 400, nie 500."""
    if department_id not in allowed_dept_ids(db, user):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    sy = db.get(Schoolyear, schoolyear_id)
    if sy is None:
        raise HTTPException(status_code=400, detail="Unbekanntes Ausbildungsjahr")

    kw_von, jahr_von = _parse_kw_kombi(von)
    kw_bis, jahr_bis = _parse_kw_kombi(bis)
    if kw_von is None or kw_bis is None:
        raise HTTPException(status_code=400, detail="Ungueltige Kalenderwoche")

    week_idx = {
        wk: i
        for i, wk in enumerate(
            iter_schoolyear_weeks(sy.start_kw, sy.start_year, sy.end_kw, sy.end_year)
        )
    }
    idx_von = week_idx.get((kw_von, jahr_von))
    idx_bis = week_idx.get((kw_bis, jahr_bis))
    if idx_von is None or idx_bis is None:
        raise HTTPException(status_code=400, detail="Woche liegt nicht im gewaehlten Ausbildungsjahr")
    if idx_von > idx_bis:
        raise HTTPException(status_code=400, detail="'Bis'-Woche darf nicht vor der 'Von'-Woche liegen")

    db.add(EinsatzVorschlag(
        trainee_id=trainee_id,
        department_id=department_id,
        schoolyear_id=schoolyear_id,
        kw_von=kw_von,
        jahr_von=jahr_von,
        kw_bis=kw_bis,
        jahr_bis=jahr_bis,
        kommentar=kommentar,
        eingereicht_von_upn=user.upn,
        eingereicht_von_name=user.name,
        status="offen",
        erstellt_am=date.today(),
    ))
    db.commit()

    return RedirectResponse(
        f"/meine-abteilung/?msg=created&schoolyear_id={schoolyear_id}", status_code=303
    )


# ── Notiz zum Azubi (Teil C, MIT Einsatz-Kontext) ────────────────────────────

@router.post("/notiz", response_class=RedirectResponse)
def create_notiz(
    db: DB,
    user: Annotated[CurrentUser, Depends(require_roles("ausbilder", "orga", "admin"))],
    trainee_id: Annotated[int, Form()],
    department_id: Annotated[int, Form()],
    schoolyear_id: Annotated[str, Form()] = "",
    kw_von: Annotated[int | None, Form()] = None,
    jahr_von: Annotated[int | None, Form()] = None,
    kw_bis: Annotated[int | None, Form()] = None,
    jahr_bis: Annotated[int | None, Form()] = None,
    text: Annotated[str, Form()] = "",
):
    """Legt eine TraineeNotiz MIT Einsatz-Kontext an (aus einem Block heraus).

    Nutzt dieselbe Berechtigungspruefung wie die Profil-Route (siehe
    app.services.trainee_notiz_service.darf_notiz_anlegen), hier mit
    department_id -> Block-Kontext-Regel: bewusst NICHT dieselbe
    Einschraenkung wie block_action/create_vorschlag oben (orga/admin sind
    hier NICHT auf die eigene UPN beschraenkt)."""
    if not darf_notiz_anlegen(db, user, trainee_id, department_id=department_id):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    notiz = erstelle_notiz(
        db, user, trainee_id, text,
        department_id=department_id,
        kw_von=kw_von, jahr_von=jahr_von, kw_bis=kw_bis, jahr_bis=jahr_bis,
    )

    msg = "created" if notiz is not None else "error"
    url = f"/meine-abteilung/?msg={msg}"
    if schoolyear_id:
        url += f"&schoolyear_id={schoolyear_id}"
    return RedirectResponse(url, status_code=303)
