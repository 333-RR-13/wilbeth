import json
from datetime import date
from typing import Annotated
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    Assignment,
    Department,
    SchoolPlan,
    SchoolPlanWeek,
    Schoolyear,
    Trainee,
    TraineeClass,
    UnterrichtsTyp,
)
from app.services.conflict_checker import describe_conflict, find_conflicts
from app.services.membership_utils import beruf_und_lehrjahr, klasse_fuer, semester_label
from app.services.dept_history import visited_departments
from app.utils.colors import department_color_map
from app.utils.kw import format_weekdays, iter_schoolyear_weeks, kw_to_monday

router = APIRouter(tags=["overview"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
DB = Annotated[Session, Depends(get_session)]

# Name des Session-Cookies fuer Filter-Persistenz
_FILTER_COOKIE = "ov_filters"


def _read_filter_cookie(request: Request) -> dict:
    """Liest den ov_filters-Cookie und gibt ein dict zurueck (leer wenn nicht vorhanden/ungueltig).

    Der Wert ist URL-encodetes JSON (siehe _set_filter_cookie), wird also erst
    percent-decoded und dann als JSON geparst.
    """
    raw = request.cookies.get(_FILTER_COOKIE, "")
    if not raw:
        return {}
    try:
        return json.loads(unquote(raw))
    except (json.JSONDecodeError, ValueError):
        return {}


def _resolve_param(query_params, key: str, cookie_data: dict) -> str:
    """Gibt den Query-Param-Wert zurueck wenn der Key im Request vorhanden ist
    (auch als leerer String), sonst den Cookie-Wert.

    Regel: Query-Param hat immer Vorrang vor Cookie – auch wenn er leer ist,
    d. h. der Nutzer hat bewusst 'Alle ...' gewaehlt. Nur wenn der Parameter
    gaenzlich fehlt, wird der gespeicherte Cookie-Wert genutzt.
    """
    if key in query_params:
        return query_params[key]
    return cookie_data.get(key, "")


def _set_filter_cookie(
    response,
    schoolyear_id: str,
    klasse_id: str,
    abteilung_id: str,
    wochen: str,
    halbjahr: str,
) -> None:
    """Schreibt die aktuellen Filter-Werte als JSON-Cookie (SameSite=Lax, kein HttpOnly).

    Das JSON wird URL-encodet (percent-encoding). Sonst wuerde Starlettes
    set_cookie das JSON wegen ',' und '"' via http.cookies in RFC-2109-Quoting
    mit Oktal-Escapes (\\054) verpacken – das dekodieren Browser nicht zurueck
    und der Client-Cookie-Jar (httpx) liefert unparsebares JSON.
    """
    payload = quote(json.dumps({
        "schoolyear_id": schoolyear_id,
        "klasse_id": klasse_id,
        "abteilung_id": abteilung_id,
        "wochen": wochen,
        "halbjahr": halbjahr,
    }, separators=(",", ":")))
    response.set_cookie(
        key=_FILTER_COOKIE,
        value=payload,
        samesite="lax",
        httponly=False,
        max_age=60 * 60 * 24 * 30,  # 30 Tage
    )


def _default_halbjahr() -> str:
    """Berechnet das aktuelle Halbjahr anhand der heutigen ISO-KW.

    H2 = KW 11-35, H1 = KW 36-10 (ueberjaehrlich).
    """
    today_kw = date.today().isocalendar().week
    if 11 <= today_kw <= 35:
        return "2"
    return "1"


def _filter_weeks_by_halbjahr(weeks: list[dict], halbjahr: str) -> list[dict]:
    """Filtert die Wochen-Liste auf das gewaehlte Halbjahr.

    H1 (halbjahr='1'): KW >= 36 oder KW <= 10
    H2 (halbjahr='2'): KW 11 bis 35
    Leerer String: alle Wochen (kein Filter).
    """
    if not halbjahr:
        return weeks
    if halbjahr == "1":
        return [w for w in weeks if w["kw"] >= 36 or w["kw"] <= 10]
    if halbjahr == "2":
        return [w for w in weeks if 11 <= w["kw"] <= 35]
    return weeks


@router.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse("/overview", status_code=302)


@router.get("/overview/konflikte", response_class=HTMLResponse)
def overview_conflicts(request: Request, db: DB):
    """Liefert die Konfliktliste mit Begruendung als Partial (HTMX, on demand)."""
    schoolyear_id = request.query_params.get("schoolyear_id", "")
    raw = find_conflicts(db, schoolyear_id) if schoolyear_id else []
    depts = {d.id: d for d in db.exec(select(Department)).all()}
    names = {t.id: f"{t.nachname}, {t.vorname}" for t in db.exec(select(Trainee)).all()}
    details = [describe_conflict(c, names, depts) for c in raw]
    return templates.TemplateResponse(request, "_partials/conflict_list.html", {
        "conflicts": details,
    })


WOCHEN_OPTIONS = [4, 8, 12, 16, 26]


@router.get("/overview", response_class=HTMLResponse)
def overview(request: Request, db: DB):
    # ── Filter-Werte: Query-Param hat Vorrang vor Cookie ──────────────────────
    _cookie = _read_filter_cookie(request)
    qp = request.query_params
    schoolyear_id = _resolve_param(qp, "schoolyear_id", _cookie)
    klasse_id_str = _resolve_param(qp, "klasse_id", _cookie)
    abteilung_id_str = _resolve_param(qp, "abteilung_id", _cookie)
    wochen_str = _resolve_param(qp, "wochen", _cookie)
    # halbjahr: Default beim ersten Aufruf (kein Cookie, kein Param) = aktuelles Halbjahr
    if "halbjahr" in qp:
        halbjahr_str = qp["halbjahr"]
    elif "halbjahr" in _cookie:
        halbjahr_str = _cookie["halbjahr"]
    else:
        halbjahr_str = _default_halbjahr()

    years = db.exec(
        select(Schoolyear)
        .where(Schoolyear.archiviert == False)  # noqa: E712
        .order_by(Schoolyear.start_year.desc())
    ).all()
    classes = db.exec(select(TraineeClass).order_by(TraineeClass.name)).all()
    all_depts = db.exec(select(Department).order_by(Department.code)).all()

    # Schultage-Hinweis je TAGE_FEST-Klasse (z. B. "Di, Mi (halbtags)")
    tage_fest_map = {
        c.id: format_weekdays(c.schul_wochentage, halbtag=c.halbtag_wochentag)
        for c in classes
        if c.unterrichts_typ == UnterrichtsTyp.TAGE_FEST and c.schul_wochentage
    }

    if not schoolyear_id and years:
        schoolyear_id = years[0].id

    year = db.get(Schoolyear, schoolyear_id) if schoolyear_id else None

    if not year:
        dept_colors = department_color_map(all_depts)
        resp = templates.TemplateResponse(request, "overview/matrix.html", {
            "trainees": [], "grouped": [], "weeks": [], "cell_map": {}, "conflict_cells": set(),
            "conflict_count": 0, "years": years, "classes": classes,
            "depts": {}, "all_depts": all_depts, "school_week_map": {}, "trainee_klasse_map": {},
            "semester_label_map": {},
            "tage_fest_map": tage_fest_map,
            "visited_map": {},
            "dept_colors": dept_colors,
            "n_wochen": 0,
            "selected_year": schoolyear_id, "selected_klasse": klasse_id_str,
            "selected_abteilung": abteilung_id_str,
            "selected_wochen": wochen_str,
            "selected_halbjahr": halbjahr_str,
            "wochen_options": WOCHEN_OPTIONS,
            "active_nav": "overview",
        })
        _set_filter_cookie(resp, schoolyear_id, klasse_id_str, abteilung_id_str, wochen_str, halbjahr_str)
        return resp

    _today = date.today().isocalendar()
    _today_key = (_today.week, _today.year)
    all_weeks = [
        {
            "kw": kw,
            "jahr": jahr,
            "monday": kw_to_monday(kw, jahr),
            "is_today": (kw, jahr) == _today_key,
        }
        for kw, jahr in iter_schoolyear_weeks(
            year.start_kw, year.start_year,
            year.end_kw, year.end_year,
        )
    ]

    # Halbjahr-Filter: auf die Wochen des Halbjahres einschraenken (nur Anzeige).
    # n_wochen steuert die sichtbare Viewport-Breite via max-width im Template.
    try:
        n_wochen = int(wochen_str) if wochen_str else 0
    except (ValueError, TypeError):
        n_wochen = 0

    weeks = _filter_weeks_by_halbjahr(all_weeks, halbjahr_str)

    # Alle aktiven Azubis laden; dann per klasse_fuer() auf das Zieljahr filtern
    q = select(Trainee).where(Trainee.aktiv == True)  # noqa: E712
    if abteilung_id_str:
        trainee_ids_in_dept = db.exec(
            select(Assignment.trainee_id).where(
                Assignment.schoolyear_id == schoolyear_id,
                Assignment.abteilung_id == int(abteilung_id_str),
            )
        ).all()
        q = q.where(Trainee.id.in_(trainee_ids_in_dept))
    all_active_trainees = db.exec(q.order_by(Trainee.nachname, Trainee.vorname)).all()

    # Berechnete Klasse je Trainee fuer das gewaehlte Lehrjahr (None = Absolvent/vor Beginn)
    trainee_klasse_map: dict[int, int | None] = {
        t.id: klasse_fuer(db, t, schoolyear_id)
        for t in all_active_trainees
    }

    # Ausschluss NUR von Absolventen / vor Beginn: Anker (klasse_id) vorhanden, aber
    # berechnet -> None. Trainees OHNE Anker (klasse_id None) bleiben sichtbar und
    # landen in der Gruppe "Ohne Klasse" (sonst wuerden neu angelegte Azubis lautlos
    # aus der Uebersicht verschwinden).
    trainees = [
        t for t in all_active_trainees
        if trainee_klasse_map[t.id] is not None or t.klasse_id is None
    ]

    # Klassen-Filter auf Basis der berechneten Klasse
    if klasse_id_str:
        klasse_id_int = int(klasse_id_str)
        trainees = [t for t in trainees if trainee_klasse_map[t.id] == klasse_id_int]

    # Assignments for the selected trainees
    trainee_ids = [t.id for t in trainees]
    if trainee_ids:
        assignments = db.exec(
            select(Assignment).where(
                Assignment.schoolyear_id == schoolyear_id,
                Assignment.trainee_id.in_(trainee_ids),
            )
        ).all()
    else:
        assignments = []

    # cell_map[trainee_id]["kw,jahr"] = Assignment
    cell_map: dict[int, dict[str, Assignment]] = {}
    for a in assignments:
        cell_map.setdefault(a.trainee_id, {})[f"{a.kw},{a.jahr}"] = a

    # Conflict detection. Fuer Doppelbelegungen (trainee_id=None) werden alle
    # beteiligten Trainees markiert, damit auch sie in der Matrix rot erscheinen.
    raw_conflicts = find_conflicts(db, schoolyear_id)
    conflict_cells: set[str] = set()
    for c in raw_conflicts:
        ids = c.trainee_ids if c.trainee_ids else ((c.trainee_id,) if c.trainee_id is not None else ())
        for tid in ids:
            conflict_cells.add(f"{tid}~{c.kw}~{c.jahr}")

    depts = {d.id: d for d in db.exec(select(Department)).all()}
    dept_colors = department_color_map(depts.values())

    # school_week_map[klasse_id] = dict "kw,jahr" -> typ_value for highlighting + chip rendering
    school_week_map: dict[int, dict[str, str]] = {}
    for plan in db.exec(
        select(SchoolPlan).where(SchoolPlan.schoolyear_id == schoolyear_id)
    ).all():
        sw: dict[str, str] = {}
        for w in db.exec(
            select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan.id)
        ).all():
            sw[f"{w.kw},{w.jahr}"] = w.typ.value
        school_week_map[plan.klasse_id] = sw

    # semester_label_map: Semester-Label fuer DH-Studenten (None fuer AZUBI)
    semester_label_map: dict[int, str | None] = {
        t.id: semester_label(db, t, schoolyear_id, halbjahr_str)
        for t in trainees
    }

    # visited_map[trainee_id] = list of departments this trainee has already been in
    visited_map: dict[int, list] = {t.id: visited_departments(db, t.id) for t in trainees}

    # Klassen-Lookup fuer Gruppierung
    classes_by_id: dict[int, TraineeClass] = {c.id: c for c in classes}

    # Zweistufige Gruppierung: Beruf -> Klasse -> Trainees
    # Intermediate: beruf -> klasse_key -> trainees
    _grp: dict[str, dict[tuple[int | None, str | None], list]] = {}
    for t in trainees:
        klasse_id = trainee_klasse_map.get(t.id)
        klasse = classes_by_id.get(klasse_id) if klasse_id is not None else None
        klasse_name = klasse.name if klasse is not None else None
        beruf, _lj = beruf_und_lehrjahr(klasse_name)
        _grp.setdefault(beruf, {}).setdefault((klasse_id, klasse_name), []).append(t)

    # Ohne-Klasse-Gruppe ans Ende: separate aus dem Dict entfernen und am Ende anfuegen
    _ohne_key = "Ohne Klasse"
    _ohne_grp = _grp.pop(_ohne_key, {})

    def _klasse_sort_key(item: tuple[tuple[int | None, str | None], list]) -> tuple:
        (kid, kname), _ = item
        _, lj = beruf_und_lehrjahr(kname)
        lj_sort = lj if lj is not None else 9999
        return (lj_sort, kname or "")

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
                }
                for (kid, kname), ts in klassen_items
            ],
        })

    # Ohne-Klasse-Gruppe ganz ans Ende
    if _ohne_grp:
        klassen_items = sorted(_ohne_grp.items(), key=_klasse_sort_key)
        grouped.append({
            "beruf": _ohne_key,
            "klassen": [
                {
                    "name": kname,
                    "klasse_id": kid,
                    "trainees": sorted(ts, key=lambda t: (t.nachname, t.vorname)),
                }
                for (kid, kname), ts in klassen_items
            ],
        })

    resp = templates.TemplateResponse(request, "overview/matrix.html", {
        "trainees": trainees,
        "grouped": grouped,
        "weeks": weeks,
        "cell_map": cell_map,
        "conflict_cells": conflict_cells,
        "conflict_count": len(raw_conflicts),
        "years": years,
        "classes": classes,
        "depts": depts,
        "all_depts": all_depts,
        "school_week_map": school_week_map,
        "trainee_klasse_map": trainee_klasse_map,
        "semester_label_map": semester_label_map,
        "tage_fest_map": tage_fest_map,
        "visited_map": visited_map,
        "dept_colors": dept_colors,
        "n_wochen": n_wochen,
        "selected_year": schoolyear_id,
        "selected_klasse": klasse_id_str,
        "selected_abteilung": abteilung_id_str,
        "selected_wochen": wochen_str,
        "selected_halbjahr": halbjahr_str,
        "wochen_options": WOCHEN_OPTIONS,
        "active_nav": "overview",
    })
    _set_filter_cookie(resp, schoolyear_id, klasse_id_str, abteilung_id_str, wochen_str, halbjahr_str)
    return resp
