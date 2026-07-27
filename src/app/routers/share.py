"""Azubi-Self-Service: Token-basierter Zugang unter /mein-plan/{token}.

- Lesen: eigener Einsatzplan + Klassen-Schulplan (keine Konflikt-Anzeige).
- Schreiben (gescoped): eigenen Urlaub eintragen/loeschen, eigene Wuensche pflegen.

Sicherheit: Der Token ist eine Capability-URL. Es werden ausschliesslich die
eigenen Daten des per Token identifizierten Trainees gelesen/geschrieben.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

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
from app.services.membership_utils import (
    aktuelles_schuljahr_id,
    beruf_langname,
    beruf_und_lehrjahr,
    klasse_fuer,
)
from app.utils.colors import department_color_map
from app.utils.kw import format_weekdays, iter_schoolyear_weeks, iter_kw_range, kw_to_monday

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

    # Determine which schoolyear to show
    years_all = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    selected_param = request.query_params.get("schoolyear_id", "")
    sy = db.get(Schoolyear, selected_param) if selected_param else None
    if sy is None:
        _t = date.today().isocalendar()
        sy = _schoolyear_for_week(db, _t.week, _t.year)
    if sy is None:
        fallback_id = aktuelles_schuljahr_id(db)
        sy = db.get(Schoolyear, fallback_id) if fallback_id else None

    # Find schoolyears that have assignments for this trainee (for year-switch links)
    all_assignments = db.exec(
        select(Assignment)
        .where(Assignment.trainee_id == trainee.id)
        .order_by(Assignment.jahr, Assignment.kw)
    ).all()
    trainee_year_ids = sorted({a.schoolyear_id for a in all_assignments})
    years_with_assignments = [y for y in years_all if y.id in trainee_year_ids]

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
        "years": years_with_assignments,
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
