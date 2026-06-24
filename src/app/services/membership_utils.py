"""Hilfsfunktionen fuer TraineeClassMembership."""

from sqlmodel import Session, select

from app.models.trainee import Trainee
from app.models.trainee_class_membership import TraineeClassMembership


def klasse_fuer(db: Session, trainee: Trainee, schoolyear_id: str) -> int | None:
    """Gibt die Klasse des Trainees fuer das angegebene Lehrjahr zurueck.

    Prioritaet:
    1. TraineeClassMembership fuer (trainee, schoolyear_id)
    2. Fallback: trainee.klasse_id
    """
    membership = db.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.trainee_id == trainee.id,
            TraineeClassMembership.schoolyear_id == schoolyear_id,
        )
    ).first()
    if membership is not None:
        return membership.klasse_id
    return trainee.klasse_id


def upsert_membership(
    db: Session,
    trainee_id: int,
    schoolyear_id: str,
    klasse_id: int,
) -> TraineeClassMembership:
    """Legt eine Membership an oder aktualisiert sie (upsert).

    Gibt die (ggf. neue) Membership zurueck.  Kein commit — Aufrufer entscheidet.
    """
    existing = db.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.trainee_id == trainee_id,
            TraineeClassMembership.schoolyear_id == schoolyear_id,
        )
    ).first()
    if existing is not None:
        existing.klasse_id = klasse_id
        db.add(existing)
        return existing
    membership = TraineeClassMembership(
        trainee_id=trainee_id,
        schoolyear_id=schoolyear_id,
        klasse_id=klasse_id,
    )
    db.add(membership)
    return membership
