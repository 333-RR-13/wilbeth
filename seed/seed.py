"""Seed-Skript: Realistische Beispieldaten fuer Lehrjahre 2025-2026 und 2026-2027.

13 Azubis (alliterative Namen) + 7 DH-Studenten.
Behaelt Abteilungen und Berufsschulplaene unveraendert.

Idempotent: bricht ab, wenn bereits Lehrjahre angelegt sind.
Aufruf:  python -m seed.seed
"""

from __future__ import annotations

import sys

from sqlmodel import Session, select

from app.database import engine
from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    DepartmentKategorie,
    SchoolHoliday,
    SchoolPlan,
    SchoolPlanWeek,
    SchoolWeekTyp,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)
from app.utils.kw import iter_kw_range

SCHOOLYEAR_ID = "2025-2026"
SCHOOLYEAR_2627_ID = "2026-2027"

# FIAE-BS-Wochen aus HHS-Blockplan (c-Block = FIAE 2. LJ, a-Block = FIAE 3. LJ)
FIAE2_WEEKS_2526: list[tuple[int, int]] = [
    (41, 2025), (42, 2025), (48, 2025), (49, 2025),
    ( 4, 2026), ( 5, 2026), (11, 2026), (12, 2026),
    (20, 2026), (22, 2026), (28, 2026), (29, 2026),
]
FIAE3_WEEKS_2526: list[tuple[int, int]] = [
    (36, 2025), (37, 2025), (43, 2025), (45, 2025), (50, 2025), (51, 2025),
    ( 6, 2026), ( 7, 2026), (13, 2026), (16, 2026), (23, 2026), (24, 2026), (30, 2026),
]
FIAE2_WEEKS_2627: list[tuple[int, int]] = [
    (41, 2026), (42, 2026), (49, 2026), (50, 2026), (51, 2026),
    ( 5, 2027), ( 6, 2027), (13, 2027), (16, 2027),
    (22, 2027), (23, 2027), (24, 2027), (30, 2027), (35, 2027),
]
FIAE3_WEEKS_2627: list[tuple[int, int]] = [
    (36, 2026), (37, 2026), (45, 2026), (46, 2026), (52, 2026), (53, 2026),
    ( 2, 2027), ( 7, 2027), ( 9, 2027), (17, 2027), (18, 2027), (25, 2027), (26, 2027),
]

# ── Schuljahre ────────────────────────────────────────────────────

def seed_schoolyear(session: Session) -> Schoolyear:
    sy = Schoolyear(id=SCHOOLYEAR_ID, start_kw=36, start_year=2025, end_kw=35, end_year=2026)
    session.add(sy)
    session.flush()
    return sy


def seed_schoolyear_2627(session: Session) -> Schoolyear:
    sy = Schoolyear(id=SCHOOLYEAR_2627_ID, start_kw=36, start_year=2026, end_kw=35, end_year=2027)
    session.add(sy)
    session.flush()
    return sy


# ── Schulferien ───────────────────────────────────────────────────

def seed_holidays(session: Session) -> None:
    for name, skw, sy, ekw, ey in [
        ("Herbstferien",    44, 2025, 44, 2025),
        ("Weihnachtsferien",52, 2025,  1, 2026),
        ("Faschingsferien",  8, 2026,  8, 2026),
        ("Osterferien",     14, 2026, 15, 2026),
        ("Pfingstferien",   21, 2026, 21, 2026),
        ("Sommerferien",    31, 2026, 35, 2026),
    ]:
        session.add(SchoolHoliday(
            schoolyear_id=SCHOOLYEAR_ID, name=name,
            start_kw=skw, start_year=sy, end_kw=ekw, end_year=ey,
        ))


def seed_holidays_2627(session: Session) -> None:
    for name, skw, sy, ekw, ey in [
        ("Herbstferien",    43, 2026, 44, 2026),
        ("Weihnachtsferien", 1, 2027,  1, 2027),
        ("Faschingsferien",  8, 2027,  8, 2027),
        ("Osterferien",     14, 2027, 15, 2027),
        ("Pfingstferien",   21, 2027, 21, 2027),
        ("Sommerferien",    31, 2027, 34, 2027),
    ]:
        session.add(SchoolHoliday(
            schoolyear_id=SCHOOLYEAR_2627_ID, name=name,
            start_kw=skw, start_year=sy, end_kw=ekw, end_year=ey,
        ))


# ── Klassen ───────────────────────────────────────────────────────

def seed_classes(session: Session) -> dict[str, TraineeClass]:
    result: dict[str, TraineeClass] = {}
    # (name, schule, typ, schul_wochentage, halbtag_wochentag)
    rows: list[tuple[str, str, UnterrichtsTyp, str, int | None]] = [
        ("FISI 1. LJ",                "Josef-Durler Rastatt",     UnterrichtsTyp.BLOCK_FEST, "",    None),
        ("FISI 2. LJ",                "Josef-Durler Rastatt",     UnterrichtsTyp.BLOCK_FEST, "",    None),
        ("FISI 3. LJ",                "Josef-Durler Rastatt",     UnterrichtsTyp.BLOCK_FEST, "",    None),
        ("FIAE 1. LJ",                "Heinrich-Hertz Karlsruhe", UnterrichtsTyp.BLOCK_FEST, "",    None),
        ("FIAE 2. LJ",                "Heinrich-Hertz Karlsruhe", UnterrichtsTyp.BLOCK_FEST, "",    None),
        ("FIAE 3. LJ",                "Heinrich-Hertz Karlsruhe", UnterrichtsTyp.BLOCK_FEST, "",    None),
        ("DHBW Wirtschaftsinformatik","DHBW Karlsruhe",           UnterrichtsTyp.DH_PHASEN,  "",    None),
        ("DHBW Cybersecurity",        "DHBW Karlsruhe",           UnterrichtsTyp.DH_PHASEN,  "",    None),
        # Bürokaufleute: gemischte Wochen, feste Schultage (Sprint 6)
        ("Büro 1. LJ",                "Kaufmännische Schule Karlsruhe", UnterrichtsTyp.TAGE_FEST, "2,3", 3),
        ("Büro 2. LJ",                "Kaufmännische Schule Karlsruhe", UnterrichtsTyp.TAGE_FEST, "2,3", 3),
        ("Büro 3. LJ",                "Kaufmännische Schule Karlsruhe", UnterrichtsTyp.TAGE_FEST, "1,4", None),
        # BWL: Blockphasen wie IT-DH-Studenten
        ("BWL",                       "DHBW Karlsruhe",           UnterrichtsTyp.DH_PHASEN,  "",    None),
    ]
    for name, schule, typ, wt, halb in rows:
        c = TraineeClass(
            name=name, berufsschule=schule, unterrichts_typ=typ,
            schul_wochentage=wt, halbtag_wochentag=halb,
        )
        session.add(c)
        result[name] = c
    session.flush()
    return result


# ── Abteilungen ───────────────────────────────────────────────────

def seed_departments(session: Session) -> dict[str, Department]:
    result: dict[str, Department] = {}
    for code, name, kat, multi in [
        ("AI",   "AI Platform",             DepartmentKategorie.ITO,     False),
        ("DP",   "Delivery Platform",       DepartmentKategorie.ITO,     False),
        ("DWP",  "Digital Workplace",       DepartmentKategorie.ITO,     False),
        ("OP",   "Observability Platform",  DepartmentKategorie.ITO,     False),
        ("CP",   "Cloud Platform",          DepartmentKategorie.ITO,     False),
        ("Sec",  "Security",                DepartmentKategorie.ITO,     False),
        ("IAM",  "IAM Platform",            DepartmentKategorie.ITO,     False),
        ("CISO", "CISO",                    DepartmentKategorie.ITO,     False),
        ("BA",   "Business Applications",   DepartmentKategorie.NON_ITO, True),
        ("CS",   "Customer Service",        DepartmentKategorie.NON_ITO, False),
        ("DDAS", "Data Driven Applications",DepartmentKategorie.NON_ITO, False),
        ("KGaA", "KGaA",                    DepartmentKategorie.NON_ITO, False),
        # Bürokaufleute / BWL (Sprint 6)
        ("HR",   "Human Resources",         DepartmentKategorie.NON_ITO, False),
        ("MK",   "Marketing",               DepartmentKategorie.NON_ITO, False),
        ("FM",   "Facility Management",     DepartmentKategorie.NON_ITO, False),
        ("VT",   "Vertrieb",                DepartmentKategorie.NON_ITO, False),
        ("BANK", "Bank",                    DepartmentKategorie.NON_ITO, False),
        ("POST", "Posteingang",             DepartmentKategorie.NON_ITO, False),
        ("EMP",  "Empfang",                 DepartmentKategorie.NON_ITO, False),
    ]:
        d = Department(code=code, name=name, kategorie=kat, erlaubt_mehrfachbelegung=multi)
        session.add(d)
        result[code] = d
    session.flush()
    return result


# ── Schulplaene ───────────────────────────────────────────────────

def _add_weeks(session: Session, plan_id: int, weeks: list[tuple[int, int]]) -> None:
    for kw, jahr in weeks:
        session.add(SchoolPlanWeek(plan_id=plan_id, kw=kw, jahr=jahr, typ=SchoolWeekTyp.BERUFSSCHULE))


def seed_school_plans(session: Session, classes: dict[str, TraineeClass]) -> dict[str, SchoolPlan]:
    plans: dict[str, SchoolPlan] = {}
    for name in classes:
        p = SchoolPlan(klasse_id=classes[name].id, schoolyear_id=SCHOOLYEAR_ID)
        session.add(p)
        plans[name] = p
    session.flush()

    _add_weeks(session, plans["FISI 2. LJ"].id, [
        (38,2025),(39,2025),(45,2025),(3,2026),(4,2026),(9,2026),(10,2026),(17,2026),(18,2026),
    ])
    _add_weeks(session, plans["FISI 3. LJ"].id, [
        (40,2025),(41,2025),(47,2025),(48,2025),(49,2025),(4,2026),(5,2026),(13,2026),(14,2026),
    ])
    _add_weeks(session, plans["FIAE 2. LJ"].id, FIAE2_WEEKS_2526)
    _add_weeks(session, plans["FIAE 3. LJ"].id, FIAE3_WEEKS_2526)
    return plans


def seed_school_plans_2627(session: Session, classes: dict[str, TraineeClass]) -> dict[str, SchoolPlan]:
    plans: dict[str, SchoolPlan] = {}
    for name in classes:
        p = SchoolPlan(klasse_id=classes[name].id, schoolyear_id=SCHOOLYEAR_2627_ID)
        session.add(p)
        plans[name] = p
    session.flush()
    _add_weeks(session, plans["FIAE 2. LJ"].id, FIAE2_WEEKS_2627)
    _add_weeks(session, plans["FIAE 3. LJ"].id, FIAE3_WEEKS_2627)
    return plans


# ── Trainees ──────────────────────────────────────────────────────

def seed_trainees(session: Session, classes: dict[str, TraineeClass]) -> dict[str, Trainee]:
    # 17 Azubis (alliterative Namen) + 9 DH-Studenten
    data: list[tuple[str, str, str | None, TraineeRolle]] = [
        # FISI 2. LJ – 3 Azubis
        ("Anton",   "Altmann",  "FISI 2. LJ",               TraineeRolle.AZUBI),
        ("Beate",   "Bergmann", "FISI 2. LJ",               TraineeRolle.AZUBI),
        ("Carolin", "Clasen",   "FISI 2. LJ",               TraineeRolle.AZUBI),
        # FISI 3. LJ – 2 Azubis
        ("Dirk",    "Dörner",   "FISI 3. LJ",               TraineeRolle.AZUBI),
        ("Eva",     "Erlacher", "FISI 3. LJ",               TraineeRolle.AZUBI),
        # FIAE 2. LJ – 4 Azubis
        ("Felix",   "Fischer",  "FIAE 2. LJ",               TraineeRolle.AZUBI),
        ("Greta",   "Greiner",  "FIAE 2. LJ",               TraineeRolle.AZUBI),
        ("Hannah",  "Huber",    "FIAE 2. LJ",               TraineeRolle.AZUBI),
        ("Ingo",    "Imhof",    "FIAE 2. LJ",               TraineeRolle.AZUBI),
        # FIAE 3. LJ – 4 Azubis
        ("Jonas",   "Jäger",    "FIAE 3. LJ",               TraineeRolle.AZUBI),
        ("Katrin",  "Kühn",     "FIAE 3. LJ",               TraineeRolle.AZUBI),
        ("Leon",    "Lorenz",   "FIAE 3. LJ",               TraineeRolle.AZUBI),
        ("Mia",     "Meßner",   "FIAE 3. LJ",               TraineeRolle.AZUBI),
        # DHBW Wirtschaftsinformatik – 4 DH-Studenten
        ("Niklas",  "Neumann",  "DHBW Wirtschaftsinformatik",TraineeRolle.DH_STUDENT),
        ("Olga",    "Oberle",   "DHBW Wirtschaftsinformatik",TraineeRolle.DH_STUDENT),
        ("Pascal",  "Pfeiffer", "DHBW Wirtschaftsinformatik",TraineeRolle.DH_STUDENT),
        ("Quirin",  "Quandt",   "DHBW Wirtschaftsinformatik",TraineeRolle.DH_STUDENT),
        # DHBW Cybersecurity – 3 DH-Studenten
        ("Rahel",   "Roth",     "DHBW Cybersecurity",        TraineeRolle.DH_STUDENT),
        ("Sven",    "Schäfer",  "DHBW Cybersecurity",        TraineeRolle.DH_STUDENT),
        ("Tina",    "Tauber",   "DHBW Cybersecurity",        TraineeRolle.DH_STUDENT),
        # Bürokaufleute (TAGE_FEST) – 4 Azubis
        ("Uwe",     "Ulmer",    "Büro 1. LJ",                TraineeRolle.AZUBI),
        ("Vera",    "Voigt",    "Büro 1. LJ",                TraineeRolle.AZUBI),
        ("Wanda",   "Wirth",    "Büro 2. LJ",                TraineeRolle.AZUBI),
        ("Yara",    "Yildiz",   "Büro 3. LJ",                TraineeRolle.AZUBI),
        # BWL (DH_PHASEN) – 2 DH-Studenten
        ("Zoe",     "Ziegler",  "BWL",                       TraineeRolle.DH_STUDENT),
        ("Bruno",   "Brandt",   "BWL",                       TraineeRolle.DH_STUDENT),
    ]
    result: dict[str, Trainee] = {}
    for vorname, nachname, klasse_name, rolle in data:
        t = Trainee(
            vorname=vorname, nachname=nachname, rolle=rolle, aktiv=True,
            klasse_id=classes[klasse_name].id if klasse_name else None,
        )
        session.add(t)
        result[f"{vorname} {nachname}"] = t
    session.flush()
    return result


# ── Einsaetze ─────────────────────────────────────────────────────

def seed_assignments(
    session: Session,
    trainees: dict[str, Trainee],
    departments: dict[str, Department],
) -> int:
    """Erstellt realistische Einsaetze fuer alle 20 Personen im Lehrjahr 2025-2026.

    Azubis: BS-Wochen (AUTO) + 4 Abteilungsrotationen + 1-2 Wochen Urlaub.
    DH-Studenten: Praxisphasen (ABTEILUNG) + Theoriephasen (UNI).
    """
    AB = AssignmentTyp.ABTEILUNG
    BS = AssignmentTyp.BERUFSSCHULE
    UN = AssignmentTyp.UNI
    UR = AssignmentTyp.URLAUB
    MA = AssignmentSource.MANUAL
    AU = AssignmentSource.AUTO
    SY = SCHOOLYEAR_ID
    count = 0

    def block(name: str, kv: int, yv: int, kb: int, yb: int,
              typ: AssignmentTyp, dept: str | None = None,
              src: AssignmentSource = MA) -> None:
        nonlocal count
        dept_id = departments[dept].id if dept else None
        for kw, jahr in iter_kw_range(kv, yv, kb, yb):
            session.add(Assignment(
                trainee_id=trainees[name].id, schoolyear_id=SY,
                kw=kw, jahr=jahr, typ=typ,
                abteilung_id=dept_id, source=src, notiz="",
            ))
            count += 1

    # ── FISI 2. LJ ────────────────────────────────────────────────
    # BS-Wochen: 38-39, 45 / 3-4, 9-10, 17-18
    # Dept-Fenster: 36-37, 40-43, 46-51, 2, 5-7, 11-13, 16, 19-20, 22-30

    # Anton Altmann – Schwerpunkt Betrieb/Plattform
    for kv,yv,kb,yb,t,d in [
        (36,2025,37,2025, AB,"CS"),
        (38,2025,39,2025, BS, None),
        (40,2025,43,2025, AB,"CP"),
        (45,2025,45,2025, BS, None),
        (46,2025,50,2025, AB,"DWP"),
        (51,2025,51,2025, UR, None),
        ( 2,2026, 2,2026, AB,"DP"),
        ( 3,2026, 4,2026, BS, None),
        ( 5,2026, 7,2026, AB,"OP"),
        ( 9,2026,10,2026, BS, None),
        (11,2026,13,2026, AB,"IAM"),
        (16,2026,16,2026, AB,"Sec"),
        (17,2026,18,2026, BS, None),
        (19,2026,20,2026, AB,"Sec"),
        (22,2026,25,2026, AB,"BA"),
        (26,2026,26,2026, UR, None),
        (27,2026,30,2026, AB,"DDAS"),
    ]:
        block("Anton Altmann", kv,yv,kb,yb, t, d, AU if t==BS else MA)

    # Beate Bergmann – Schwerpunkt Delivery/Sicherheit
    for kv,yv,kb,yb,t,d in [
        (36,2025,37,2025, AB,"DP"),
        (38,2025,39,2025, BS, None),
        (40,2025,43,2025, AB,"CS"),
        (45,2025,45,2025, BS, None),
        (46,2025,50,2025, AB,"IAM"),
        (51,2025,51,2025, UR, None),
        ( 2,2026, 2,2026, AB,"DWP"),
        ( 3,2026, 4,2026, BS, None),
        ( 5,2026, 7,2026, AB,"Sec"),
        ( 9,2026,10,2026, BS, None),
        (11,2026,13,2026, AB,"AI"),
        (16,2026,16,2026, AB,"OP"),
        (17,2026,18,2026, BS, None),
        (19,2026,20,2026, AB,"OP"),
        (22,2026,25,2026, AB,"BA"),
        (26,2026,26,2026, UR, None),
        (27,2026,30,2026, AB,"KGaA"),
    ]:
        block("Beate Bergmann", kv,yv,kb,yb, t, d, AU if t==BS else MA)

    # Carolin Clasen – Schwerpunkt Observability/Applikationen
    for kv,yv,kb,yb,t,d in [
        (36,2025,37,2025, AB,"OP"),
        (38,2025,39,2025, BS, None),
        (40,2025,43,2025, AB,"DP"),
        (45,2025,45,2025, BS, None),
        (46,2025,50,2025, AB,"Sec"),
        (51,2025,51,2025, UR, None),
        ( 2,2026, 2,2026, AB,"AI"),
        ( 3,2026, 4,2026, BS, None),
        ( 5,2026, 7,2026, AB,"CISO"),
        ( 9,2026,10,2026, BS, None),
        (11,2026,13,2026, AB,"DWP"),
        (16,2026,16,2026, AB,"CP"),
        (17,2026,18,2026, BS, None),
        (19,2026,20,2026, AB,"CP"),
        (22,2026,25,2026, AB,"BA"),
        (26,2026,26,2026, UR, None),
        (27,2026,30,2026, AB,"AI"),
    ]:
        block("Carolin Clasen", kv,yv,kb,yb, t, d, AU if t==BS else MA)

    # ── FISI 3. LJ ────────────────────────────────────────────────
    # BS-Wochen: 40-41, 47-49 / 4-5, 13-14
    # Dept-Fenster: 36-39, 42-43, 46, 50-51, 2-3, 6-7, 9-12, 16, 19-20, 22-30

    # Dirk Dörner – Generalist mit BA-Schwerpunkt
    for kv,yv,kb,yb,t,d in [
        (36,2025,39,2025, AB,"BA"),
        (40,2025,41,2025, BS, None),
        (42,2025,43,2025, AB,"CP"),
        (46,2025,46,2025, AB,"DP"),
        (47,2025,49,2025, BS, None),
        (50,2025,51,2025, AB,"DWP"),
        ( 2,2026, 3,2026, AB,"Sec"),
        ( 4,2026, 5,2026, BS, None),
        ( 6,2026, 7,2026, AB,"IAM"),
        ( 9,2026,12,2026, AB,"OP"),
        (13,2026,14,2026, BS, None),
        (16,2026,16,2026, AB,"AI"),
        (19,2026,20,2026, AB,"BA"),
        (22,2026,24,2026, AB,"BA"),
        (25,2026,25,2026, UR, None),
        (26,2026,26,2026, UR, None),
        (27,2026,30,2026, AB,"DDAS"),
    ]:
        block("Dirk Dörner", kv,yv,kb,yb, t, d, AU if t==BS else MA)

    # Eva Erlacher – Schwerpunkt Entwicklung/Security
    for kv,yv,kb,yb,t,d in [
        (36,2025,39,2025, AB,"CS"),
        (40,2025,41,2025, BS, None),
        (42,2025,43,2025, AB,"DP"),
        (46,2025,46,2025, AB,"CP"),
        (47,2025,49,2025, BS, None),
        (50,2025,51,2025, AB,"Sec"),
        ( 2,2026, 3,2026, AB,"AI"),
        ( 4,2026, 5,2026, BS, None),
        ( 6,2026, 7,2026, AB,"CISO"),
        ( 9,2026,12,2026, AB,"DWP"),
        (13,2026,14,2026, BS, None),
        (16,2026,16,2026, AB,"DDAS"),
        (19,2026,20,2026, AB,"BA"),
        (22,2026,24,2026, AB,"BA"),
        (25,2026,25,2026, UR, None),
        (27,2026,30,2026, AB,"KGaA"),
    ]:
        block("Eva Erlacher", kv,yv,kb,yb, t, d, AU if t==BS else MA)

    # ── FIAE 2. LJ ────────────────────────────────────────────────
    # BS-Wochen: 41-42, 48-49 / 4-5, 11-12, 20, 22, 28-29
    # Dept-Fenster: 36-40, 43, 46-47, 50-51, 2-3, 6-7, 13, 16-19, 23-27, 30

    # Felix Fischer – Schwerpunkt Cloud/Plattform
    for kv,yv,kb,yb,t,d in [
        (36,2025,40,2025, AB,"CS"),
        (41,2025,42,2025, BS, None),
        (43,2025,43,2025, AB,"DP"),
        (46,2025,47,2025, AB,"CP"),
        (48,2025,49,2025, BS, None),
        (50,2025,51,2025, AB,"DWP"),
        ( 2,2026, 3,2026, AB,"IAM"),
        ( 4,2026, 5,2026, BS, None),
        ( 6,2026, 7,2026, AB,"Sec"),
        (11,2026,12,2026, BS, None),
        (13,2026,13,2026, AB,"AI"),
        (16,2026,19,2026, AB,"BA"),
        (20,2026,20,2026, BS, None),
        (22,2026,22,2026, BS, None),
        (23,2026,27,2026, AB,"DDAS"),
        (28,2026,29,2026, BS, None),
        (30,2026,30,2026, AB,"CP"),
    ]:
        block("Felix Fischer", kv,yv,kb,yb, t, d, AU if t==BS else MA)

    # Greta Greiner – Schwerpunkt Observability/BA
    for kv,yv,kb,yb,t,d in [
        (36,2025,40,2025, AB,"DP"),
        (41,2025,42,2025, BS, None),
        (43,2025,43,2025, AB,"OP"),
        (46,2025,47,2025, AB,"IAM"),
        (48,2025,49,2025, BS, None),
        (50,2025,51,2025, AB,"Sec"),
        ( 2,2026, 3,2026, AB,"AI"),
        ( 4,2026, 5,2026, BS, None),
        ( 6,2026, 7,2026, AB,"BA"),
        (11,2026,12,2026, BS, None),
        (13,2026,13,2026, AB,"BA"),
        (16,2026,19,2026, AB,"DDAS"),
        (20,2026,20,2026, BS, None),
        (22,2026,22,2026, BS, None),
        (23,2026,27,2026, AB,"CS"),
        (28,2026,29,2026, BS, None),
        (30,2026,30,2026, AB,"DP"),
    ]:
        block("Greta Greiner", kv,yv,kb,yb, t, d, AU if t==BS else MA)

    # Hannah Huber – Schwerpunkt IAM/Security
    for kv,yv,kb,yb,t,d in [
        (36,2025,40,2025, AB,"OP"),
        (41,2025,42,2025, BS, None),
        (43,2025,43,2025, AB,"AI"),
        (46,2025,47,2025, AB,"BA"),
        (48,2025,49,2025, BS, None),
        (50,2025,50,2025, AB,"KGaA"),
        (51,2025,51,2025, UR, None),
        ( 2,2026, 3,2026, AB,"DWP"),
        ( 4,2026, 5,2026, BS, None),
        ( 6,2026, 7,2026, AB,"CP"),
        (11,2026,12,2026, BS, None),
        (13,2026,13,2026, AB,"DP"),
        (16,2026,19,2026, AB,"CS"),
        (20,2026,20,2026, BS, None),
        (22,2026,22,2026, BS, None),
        (23,2026,27,2026, AB,"AI"),
        (28,2026,29,2026, BS, None),
        (30,2026,30,2026, AB,"DWP"),
    ]:
        block("Hannah Huber", kv,yv,kb,yb, t, d, AU if t==BS else MA)

    # Ingo Imhof – Schwerpunkt CISO/Governance
    for kv,yv,kb,yb,t,d in [
        (36,2025,40,2025, AB,"IAM"),
        (41,2025,42,2025, BS, None),
        (43,2025,43,2025, AB,"CISO"),
        (46,2025,47,2025, AB,"CP"),
        (48,2025,49,2025, BS, None),
        (50,2025,51,2025, AB,"DDAS"),
        ( 2,2026, 3,2026, AB,"Sec"),
        ( 4,2026, 5,2026, BS, None),
        ( 6,2026, 7,2026, AB,"DWP"),
        (11,2026,12,2026, BS, None),
        (13,2026,13,2026, AB,"CS"),
        (16,2026,18,2026, AB,"OP"),
        (19,2026,19,2026, UR, None),
        (20,2026,20,2026, BS, None),
        (22,2026,22,2026, BS, None),
        (23,2026,27,2026, AB,"BA"),
        (28,2026,29,2026, BS, None),
        (30,2026,30,2026, AB,"IAM"),
    ]:
        block("Ingo Imhof", kv,yv,kb,yb, t, d, AU if t==BS else MA)

    # ── FIAE 3. LJ ────────────────────────────────────────────────
    # BS-Wochen: 36-37, 43, 45, 50-51 / 6-7, 13, 16, 23-24, 30
    # Dept-Fenster: 38-42, 46-49, 2-5, 9-12, 17-22, 25-29

    # Jonas Jäger – Schwerpunkt Cloud/Entwicklung
    for kv,yv,kb,yb,t,d in [
        (36,2025,37,2025, BS, None),
        (38,2025,42,2025, AB,"CP"),
        (43,2025,43,2025, BS, None),
        (45,2025,45,2025, BS, None),
        (46,2025,49,2025, AB,"DWP"),
        (50,2025,51,2025, BS, None),
        ( 2,2026, 5,2026, AB,"BA"),
        ( 6,2026, 7,2026, BS, None),
        ( 9,2026,12,2026, AB,"AI"),
        (13,2026,13,2026, BS, None),
        (16,2026,16,2026, BS, None),
        (17,2026,19,2026, AB,"DDAS"),
        (20,2026,20,2026, UR, None),
        (22,2026,22,2026, AB,"CS"),
        (23,2026,24,2026, BS, None),
        (25,2026,29,2026, AB,"DP"),
        (30,2026,30,2026, BS, None),
    ]:
        block("Jonas Jäger", kv,yv,kb,yb, t, d, AU if t==BS else MA)

    # Katrin Kühn – Schwerpunkt Security/IAM
    for kv,yv,kb,yb,t,d in [
        (36,2025,37,2025, BS, None),
        (38,2025,42,2025, AB,"Sec"),
        (43,2025,43,2025, BS, None),
        (45,2025,45,2025, BS, None),
        (46,2025,49,2025, AB,"IAM"),
        (50,2025,51,2025, BS, None),
        ( 2,2026, 5,2026, AB,"OP"),
        ( 6,2026, 7,2026, BS, None),
        ( 9,2026,12,2026, AB,"DWP"),
        (13,2026,13,2026, BS, None),
        (16,2026,16,2026, BS, None),
        (17,2026,19,2026, AB,"CS"),
        (20,2026,20,2026, UR, None),
        (22,2026,22,2026, AB,"BA"),
        (23,2026,24,2026, BS, None),
        (25,2026,29,2026, AB,"KGaA"),
        (30,2026,30,2026, BS, None),
    ]:
        block("Katrin Kühn", kv,yv,kb,yb, t, d, AU if t==BS else MA)

    # Leon Lorenz – Schwerpunkt BA/Data
    for kv,yv,kb,yb,t,d in [
        (36,2025,37,2025, BS, None),
        (38,2025,42,2025, AB,"DP"),
        (43,2025,43,2025, BS, None),
        (45,2025,45,2025, BS, None),
        (46,2025,49,2025, AB,"CS"),
        (50,2025,51,2025, BS, None),
        ( 2,2026, 5,2026, AB,"IAM"),
        ( 6,2026, 7,2026, BS, None),
        ( 9,2026,12,2026, AB,"Sec"),
        (13,2026,13,2026, BS, None),
        (16,2026,16,2026, BS, None),
        (17,2026,20,2026, AB,"BA"),
        (22,2026,22,2026, AB,"BA"),
        (23,2026,24,2026, BS, None),
        (25,2026,27,2026, AB,"DDAS"),
        (28,2026,28,2026, UR, None),
        (29,2026,29,2026, UR, None),
        (30,2026,30,2026, BS, None),
    ]:
        block("Leon Lorenz", kv,yv,kb,yb, t, d, AU if t==BS else MA)

    # Mia Meßner – Schwerpunkt AI/Observability
    for kv,yv,kb,yb,t,d in [
        (36,2025,37,2025, BS, None),
        (38,2025,42,2025, AB,"AI"),
        (43,2025,43,2025, BS, None),
        (45,2025,45,2025, BS, None),
        (46,2025,49,2025, AB,"OP"),
        (50,2025,51,2025, BS, None),
        ( 2,2026, 5,2026, AB,"CISO"),
        ( 6,2026, 7,2026, BS, None),
        ( 9,2026,12,2026, AB,"CP"),
        (13,2026,13,2026, BS, None),
        (16,2026,16,2026, BS, None),
        (17,2026,19,2026, AB,"DWP"),
        (20,2026,20,2026, UR, None),
        (22,2026,22,2026, AB,"AI"),
        (23,2026,24,2026, BS, None),
        (25,2026,29,2026, AB,"OP"),
        (30,2026,30,2026, BS, None),
    ]:
        block("Mia Meßner", kv,yv,kb,yb, t, d, AU if t==BS else MA)

    # ── DH-Studenten DHBW Wirtschaftsinformatik ───────────────────
    # Theoriephasen: KW41-51/2025 (ohne Herbst+Weihnacht), KW22-30/2026
    # Praxisphasen:  KW36-40/2025, KW2-20/2026 (ohne Ferien)
    # Je 4 Personen → staggered dept-Zuweisung pro Praxisblock

    # Praxisblock 1: KW36-40/2025
    # Niklas=BA, Olga=DP, Pascal=CP, Quirin=OP
    block("Niklas Neumann",  36,2025,40,2025, AB,"BA")
    block("Olga Oberle",     36,2025,40,2025, AB,"DP")
    block("Pascal Pfeiffer", 36,2025,40,2025, AB,"CP")
    block("Quirin Quandt",   36,2025,40,2025, AB,"OP")

    # Theoriephase 1: KW41-51/2025 (KW44 Herbst, KW52 Weihnacht → auslassen)
    for name in ["Niklas Neumann","Olga Oberle","Pascal Pfeiffer","Quirin Quandt"]:
        for kv,yv,kb,yb in [(41,2025,43,2025),(46,2025,51,2025)]:
            block(name, kv,yv,kb,yb, UN, None, AU)

    # Praxisblock 2: KW2-7/2026
    # Niklas=DDAS, Olga=CS, Pascal=DWP, Quirin=IAM
    block("Niklas Neumann",  2,2026,7,2026, AB,"DDAS")
    block("Olga Oberle",     2,2026,7,2026, AB,"CS")
    block("Pascal Pfeiffer", 2,2026,7,2026, AB,"DWP")
    block("Quirin Quandt",   2,2026,7,2026, AB,"IAM")

    # Praxisblock 3: KW9-20/2026 (KW14-15 Ostern, KW21 Pfingst ausgelassen)
    # Niklas=AI, Olga=KGaA, Pascal=Sec, Quirin=BA
    for kv,yv,kb,yb in [(9,2026,13,2026),(16,2026,20,2026)]:
        block("Niklas Neumann",  kv,yv,kb,yb, AB,"AI")
        block("Olga Oberle",     kv,yv,kb,yb, AB,"KGaA")
        block("Pascal Pfeiffer", kv,yv,kb,yb, AB,"Sec")
        block("Quirin Quandt",   kv,yv,kb,yb, AB,"BA")

    # Theoriephase 2: KW22-30/2026
    for name in ["Niklas Neumann","Olga Oberle","Pascal Pfeiffer","Quirin Quandt"]:
        block(name, 22,2026,30,2026, UN, None, AU)

    # ── DH-Studenten DHBW Cybersecurity ──────────────────────────
    # Rahel=Security-Fokus, Sven=IAM-Fokus, Tina=CP-Fokus

    # Praxisblock 1: KW36-40/2025
    block("Rahel Roth",   36,2025,40,2025, AB,"Sec")
    block("Sven Schäfer", 36,2025,40,2025, AB,"IAM")
    block("Tina Tauber",  36,2025,40,2025, AB,"CISO")

    # Theoriephase 1: KW41-51/2025
    for name in ["Rahel Roth","Sven Schäfer","Tina Tauber"]:
        for kv,yv,kb,yb in [(41,2025,43,2025),(46,2025,51,2025)]:
            block(name, kv,yv,kb,yb, UN, None, AU)

    # Praxisblock 2: KW2-7/2026
    block("Rahel Roth",   2,2026,7,2026, AB,"CISO")
    block("Sven Schäfer", 2,2026,7,2026, AB,"AI")
    block("Tina Tauber",  2,2026,7,2026, AB,"CP")

    # Praxisblock 3: KW9-20/2026
    for kv,yv,kb,yb in [(9,2026,13,2026),(16,2026,20,2026)]:
        block("Rahel Roth",   kv,yv,kb,yb, AB,"Sec")
        block("Sven Schäfer", kv,yv,kb,yb, AB,"IAM")
        block("Tina Tauber",  kv,yv,kb,yb, AB,"DP")

    # Theoriephase 2: KW22-30/2026
    for name in ["Rahel Roth","Sven Schäfer","Tina Tauber"]:
        block(name, 22,2026,30,2026, UN, None, AU)

    # ── Bürokaufleute (TAGE_FEST) ─────────────────────────────────
    # Keine BS-Wochen: Schule liegt auf festen Wochentagen (Klassen-Eigenschaft).
    # Ganzjährig Abteilung, Urlaub als ganze (Betriebs-)Woche. Pro Zeitfenster
    # sind die 4 Büro-Azubis in unterschiedlichen Abteilungen (keine Doppelbelegung).
    for kv,yv,kb,yb,t,d in [
        (36,2025,43,2025, AB,"EMP"),
        (46,2025,51,2025, AB,"POST"),
        (52,2025,52,2025, UR, None),
        ( 2,2026, 7,2026, AB,"HR"),
        ( 9,2026,13,2026, AB,"MK"),
        (16,2026,19,2026, AB,"FM"),
        (20,2026,20,2026, UR, None),
        (21,2026,22,2026, AB,"FM"),
        (23,2026,30,2026, AB,"VT"),
    ]:
        block("Uwe Ulmer", kv,yv,kb,yb, t, d)

    for kv,yv,kb,yb,t,d in [
        (36,2025,43,2025, AB,"POST"),
        (46,2025,51,2025, AB,"EMP"),
        (52,2025,52,2025, UR, None),
        ( 2,2026, 7,2026, AB,"MK"),
        ( 9,2026,13,2026, AB,"HR"),
        (16,2026,22,2026, AB,"VT"),
        (23,2026,30,2026, AB,"FM"),
    ]:
        block("Vera Voigt", kv,yv,kb,yb, t, d)

    for kv,yv,kb,yb,t,d in [
        (36,2025,43,2025, AB,"HR"),
        (46,2025,51,2025, AB,"VT"),
        (52,2025,52,2025, UR, None),
        ( 2,2026, 7,2026, AB,"BANK"),
        ( 9,2026,13,2026, AB,"FM"),
        (16,2026,22,2026, AB,"POST"),
        (23,2026,30,2026, AB,"MK"),
    ]:
        block("Wanda Wirth", kv,yv,kb,yb, t, d)

    for kv,yv,kb,yb,t,d in [
        (36,2025,43,2025, AB,"FM"),
        (46,2025,50,2025, AB,"HR"),
        (51,2025,51,2025, UR, None),
        ( 2,2026, 7,2026, AB,"EMP"),
        ( 9,2026,13,2026, AB,"VT"),
        (16,2026,22,2026, AB,"BANK"),
        (23,2026,30,2026, AB,"POST"),
    ]:
        block("Yara Yildiz", kv,yv,kb,yb, t, d)

    # ── BWL-Studenten (DH_PHASEN, Blockphasen wie IT-DH) ──────────
    # Zoe Ziegler – Praxis in Vertrieb/Bank/HR
    block("Zoe Ziegler", 36,2025,40,2025, AB,"VT")
    for kv,yv,kb,yb in [(41,2025,43,2025),(46,2025,51,2025)]:
        block("Zoe Ziegler", kv,yv,kb,yb, UN, None, AU)
    block("Zoe Ziegler", 2,2026,7,2026, AB,"VT")
    for kv,yv,kb,yb,d in [(9,2026,13,2026,"BANK"),(16,2026,20,2026,"HR")]:
        block("Zoe Ziegler", kv,yv,kb,yb, AB, d)
    block("Zoe Ziegler", 22,2026,30,2026, UN, None, AU)

    # Bruno Brandt – Praxis in Bank/Posteingang/Marketing
    block("Bruno Brandt", 36,2025,40,2025, AB,"BANK")
    for kv,yv,kb,yb in [(41,2025,43,2025),(46,2025,51,2025)]:
        block("Bruno Brandt", kv,yv,kb,yb, UN, None, AU)
    block("Bruno Brandt", 2,2026,7,2026, AB,"POST")
    for kv,yv,kb,yb,d in [(9,2026,13,2026,"POST"),(16,2026,20,2026,"MK")]:
        block("Bruno Brandt", kv,yv,kb,yb, AB, d)
    block("Bruno Brandt", 22,2026,30,2026, UN, None, AU)

    return count


# ── main ──────────────────────────────────────────────────────────

def main() -> int:
    with Session(engine) as session:
        existing = session.exec(select(Schoolyear)).first()
        if existing is not None:
            print(
                f"Datenbank enthaelt bereits Lehrjahr '{existing.id}'. "
                "Seed-Skript bricht ab. Loesche die DB-Datei fuer einen frischen Seed.",
                file=sys.stderr,
            )
            return 1

        seed_schoolyear(session)
        seed_holidays(session)
        seed_schoolyear_2627(session)
        seed_holidays_2627(session)
        classes = seed_classes(session)
        departments = seed_departments(session)
        trainees = seed_trainees(session, classes)
        seed_school_plans(session, classes)
        seed_school_plans_2627(session, classes)
        assignment_count = seed_assignments(session, trainees, departments)

        session.commit()
        print(
            "Seed erfolgreich:\n"
            f"  - 2 Lehrjahre ({SCHOOLYEAR_ID}, {SCHOOLYEAR_2627_ID})\n"
            f"  - 12 Schulferien-Eintraege (6 je Lehrjahr)\n"
            f"  - {len(classes)} Klassen, {len(departments)} Abteilungen\n"
            f"  - {len(trainees)} Trainees "
            f"(17 Azubis inkl. 4 Bürokaufleute/TAGE_FEST | 9 DH-Studenten inkl. 2 BWL)\n"
            f"  - Schulplaene je Klasse/Lehrjahr (Büro/BWL ohne BS-Wochen)\n"
            f"  - {assignment_count} Einsaetze fuer 2025-2026"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
