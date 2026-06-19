"""Einmal-/Wartungs-Skript: legt das Lehrjahr 2025-2026 (falls fehlend) und die
FISI-Schulplaene (2. & 3. LJ) mit ihren BS-Wochen an. Gedacht fuer den Zustand
nach `python -m seed.clean` (Klassen + Abteilungen bleiben, Rest geleert).

Idempotent: vorhandenes Lehrjahr/Plan/Woche wird nicht doppelt angelegt.

Aufruf:  python -m seed.add_fisi_plan
"""
from __future__ import annotations

import sys

from sqlmodel import Session, select

from app.database import engine
from app.models import (
    SchoolPlan,
    SchoolPlanWeek,
    SchoolWeekTyp,
    Schoolyear,
    TraineeClass,
)

SCHOOLYEAR_ID = "2025-2026"

# BS-Wochen laut Projekt-Brief (JDSR-Plan)
FISI2_WEEKS = [(38, 2025), (39, 2025), (45, 2025), (3, 2026), (4, 2026),
               (9, 2026), (10, 2026), (17, 2026), (18, 2026)]
FISI3_WEEKS = [(40, 2025), (41, 2025), (47, 2025), (48, 2025), (49, 2025),
               (4, 2026), (5, 2026), (13, 2026), (14, 2026)]


def _ensure_plan(session: Session, klasse_name: str, weeks: list[tuple[int, int]]) -> int:
    klasse = session.exec(select(TraineeClass).where(TraineeClass.name == klasse_name)).first()
    if not klasse:
        print(f"  ! Klasse '{klasse_name}' nicht gefunden — uebersprungen.")
        return 0
    plan = session.exec(
        select(SchoolPlan).where(
            SchoolPlan.klasse_id == klasse.id,
            SchoolPlan.schoolyear_id == SCHOOLYEAR_ID,
        )
    ).first()
    if not plan:
        plan = SchoolPlan(klasse_id=klasse.id, schoolyear_id=SCHOOLYEAR_ID)
        session.add(plan)
        session.flush()
    existing = {
        (w.kw, w.jahr)
        for w in session.exec(select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan.id)).all()
    }
    added = 0
    for kw, jahr in weeks:
        if (kw, jahr) not in existing:
            session.add(SchoolPlanWeek(plan_id=plan.id, kw=kw, jahr=jahr, typ=SchoolWeekTyp.BERUFSSCHULE))
            added += 1
    return added


def main() -> int:
    with Session(engine) as session:
        sy = session.get(Schoolyear, SCHOOLYEAR_ID)
        if not sy:
            session.add(Schoolyear(id=SCHOOLYEAR_ID, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
            session.flush()
            print(f"Lehrjahr {SCHOOLYEAR_ID} angelegt.")
        else:
            print(f"Lehrjahr {SCHOOLYEAR_ID} existiert bereits.")

        a2 = _ensure_plan(session, "FISI 2. LJ", FISI2_WEEKS)
        a3 = _ensure_plan(session, "FISI 3. LJ", FISI3_WEEKS)
        session.commit()
        print(f"FISI 2. LJ: +{a2} BS-Wochen, FISI 3. LJ: +{a3} BS-Wochen eingetragen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
