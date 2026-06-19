"""Wartungs-Skript: leert ALLE Daten ausser Klassen (trainee_class) und
Abteilungen (department). Schema bleibt unberuehrt (kein Alembic-Eingriff).

Geloescht werden (FK-sicher, Kinder zuerst): Einsaetze, Wuensche, Schulplan-
Wochen, Schulplaene, Schulferien, Trainees, Lehrjahre.

Achtung: nach diesem Clean NICHT `python -m seed.seed` laufen lassen — der Seed
wuerde Klassen/Abteilungen erneut anlegen und an den Unique-Constraints scheitern.

Aufruf:  python -m seed.clean
"""
from __future__ import annotations

import sys

from sqlmodel import Session, select

from app.database import engine
from app.models import (
    Assignment,
    Department,
    SchoolHoliday,
    SchoolPlan,
    SchoolPlanWeek,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeWish,
)

# Reihenfolge: Kinder vor Eltern (FK-sicher)
CLEAR_ORDER = (
    Assignment,
    TraineeWish,
    SchoolPlanWeek,
    SchoolPlan,
    SchoolHoliday,
    Trainee,
    Schoolyear,
)


def main() -> int:
    with Session(engine) as session:
        for model in CLEAR_ORDER:
            for row in session.exec(select(model)).all():
                session.delete(row)
        session.commit()

        klassen = len(session.exec(select(TraineeClass)).all())
        depts = len(session.exec(select(Department)).all())
        print(
            "DB bereinigt. Behalten: "
            f"{klassen} Klassen, {depts} Abteilungen. "
            "Lehrjahre, Schulpläne, Ferien, Trainees, Einsätze & Wünsche geleert."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
