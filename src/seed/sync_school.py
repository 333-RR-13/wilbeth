"""Backfill-Skript: AUTO-Berufsschul-Einsaetze fuer alle Trainees materialisieren.

Aufruf:  python -m seed.sync_school
"""

from sqlmodel import Session, select

from app.database import engine
from app.models import Assignment, AssignmentSource, AssignmentTyp
from app.services.school_sync import resync_all

_AUTO_SCHOOL_TYPS = frozenset({AssignmentTyp.BERUFSSCHULE, AssignmentTyp.UNI})


def main() -> None:
    with Session(engine) as db:
        resync_all(db)
        count = len(
            db.exec(
                select(Assignment).where(
                    Assignment.source == AssignmentSource.AUTO,
                    Assignment.typ.in_(_AUTO_SCHOOL_TYPS),  # type: ignore[attr-defined]
                )
            ).all()
        )
        print(f"Fertig. {count} AUTO-Schuleintraege (BERUFSSCHULE/UNI) in der Datenbank.")


if __name__ == "__main__":
    main()
