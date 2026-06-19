"""Schulplan-Synchronisation: AUTO-Einsaetze aus SchoolPlanWeeks erzeugen/bereinigen.

Regeln:
- Nur leere Wochen besetzen: ein AUTO-Eintrag wird nur angelegt, wenn die
  (trainee_id, kw, jahr)-Kombination noch keinen Einsatz hat.
- Existierende AUTO-Eintraege mit falschem Typ werden korrigiert.
- Veraltete AUTO-Eintraege (Schulplan-Woche entfernt oder Trainee hat Klasse
  gewechselt) werden geloescht.
- MANUAL/SELBST/SAP-Eintraege werden niemals veraendert oder geloescht.
"""

from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    SchoolPlan,
    SchoolPlanWeek,
    SchoolWeekTyp,
    Trainee,
)

_TYP_MAP: dict[SchoolWeekTyp, AssignmentTyp] = {
    SchoolWeekTyp.BERUFSSCHULE: AssignmentTyp.BERUFSSCHULE,
    SchoolWeekTyp.UNI: AssignmentTyp.UNI,
}

# AUTO-Typen, die wir verwalten
_AUTO_SCHOOL_TYPS = frozenset({AssignmentTyp.BERUFSSCHULE, AssignmentTyp.UNI})


def sync_trainee(db: Session, trainee_id: int, commit: bool = True) -> None:
    """Reconcile AUTO school assignments for a single trainee.

    - Builds desired set from the trainee's current class plans.
    - Creates AUTO assignments where the cell is empty.
    - Fixes AUTO assignments with the wrong typ.
    - Deletes AUTO school assignments not in the desired set (stale).
    - Never touches non-AUTO entries.
    """
    trainee = db.get(Trainee, trainee_id)
    if trainee is None:
        return

    # Build desired: (schoolyear_id, kw, jahr) -> AssignmentTyp
    desired: dict[tuple[str, int, int], AssignmentTyp] = {}

    if trainee.klasse_id is not None:
        plans = db.exec(
            select(SchoolPlan).where(SchoolPlan.klasse_id == trainee.klasse_id)
        ).all()
        for plan in plans:
            weeks = db.exec(
                select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan.id)
            ).all()
            for w in weeks:
                desired[(plan.schoolyear_id, w.kw, w.jahr)] = _TYP_MAP[w.typ]

    # Fetch all existing assignments for this trainee, keyed by (schoolyear_id, kw, jahr)
    existing_all = db.exec(
        select(Assignment).where(Assignment.trainee_id == trainee_id)
    ).all()
    existing_by_cell: dict[tuple[str, int, int], Assignment] = {
        (a.schoolyear_id, a.kw, a.jahr): a for a in existing_all
    }

    # Process desired cells
    for (sy_id, kw, jahr), target_typ in desired.items():
        cell_key = (sy_id, kw, jahr)
        if cell_key in existing_by_cell:
            a = existing_by_cell[cell_key]
            if a.source == AssignmentSource.AUTO and a.typ != target_typ:
                # Fix wrong typ on an existing AUTO assignment
                a.typ = target_typ
                db.add(a)
            # If non-AUTO entry exists: leave it untouched (conflict stays visible)
        else:
            # Cell is empty — create AUTO assignment
            db.add(Assignment(
                trainee_id=trainee_id,
                schoolyear_id=sy_id,
                kw=kw,
                jahr=jahr,
                typ=target_typ,
                source=AssignmentSource.AUTO,
            ))

    # Delete stale AUTO school assignments (no longer in desired)
    for cell_key, a in existing_by_cell.items():
        if (
            a.source == AssignmentSource.AUTO
            and a.typ in _AUTO_SCHOOL_TYPS
            and cell_key not in desired
        ):
            db.delete(a)

    if commit:
        db.commit()


def sync_class(db: Session, klasse_id: int, commit: bool = True) -> None:
    """Reconcile AUTO school assignments for every trainee in a class."""
    trainees = db.exec(
        select(Trainee).where(Trainee.klasse_id == klasse_id)
    ).all()
    for t in trainees:
        sync_trainee(db, t.id, commit=False)
    if commit:
        db.commit()


def resync_all(db: Session, commit: bool = True) -> None:
    """Reconcile AUTO school assignments for every trainee in the database."""
    trainees = db.exec(select(Trainee)).all()
    for t in trainees:
        sync_trainee(db, t.id, commit=False)
    if commit:
        db.commit()
