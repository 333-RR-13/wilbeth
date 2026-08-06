"""Abteilungs-Historie eines Azubis.

Liefert, in welchen Abteilungen ein Trainee bereits war (ABTEILUNG-Einsaetze,
ueber alle Schuljahre hinweg), mit optionalem Ausschluss einer einzelnen Zelle.
"""

from sqlmodel import Session, select

from app.models.assignment import Assignment, AssignmentTyp
from app.models.department import Department
from app.utils.kw import week_is_past


def visited_department_ids(
    db: Session,
    trainee_id: int,
    exclude_kw: int | None = None,
    exclude_jahr: int | None = None,
    nur_vergangenheit: bool = False,
) -> set[int]:
    """Gibt die Menge der abteilung_id-Werte zurueck, in denen der Trainee
    bereits einen ABTEILUNG-Einsatz hatte (ueber alle Schuljahre).

    Wenn exclude_kw und exclude_jahr angegeben sind, wird der Einsatz in
    genau dieser KW/Jahr-Kombination aus der Berechnung ausgeschlossen.

    nur_vergangenheit=False (Default): bisheriges Verhalten, zaehlt JEDEN
    ABTEILUNG-Einsatz -- auch einen laufenden oder erst geplanten
    zukuenftigen. Wird u. a. von der Planer-Uebersicht ("War bereits in")
    und dem Auto-Planer genutzt, deren Verhalten sich NICHT aendern soll.

    nur_vergangenheit=True: zaehlt nur Einsaetze, deren Woche vollstaendig
    in der Vergangenheit liegt (Freitag der KW < heute, siehe
    app.utils.kw.week_is_past). Genutzt um einen Abteilungswunsch als
    "bereits erfuellt" zu erkennen -- ein nur geplanter, aber noch nicht
    abgeschlossener Einsatz zaehlt dafuer nicht.
    """
    q = select(Assignment.abteilung_id, Assignment.kw, Assignment.jahr).where(
        Assignment.trainee_id == trainee_id,
        Assignment.typ == AssignmentTyp.ABTEILUNG,
        Assignment.abteilung_id.is_not(None),  # type: ignore[union-attr]
    )
    if exclude_kw is not None and exclude_jahr is not None:
        q = q.where(
            ~((Assignment.kw == exclude_kw) & (Assignment.jahr == exclude_jahr))
        )
    rows = db.exec(q).all()
    if nur_vergangenheit:
        return {
            abteilung_id for abteilung_id, kw, jahr in rows
            if abteilung_id is not None and week_is_past(kw, jahr)
        }
    return {abteilung_id for abteilung_id, kw, jahr in rows if abteilung_id is not None}


def visited_departments(db: Session, trainee_id: int) -> list[Department]:
    """Gibt die Department-Objekte zurueck, in denen der Trainee bereits war,
    sortiert nach Code."""
    ids = visited_department_ids(db, trainee_id)
    if not ids:
        return []
    depts = db.exec(
        select(Department)
        .where(Department.id.in_(ids))  # type: ignore[union-attr]
        .order_by(Department.code)
    ).all()
    return list(depts)
