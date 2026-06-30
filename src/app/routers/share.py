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
from app.services.membership_utils import beruf_und_lehrjahr
from app.utils.colors import department_color_map
from app.utils.kw import format_weekdays, iter_schoolyear_weeks, iter_kw_range, kw_to_monday

router = APIRouter(prefix="/mein-plan", tags=["self-service"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
templates.env.globals["prioritaet_label"] = prioritaet_label
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
    if sy is None and years_all:
        sy = years_all[0]

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
    """Read-only Matrix der eigenen Klasse — ohne Konflikte, ohne Bearbeiten."""
    trainee = _trainee_by_token(db, token)
    klasse = db.get(TraineeClass, trainee.klasse_id) if trainee.klasse_id else None
    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()

    if klasse is None or not years:
        return templates.TemplateResponse(request, "share/klasse.html", {
            "trainee": trainee, "token": token, "active": "klasse",
            "klasse": klasse,
            "classmates": [], "weeks": [], "cell_map": {}, "school_weeks": {},
            "depts": {}, "dept_colors": {}, "selected_year": "", "years": years, "schul_tage": "",
            "trainees": [], "highlight_id": trainee.id,
        })

    # Lehrjahr: Query-Param, sonst das mit dem heutigen Datum, sonst neuestes
    selected = request.query_params.get("schoolyear_id", "")
    sy = db.get(Schoolyear, selected) if selected else None
    if sy is None:
        _t = date.today().isocalendar()
        sy = _schoolyear_for_week(db, _t.week, _t.year) or years[0]

    classmates = db.exec(
        select(Trainee).where(Trainee.klasse_id == klasse.id)
        .order_by(Trainee.nachname, Trainee.vorname)
    ).all()
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


# ── Gesamtuebersicht (read-only, alle aktiven Trainees) ─────────────────────

@router.get("/{token}/uebersicht", response_class=HTMLResponse)
def uebersicht_page(request: Request, token: str, db: DB):
    """Read-only Gesamtuebersicht aller aktiven Trainees, gruppiert nach Beruf/Klasse."""
    trainee = _trainee_by_token(db, token)

    years = db.exec(select(Schoolyear).order_by(Schoolyear.start_year.desc())).all()
    selected_param = request.query_params.get("schoolyear_id", "")
    sy = db.get(Schoolyear, selected_param) if selected_param else None
    if sy is None:
        _t = date.today().isocalendar()
        sy = _schoolyear_for_week(db, _t.week, _t.year)
    if sy is None and years:
        sy = years[0]

    all_trainees = db.exec(
        select(Trainee)
        .where(Trainee.aktiv == True)  # noqa: E712
        .order_by(Trainee.nachname, Trainee.vorname)
    ).all()

    all_depts = db.exec(select(Department)).all()
    depts = {d.id: d for d in all_depts}
    dept_colors = department_color_map(all_depts)

    weeks = []
    cell_map: dict[int, dict[str, Assignment]] = {}
    school_week_map: dict[int, dict[str, str]] = {}

    if sy:
        _today = date.today().isocalendar()
        today_key = (_today.week, _today.year)
        trainee_ids = [t.id for t in all_trainees]
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
        for plan in db.exec(
            select(SchoolPlan).where(SchoolPlan.schoolyear_id == sy.id)
        ).all():
            sw: dict[str, str] = {}
            for w in db.exec(
                select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan.id)
            ).all():
                sw[f"{w.kw},{w.jahr}"] = w.typ.value
            school_week_map[plan.klasse_id] = sw

    all_classes = db.exec(select(TraineeClass)).all()
    classes_by_id: dict[int, TraineeClass] = {c.id: c for c in all_classes}

    # Zweistufige Gruppierung: Beruf -> Klasse -> Trainees (analog overview.py)
    _grp: dict[str, dict[tuple[int | None, str | None], list]] = {}
    for t in all_trainees:
        klasse = classes_by_id.get(t.klasse_id) if t.klasse_id is not None else None
        klasse_name = klasse.name if klasse is not None else None
        beruf, _lj = beruf_und_lehrjahr(klasse_name)
        _grp.setdefault(beruf, {}).setdefault((t.klasse_id, klasse_name), []).append(t)

    _ohne_key = "Ohne Klasse"
    _ohne_grp = _grp.pop(_ohne_key, {})

    def _klasse_sort_key(item: tuple) -> tuple:
        (kid, kname), _ = item
        _, lj = beruf_und_lehrjahr(kname)
        return (lj if lj is not None else 9999, kname or "")

    grouped: list[dict] = []
    for beruf in sorted(_grp.keys()):
        klassen_items = sorted(_grp[beruf].items(), key=_klasse_sort_key)
        grouped.append({
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
    if _ohne_grp:
        klassen_items = sorted(_ohne_grp.items(), key=_klasse_sort_key)
        grouped.append({
            "beruf": _ohne_key,
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
