"""Konflikt-Erkennung fuer Einsatzplanung.

Drei Konflikt-Arten:
1. SCHUL_KONFLIKT   – ABTEILUNG oder URLAUB in einer Schulwoche laut SchoolPlan.
2. FERIEN_KONFLIKT  – BERUFSSCHULE oder UNI in einer Schulferienswoche.
3. DOPPELBELEGUNG   – Mehrere Trainees in derselben Abteilung in derselben KW
                      (ausser wenn erlaubt_mehrfachbelegung = True).
"""

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentTyp,
    Department,
    SchoolHoliday,
    SchoolPlan,
    SchoolPlanWeek,
    Trainee,
)
from app.utils.kw import holiday_contains_week


class ConflictKind(str, Enum):
    SCHUL_KONFLIKT = "SCHUL_KONFLIKT"
    FERIEN_KONFLIKT = "FERIEN_KONFLIKT"
    DOPPELBELEGUNG = "DOPPELBELEGUNG"


@dataclass(frozen=True)
class Conflict:
    kind: ConflictKind
    trainee_id: int | None
    kw: int
    jahr: int
    message: str
    # Strukturierte Zusatzinfos fuer die UI-Erklaerung (siehe describe_conflict):
    dept_id: int | None = None
    holiday_name: str | None = None
    trainee_ids: tuple[int, ...] = ()


def find_conflicts(session: Session, schoolyear_id: str) -> list[Conflict]:
    """Returns all current conflicts for the given schoolyear."""
    assignments = session.exec(
        select(Assignment).where(Assignment.schoolyear_id == schoolyear_id)
    ).all()

    holidays = session.exec(
        select(SchoolHoliday).where(SchoolHoliday.schoolyear_id == schoolyear_id)
    ).all()

    # trainee_id → klasse_id for trainees that have a class
    trainee_class_map: dict[int, int] = {
        t.id: t.klasse_id
        for t in session.exec(select(Trainee)).all()
        if t.klasse_id is not None
    }

    # (klasse_id, kw, jahr) → True for weeks that appear in any SchoolPlan
    school_weeks: set[tuple[int, int, int]] = set()
    for plan in session.exec(
        select(SchoolPlan).where(SchoolPlan.schoolyear_id == schoolyear_id)
    ).all():
        for w in session.exec(
            select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan.id)
        ).all():
            school_weeks.add((plan.klasse_id, w.kw, w.jahr))

    dept_allows_multi: dict[int, bool] = {}
    conflicts: list[Conflict] = []
    dept_week_trainees: dict[tuple[int, int, int], list[int]] = defaultdict(list)

    for a in assignments:
        # Cache dept flag on first encounter
        if a.abteilung_id is not None and a.abteilung_id not in dept_allows_multi:
            dept = session.get(Department, a.abteilung_id)
            if dept:
                dept_allows_multi[a.abteilung_id] = dept.erlaubt_mehrfachbelegung

        # 1. SCHUL_KONFLIKT: ABTEILUNG or URLAUB entry falls in a school week
        if a.typ in (AssignmentTyp.ABTEILUNG, AssignmentTyp.URLAUB):
            klasse_id = trainee_class_map.get(a.trainee_id)
            if klasse_id and (klasse_id, a.kw, a.jahr) in school_weeks:
                conflicts.append(Conflict(
                    kind=ConflictKind.SCHUL_KONFLIKT,
                    trainee_id=a.trainee_id,
                    kw=a.kw,
                    jahr=a.jahr,
                    message=f"KW {a.kw}/{a.jahr}: {a.typ.value} in Schulwoche",
                    dept_id=a.abteilung_id,
                    trainee_ids=(a.trainee_id,),
                ))

        # 2. FERIEN_KONFLIKT: BERUFSSCHULE or UNI entry falls in a holiday
        if a.typ in (AssignmentTyp.BERUFSSCHULE, AssignmentTyp.UNI):
            for h in holidays:
                if holiday_contains_week(h.start_kw, h.start_year, h.end_kw, h.end_year, a.kw, a.jahr):
                    conflicts.append(Conflict(
                        kind=ConflictKind.FERIEN_KONFLIKT,
                        trainee_id=a.trainee_id,
                        kw=a.kw,
                        jahr=a.jahr,
                        message=f"KW {a.kw}/{a.jahr}: {a.typ.value} in Ferienwoche ({h.name})",
                        holiday_name=h.name,
                        trainee_ids=(a.trainee_id,),
                    ))
                    break

        # Collect for DOPPELBELEGUNG check
        if a.typ == AssignmentTyp.ABTEILUNG and a.abteilung_id is not None:
            dept_week_trainees[(a.abteilung_id, a.kw, a.jahr)].append(a.trainee_id)

    # 3. DOPPELBELEGUNG: multiple trainees in same dept/week without allowance
    for (dept_id, kw, jahr), trainee_ids in dept_week_trainees.items():
        if len(trainee_ids) > 1 and not dept_allows_multi.get(dept_id, False):
            conflicts.append(Conflict(
                kind=ConflictKind.DOPPELBELEGUNG,
                trainee_id=None,
                kw=kw,
                jahr=jahr,
                message=f"KW {kw}/{jahr}: {len(trainee_ids)} Trainees in Abteilung {dept_id}",
                dept_id=dept_id,
                trainee_ids=tuple(trainee_ids),
            ))

    return conflicts


def describe_conflict(
    c: Conflict,
    trainee_names: dict[int, str],
    depts: dict[int, "Department"],
) -> dict:
    """Macht aus einem Conflict eine menschenlesbare Erklaerung fuer die UI.

    Liefert ein Dict mit title/badge/when/who/why — nutzbar im Konflikt-Panel
    der Uebersicht und in der Warnbox des Zell-Dialogs.
    """
    when = f"KW {c.kw}/{c.jahr}"

    if c.kind == ConflictKind.SCHUL_KONFLIKT:
        return {
            "kind": c.kind.value,
            "title": "Schul-Konflikt",
            "badge": "badge-red",
            "when": when,
            "who": trainee_names.get(c.trainee_id, "Unbekannt"),
            "why": (
                "In dieser Woche ist die Klasse laut Schulplan in der "
                "Berufsschule bzw. Uni. Ein Abteilungs- oder Urlaubs-Einsatz "
                "passt da nicht — die Person kann nicht gleichzeitig im "
                "Betrieb und in der Schule sein."
            ),
        }

    if c.kind == ConflictKind.FERIEN_KONFLIKT:
        ferien = c.holiday_name or "Ferien"
        return {
            "kind": c.kind.value,
            "title": "Ferien-Konflikt",
            "badge": "badge-orange",
            "when": when,
            "who": trainee_names.get(c.trainee_id, "Unbekannt"),
            "why": (
                f"Hier ist Berufsschule/Uni eingetragen, obwohl in dieser "
                f"Woche Ferien sind ({ferien}). Meist ist der Schulplan dann "
                f"nicht auf dem aktuellen Stand."
            ),
        }

    # DOPPELBELEGUNG
    dept = depts.get(c.dept_id)
    dept_label = f"{dept.code} – {dept.name}" if dept else "derselben Abteilung"
    names = ", ".join(trainee_names.get(t, "Unbekannt") for t in c.trainee_ids)
    return {
        "kind": c.kind.value,
        "title": "Doppelbelegung",
        "badge": "badge-yellow",
        "when": when,
        "who": names,
        "why": (
            f"Mehrere Trainees sind gleichzeitig in {dept_label} geplant "
            f"({names}). Diese Abteilung erlaubt keine Mehrfachbelegung."
        ),
    }
