"""Hilfsfunktionen fuer TraineeClassMembership."""

import re

from sqlmodel import Session, select

from app.models.trainee import Trainee
from app.models.trainee_class import TraineeClass
from app.models.trainee_class_membership import TraineeClassMembership

# Klassennamen folgen der Konvention "<Beruf> <n>. LJ" (z. B. "FISI 2. LJ").
_LJ_RE = re.compile(r"^(?P<beruf>.+?)\s*(?P<lj>\d)\.\s*LJ\s*$")

# Mapping bekannter Berufstoken auf den offiziellen Langnamen (case-insensitive Lookup).
BERUF_LANGNAMEN: dict[str, str] = {
    "FISI": "Fachinformatiker für Systemintegration",
    "FIAE": "Fachinformatiker für Anwendungsentwicklung",
}


def beruf_langname(token: str) -> str:
    """Gibt den Langnamen eines Berufstoken zurueck.

    Beispiele:
      "FISI"  -> "Fachinformatiker für Systemintegration"
      "fisi"  -> "Fachinformatiker für Systemintegration"
      "BWL"   -> "BWL"  (unbekannte Token unveraendert)
    """
    return BERUF_LANGNAMEN.get(token.strip().upper(), token.strip())


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


def beruf_und_lehrjahr(name: str | None) -> tuple[str, int | None]:
    """Leitet Beruf und Lehrjahr aus einem Klassennamen ab.

    Beispiele:
      "FISI 2. LJ"        -> ("FISI", 2)
      "Büro 3. LJ"        -> ("Büro", 3)
      "DHBW Cybersecurity" -> ("DHBW Cybersecurity", None)
      None                 -> ("Ohne Klasse", None)
    """
    if not name:
        return ("Ohne Klasse", None)
    m = _LJ_RE.match(name)
    if m:
        return (m.group("beruf").strip(), int(m.group("lj")))
    return (name, None)


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
