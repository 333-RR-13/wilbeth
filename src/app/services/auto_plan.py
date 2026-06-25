"""Auto-Plan Service.

Berechnet automatische Abteilungs-Einsaetze fuer ausgewaehlte Azubis
basierend auf ihren Wunsch-Prioritaeten und freien Wochen.

Reine Logik ohne DB-Write – der Router schreibt die Vorschlaege
per separatem Schritt als Assignment(source=AUTO) in die DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

from sqlmodel import Session, select

from app.models.assignment import Assignment, AssignmentSource, AssignmentTyp
from app.models.department import Department
from app.models.school_plan import SchoolPlan, SchoolPlanWeek
from app.models.schoolyear import Schoolyear
from app.models.trainee import Trainee
from app.models.trainee_wish import TraineeWish
from app.services.dept_history import visited_department_ids
from app.services.membership_utils import klasse_fuer
from app.utils.kw import iter_schoolyear_weeks


# ── Datentypen ────────────────────────────────────────────────────────────────

class PlannedEntry(NamedTuple):
    """Ein einzelner geplanter Einsatz (noch nicht in die DB geschrieben)."""
    trainee_id: int
    kw: int
    jahr: int
    abteilung_id: int
    source: AssignmentSource = AssignmentSource.AUTO


@dataclass
class SkippedEntry:
    """Eine uebersprungene Woche oder ein uebersprungener Azubi mit Begruendung."""
    trainee_id: int
    kw: int | None  # None = ganzer Azubi uebersprungen (z. B. keine Wuensche)
    jahr: int | None
    reason: str


@dataclass
class AutoPlanResult:
    """Ergebnis von plan_assignments."""
    planned: list[PlannedEntry] = field(default_factory=list)
    skipped: list[SkippedEntry] = field(default_factory=list)


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _build_occupied_keys(
    existing: list[Assignment],
    planned_so_far: list[PlannedEntry],
) -> set[tuple[int, int, int]]:
    """Gibt alle (abteilung_id, kw, jahr)-Tupel zurueck, die belegt sind.

    Beachtet sowohl bestehende Assignments (ABTEILUNG-Typ) als auch
    bereits in diesem Lauf geplante Eintraege.
    """
    keys: set[tuple[int, int, int]] = set()
    for a in existing:
        if a.typ == AssignmentTyp.ABTEILUNG and a.abteilung_id is not None:
            keys.add((a.abteilung_id, a.kw, a.jahr))
    for p in planned_so_far:
        keys.add((p.abteilung_id, p.kw, p.jahr))
    return keys


def _sort_candidates(
    wishes: list[TraineeWish],
    visited_ids: set[int],
) -> list[TraineeWish]:
    """Sortiert Wuensche: unbesuchte zuerst (stabil), dann besuchte.

    Innerhalb beider Gruppen bleibt die Reihenfolge (prioritaet ASC,
    dann department_id ASC) erhalten.
    """
    sorted_wishes = sorted(wishes, key=lambda w: (w.prioritaet, w.department_id))
    unvisited = [w for w in sorted_wishes if w.department_id not in visited_ids]
    visited = [w for w in sorted_wishes if w.department_id in visited_ids]
    return unvisited + visited


# ── Haupt-Algorithmus ─────────────────────────────────────────────────────────

def plan_assignments(
    db: Session,
    schoolyear_id: str,
    trainee_ids: list[int],
    block_length: int = 4,
) -> AutoPlanResult:
    """Berechnet automatische Einsaetze fuer die angegebenen Azubis.

    Regeln (entsprechend Feature-Spec):
    1. Lehrjahr-Wochen via iter_schoolyear_weeks.
    2. Freie Wochen = Wochen ohne bestehenden Assignment-Eintrag.
    3. Kandidaten-Abteilungen aus TraineeWish, sortiert nach Prioritaet;
       bereits besuchte Abteilungen werden ans Ende geschoben (soft).
    4. Azubi ohne Wuensche -> komplett ueberspringen.
    5. Freie Wochen chronologisch in Bloecken der Laenge block_length fuellen,
       Round-Robin ueber Kandidatenliste.
    6. Doppelbelegung vermeiden bei erlaubt_mehrfachbelegung=False.
    7. Keine Schul-/Ferien-Konflikte (Schulwochen sind bereits materialisiert
       und damit besetzt -> durch Punkt 2 abgedeckt).
    8. Bestehende Einsaetze nie ueberschreiben.

    Gibt AutoPlanResult zurueck (kein DB-Write).
    """
    result = AutoPlanResult()

    # Schuljahr laden
    year = db.get(Schoolyear, schoolyear_id)
    if year is None:
        return result

    # Alle Wochen des Lehrjahrs (chronologisch)
    all_weeks = list(iter_schoolyear_weeks(
        year.start_kw, year.start_year,
        year.end_kw, year.end_year,
    ))

    # Alle bestehenden Assignments dieses Lehrjahrs laden
    existing_assignments: list[Assignment] = db.exec(
        select(Assignment).where(Assignment.schoolyear_id == schoolyear_id)
    ).all()

    # Abteilungs-Cache (id -> Department)
    dept_cache: dict[int, Department] = {
        d.id: d for d in db.exec(select(Department)).all()
    }

    # Schulwochen je Klasse fuer dieses Lehrjahr. Diese Wochen gelten als belegt,
    # auch wenn sie (noch) nicht als Assignment materialisiert sind – sonst wuerde
    # der Auto-Plan eingetragene Berufsschul-/Uni-Wochen ueberschreiben.
    school_weeks_by_klasse: dict[int, set[tuple[int, int]]] = {}
    for plan in db.exec(
        select(SchoolPlan).where(SchoolPlan.schoolyear_id == schoolyear_id)
    ).all():
        school_weeks_by_klasse[plan.klasse_id] = {
            (w.kw, w.jahr)
            for w in db.exec(
                select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan.id)
            ).all()
        }

    # Bereits belegte (abteilung_id, kw, jahr)-Tupel fuer Doppelbelegungs-Check.
    # Wird innerhalb der Schleife laufend aktualisiert.
    occupied: set[tuple[int, int, int]] = _build_occupied_keys(existing_assignments, [])

    for trainee_id in trainee_ids:
        # Wuensche dieses Azubis laden
        wishes: list[TraineeWish] = db.exec(
            select(TraineeWish).where(TraineeWish.trainee_id == trainee_id)
        ).all()

        if not wishes:
            result.skipped.append(SkippedEntry(
                trainee_id=trainee_id,
                kw=None,
                jahr=None,
                reason="keine Wünsche hinterlegt",
            ))
            continue

        # Bereits besuchte Abteilungen (ueber alle Schuljahre hinweg)
        visited_ids = visited_department_ids(db, trainee_id)

        # Kandidatenliste sortieren: unbesuchte zuerst, dann besuchte
        candidates = _sort_candidates(wishes, visited_ids)

        # Belegte Wochen dieses Azubis: bestehende Assignments PLUS die Schulwochen
        # seiner Klasse-fuer-dieses-Lehrjahr (auch wenn noch nicht materialisiert).
        trainee = db.get(Trainee, trainee_id)
        klasse_id = klasse_fuer(db, trainee, schoolyear_id) if trainee else None
        school_busy = (
            school_weeks_by_klasse.get(klasse_id, set())
            if klasse_id is not None else set()
        )
        trainee_busy: set[tuple[int, int]] = {
            (a.kw, a.jahr)
            for a in existing_assignments
            if a.trainee_id == trainee_id
        } | school_busy
        # Auch bereits in diesem Lauf geplante Wochen als besetzt markieren
        planned_busy: set[tuple[int, int]] = set()

        # Freie Wochen des Azubis (chronologisch)
        free_weeks = [
            (kw, jahr)
            for kw, jahr in all_weeks
            if (kw, jahr) not in trainee_busy
        ]

        if not free_weeks:
            # Alle Wochen bereits belegt -> nichts zu planen, kein Fehler noetig
            continue

        # Wochen in Bloecken zuteilen (Round-Robin ueber candidates)
        cand_idx = 0
        week_idx = 0

        while week_idx < len(free_weeks):
            # Naechsten freien Block-Start suchen (der sich noch nicht in
            # planned_busy befindet – noetig, weil wir planned_busy laufend fuellen)
            block_weeks: list[tuple[int, int]] = []
            collect_idx = week_idx

            while len(block_weeks) < block_length and collect_idx < len(free_weeks):
                candidate_week = free_weeks[collect_idx]
                if candidate_week not in planned_busy:
                    block_weeks.append(candidate_week)
                collect_idx += 1

            if not block_weeks:
                break

            # Abteilung fuer diesen Block waehlen (Round-Robin, Doppelbelegungs-Check
            # pro Woche separat)
            # Versuche candidates ab cand_idx, einmal rund herum
            dept_found = False
            attempts = 0
            while attempts < len(candidates):
                wish = candidates[(cand_idx + attempts) % len(candidates)]
                dept_id = wish.department_id
                dept = dept_cache.get(dept_id)

                if dept is None:
                    attempts += 1
                    continue

                # Pruefen: fuer jede Woche im Block – darf diese Abteilung zugewiesen werden?
                if dept.erlaubt_mehrfachbelegung:
                    # Mehrfachbelegung erlaubt -> alle Wochen gehen
                    usable_weeks = block_weeks
                else:
                    # Nur Wochen nehmen, in denen diese Abteilung noch NICHT belegt ist
                    usable_weeks = [
                        (kw, jahr) for kw, jahr in block_weeks
                        if (dept_id, kw, jahr) not in occupied
                    ]

                if usable_weeks:
                    # Einsaetze planen
                    for kw, jahr in usable_weeks:
                        entry = PlannedEntry(
                            trainee_id=trainee_id,
                            kw=kw,
                            jahr=jahr,
                            abteilung_id=dept_id,
                            source=AssignmentSource.AUTO,
                        )
                        result.planned.append(entry)
                        planned_busy.add((kw, jahr))
                        occupied.add((dept_id, kw, jahr))

                    # Wochen, die wegen Doppelbelegung nicht zugeteilt wurden, überspringen
                    skipped_weeks = set(block_weeks) - set(usable_weeks)
                    for kw, jahr in skipped_weeks:
                        result.skipped.append(SkippedEntry(
                            trainee_id=trainee_id,
                            kw=kw,
                            jahr=jahr,
                            reason=(
                                f"Abteilung {dept.code} in KW {kw}/{jahr} "
                                "bereits durch anderen Trainee belegt"
                            ),
                        ))

                    cand_idx = (cand_idx + attempts + 1) % len(candidates)
                    dept_found = True
                    break

                attempts += 1

            if not dept_found:
                # Keine passende Abteilung fuer diesen Block gefunden
                for kw, jahr in block_weeks:
                    result.skipped.append(SkippedEntry(
                        trainee_id=trainee_id,
                        kw=kw,
                        jahr=jahr,
                        reason="keine passende Abteilung verfügbar (Doppelbelegung überall)",
                    ))
                    planned_busy.add((kw, jahr))  # trotzdem überspringen

            # Weiter zum naechsten Block
            # Berechne neuen week_idx: naechste Woche, die noch nicht in planned_busy ist
            week_idx = collect_idx
            # Springe ueber bereits geplante Wochen hinweg
            while week_idx < len(free_weeks) and free_weeks[week_idx] in planned_busy:
                week_idx += 1

    return result


# ── DB-Write-Helfer ───────────────────────────────────────────────────────────

def apply_auto_plan(
    db: Session,
    schoolyear_id: str,
    trainee_ids: list[int],
    block_length: int = 4,
) -> AutoPlanResult:
    """Berechnet und schreibt den Auto-Plan in die DB.

    Bestehende Assignments werden nie ueberschrieben (unique constraint
    uq_assign_trainee_kw_jahr schuetzt zusaetzlich).
    Gibt das gleiche AutoPlanResult zurueck wie plan_assignments.
    """
    result = plan_assignments(db, schoolyear_id, trainee_ids, block_length)

    for entry in result.planned:
        assignment = Assignment(
            trainee_id=entry.trainee_id,
            schoolyear_id=schoolyear_id,
            kw=entry.kw,
            jahr=entry.jahr,
            typ=AssignmentTyp.ABTEILUNG,
            abteilung_id=entry.abteilung_id,
            source=AssignmentSource.AUTO,
        )
        db.add(assignment)

    db.commit()
    return result
