"""Staff-UI fuer Feedbackboegen (Typ AUSBILDER + Typ AZUBI, siehe
app/services/feedback_def.py fuer die Fachlogik der beiden Bogen-Typen).

- GET  /feedback/                 -> Liste aller sichtbaren Boegen (Filter).
- GET  /feedback/neu               -> AUSBILDER-Formular, vorbefuellt aus dem
  Block-Link (Meine Abteilung).
- POST /feedback/                  -> legt den AUSBILDER-Bogen an.
- GET  /feedback/{id}              -> Detail: bearbeitbares Formular solange
  Status entwurf + Rechte, sonst Read-only (BEIDE Typen lesbar).
- POST /feedback/{id}              -> Update (nur Status entwurf).
- POST /feedback/{id}/besprochen   -> abgeschlossen -> besprochen.
- POST /feedback/{id}/reopen       -> besprochen/abgeschlossen -> entwurf
  (Korrektur, NUR orga/admin).
- POST /feedback/{id}/loeschen     -> endgueltig (NUR admin).

Sichtbarkeits-/Bearbeitungsregel (siehe app/routers/ausbilder.py): orga/admin
sehen und bearbeiten ALLE Boegen; ausbilder NUR Boegen, deren department_id in
allowed_dept_ids(db, user) liegt -- jede Abweichung ist ein 403/404,
allowed_dept_ids ist dafuer die alleinige Quelle der Wahrheit.

AZUBI-Boegen (Selbsteinschaetzung) gehoeren dem Azubi: Im Status "entwurf"
sind sie fuer Staff UNSICHTBAR (Liste filtert sie aus, Detail -> 404) --
symmetrisch zum AUSBILDER-Entwurf, der dem Azubi verborgen bleibt. Ab
"abgeschlossen" sind sie fuer Staff read-only; inhaltlich bearbeiten
(POST /feedback/{id}) kann sie Staff NIE (403). Der Status-Workflow
(besprochen/reopen/loeschen) bleibt fuer Staff moeglich.

Kein Endpunkt fuer Status "bestaetigt" -- das macht ausschliesslich der Azubi
ueber /mein-plan (anderer Router).
"""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, or_, select

from app.database import get_session
from app.models import Department, FeedbackBogen, Schoolyear, Trainee, TraineeClass
from app.services.auth_service import CurrentUser, allowed_dept_ids, require_roles
from app.services.feedback_def import (
    AUSBILDER_SEKTIONEN,
    AZUBI_SEKTIONEN,
    EINSATZARTEN,
    FREITEXT_AUSBILDER,
    FREITEXT_AZUBI,
    SKALA_ANFORDERUNGEN,
    SKALA_ERWARTUNGEN,
    STATUS_BADGE_FARBE,
    STATUS_LABELS,
    VERSION_AUSBILDER,
    alle_frage_keys,
)
from app.services.feedback_utils import (
    bogen_fuer_block,
    fehlzeiten_vorbelegung,
    partner_bogen,
)
from app.services.membership_utils import beruf_langname, beruf_und_lehrjahr, klasse_fuer

router = APIRouter(prefix="/feedback", tags=["feedback"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]
CU = Annotated[CurrentUser, Depends(require_roles("ausbilder", "orga", "admin"))]


# ── Kleine Helfer ─────────────────────────────────────────────────────────

def _sektionen_fuer(typ: str) -> list[dict]:
    return AUSBILDER_SEKTIONEN if typ == "AUSBILDER" else AZUBI_SEKTIONEN


def _freitext_felder_fuer(typ: str) -> list[dict]:
    return FREITEXT_AUSBILDER if typ == "AUSBILDER" else FREITEXT_AZUBI


def _skala_fuer(typ: str) -> list[tuple[int, str]]:
    return SKALA_ANFORDERUNGEN if typ == "AUSBILDER" else SKALA_ERWARTUNGEN


def _get_or_404(db: Session, bogen_id: int) -> FeedbackBogen:
    bogen = db.get(FeedbackBogen, bogen_id)
    if bogen is None:
        raise HTTPException(status_code=404, detail="Feedbackbogen nicht gefunden")
    return bogen


def _check_access(db: Session, user: CurrentUser, department_id: int) -> None:
    """403, wenn ein Ausbilder auf eine fremde Abteilung zugreifen will.

    allowed_dept_ids(db, user) ist die alleinige Quelle der Wahrheit -- orga/
    admin sind von dieser Pruefung ausgenommen (duerfen alles).
    """
    if user.rolle == "ausbilder" and department_id not in allowed_dept_ids(db, user):
        raise HTTPException(status_code=403, detail="Keine Berechtigung")


def _parse_int_or_none(raw: str | None) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_antworten(form, typ: str) -> dict:
    antworten: dict[str, int] = {}
    for key in alle_frage_keys(typ):
        wert = _parse_int_or_none(form.get(f"frage_{key}"))
        if wert is not None:
            antworten[key] = wert
    return antworten


def _parse_freitexte(form, typ: str) -> dict:
    return {
        feld["key"]: (form.get(feld["key"]) or "").strip()
        for feld in _freitext_felder_fuer(typ)
    }


def _parse_lernziele(form) -> list:
    texte = form.getlist("lernziel_text")
    werte = form.getlist("lernziel_wert")
    lernziele = []
    for i, text in enumerate(texte):
        text = (text or "").strip()
        if not text:
            continue
        wert = _parse_int_or_none(werte[i] if i < len(werte) else "")
        lernziele.append({"text": text, "bewertung": wert})
    return lernziele


def _kopf_kontext(db: Session, trainee: Trainee | None, schoolyear_id: str) -> dict:
    """Ausbildungsrichtung (beruf_langname/beruf_und_lehrjahr) + Jahrgang
    (Jahr des Ausbildungsbeginns) fuer den Formular-/Detail-Kopf."""
    if trainee is None:
        return {"beruf_lang": "", "jahrgang": None}
    klasse_id = klasse_fuer(db, trainee, schoolyear_id)
    klasse = db.get(TraineeClass, klasse_id) if klasse_id else None
    beruf_token, _lehrjahr = beruf_und_lehrjahr(klasse.name if klasse else None)
    return {
        "beruf_lang": beruf_langname(beruf_token),
        "jahrgang": trainee.ausbildungsbeginn.year if trainee.ausbildungsbeginn else None,
    }


def _form_context(bogen: FeedbackBogen | None, typ: str) -> dict:
    """Gemeinsame Sektions-/Skala-Kontextwerte fuer form.html + detail.html."""
    return {
        "sektionen": _sektionen_fuer(typ),
        "freitext_felder": _freitext_felder_fuer(typ),
        "skala": _skala_fuer(typ),
        "skala_lernziele": SKALA_ANFORDERUNGEN,
        "antworten": bogen.antworten if bogen else {},
        "freitexte": bogen.freitexte if bogen else {},
        "lernziele": bogen.lernziele if bogen else [],
    }


# ── Liste ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def list_feedback(request: Request, db: DB, user: CU):
    dept_ids: set[int] | None = None
    if user.rolle == "ausbilder":
        dept_ids = allowed_dept_ids(db, user)

    trainee_filter = request.query_params.get("trainee_id", "")
    department_filter = request.query_params.get("department_id", "")
    schoolyear_filter = request.query_params.get("schoolyear_id", "")
    status_filter = request.query_params.get("status", "")

    query = select(FeedbackBogen)
    # AZUBI-Entwuerfe sind privat (gehoeren dem Azubi, solange er sie nicht
    # abgeschlossen hat) -- fuer Staff komplett ausblenden.
    query = query.where(
        or_(FeedbackBogen.typ != "AZUBI", FeedbackBogen.status != "entwurf")
    )
    if dept_ids is not None:
        query = query.where(FeedbackBogen.department_id.in_(list(dept_ids) or [-1]))
    if trainee_filter.isdigit():
        query = query.where(FeedbackBogen.trainee_id == int(trainee_filter))
    if department_filter.isdigit():
        query = query.where(FeedbackBogen.department_id == int(department_filter))
    if schoolyear_filter:
        query = query.where(FeedbackBogen.schoolyear_id == schoolyear_filter)
    if status_filter:
        query = query.where(FeedbackBogen.status == status_filter)

    rows = db.exec(query).all()
    rows_sorted = sorted(
        rows,
        key=lambda b: ((b.erstellt_am or date.min).toordinal(), b.id or 0),
        reverse=True,
    )

    trainee_map = {t.id: t for t in db.exec(select(Trainee)).all()}
    dept_map = {d.id: d for d in db.exec(select(Department)).all()}
    if dept_ids is not None:
        depts_filter = [d for d in dept_map.values() if d.id in dept_ids]
        depts_filter.sort(key=lambda d: d.code)
    else:
        depts_filter = sorted(dept_map.values(), key=lambda d: d.code)
    trainees_filter = sorted(
        trainee_map.values(), key=lambda t: (t.nachname, t.vorname)
    )
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()

    return templates.TemplateResponse(request, "feedback/index.html", {
        "boegen": rows_sorted,
        "trainee_map": trainee_map,
        "dept_map": dept_map,
        "depts_filter": depts_filter,
        "trainees_filter": trainees_filter,
        "years": years,
        "status_labels": STATUS_LABELS,
        "status_colors": STATUS_BADGE_FARBE,
        "f_trainee_id": trainee_filter,
        "f_department_id": department_filter,
        "f_schoolyear_id": schoolyear_filter,
        "f_status": status_filter,
        "active_nav": "feedback",
    })


# ── Anlegen (AUSBILDER-Bogen) ────────────────────────────────────────────

@router.get("/neu", response_class=HTMLResponse)
def neu_feedback(
    request: Request,
    db: DB,
    user: CU,
    trainee_id: int,
    department_id: int,
    schoolyear_id: str,
    kw_von: int,
    jahr_von: int,
    kw_bis: int,
    jahr_bis: int,
):
    trainee = db.get(Trainee, trainee_id)
    department = db.get(Department, department_id)
    schoolyear = db.get(Schoolyear, schoolyear_id)
    if trainee is None or department is None or schoolyear is None:
        raise HTTPException(
            status_code=404, detail="Trainee, Abteilung oder Schuljahr nicht gefunden"
        )

    _check_access(db, user, department_id)

    kopf = _kopf_kontext(db, trainee, schoolyear_id)
    fehlzeiten = fehlzeiten_vorbelegung(
        db, trainee_id, schoolyear_id, kw_von, jahr_von, kw_bis, jahr_bis
    )

    ctx = {
        "bogen": None,
        "typ": "AUSBILDER",
        "trainee": trainee,
        "department": department,
        "schoolyear": schoolyear,
        "kw_von": kw_von, "jahr_von": jahr_von, "kw_bis": kw_bis, "jahr_bis": jahr_bis,
        "einsatzarten": EINSATZARTEN,
        "einsatzart_selected": "",
        "fachausbilder_name": user.name or user.upn,
        "fehl_krank": None,
        "fehl_urlaub": fehlzeiten["urlaub"],
        "fehl_schule": fehlzeiten["schule"],
        "fehl_sonstige": None,
        "weiterer_einsatz": "",
        "zugriffe_geloescht": False,
        "action_url": "/feedback/",
        "cancel_url": "/meine-abteilung/",
        "active_nav": "feedback",
        **kopf,
        **_form_context(None, "AUSBILDER"),
    }
    return templates.TemplateResponse(request, "feedback/form.html", ctx)


@router.post("/", response_class=RedirectResponse)
async def create_feedback(request: Request, db: DB, user: CU):
    form = await request.form()

    trainee_id = _parse_int_or_none(form.get("trainee_id"))
    department_id = _parse_int_or_none(form.get("department_id"))
    schoolyear_id = (form.get("schoolyear_id") or "").strip()
    kw_von = _parse_int_or_none(form.get("kw_von"))
    jahr_von = _parse_int_or_none(form.get("jahr_von"))
    kw_bis = _parse_int_or_none(form.get("kw_bis"))
    jahr_bis = _parse_int_or_none(form.get("jahr_bis"))

    if (
        trainee_id is None or department_id is None or not schoolyear_id
        or kw_von is None or jahr_von is None or kw_bis is None or jahr_bis is None
    ):
        raise HTTPException(status_code=400, detail="Pflichtfelder fehlen")

    _check_access(db, user, department_id)

    # Doppelanlage verhindern (Doppel-Submit, Back-Button, zweiter Ausbilder
    # derselben Abteilung): existiert schon ein AUSBILDER-Bogen mit
    # ueberlappendem Zeitraum, dorthin umleiten statt neu anzulegen.
    existing = bogen_fuer_block(
        db, "AUSBILDER", trainee_id, department_id, schoolyear_id,
        kw_von, jahr_von, kw_bis, jahr_bis,
    )
    if existing is not None:
        return RedirectResponse(f"/feedback/{existing.id}?msg=exists", status_code=303)

    action = form.get("action", "entwurf")
    status = "abgeschlossen" if action == "abschliessen" else "entwurf"

    bogen = FeedbackBogen(
        typ="AUSBILDER",
        bogen_version=VERSION_AUSBILDER,
        trainee_id=trainee_id,
        department_id=department_id,
        schoolyear_id=schoolyear_id,
        kw_von=kw_von, jahr_von=jahr_von, kw_bis=kw_bis, jahr_bis=jahr_bis,
        einsatzart=(form.get("einsatzart") or "").strip(),
        fachausbilder_name=(form.get("fachausbilder_name") or "").strip(),
        lernziele=_parse_lernziele(form),
        antworten=_parse_antworten(form, "AUSBILDER"),
        freitexte=_parse_freitexte(form, "AUSBILDER"),
        fehl_krank=_parse_int_or_none(form.get("fehl_krank")),
        fehl_urlaub=_parse_int_or_none(form.get("fehl_urlaub")),
        fehl_schule=_parse_int_or_none(form.get("fehl_schule")),
        fehl_sonstige=_parse_int_or_none(form.get("fehl_sonstige")),
        weiterer_einsatz=(form.get("weiterer_einsatz") or "").strip(),
        zugriffe_geloescht=form.get("zugriffe_geloescht") is not None,
        status=status,
        erstellt_von_upn=user.upn,
        erstellt_am=date.today(),
    )
    db.add(bogen)
    db.commit()
    db.refresh(bogen)

    return RedirectResponse(f"/feedback/{bogen.id}?msg=created", status_code=303)


# ── Detail (bearbeitbar solange Entwurf, sonst Read-only) ───────────────

@router.get("/{bogen_id:int}", response_class=HTMLResponse)
def feedback_detail(request: Request, bogen_id: int, db: DB, user: CU):
    bogen = _get_or_404(db, bogen_id)
    _check_access(db, user, bogen.department_id)

    # AZUBI-Entwuerfe sind privat -- fuer Staff nicht einsehbar (symmetrisch
    # zum AUSBILDER-Entwurf, den der Azubi nicht sieht).
    if bogen.typ == "AZUBI" and bogen.status == "entwurf":
        raise HTTPException(status_code=404, detail="Feedbackbogen nicht gefunden")

    trainee = db.get(Trainee, bogen.trainee_id)
    department = db.get(Department, bogen.department_id)
    schoolyear = db.get(Schoolyear, bogen.schoolyear_id)
    kopf = _kopf_kontext(db, trainee, bogen.schoolyear_id)

    if bogen.status == "entwurf":
        ctx = {
            "bogen": bogen,
            "typ": bogen.typ,
            "trainee": trainee,
            "department": department,
            "schoolyear": schoolyear,
            "kw_von": bogen.kw_von, "jahr_von": bogen.jahr_von,
            "kw_bis": bogen.kw_bis, "jahr_bis": bogen.jahr_bis,
            "einsatzarten": EINSATZARTEN,
            "einsatzart_selected": bogen.einsatzart,
            "fachausbilder_name": bogen.fachausbilder_name,
            "fehl_krank": bogen.fehl_krank,
            "fehl_urlaub": bogen.fehl_urlaub,
            "fehl_schule": bogen.fehl_schule,
            "fehl_sonstige": bogen.fehl_sonstige,
            "weiterer_einsatz": bogen.weiterer_einsatz,
            "zugriffe_geloescht": bogen.zugriffe_geloescht,
            "action_url": f"/feedback/{bogen.id}",
            "cancel_url": f"/feedback/{bogen.id}",
            "active_nav": "feedback",
            **kopf,
            **_form_context(bogen, bogen.typ),
        }
        return templates.TemplateResponse(request, "feedback/form.html", ctx)

    partner = partner_bogen(db, bogen)
    skala = _skala_fuer(bogen.typ)
    ctx = {
        "bogen": bogen,
        "typ": bogen.typ,
        "trainee": trainee,
        "department": department,
        "schoolyear": schoolyear,
        "partner": partner,
        "status_labels": STATUS_LABELS,
        "status_colors": STATUS_BADGE_FARBE,
        "skala_dict": dict(skala),
        "skala_lernziele_dict": dict(SKALA_ANFORDERUNGEN),
        "can_reopen": user.rolle in ("orga", "admin"),
        "can_delete": user.rolle == "admin",
        "today": date.today().isoformat(),
        "active_nav": "feedback",
        **kopf,
        **_form_context(bogen, bogen.typ),
    }
    return templates.TemplateResponse(request, "feedback/detail.html", ctx)


@router.post("/{bogen_id:int}", response_class=RedirectResponse)
async def update_feedback(request: Request, bogen_id: int, db: DB, user: CU):
    bogen = _get_or_404(db, bogen_id)
    _check_access(db, user, bogen.department_id)
    # Die Selbsteinschaetzung des Azubis darf Staff NIE inhaltlich aendern --
    # sonst koennte ein Ausbilder sie ueberschreiben und "im Namen des Azubis"
    # abschliessen.
    if bogen.typ == "AZUBI":
        raise HTTPException(
            status_code=403, detail="AZUBI-Boegen koennen nur vom Azubi selbst bearbeitet werden"
        )
    if bogen.status != "entwurf":
        raise HTTPException(
            status_code=400, detail="Bogen ist nicht mehr im Status Entwurf"
        )

    form = await request.form()
    action = form.get("action", "entwurf")

    bogen.einsatzart = (form.get("einsatzart") or "").strip()
    bogen.fachausbilder_name = (form.get("fachausbilder_name") or "").strip()
    bogen.lernziele = _parse_lernziele(form)
    bogen.antworten = _parse_antworten(form, bogen.typ)
    bogen.freitexte = _parse_freitexte(form, bogen.typ)
    bogen.fehl_krank = _parse_int_or_none(form.get("fehl_krank"))
    bogen.fehl_urlaub = _parse_int_or_none(form.get("fehl_urlaub"))
    bogen.fehl_schule = _parse_int_or_none(form.get("fehl_schule"))
    bogen.fehl_sonstige = _parse_int_or_none(form.get("fehl_sonstige"))
    bogen.weiterer_einsatz = (form.get("weiterer_einsatz") or "").strip()
    bogen.zugriffe_geloescht = form.get("zugriffe_geloescht") is not None
    bogen.status = "abgeschlossen" if action == "abschliessen" else "entwurf"
    bogen.aktualisiert_am = date.today()

    db.add(bogen)
    db.commit()

    return RedirectResponse(f"/feedback/{bogen.id}?msg=updated", status_code=303)


# ── Status-Workflow ──────────────────────────────────────────────────────

@router.post("/{bogen_id:int}/besprochen", response_class=RedirectResponse)
async def besprochen_feedback(request: Request, bogen_id: int, db: DB, user: CU):
    bogen = _get_or_404(db, bogen_id)
    _check_access(db, user, bogen.department_id)
    if bogen.status != "abgeschlossen":
        raise HTTPException(
            status_code=400, detail="Bogen ist nicht im Status Abgeschlossen"
        )

    form = await request.form()
    raw = (form.get("besprochen_am") or "").strip()
    if raw:
        try:
            besprochen_am = date.fromisoformat(raw)
        except ValueError:
            besprochen_am = date.today()
    else:
        besprochen_am = date.today()

    bogen.status = "besprochen"
    bogen.besprochen_am = besprochen_am
    db.add(bogen)
    db.commit()

    return RedirectResponse(f"/feedback/{bogen.id}?msg=updated", status_code=303)


@router.post("/{bogen_id:int}/reopen", response_class=RedirectResponse)
def reopen_feedback(
    bogen_id: int,
    db: DB,
    user: Annotated[CurrentUser, Depends(require_roles("orga", "admin"))],
):
    bogen = _get_or_404(db, bogen_id)
    if bogen.status not in ("abgeschlossen", "besprochen"):
        raise HTTPException(
            status_code=400, detail="Bogen kann in diesem Status nicht zurueckgesetzt werden"
        )

    bogen.status = "entwurf"
    bogen.besprochen_am = None
    db.add(bogen)
    db.commit()

    return RedirectResponse(f"/feedback/{bogen.id}?msg=updated", status_code=303)


@router.post("/{bogen_id:int}/loeschen", response_class=RedirectResponse)
def loeschen_feedback(
    bogen_id: int,
    db: DB,
    user: Annotated[CurrentUser, Depends(require_roles("admin"))],
):
    bogen = _get_or_404(db, bogen_id)
    db.delete(bogen)
    db.commit()

    return RedirectResponse("/feedback/?msg=deleted", status_code=303)
