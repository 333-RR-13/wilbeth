"""Stammdaten-Seed (OHNE Trainees/Einsaetze).

Legt nur die Stammdaten an, die man zum Loslegen braucht:
  - Lehrjahre 2025-2026 und 2026-2027
  - Schulferien (je Lehrjahr)
  - Klassen (FISI/FIAE/DHBW/Buero/BWL)
  - Abteilungen
  - Berufsschulplaene (BS-Blockwochen fuer FISI/FIAE 2.+3. LJ)

Trainees legt man anschliessend selbst an (UI). Sobald ein Trainee einer Klasse
zugeordnet ist, materialisiert school_sync die BS-Wochen automatisch.

Wiederverwendung der Funktionen aus seed.seed (eine Quelle der Wahrheit).
Idempotent: bricht ab, wenn bereits ein Lehrjahr existiert.

Aufruf (aus src/):  python -m seed.seed_stammdaten
"""

from __future__ import annotations

import sys

from sqlmodel import Session, select

from app.database import engine
from app.models import Schoolyear
from seed.seed import (
    seed_classes,
    seed_departments,
    seed_holidays,
    seed_holidays_2627,
    seed_school_plans,
    seed_school_plans_2627,
    seed_schoolyear,
    seed_schoolyear_2627,
)


def main() -> int:
    with Session(engine) as session:
        if session.exec(select(Schoolyear)).first() is not None:
            print(
                "Datenbank enthaelt bereits ein Lehrjahr. Seed bricht ab. "
                "Loesche die DB-Datei fuer einen frischen Seed.",
                file=sys.stderr,
            )
            return 1

        seed_schoolyear(session)
        seed_holidays(session)
        seed_schoolyear_2627(session)
        seed_holidays_2627(session)
        classes = seed_classes(session)
        departments = seed_departments(session)
        seed_school_plans(session, classes)
        seed_school_plans_2627(session, classes)

        session.commit()
        print(
            "Stammdaten-Seed erfolgreich (ohne Trainees/Einsaetze):\n"
            "  - 2 Lehrjahre (2025-2026, 2026-2027) + 12 Schulferien-Eintraege\n"
            f"  - {len(classes)} Klassen, {len(departments)} Abteilungen\n"
            "  - Berufsschulplaene fuer FISI/FIAE 2.+3. LJ "
            "(1. LJ, Buero, DHBW, BWL ohne BS-Blockwochen)\n"
            "  - Trainees legst du selbst an."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
