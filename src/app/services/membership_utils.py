"""Hilfsfunktionen fuer TraineeClassMembership."""

import re

from sqlmodel import Session, select

from app.models.trainee import Trainee
from app.models.trainee_class import TraineeClass
from app.models.trainee_class_membership import TraineeClassMembership

# Klassennamen folgen der Konvention "<Beruf> <n>. LJ" (z. B. "FISI 2. LJ").
_LJ_RE = re.compile(r"^(?P<beruf>.+?)\s*(?P<lj>\d)\.\s*LJ\s*$")


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


def next_class_for(
    klasse: TraineeClass,
    all_classes: list[TraineeClass],
) -> TraineeClass | None:
    """Naechste Klasse beim Jahreswechsel.

    1. Expliziter Override via ``klasse.next_class_id``.
    2. Sonst aus dem Namen abgeleitet nach der Konvention "<Beruf> <n>. LJ"
       -> "<Beruf> <n+1>. LJ" (z. B. "FISI 2. LJ" -> "FISI 3. LJ").
    3. 3. LJ bzw. unbekanntes Namensmuster -> None (= Abschluss).
    """
    if klasse.next_class_id is not None:
        return next((c for c in all_classes if c.id == klasse.next_class_id), None)
    m = _LJ_RE.match(klasse.name or "")
    if not m:
        return None
    beruf = m.group("beruf").strip()
    lj = int(m.group("lj"))
    target_name = f"{beruf} {lj + 1}. LJ"
    return next((c for c in all_classes if c.name == target_name), None)
