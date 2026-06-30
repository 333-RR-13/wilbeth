"""Hilfsfunktionen fuer TraineeClassMembership."""

import re
from datetime import date

from sqlmodel import Session, select

from app.models.schoolyear import Schoolyear
from app.models.trainee import Trainee, TraineeRolle
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


def _start_year(d: date | None) -> int | None:
    """Leitet das Startjahr des Schuljahres aus dem Ausbildungsbeginn ab.

    Konvention: Ausbildungsjahrgang beginnt im Schuljahr das ab August gilt.
    - Monat >= 8: start_year = d.year
    - Monat < 8:  start_year = d.year - 1
    - None:       None
    """
    if d is None:
        return None
    return d.year if d.month >= 8 else d.year - 1


def klasse_fuer(db: Session, trainee: Trainee, schoolyear_id: str) -> int | None:
    """Gibt die Klasse des Trainees fuer das angegebene Lehrjahr zurueck.

    Re-Anker-Logik: der Anker ist der juengste Pin <= Zieljahr.
    Pins sind: (a) globaler Start (start_year aus ausbildungsbeginn, klasse_id) und
    (b) jede Override-Membership des Trainees (year = msy.start_year, klasse_id = m.klasse_id).

    Prioritaet / Ablauf:
    1. Exakter Override fuer schoolyear_id vorhanden -> return dessen klasse_id.
    2. target (Schoolyear) nicht vorhanden -> statischer Fallback (trainee.klasse_id).
    3. Pins sammeln und juengsten Pin <= target.start_year suchen.
       - Keine Candidates, aber Pins vorhanden -> None (Zieljahr vor erstem Anker).
       - Keine Candidates und keine Pins -> statischer Fallback (trainee.klasse_id).
    4. Ab dem juengsten Anker steps-mal next_class_for anwenden.
       AZUBI ohne Nachfolger -> None (Absolvent); nicht-AZUBI -> letzte Klasse.
    """
    # (1) Exakter Override via Membership
    membership = db.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.trainee_id == trainee.id,
            TraineeClassMembership.schoolyear_id == schoolyear_id,
        )
    ).first()
    if membership is not None:
        return membership.klasse_id

    # (2) Zieljahr nicht aufloesbar -> statischer Fallback
    target = db.get(Schoolyear, schoolyear_id)
    if target is None:
        return trainee.klasse_id

    # (3) Pins sammeln: (year, klasse_id)
    anchors: list[tuple[int, int]] = []

    global_start_year = _start_year(trainee.ausbildungsbeginn)
    if global_start_year is not None and trainee.klasse_id is not None:
        anchors.append((global_start_year, trainee.klasse_id))

    all_memberships = db.exec(
        select(TraineeClassMembership).where(
            TraineeClassMembership.trainee_id == trainee.id,
        )
    ).all()
    for m in all_memberships:
        msy = db.get(Schoolyear, m.schoolyear_id)
        if msy is not None:
            anchors.append((msy.start_year, m.klasse_id))

    # (4) Juengster Anker <= target.start_year
    candidates = [(yr, kid) for (yr, kid) in anchors if yr <= target.start_year]

    if not candidates:
        if anchors:
            return None  # Zieljahr liegt vor dem ersten Anker
        return trainee.klasse_id  # statischer Fallback, altes Verhalten

    anchor_year, anchor_klasse_id = max(candidates, key=lambda a: a[0])

    steps = target.start_year - anchor_year

    if steps == 0:
        return anchor_klasse_id

    # steps > 0: Klasse um 'steps' Schritte vorwaerts bewegen
    klasse = db.get(TraineeClass, anchor_klasse_id)
    if klasse is None:
        return None

    all_classes = db.exec(select(TraineeClass)).all()

    for _ in range(steps):
        next_k = next_class_for(klasse, all_classes)
        if next_k is None:
            if trainee.rolle == TraineeRolle.AZUBI:
                return None  # Absolvent
            else:
                break  # DH bleibt in letzter Klasse
        klasse = next_k

    return klasse.id


def semester_label(
    db: Session,
    trainee: Trainee,
    schoolyear_id: str,
    halbjahr: str,
) -> str | None:
    """Gibt das Semester-Label fuer einen nicht-AZUBI zurueck.

    Nur sinnvoll fuer trainee.rolle != AZUBI.
    Gibt None zurueck wenn nicht ableitbar.

    halbjahr:
      "1"  -> "<n>. Semester"
      "2"  -> "<n+1>. Semester"
      ""   -> "<n>./<n+1>. Semester"
    """
    if trainee.rolle == TraineeRolle.AZUBI:
        return None

    start_year = _start_year(trainee.ausbildungsbeginn)
    target = db.get(Schoolyear, schoolyear_id)

    if start_year is None or target is None:
        return None

    steps_years = target.start_year - start_year
    if steps_years < 0:
        return None

    base = 2 * steps_years

    if halbjahr == "2":
        return f"{base + 2}. Semester"
    elif halbjahr == "1":
        return f"{base + 1}. Semester"
    else:
        return f"{base + 1}./{base + 2}. Semester"


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
