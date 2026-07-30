"""Azubi-Self-Service: Token-basierter Zugang unter /mein-plan/{token}.

- Lesen: eigener Einsatzplan + Klassen-Schulplan (keine Konflikt-Anzeige).
- Schreiben (gescoped): eigenen Urlaub eintragen/loeschen, eigene Wuensche pflegen.

Sicherheit: Der Token ist eine Capability-URL. Es werden ausschliesslich die
eigenen Daten des per Token identifizierten Trainees gelesen/geschrieben.
"""
import json
from datetime import date, datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    FeedbackBogen,
    SchoolPlan,
    SchoolPlanWeek,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeWish,
    UnterrichtsTyp,
)
from app.models.trainee_wish import prioritaet_label
from app.routers.assignments import _apply_assignments, _resolve_range
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
    VERSION_AZUBI,
    alle_frage_keys,
)
from app.services.feedback_utils import bogen_fuer_block, partner_bogen, trainee_bloecke
from app.services.membership_utils import (
    aktuelles_schuljahr_id,
    beruf_langname,
    beruf_und_lehrjahr,
    klasse_fuer,
)
from app.utils.colors import department_color_map
from app.utils.kw import format_weekdays, iter_schoolyear_weeks, iter_kw_range, kw_to_monday

# Badge-Farbklasse je Feedbackbogen-Status -- abgeleitet aus der gemeinsamen
# Farb-Map in feedback_def.py, damit Staff- und Azubi-UI identisch einfaerben.
STATUS_BADGE_CLASS = {
    status: f"badge-{farbe}" for status, farbe in STATUS_BADGE_FARBE.items()
}

router = APIRouter(prefix="/mein-plan", tags=["self-service"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
templates.env.globals["prioritaet_label"] = prioritaet_label
templates.env.globals["beruf_langname"] = beruf_langname
DB = Annotated[Session, Depends(get_session)]


# ── Helpers ─────────────────────────────────────────────────────────────────

def _trainee_by_token(db: Session, token: str) -> Trainee:
    if not token:
        raise HTTPException(status_code=404, detail="Ungueltiger Link")
    trainee = db.exec(select(Trainee).where(Trainee.share_token == token)).first()
    if trainee is None:
        raise HTTPException(status_code=404, detail="Link ungueltig oder deaktiviert")
    return trainee


def _schoolyear_for_week(db: Session, kw: int, jahr: int) -> Schoolyear | None:
    target = kw_to_monday(kw, jahr)
    for sy in db.exec(select(Schoolyear)).all():
        if kw_to_monday(sy.start_kw, sy.start_year) <= target <= kw_to_monday(sy.end_kw, sy.end_year):
            return sy
    return None


def _school_weeks_for_trainee(db: Session, trainee: Trainee) -> dict[str, str]:
    """Dict "kw,jahr" -> typ_value der Schulwochen laut Klassenplan (alle Lehrjahre)."""
    if not trainee.klasse_id:
        return {}
    result: dict[str, str] = {}
    for plan in db.exec(select(SchoolPlan).where(SchoolPlan.klasse_id == trainee.klasse_id)).all():
        for w in db.exec(select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan.id)).all():
            result[f"{w.kw},{w.jahr}"] = w.typ.value
    return result


def _resolve_schoolyear(db: Session, request: Request, years: list[Schoolyear]) -> Schoolyear | None:
    """Ermittelt das anzuzeigende Schuljahr fuer die Klassen-/Jahrgang-/Uebersicht-Seiten.

    Reihenfolge: Query-Param, sonst das Jahr mit der heutigen KW, sonst das
    laufende Jahr laut aktuelles_schuljahr_id(), sonst (falls 'years' nicht leer
    ist) das neueste ueberhaupt — sonst None.
    """
    selected = request.query_params.get("schoolyear_id", "")
    sy = db.get(Schoolyear, selected) if selected else None
    if sy is None:
        _t = date.today().isocalendar()
        sy = _schoolyear_for_week(db, _t.week, _t.year)
    if sy is None:
        fallback_id = aktuelles_schuljahr_id(db)
        sy = db.get(Schoolyear, fallback_id) if fallback_id else None
    if sy is None and years:
        sy = years[0]
    return sy


def _jahrgang_start_year(d: date | None) -> int | None:
    """Startjahrgang aus dem Ausbildungsbeginn.

    Duplikat von app.services.membership_utils._start_year: jene Funktion ist
    modulprivat (Unterstrich-Praefix) und wird daher hier bewusst nicht
    importiert, sondern die (kurze) Logik dupliziert: Monat >= 8 -> Jahr, sonst
    Jahr - 1. None wenn kein Ausbildungsbeginn hinterlegt ist.
    """
    if d is None:
        return None
    return d.year if d.month >= 8 else d.year - 1


def _visible_trainees(db: Session, trainees: list[Trainee], schoolyear_id: str) -> list[Trainee]:
    """Blendet Absolventen aus (Fix Paket B, Bug 3).

    Ausschluss NUR wenn ein Anker (trainee.klasse_id) vorhanden ist, die
    berechnete Klasse fuers Zieljahr (klasse_fuer) aber None ergibt (Abschluss
    bzw. Zieljahr vor Ausbildungsbeginn). Trainees OHNE jeglichen Anker
    (klasse_id None) bleiben sichtbar und landen in der Gruppe "Ohne Klasse" —
    sonst wuerden neu angelegte Trainees kommentarlos aus den Listen verschwinden.
    """
    return [
        t for t in trainees
        if klasse_fuer(db, t, schoolyear_id) is not None or t.klasse_id is None
    ]


def _group_beruf_klasse(
    db: Session,
    trainees: list[Trainee],
    schoolyear_id: str,
    school_week_map: dict[int, dict[str, str]] | None = None,
) -> list[dict]:
    """Gruppiert Trainees zweistufig Beruf -> BERECHNETE Klasse fuers Zieljahr.

    Analog app.routers.overview.overview(); zentral hier gehalten, damit
    Klasse-/Jahrgang-/Uebersicht-Seite dieselbe Gruppierungs- und
    Sortierlogik verwenden (Beruf alphabetisch, dann Lehrjahr, dann
    Nachname; "Ohne Klasse" immer ganz am Ende).
    """
    school_week_map = school_week_map or {}
    all_classes = {c.id: c for c in db.exec(select(TraineeClass)).all()}

    _grp: dict[str, dict[tuple[int | None, str | None], list]] = {}
    for t in trainees:
        klasse_id = klasse_fuer(db, t, schoolyear_id)
        klasse = all_classes.get(klasse_id) if klasse_id is not None else None
        klasse_name = klasse.name if klasse is not None else None
        beruf, _lj = beruf_und_lehrjahr(klasse_name)
        _grp.setdefault(beruf, {}).setdefault((klasse_id, klasse_name), []).append(t)

    _ohne_key = "Ohne Klasse"
    _ohne_grp = _grp.pop(_ohne_key, {})

    def _klasse_sort_key(item: tuple) -> tuple:
        (kid, kname), _ts = item
        _, lj = beruf_und_lehrjahr(kname)
        return (lj if lj is not None else 9999, kname or "")

    def _build(berufe: list[str], grp: dict) -> list[dict]:
        out = []
        for beruf in berufe:
            klassen_items = sorted(grp[beruf].items(), key=_klasse_sort_key)
            out.append({
                "beruf": beruf,
                "klassen": [
                    {
                        "name": kname,
                        "klasse_id": kid,
                        "trainees": sorted(ts, key=lambda t: (t.nachname, t.vorname)),
                        "school_weeks": school_week_map.get(kid, {}),
                    }
                    for (kid, kname), ts in klassen_items
                ],
            })
        return out

    grouped = _build(sorted(_grp.keys()), _grp)
    if _ohne_grp:
        grouped += _build([_ohne_key], {_ohne_key: _ohne_grp})
    return grouped


# ── Meine Einsätze (single-row matrix) ──────────────────────────────────────

@router.get("/{token}", response_class=HTMLResponse)
def my_plan(request: Request, token: str, db: DB):
    trainee = _trainee_by_token(db, token)

    # Jahres-Auswahl wie auf den anderen Azubi-Seiten: ALLE Schuljahre stehen
    # zur Wahl. Frueher wurden hier nur Jahre angeboten, in denen der Trainee
    # bereits Einsaetze hatte -- bei genau einem solchen Jahr (Normalfall)
    # blendete das Template den Umschalter dann komplett aus, und kuenftige
    # Jahre waren gar nicht erreichbar.
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    sy = _resolve_schoolyear(db, request, years)

    all_assignments = db.exec(
        select(Assignment)
        .where(Assignment.trainee_id == trainee.id)
        .order_by(Assignment.jahr, Assignment.kw)
    ).all()

    all_depts = db.exec(select(Department)).all()
    depts = {d.id: d for d in all_depts}
    dept_colors = department_color_map(all_depts)
    school_weeks = _school_weeks_for_trainee(db, trainee)

    _today = date.today().isocalendar()
    today_key = (_today.week, _today.year)

    weeks = []
    cell_map: dict[int, dict[str, Assignment]] = {}

    if sy:
        sy_assignments = {f"{a.kw},{a.jahr}": a for a in all_assignments if a.schoolyear_id == sy.id}
        cell_map[trainee.id] = sy_assignments
        for kw, jahr in iter_schoolyear_weeks(sy.start_kw, sy.start_year, sy.end_kw, sy.end_year):
            weeks.append({
                "kw": kw,
                "jahr": jahr,
                "monday": kw_to_monday(kw, jahr),
                "is_today": (kw, jahr) == today_key,
            })

    # Schultage-Hinweis (nur Wochentag-Schule)
    schul_tage = ""
    klasse = db.get(TraineeClass, trainee.klasse_id) if trainee.klasse_id else None
    if klasse and klasse.unterrichts_typ == UnterrichtsTyp.TAGE_FEST:
        schul_tage = format_weekdays(klasse.schul_wochentage, full=True, halbtag=klasse.halbtag_wochentag)

    return templates.TemplateResponse(request, "share/plan.html", {
        "trainee": trainee,
        "token": token,
        "active": "einsaetze",
        "trainees": [trainee],
        "weeks": weeks,
        "cell_map": cell_map,
        "school_weeks": school_weeks,
        "depts": depts,
        "dept_colors": dept_colors,
        "highlight_id": trainee.id,
        "selected_year": sy.id if sy else "",
        "years": years,
        "schul_tage": schul_tage,
    })


# ── Meine Klasse ─────────────────────────────────────────────────────────────

@router.get("/{token}/klasse", response_class=HTMLResponse)
def my_class(request: Request, token: str, db: DB):
    """Read-only Matrix der eigenen (fuers gewaehlte Jahr BERECHNETEN) Klasse.

    Fix Paket B (Bugs 1+2): Mitglieder und Titel kommen aus klasse_fuer() statt
    aus trainee.klasse_id/Beruf — sonst zeigt die Seite bei Jahreswechsel die
    Anker-Einstiegsklasse bzw. alle Trainees des ganzen Berufs statt nur die
    eigene (berechnete) Klasse.
    """
    trainee = _trainee_by_token(db, token)
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()

    def _empty(selected_year: str) -> HTMLResponse:
        return templates.TemplateResponse(request, "share/klasse.html", {
            "trainee": trainee, "token": token, "active": "klasse",
            "klasse": None,
            "classmates": [], "weeks": [], "cell_map": {}, "school_weeks": {},
            "depts": {}, "dept_colors": {}, "selected_year": selected_year, "years": years, "schul_tage": "",
            "trainees": [], "highlight_id": trainee.id,
        })

    if not years:
        return _empty("")

    sy = _resolve_schoolyear(db, request, years)
    if sy is None:
        return _empty("")

    # Fix 2: Titel/Inhalt der Seite folgen der BERECHNETEN Klasse fuers Jahr, nicht
    # der statischen Anker-Einstiegsklasse.
    my_klasse_id = klasse_fuer(db, trainee, sy.id)
    klasse = db.get(TraineeClass, my_klasse_id) if my_klasse_id is not None else None

    if klasse is None:
        return _empty(sy.id)

    # Fix 1+3: Mitglieder = alle aktiven Trainees, deren BERECHNETE Klasse fuers Jahr
    # exakt der eigenen berechneten Klasse entspricht (nicht ueber trainee.klasse_id
    # bzw. den ganzen Beruf). Absolventen (klasse_fuer -> None) matchen nie.
    all_active = db.exec(select(Trainee).where(Trainee.aktiv == True)).all()  # noqa: E712
    classmates = sorted(
        (t for t in all_active if klasse_fuer(db, t, sy.id) == my_klasse_id),
        key=lambda t: (t.nachname, t.vorname),
    )
    ids = [t.id for t in classmates]
    assignments = db.exec(
        select(Assignment).where(
            Assignment.schoolyear_id == sy.id,
            Assignment.trainee_id.in_(ids),
        )
    ).all() if ids else []

    cell_map: dict[int, dict[str, Assignment]] = {}
    for a in assignments:
        cell_map.setdefault(a.trainee_id, {})[f"{a.kw},{a.jahr}"] = a

    _t = date.today().isocalendar()
    today_key = (_t.week, _t.year)
    weeks = [
        {"kw": kw, "jahr": jahr, "monday": kw_to_monday(kw, jahr), "is_today": (kw, jahr) == today_key}
        for kw, jahr in iter_schoolyear_weeks(sy.start_kw, sy.start_year, sy.end_kw, sy.end_year)
    ]

    school_weeks: dict[str, str] = {}
    plan = db.exec(
        select(SchoolPlan).where(SchoolPlan.klasse_id == klasse.id, SchoolPlan.schoolyear_id == sy.id)
    ).first()
    if plan:
        for w in db.exec(select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan.id)).all():
            school_weeks[f"{w.kw},{w.jahr}"] = w.typ.value

    schul_tage = ""
    if klasse.unterrichts_typ == UnterrichtsTyp.TAGE_FEST:
        schul_tage = format_weekdays(klasse.schul_wochentage, full=True, halbtag=klasse.halbtag_wochentag)

    all_depts_class = db.exec(select(Department)).all()
    depts = {d.id: d for d in all_depts_class}
    dept_colors_class = department_color_map(all_depts_class)

    return templates.TemplateResponse(request, "share/klasse.html", {
        "trainee": trainee, "token": token, "active": "klasse",
        "klasse": klasse,
        "classmates": classmates,
        "trainees": classmates,          # alias for week_matrix partial
        "highlight_id": trainee.id,
        "weeks": weeks, "cell_map": cell_map,
        "school_weeks": school_weeks, "depts": depts,
        "dept_colors": dept_colors_class,
        "selected_year": sy.id, "years": years, "schul_tage": schul_tage,
    })


# ── Mein Jahrgang ────────────────────────────────────────────────────────────

@router.get("/{token}/jahrgang", response_class=HTMLResponse)
def my_jahrgang(request: Request, token: str, db: DB):
    """Read-only Matrix aller aktiven Trainees desselben Start-Jahrgangs.

    Beruf-uebergreifend (inkl. Studis/DH), gruppiert nach Beruf -> berechneter
    Klasse (analog Uebersicht). "Startjahrgang" = Jahr aus dem Ausbildungsbeginn
    (Monat >= 8 -> Jahr, sonst Jahr - 1, siehe _jahrgang_start_year).
    """
    trainee = _trainee_by_token(db, token)
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    my_start = _jahrgang_start_year(trainee.ausbildungsbeginn)

    def _empty(selected_year: str) -> HTMLResponse:
        return templates.TemplateResponse(request, "share/jahrgang.html", {
            "trainee": trainee, "token": token, "active": "jahrgang",
            "my_start": my_start,
            "grouped": [], "weeks": [], "cell_map": {},
            "depts": {}, "dept_colors": {}, "selected_year": selected_year, "years": years,
            "highlight_id": trainee.id,
        })

    if my_start is None or not years:
        return _empty("")

    sy = _resolve_schoolyear(db, request, years)
    if sy is None:
        return _empty("")

    all_active = db.exec(select(Trainee).where(Trainee.aktiv == True)).all()  # noqa: E712
    same_jahrgang = [t for t in all_active if _jahrgang_start_year(t.ausbildungsbeginn) == my_start]

    # Fix 3 (analog Klasse-/Uebersicht-Seite): Absolventen mit Anker aber
    # berechnet-None ausblenden; ankerlose Trainees bleiben ("Ohne Klasse").
    visible = _visible_trainees(db, same_jahrgang, sy.id)

    ids = [t.id for t in visible]
    assignments = db.exec(
        select(Assignment).where(
            Assignment.schoolyear_id == sy.id,
            Assignment.trainee_id.in_(ids),
        )
    ).all() if ids else []
    cell_map: dict[int, dict[str, Assignment]] = {}
    for a in assignments:
        cell_map.setdefault(a.trainee_id, {})[f"{a.kw},{a.jahr}"] = a

    _t = date.today().isocalendar()
    today_key = (_t.week, _t.year)
    weeks = [
        {"kw": kw, "jahr": jahr, "monday": kw_to_monday(kw, jahr), "is_today": (kw, jahr) == today_key}
        for kw, jahr in iter_schoolyear_weeks(sy.start_kw, sy.start_year, sy.end_kw, sy.end_year)
    ]

    school_week_map: dict[int, dict[str, str]] = {}
    for plan in db.exec(select(SchoolPlan).where(SchoolPlan.schoolyear_id == sy.id)).all():
        sw: dict[str, str] = {}
        for w in db.exec(select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan.id)).all():
            sw[f"{w.kw},{w.jahr}"] = w.typ.value
        school_week_map[plan.klasse_id] = sw

    grouped = _group_beruf_klasse(db, visible, sy.id, school_week_map)

    all_depts = db.exec(select(Department)).all()
    depts = {d.id: d for d in all_depts}
    dept_colors = department_color_map(all_depts)

    return templates.TemplateResponse(request, "share/jahrgang.html", {
        "trainee": trainee, "token": token, "active": "jahrgang",
        "my_start": my_start,
        "grouped": grouped,
        "weeks": weeks, "cell_map": cell_map,
        "depts": depts, "dept_colors": dept_colors,
        "highlight_id": trainee.id,
        "selected_year": sy.id, "years": years,
    })


# ── Urlaub-Seite ─────────────────────────────────────────────────────────────

@router.get("/{token}/urlaub", response_class=HTMLResponse)
def urlaub_page(request: Request, token: str, db: DB):
    trainee = _trainee_by_token(db, token)

    own_urlaub = db.exec(
        select(Assignment).where(
            Assignment.trainee_id == trainee.id,
            Assignment.typ == AssignmentTyp.URLAUB,
            Assignment.source == AssignmentSource.SELBST,
        ).order_by(Assignment.jahr, Assignment.kw)
    ).all()

    return templates.TemplateResponse(request, "share/urlaub.html", {
        "trainee": trainee,
        "token": token,
        "active": "urlaub",
        "own_urlaub": own_urlaub,
    })


# ── Urlaub eintragen / loeschen ─────────────────────────────────────────────

@router.post("/{token}/urlaub", response_class=RedirectResponse)
def add_urlaub(
    token: str,
    db: DB,
    kw: Annotated[int, Form()],
    jahr: Annotated[int, Form()],
    kw_end: Annotated[str, Form()] = "",
    jahr_end: Annotated[str, Form()] = "",
):
    trainee = _trainee_by_token(db, token)

    if kw_end and jahr_end:
        kw_list = list(iter_kw_range(kw, jahr, int(kw_end), int(jahr_end)))
    else:
        kw_list = [(kw, jahr)]

    created = skipped = 0
    for kw_i, jahr_i in kw_list:
        sy = _schoolyear_for_week(db, kw_i, jahr_i)
        if sy is None:
            skipped += 1
            continue
        to_create, to_override, sk, pending = _resolve_range(
            db, trainee.id, sy.id, [(kw_i, jahr_i)], AssignmentTyp.URLAUB, frozenset()
        )
        _apply_assignments(
            db, trainee.id, sy.id, AssignmentTyp.URLAUB, None, "",
            to_create, to_override, source=AssignmentSource.SELBST,
        )
        created += len(to_create) + len(to_override)
        skipped += len(sk) + len(pending)
    db.commit()

    return RedirectResponse(
        f"/mein-plan/{token}/urlaub?msg=urlaub&n={created}&s={skipped}", status_code=303
    )


@router.post("/{token}/urlaub/loeschen", response_class=RedirectResponse)
def delete_urlaub(
    token: str,
    db: DB,
    assignment_id: Annotated[int, Form()],
):
    trainee = _trainee_by_token(db, token)
    a = db.get(Assignment, assignment_id)
    # Nur eigene, selbst eingetragene Urlaube duerfen entfernt werden
    if (
        a is not None
        and a.trainee_id == trainee.id
        and a.typ == AssignmentTyp.URLAUB
        and a.source == AssignmentSource.SELBST
    ):
        db.delete(a)
        db.commit()
    return RedirectResponse(f"/mein-plan/{token}/urlaub?msg=urlaub_geloescht", status_code=303)


# ── Wuensche-Seite ──────────────────────────────────────────────────────────

@router.get("/{token}/wuensche", response_class=HTMLResponse)
def wuensche_page(request: Request, token: str, db: DB):
    trainee = _trainee_by_token(db, token)

    wishes = {
        w.department_id: w.prioritaet
        for w in db.exec(select(TraineeWish).where(TraineeWish.trainee_id == trainee.id)).all()
    }
    all_depts = db.exec(select(Department).order_by(Department.code)).all()

    return templates.TemplateResponse(request, "share/wuensche.html", {
        "trainee": trainee,
        "token": token,
        "active": "wuensche",
        "wishes": wishes,
        "wunsch_notiz": trainee.wunsch_notiz or "",
        "all_depts": all_depts,
    })


# ── Wuensche pflegen ────────────────────────────────────────────────────────

@router.post("/{token}/wuensche", response_class=RedirectResponse)
async def save_wishes(token: str, request: Request, db: DB):
    trainee = _trainee_by_token(db, token)
    form = await request.form()

    # Bestehende Wuensche ersetzen
    for w in db.exec(select(TraineeWish).where(TraineeWish.trainee_id == trainee.id)).all():
        db.delete(w)

    for d in db.exec(select(Department)).all():
        val = form.get(f"prio_{d.id}", "")
        if val in ("1", "2", "3"):
            db.add(TraineeWish(trainee_id=trainee.id, department_id=d.id, prioritaet=int(val)))

    trainee.wunsch_notiz = (form.get("wunsch_notiz") or "").strip()
    db.commit()
    return RedirectResponse(f"/mein-plan/{token}/wuensche?msg=wuensche", status_code=303)


# ── ICS-Export ──────────────────────────────────────────────────────────────

def _ics_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _ics_summary(a: Assignment, depts: dict[int, Department]) -> str | None:
    if a.typ == AssignmentTyp.ABTEILUNG:
        d = depts.get(a.abteilung_id)
        return f"{d.code} – {d.name}" if d else "Abteilung"
    if a.typ == AssignmentTyp.BERUFSSCHULE:
        return "Berufsschule"
    if a.typ == AssignmentTyp.UNI:
        return "Uni / DHBW"
    if a.typ == AssignmentTyp.URLAUB:
        return "Urlaub"
    return None  # FREI -> kein Termin


@router.get("/{token}/calendar.ics")
def calendar_ics(token: str, db: DB):
    trainee = _trainee_by_token(db, token)
    depts = {d.id: d for d in db.exec(select(Department)).all()}
    assignments = db.exec(
        select(Assignment)
        .where(Assignment.trainee_id == trainee.id)
        .order_by(Assignment.jahr, Assignment.kw)
    ).all()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Wilbeth//Einsatzplan//DE",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:Einsatzplan {_ics_escape(trainee.vorname + ' ' + trainee.nachname)}",
    ]
    for a in assignments:
        summary = _ics_summary(a, depts)
        if summary is None:
            continue
        monday = kw_to_monday(a.kw, a.jahr)
        saturday = monday + timedelta(days=5)  # DTEND ist exklusiv -> Sa deckt Mo..Fr ab
        lines += [
            "BEGIN:VEVENT",
            f"UID:wilbeth-assignment-{a.id}@wilbeth",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{monday.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{saturday.strftime('%Y%m%d')}",
            f"SUMMARY:{_ics_escape(summary)}",
            f"DESCRIPTION:KW {a.kw}/{a.jahr}" + (f" – {_ics_escape(a.notiz)}" if a.notiz else ""),
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")

    body = "\r\n".join(lines) + "\r\n"
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="einsatzplan.ics"'},
    )


# ── Alle Azubis & Studis (read-only, alle aktiven Trainees) ─────────────────

@router.get("/{token}/uebersicht", response_class=HTMLResponse)
def uebersicht_page(request: Request, token: str, db: DB):
    """Read-only Gesamtuebersicht aller aktiven Trainees, gruppiert nach Beruf/
    BERECHNETER Klasse.

    Fix Paket B (Bug 3): Absolventen (klasse_fuer -> None trotz Anker) werden
    fuers gewaehlte Jahr nicht mehr angezeigt — analog app.routers.overview.
    """
    trainee = _trainee_by_token(db, token)

    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    sy = _resolve_schoolyear(db, request, years)

    all_depts = db.exec(select(Department)).all()
    depts = {d.id: d for d in all_depts}
    dept_colors = department_color_map(all_depts)

    weeks = []
    cell_map: dict[int, dict[str, Assignment]] = {}
    grouped: list[dict] = []

    if sy:
        all_active_trainees = db.exec(
            select(Trainee)
            .where(Trainee.aktiv == True)  # noqa: E712
            .order_by(Trainee.nachname, Trainee.vorname)
        ).all()
        visible = _visible_trainees(db, all_active_trainees, sy.id)

        _today = date.today().isocalendar()
        today_key = (_today.week, _today.year)
        trainee_ids = [t.id for t in visible]
        if trainee_ids:
            assignments = db.exec(
                select(Assignment).where(
                    Assignment.schoolyear_id == sy.id,
                    Assignment.trainee_id.in_(trainee_ids),
                )
            ).all()
            for a in assignments:
                cell_map.setdefault(a.trainee_id, {})[f"{a.kw},{a.jahr}"] = a

        for kw, jahr in iter_schoolyear_weeks(sy.start_kw, sy.start_year, sy.end_kw, sy.end_year):
            weeks.append({
                "kw": kw,
                "jahr": jahr,
                "monday": kw_to_monday(kw, jahr),
                "is_today": (kw, jahr) == today_key,
            })

        # Schulwochen-Map je Klasse fuer dieses Lehrjahr
        school_week_map: dict[int, dict[str, str]] = {}
        for plan in db.exec(
            select(SchoolPlan).where(SchoolPlan.schoolyear_id == sy.id)
        ).all():
            sw: dict[str, str] = {}
            for w in db.exec(
                select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan.id)
            ).all():
                sw[f"{w.kw},{w.jahr}"] = w.typ.value
            school_week_map[plan.klasse_id] = sw

        grouped = _group_beruf_klasse(db, visible, sy.id, school_week_map)

    return templates.TemplateResponse(request, "share/uebersicht.html", {
        "trainee": trainee,
        "token": token,
        "active": "uebersicht",
        "grouped": grouped,
        "weeks": weeks,
        "cell_map": cell_map,
        "depts": depts,
        "dept_colors": dept_colors,
        "highlight_id": trainee.id,
        "selected_year": sy.id if sy else "",
        "years": years,
    })


# ── Über Wilbeth (share-Layout, kein Auth-Guard) ─────────────────────────────

@router.get("/{token}/ueber", response_class=HTMLResponse)
def ueber_page(request: Request, token: str, db: DB):
    """Kompakte 'Ueber Wilbeth'-Seite im share-Layout.

    Fix (e): der bisherige Sidebar-Link zeigte auf /ueber-wilbeth — das
    Planer-Layout hinter dem Auth-Guard, wo Azubis weggeleitet werden bzw.
    Staff in der Admin-UI landet. Diese Route rendert stattdessen eine eigene,
    gekuerzte Seite ohne Planer-Interna im share/_base.html-Layout.
    """
    trainee = _trainee_by_token(db, token)
    return templates.TemplateResponse(request, "share/ueber.html", {
        "trainee": trainee,
        "token": token,
        "active": "ueber",
    })


# ── Abteilungsliste (read-only) ──────────────────────────────────────────────

@router.get("/{token}/abteilungen", response_class=HTMLResponse)
def abteilungen_page(request: Request, token: str, db: DB):
    """Read-only Liste aller Abteilungen."""
    trainee = _trainee_by_token(db, token)
    all_depts = db.exec(select(Department).order_by(Department.code)).all()

    return templates.TemplateResponse(request, "share/abteilungen.html", {
        "trainee": trainee,
        "token": token,
        "active": "abteilungen",
        "all_depts": all_depts,
    })


# ── Feedbackboegen (Azubi-Sicht) ─────────────────────────────────────────────

def _form_int(raw) -> int | None:
    """Defensives int-Parsen von Formularwerten: ''/None/Muell -> None statt
    ValueError (ein manipulierter POST darf keinen 500er ausloesen)."""
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _pruefe_block_existiert(
    db: Session, trainee_id: int, department_id: int, schoolyear_id: str,
    kw_von: int, jahr_von: int, kw_bis: int, jahr_bis: int,
) -> None:
    """400, wenn der uebergebene Zeitraum keinen realen Abteilungs-Block des
    Trainees ueberlappt -- verhindert frei erfundene Boegen per manuellem POST
    (kein Rechte-Problem, aber Datenmuell in der Staff-Liste)."""
    sy = db.get(Schoolyear, schoolyear_id)
    if sy is None:
        raise HTTPException(status_code=404, detail="Schuljahr nicht gefunden")
    week_idx = {
        wk: i for i, wk in enumerate(iter_schoolyear_weeks(
            sy.start_kw, sy.start_year, sy.end_kw, sy.end_year,
        ))
    }
    von = week_idx.get((kw_von, jahr_von))
    bis = week_idx.get((kw_bis, jahr_bis))
    if von is None or bis is None or bis < von:
        raise HTTPException(status_code=400, detail="Zeitraum liegt nicht im Schuljahr")
    for block in trainee_bloecke(db, trainee_id, schoolyear_id):
        if block["department"].id != department_id:
            continue
        b_von = week_idx.get((block["kw_von"], block["jahr_von"]))
        b_bis = week_idx.get((block["kw_bis"], block["jahr_bis"]))
        if b_von is not None and b_bis is not None and von <= b_bis and bis >= b_von:
            return
    raise HTTPException(
        status_code=400, detail="Kein Abteilungs-Einsatz im angegebenen Zeitraum"
    )


def _feedback_block_view(db: Session, trainee: Trainee, token: str, sy: Schoolyear, block: dict) -> dict:
    """Baut die Uebersichts-Zeile eines Abteilungs-Blocks: eigenen AZUBI-Bogen
    (Status + Link) sowie den AUSBILDER-Bogen ueber den Azubi (nur sichtbar ab
    Status "besprochen"/"bestaetigt", sonst neutraler Hinweistext ohne zu
    verraten, ob ein Bogen existiert).

    Bewusste Ausnahme von dieser Regel: Die Lernziel-TEXTE eines (auch noch
    unbesprochenen) AUSBILDER-Bogens werden im AZUBI-Formular als Vorgabe
    uebernommen -- laut Papierbogen werden die Lernziele dem Azubi zu
    Einsatzbeginn vom Fachausbilder vorgegeben, sie sind also kein
    Bewertungs-Geheimnis. Bewertungen, Antworten und Freitexte des
    AUSBILDER-Bogens bleiben bis "besprochen" unsichtbar (siehe
    feedback_neu/feedback_detail)."""
    dept = block["department"]
    kw_von, jahr_von = block["kw_von"], block["jahr_von"]
    kw_bis, jahr_bis = block["kw_bis"], block["jahr_bis"]

    mein_bogen = bogen_fuer_block(db, "AZUBI", trainee.id, dept.id, sy.id, kw_von, jahr_von, kw_bis, jahr_bis)
    if mein_bogen is not None:
        mein = {
            "exists": True,
            "status": mein_bogen.status,
            "badge_class": STATUS_BADGE_CLASS.get(mein_bogen.status, "badge-gray"),
            "url": f"/mein-plan/{token}/feedback/{mein_bogen.id}",
        }
    else:
        neu_qs = urlencode({
            "department_id": dept.id, "schoolyear_id": sy.id,
            "kw_von": kw_von, "jahr_von": jahr_von, "kw_bis": kw_bis, "jahr_bis": jahr_bis,
        })
        mein = {
            "exists": False, "status": None, "badge_class": "",
            "url": f"/mein-plan/{token}/feedback/neu?{neu_qs}",
        }

    ausbilder_bogen = bogen_fuer_block(db, "AUSBILDER", trainee.id, dept.id, sy.id, kw_von, jahr_von, kw_bis, jahr_bis)
    ausbilder_visible = ausbilder_bogen is not None and ausbilder_bogen.status in ("besprochen", "bestaetigt")
    ausbilder = {
        "visible": ausbilder_visible,
        "status": ausbilder_bogen.status if ausbilder_visible else None,
        "badge_class": STATUS_BADGE_CLASS.get(ausbilder_bogen.status, "badge-gray") if ausbilder_visible else "",
        "needs_bestaetigung": ausbilder_visible and ausbilder_bogen.status == "besprochen",
        "url": f"/mein-plan/{token}/feedback/{ausbilder_bogen.id}" if ausbilder_visible else None,
    }

    return {
        "department": dept,
        "kw_von": kw_von, "jahr_von": jahr_von, "kw_bis": kw_bis, "jahr_bis": jahr_bis,
        "mein": mein, "ausbilder": ausbilder,
    }


@router.get("/{token}/feedback", response_class=HTMLResponse)
def feedback_overview(request: Request, token: str, db: DB):
    """Uebersicht aller Abteilungs-Bloecke des Trainees im gewaehlten Schuljahr
    mit dem Status des eigenen AZUBI-Bogens und (falls besprochen/bestaetigt)
    des AUSBILDER-Bogens ueber ihn."""
    trainee = _trainee_by_token(db, token)
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    sy = _resolve_schoolyear(db, request, years)

    blocks = []
    if sy is not None:
        blocks = [
            _feedback_block_view(db, trainee, token, sy, block)
            for block in trainee_bloecke(db, trainee.id, sy.id)
        ]

    return templates.TemplateResponse(request, "share/feedback.html", {
        "trainee": trainee,
        "token": token,
        "active": "feedback",
        "blocks": blocks,
        "status_labels": STATUS_LABELS,
        "selected_year": sy.id if sy else "",
        "years": years,
    })


def _feedback_form_context(
    request: Request, token: str, trainee: Trainee, *,
    typ: str, bogen: FeedbackBogen | None, readonly: bool,
    department: Department | None, schoolyear: Schoolyear | None,
    kw_von: int, jahr_von: int, kw_bis: int, jahr_bis: int,
    einsatzart: str, has_partner: bool, lernziele: list[dict],
    antworten: dict, freitexte: dict, weiterer_einsatz: str,
    post_url: str, fachausbilder_name: str = "",
    bestaetigen_url: str = "", show_bestaetigen: bool = False,
) -> dict:
    if typ == "AUSBILDER":
        sektionen, skala, freitext_defs = AUSBILDER_SEKTIONEN, SKALA_ANFORDERUNGEN, FREITEXT_AUSBILDER
    else:
        sektionen, skala, freitext_defs = AZUBI_SEKTIONEN, SKALA_ERWARTUNGEN, FREITEXT_AZUBI

    return {
        "trainee": trainee, "token": token, "active": "feedback",
        "typ": typ, "bogen": bogen, "readonly": readonly,
        "department": department, "schoolyear": schoolyear,
        "kw_von": kw_von, "jahr_von": jahr_von, "kw_bis": kw_bis, "jahr_bis": jahr_bis,
        "einsatzart": einsatzart, "einsatzarten": EINSATZARTEN,
        "has_partner": has_partner, "lernziele": lernziele,
        "sektionen": sektionen, "skala": skala,
        "skala_map": dict(skala),
        # Lernziele werden IMMER auf der Anforderungen-Skala bewertet (wie im
        # Papierbogen und in der Staff-UI) -- auch im AZUBI-Bogen; skala_json
        # speist ausschliesslich die dynamischen Lernziel-Zeilen im JS.
        "skala_lernziele": SKALA_ANFORDERUNGEN,
        "skala_lernziele_map": dict(SKALA_ANFORDERUNGEN),
        "skala_json": json.dumps(SKALA_ANFORDERUNGEN),
        "freitext_defs": freitext_defs, "antworten": antworten, "freitexte": freitexte,
        "weiterer_einsatz": weiterer_einsatz,
        "post_url": post_url,
        "status_labels": STATUS_LABELS,
        "status_badge_class_map": STATUS_BADGE_CLASS,
        "fachausbilder_name": fachausbilder_name,
        "bestaetigen_url": bestaetigen_url,
        "show_bestaetigen": show_bestaetigen,
    }


@router.get("/{token}/feedback/neu", response_class=HTMLResponse)
def feedback_neu(
    request: Request, token: str, db: DB,
    department_id: int, schoolyear_id: str,
    kw_von: int, jahr_von: int, kw_bis: int, jahr_bis: int,
):
    """AZUBI-Formular fuer einen neuen Bogen zu einem Abteilungs-Block.

    Uebernimmt die Lernziel-TEXTE des AUSBILDER-Partnerbogens (falls
    vorhanden) read-only -- bewusst UNABHAENGIG von dessen Status, denn die
    Lernziele werden dem Azubi laut Papierbogen zu Einsatzbeginn vorgegeben.
    Es duerfen dabei ausschliesslich die Texte uebernommen werden, NIE die
    Bewertungen/Antworten/Freitexte des Ausbilders (die bleiben bis
    "besprochen" unsichtbar). Ohne Partner-Bogen kann der Azubi eigene
    Lernziel-Zeilen anlegen (siehe feedback_form.html JS).
    """
    trainee = _trainee_by_token(db, token)
    department = db.get(Department, department_id)
    if department is None:
        raise HTTPException(status_code=404, detail="Abteilung nicht gefunden")
    schoolyear = db.get(Schoolyear, schoolyear_id)
    if schoolyear is None:
        raise HTTPException(status_code=404, detail="Schuljahr nicht gefunden")

    # Transientes (nicht persistiertes) Objekt nur fuer den Partner-Lookup
    transient = FeedbackBogen(
        typ="AZUBI", trainee_id=trainee.id, department_id=department_id,
        schoolyear_id=schoolyear_id, kw_von=kw_von, jahr_von=jahr_von,
        kw_bis=kw_bis, jahr_bis=jahr_bis,
    )
    partner = partner_bogen(db, transient)
    has_partner = partner is not None
    lernziele = [
        {"text": lz.get("text", ""), "bewertung": None}
        for lz in (partner.lernziele if partner is not None else [])
    ]

    ctx = _feedback_form_context(
        request, token, trainee,
        typ="AZUBI", bogen=None, readonly=False,
        department=department, schoolyear=schoolyear,
        kw_von=kw_von, jahr_von=jahr_von, kw_bis=kw_bis, jahr_bis=jahr_bis,
        einsatzart="", has_partner=has_partner, lernziele=lernziele,
        antworten={}, freitexte={}, weiterer_einsatz="",
        post_url=f"/mein-plan/{token}/feedback",
    )
    return templates.TemplateResponse(request, "share/feedback_form.html", ctx)


@router.post("/{token}/feedback", response_class=RedirectResponse)
async def feedback_create(token: str, request: Request, db: DB):
    """Legt einen neuen AZUBI-Bogen an. Existiert fuer denselben Block schon
    einer, wird stattdessen dorthin umgeleitet (keine Doppelanlage)."""
    trainee = _trainee_by_token(db, token)
    form = await request.form()

    department_id = _form_int(form.get("department_id"))
    schoolyear_id = str(form.get("schoolyear_id") or "")
    kw_von = _form_int(form.get("kw_von"))
    jahr_von = _form_int(form.get("jahr_von"))
    kw_bis = _form_int(form.get("kw_bis"))
    jahr_bis = _form_int(form.get("jahr_bis"))
    if (
        department_id is None or not schoolyear_id
        or kw_von is None or jahr_von is None or kw_bis is None or jahr_bis is None
    ):
        raise HTTPException(status_code=400, detail="Pflichtfelder fehlen oder ungueltig")

    department = db.get(Department, department_id)
    if department is None:
        raise HTTPException(status_code=404, detail="Abteilung nicht gefunden")
    schoolyear = db.get(Schoolyear, schoolyear_id)
    if schoolyear is None:
        raise HTTPException(status_code=404, detail="Schuljahr nicht gefunden")

    existing = bogen_fuer_block(
        db, "AZUBI", trainee.id, department_id, schoolyear_id,
        kw_von, jahr_von, kw_bis, jahr_bis,
    )
    if existing is not None:
        return RedirectResponse(f"/mein-plan/{token}/feedback/{existing.id}", status_code=303)

    _pruefe_block_existiert(
        db, trainee.id, department_id, schoolyear_id,
        kw_von, jahr_von, kw_bis, jahr_bis,
    )

    texts = form.getlist("lernziel_text")
    bewertungen = form.getlist("lernziel_bewertung")
    lernziele = []
    for txt, bew in zip(texts, bewertungen):
        txt = (txt or "").strip()
        if not txt:
            continue
        lernziele.append({"text": txt, "bewertung": _form_int(bew)})

    antworten = {}
    for key in alle_frage_keys("AZUBI"):
        val = _form_int(form.get(key, ""))
        if val is not None:
            antworten[key] = val

    freitexte = {fd["key"]: (form.get(fd["key"]) or "").strip() for fd in FREITEXT_AZUBI}

    weiterer_einsatz = form.get("weiterer_einsatz", "")
    if weiterer_einsatz not in ("ja", "nein"):
        weiterer_einsatz = ""

    action = form.get("action", "entwurf")
    status = "abgeschlossen" if action == "abschliessen" else "entwurf"

    erstellt_von_upn = trainee.upn if trainee.upn else f"azubi:{trainee.id}"

    bogen = FeedbackBogen(
        typ="AZUBI", bogen_version=VERSION_AZUBI,
        trainee_id=trainee.id, department_id=department_id, schoolyear_id=schoolyear_id,
        kw_von=kw_von, jahr_von=jahr_von, kw_bis=kw_bis, jahr_bis=jahr_bis,
        einsatzart=str(form.get("einsatzart") or ""),
        lernziele=lernziele, antworten=antworten, freitexte=freitexte,
        weiterer_einsatz=weiterer_einsatz,
        status=status,
        erstellt_von_upn=erstellt_von_upn, erstellt_am=date.today(),
    )
    db.add(bogen)
    db.commit()
    db.refresh(bogen)

    return RedirectResponse(f"/mein-plan/{token}/feedback/{bogen.id}", status_code=303)


@router.get("/{token}/feedback/{bogen_id}", response_class=HTMLResponse)
def feedback_detail(request: Request, token: str, bogen_id: int, db: DB):
    """Detailseite eines Bogens. Harte Regel: bogen.trainee_id MUSS dem
    Token-Trainee gehoeren, sonst 404. AUSBILDER-Boegen sind fuer den Azubi
    erst ab Status "besprochen"/"bestaetigt" sichtbar (sonst 404 -- verraet
    nicht, ob ein Bogen existiert)."""
    trainee = _trainee_by_token(db, token)
    bogen = db.get(FeedbackBogen, bogen_id)
    if bogen is None or bogen.trainee_id != trainee.id:
        raise HTTPException(status_code=404, detail="Bogen nicht gefunden")

    department = db.get(Department, bogen.department_id)
    schoolyear = db.get(Schoolyear, bogen.schoolyear_id)

    if bogen.typ == "AZUBI":
        readonly = bogen.status != "entwurf"
        partner = partner_bogen(db, bogen)
        has_partner = partner is not None
        lernziele = [
            {"text": lz.get("text", ""), "bewertung": lz.get("bewertung")}
            for lz in bogen.lernziele
        ]
        ctx = _feedback_form_context(
            request, token, trainee,
            typ="AZUBI", bogen=bogen, readonly=readonly,
            department=department, schoolyear=schoolyear,
            kw_von=bogen.kw_von, jahr_von=bogen.jahr_von,
            kw_bis=bogen.kw_bis, jahr_bis=bogen.jahr_bis,
            einsatzart=bogen.einsatzart, has_partner=has_partner, lernziele=lernziele,
            antworten=bogen.antworten, freitexte=bogen.freitexte,
            weiterer_einsatz=bogen.weiterer_einsatz,
            post_url=f"/mein-plan/{token}/feedback/{bogen.id}",
        )
        return templates.TemplateResponse(request, "share/feedback_form.html", ctx)

    # typ == "AUSBILDER": nur sichtbar, wenn mit dem Azubi besprochen
    if bogen.status not in ("besprochen", "bestaetigt"):
        raise HTTPException(status_code=404, detail="Bogen noch nicht besprochen")

    lernziele = [
        {"text": lz.get("text", ""), "bewertung": lz.get("bewertung")}
        for lz in bogen.lernziele
    ]
    ctx = _feedback_form_context(
        request, token, trainee,
        typ="AUSBILDER", bogen=bogen, readonly=True,
        department=department, schoolyear=schoolyear,
        kw_von=bogen.kw_von, jahr_von=bogen.jahr_von,
        kw_bis=bogen.kw_bis, jahr_bis=bogen.jahr_bis,
        einsatzart=bogen.einsatzart, has_partner=False, lernziele=lernziele,
        antworten=bogen.antworten, freitexte=bogen.freitexte,
        weiterer_einsatz=bogen.weiterer_einsatz,
        post_url="",
        fachausbilder_name=bogen.fachausbilder_name,
        bestaetigen_url=f"/mein-plan/{token}/feedback/{bogen.id}/bestaetigen",
        show_bestaetigen=bogen.status == "besprochen",
    )
    return templates.TemplateResponse(request, "share/feedback_form.html", ctx)


@router.post("/{token}/feedback/{bogen_id}", response_class=RedirectResponse)
async def feedback_update(token: str, bogen_id: int, request: Request, db: DB):
    """Aktualisiert den EIGENEN AZUBI-Bogen -- nur solange er im Status
    "entwurf" ist."""
    trainee = _trainee_by_token(db, token)
    bogen = db.get(FeedbackBogen, bogen_id)
    if bogen is None or bogen.trainee_id != trainee.id or bogen.typ != "AZUBI":
        raise HTTPException(status_code=404, detail="Bogen nicht gefunden")
    if bogen.status != "entwurf":
        raise HTTPException(status_code=400, detail="Bogen ist nicht mehr im Entwurf-Status")

    form = await request.form()

    texts = form.getlist("lernziel_text")
    bewertungen = form.getlist("lernziel_bewertung")
    lernziele = []
    for txt, bew in zip(texts, bewertungen):
        txt = (txt or "").strip()
        if not txt:
            continue
        lernziele.append({"text": txt, "bewertung": _form_int(bew)})
    bogen.lernziele = lernziele

    antworten = {}
    for key in alle_frage_keys("AZUBI"):
        val = _form_int(form.get(key, ""))
        if val is not None:
            antworten[key] = val
    bogen.antworten = antworten

    bogen.freitexte = {fd["key"]: (form.get(fd["key"]) or "").strip() for fd in FREITEXT_AZUBI}

    weiterer_einsatz = form.get("weiterer_einsatz", "")
    if weiterer_einsatz not in ("ja", "nein"):
        weiterer_einsatz = ""
    bogen.weiterer_einsatz = weiterer_einsatz

    # Ohne Truthy-Guard zuweisen, damit eine einmal gewaehlte Einsatzart auch
    # wieder auf "leer" zurueckgesetzt werden kann (Select sendet dann "").
    bogen.einsatzart = str(form.get("einsatzart") or "")

    action = form.get("action", "entwurf")
    bogen.status = "abgeschlossen" if action == "abschliessen" else "entwurf"
    bogen.aktualisiert_am = date.today()

    db.add(bogen)
    db.commit()

    return RedirectResponse(f"/mein-plan/{token}/feedback/{bogen.id}", status_code=303)


@router.post("/{token}/feedback/{bogen_id}/bestaetigen", response_class=RedirectResponse)
def feedback_bestaetigen(token: str, bogen_id: int, db: DB):
    """Kenntnisnahme des Azubis: nur fuer den AUSBILDER-Bogen ueber ihn selbst
    und nur im Status "besprochen" -> "bestaetigt"."""
    trainee = _trainee_by_token(db, token)
    bogen = db.get(FeedbackBogen, bogen_id)
    if bogen is None or bogen.trainee_id != trainee.id or bogen.typ != "AUSBILDER":
        raise HTTPException(status_code=404, detail="Bogen nicht gefunden")
    if bogen.status != "besprochen":
        raise HTTPException(status_code=400, detail="Bogen ist nicht im Status 'besprochen'")

    bogen.status = "bestaetigt"
    bogen.bestaetigt_am = date.today()
    db.add(bogen)
    db.commit()

    return RedirectResponse(f"/mein-plan/{token}/feedback/{bogen.id}", status_code=303)
