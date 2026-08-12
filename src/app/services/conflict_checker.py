"""Konflikt-Erkennung fuer Einsatzplanung.

Vier Konflikt-Arten:
1. SCHUL_KONFLIKT   – ABTEILUNG in einer Schulwoche laut SchoolPlan.
2. FERIEN_KONFLIKT  – BERUFSSCHULE oder UNI in einer Schulferienswoche.
3. DOPPELBELEGUNG   – Mehrere Trainees in derselben Abteilung in derselben KW
                      (ausser wenn erlaubt_mehrfachbelegung = True).
4. BEREICH_KONFLIKT – Trainee in einer Abteilung, deren erlaubte_berufe
                      NICHT leer ist und den Beruf seiner (fuer das Jahr
                      berechneten) Klasse nicht enthaelt. Leere Liste
                      bedeutet "alle Berufe erlaubt" -- dann nie ein
                      Konflikt. Reine Warnung, kein Block -- der Einsatz
                      bleibt planbar (siehe TEIL B der Aufgabe).
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
    TraineeClass,
)
from app.models.trainee_class_membership import TraineeClassMembership
from app.services.membership_utils import beruf_langname, beruf_und_lehrjahr, klasse_fuer
from app.utils.kw import holiday_contains_week


class ConflictKind(str, Enum):
    SCHUL_KONFLIKT = "SCHUL_KONFLIKT"
    FERIEN_KONFLIKT = "FERIEN_KONFLIKT"
    DOPPELBELEGUNG = "DOPPELBELEGUNG"
    BEREICH_KONFLIKT = "BEREICH_KONFLIKT"


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
    # Nur BEREICH_KONFLIKT: fertig formulierter Erklaerungssatz (z. B.
    # "Kaufmaennische/r Azubi in einer reinen IT-Abteilung").
    detail: str | None = None


def _bereich_konflikt_text(beruf_token: str) -> str:
    """Baut den Erklaerungssatz fuer einen BEREICH_KONFLIKT.

    >>> _bereich_konflikt_text("FISI")
    'Fachinformatiker für Systemintegration ist in dieser Abteilung nicht vorgesehen'
    """
    return f"{beruf_langname(beruf_token)} ist in dieser Abteilung nicht vorgesehen"


def find_conflicts(session: Session, schoolyear_id: str) -> list[Conflict]:
    """Returns all current conflicts for the given schoolyear."""
    assignments = session.exec(
        select(Assignment).where(Assignment.schoolyear_id == schoolyear_id)
    ).all()

    holidays = session.exec(
        select(SchoolHoliday).where(SchoolHoliday.schoolyear_id == schoolyear_id)
    ).all()

    # trainee_id → klasse_id fuer das angegebene Lehrjahr.
    # Prioritaet: Membership fuer schoolyear_id, sonst Fallback trainee.klasse_id
    memberships_for_year: dict[int, int] = {
        m.trainee_id: m.klasse_id
        for m in session.exec(
            select(TraineeClassMembership).where(
                TraineeClassMembership.schoolyear_id == schoolyear_id
            )
        ).all()
    }
    trainee_class_map: dict[int, int] = {}
    trainees_by_id: dict[int, Trainee] = {}
    for t in session.exec(select(Trainee)).all():
        trainees_by_id[t.id] = t
        if t.id in memberships_for_year:
            trainee_class_map[t.id] = memberships_for_year[t.id]
        elif t.klasse_id is not None:
            trainee_class_map[t.id] = t.klasse_id

    # (klasse_id, kw, jahr) → True for weeks that appear in any SchoolPlan
    school_weeks: set[tuple[int, int, int]] = set()
    for plan in session.exec(
        select(SchoolPlan).where(SchoolPlan.schoolyear_id == schoolyear_id)
    ).all():
        for w in session.exec(
            select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan.id)
        ).all():
            school_weeks.add((plan.klasse_id, w.kw, w.jahr))

    # Fuer BEREICH_KONFLIKT: alle Klassen vorab laden (Nachschlagen des
    # bereich-Felds ueber die per klasse_fuer() berechnete Klasse).
    classes_by_id: dict[int, TraineeClass] = {
        c.id: c for c in session.exec(select(TraineeClass)).all()
    }
    # Cache: trainee_id -> berechnete klasse_id fuer schoolyear_id (kann None
    # sein, z. B. Absolvent) -- vermeidet wiederholte klasse_fuer()-Aufrufe
    # bei mehreren Assignments desselben Trainees.
    berechnete_klasse_cache: dict[int, int | None] = {}

    dept_allows_multi: dict[int, bool] = {}
    dept_erlaubte_berufe: dict[int, list[str]] = {}
    conflicts: list[Conflict] = []
    dept_week_trainees: dict[tuple[int, int, int], list[int]] = defaultdict(list)

    for a in assignments:
        # Cache dept flags on first encounter
        if a.abteilung_id is not None and a.abteilung_id not in dept_allows_multi:
            dept = session.get(Department, a.abteilung_id)
            if dept:
                dept_allows_multi[a.abteilung_id] = dept.erlaubt_mehrfachbelegung
                dept_erlaubte_berufe[a.abteilung_id] = dept.erlaubte_berufe or []

        # 1. SCHUL_KONFLIKT: ABTEILUNG entry falls in a school week
        if a.typ == AssignmentTyp.ABTEILUNG:
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

        # 4. BEREICH_KONFLIKT: Beruf der (fuer das Jahr berechneten) Klasse
        # des Trainees ist nicht in der erlaubten Beruf-Liste der Abteilung.
        # Leere Liste = alle Berufe erlaubt (kein Konflikt moeglich). Reine
        # Warnung -- der Einsatz bleibt planbar.
        if a.typ == AssignmentTyp.ABTEILUNG and a.abteilung_id is not None:
            erlaubte_berufe = dept_erlaubte_berufe.get(a.abteilung_id, [])
            if erlaubte_berufe:
                trainee = trainees_by_id.get(a.trainee_id)
                if trainee is not None:
                    if a.trainee_id not in berechnete_klasse_cache:
                        berechnete_klasse_cache[a.trainee_id] = klasse_fuer(
                            session, trainee, schoolyear_id
                        )
                    klasse_id = berechnete_klasse_cache[a.trainee_id]
                    # Trainees ohne berechnete Klasse (Absolventen o. ae.)
                    # erzeugen KEINEN Konflikt.
                    if klasse_id is not None:
                        klasse = classes_by_id.get(klasse_id)
                        if klasse is not None:
                            beruf_token, _lj = beruf_und_lehrjahr(klasse.name)
                            if beruf_token not in erlaubte_berufe:
                                text = _bereich_konflikt_text(beruf_token)
                                conflicts.append(Conflict(
                                    kind=ConflictKind.BEREICH_KONFLIKT,
                                    trainee_id=a.trainee_id,
                                    kw=a.kw,
                                    jahr=a.jahr,
                                    message=f"KW {a.kw}/{a.jahr}: {text}",
                                    dept_id=a.abteilung_id,
                                    trainee_ids=(a.trainee_id,),
                                    detail=text,
                                ))

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
                "Berufsschule bzw. Uni. Ein Abteilungs-Einsatz passt da "
                "nicht — die Person kann nicht gleichzeitig im Betrieb und "
                "in der Schule sein."
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

    if c.kind == ConflictKind.BEREICH_KONFLIKT:
        return {
            "kind": c.kind.value,
            "title": "Bereichs-Konflikt",
            "badge": "badge-yellow",
            "when": when,
            "who": trainee_names.get(c.trainee_id, "Unbekannt"),
            "why": (
                f"{c.detail}. Der Ausbildungsberuf der Person steht nicht in "
                "der Liste der fuer diese Abteilung erlaubten Berufe. Der "
                "Einsatz bleibt trotzdem planbar — dies ist nur ein Hinweis, "
                "kein Blocker."
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
