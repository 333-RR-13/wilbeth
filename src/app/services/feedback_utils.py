"""Hilfsfunktionen fuer Feedbackboegen: Fehlzeiten-Vorbelegung, Trainee-
Bloecke ueber alle Abteilungen sowie Partner-/Block-Lookup zwischen den
beiden Bogen-Typen (AUSBILDER/AZUBI)."""

from sqlmodel import Session, select

from app.models.assignment import Assignment, AssignmentTyp
from app.models.department import Department
from app.models.feedback_bogen import FeedbackBogen
from app.models.school_plan import SchoolPlan, SchoolPlanWeek
from app.models.schoolyear import Schoolyear
from app.models.trainee import Trainee
from app.services.membership_utils import klasse_fuer
from app.utils.kw import iter_schoolyear_weeks, kw_to_monday


def fehlzeiten_vorbelegung(
    db: Session,
    trainee_id: int,
    schoolyear_id: str,
    kw_von: int,
    jahr_von: int,
    kw_bis: int,
    jahr_bis: int,
) -> dict:
    """Zaehlt fuer den KW-Bereich [kw_von/jahr_von .. kw_bis/jahr_bis]
    (inklusive) die Urlaubs- und Schulwochen des Trainees in WOCHEN.

    Urlaub: Assignments mit typ URLAUB im Bereich.
    Schule: Assignments mit typ BERUFSSCHULE/UNI im Bereich, vereinigt mit
    den Schulwochen aus dem Schulplan der fuer schoolyear_id berechneten
    Klasse (klasse_fuer) -- die Vereinigung (Set) verhindert Doppelzaehlung
    von Wochen, die bereits als Assignment gezaehlt wurden.
    """
    range_set = set(iter_schoolyear_weeks(kw_von, jahr_von, kw_bis, jahr_bis))

    rows = db.exec(
        select(Assignment).where(
            Assignment.trainee_id == trainee_id,
            Assignment.schoolyear_id == schoolyear_id,
        )
    ).all()

    urlaub_weeks = {
        (a.kw, a.jahr) for a in rows
        if a.typ == AssignmentTyp.URLAUB and (a.kw, a.jahr) in range_set
    }
    schule_weeks = {
        (a.kw, a.jahr) for a in rows
        if a.typ in (AssignmentTyp.BERUFSSCHULE, AssignmentTyp.UNI) and (a.kw, a.jahr) in range_set
    }

    trainee = db.get(Trainee, trainee_id)
    if trainee is not None:
        klasse_id = klasse_fuer(db, trainee, schoolyear_id)
        if klasse_id is not None:
            plan = db.exec(
                select(SchoolPlan).where(
                    SchoolPlan.klasse_id == klasse_id,
                    SchoolPlan.schoolyear_id == schoolyear_id,
                )
            ).first()
            if plan is not None:
                plan_weeks = db.exec(
                    select(SchoolPlanWeek).where(SchoolPlanWeek.plan_id == plan.id)
                ).all()
                for w in plan_weeks:
                    key = (w.kw, w.jahr)
                    if key in range_set:
                        schule_weeks.add(key)

    return {"urlaub": len(urlaub_weeks), "schule": len(schule_weeks)}


def _dept_block(
    db: Session,
    department_id: int,
    cells: list[Assignment],
    week_idx: dict[tuple[int, int], int],
) -> tuple[int, dict]:
    department = db.get(Department, department_id)
    first, last = cells[0], cells[-1]
    block = {
        "department": department,
        "kw_von": first.kw,
        "jahr_von": first.jahr,
        "kw_bis": last.kw,
        "jahr_bis": last.jahr,
    }
    return week_idx[(first.kw, first.jahr)], block


def trainee_bloecke(db: Session, trainee_id: int, schoolyear_id: str) -> list[dict]:
    """Gruppiert die ABTEILUNG-Einsaetze EINES Trainees (ueber alle
    Abteilungen) zu zusammenhaengenden KW-Bloecken je Abteilung.

    Analog services.block_utils.assignment_blocks, aber fuer einen Trainee
    statt fuer eine Abteilung. Sortiert nach dem ersten Wochenindex des
    Blocks (bezogen auf die Wochenliste des Schuljahres, damit Jahreswechsel
    innerhalb eines Schuljahres korrekt als "aufeinanderfolgend" erkannt
    werden).
    """
    schoolyear = db.get(Schoolyear, schoolyear_id)
    if schoolyear is None:
        return []

    weeks = list(
        iter_schoolyear_weeks(
            schoolyear.start_kw, schoolyear.start_year,
            schoolyear.end_kw, schoolyear.end_year,
        )
    )
    week_idx = {wk: i for i, wk in enumerate(weeks)}

    rows = db.exec(
        select(Assignment).where(
            Assignment.trainee_id == trainee_id,
            Assignment.schoolyear_id == schoolyear_id,
            Assignment.typ == AssignmentTyp.ABTEILUNG,
        )
    ).all()

    by_dept: dict[int, list[Assignment]] = {}
    for a in rows:
        if a.abteilung_id is None:
            continue
        idx = week_idx.get((a.kw, a.jahr))
        if idx is None:
            continue  # Zelle ausserhalb der Wochenliste des Schuljahres
        by_dept.setdefault(a.abteilung_id, []).append(a)

    sortable: list[tuple[int, dict]] = []
    for dept_id, cells in by_dept.items():
        cells.sort(key=lambda a: week_idx[(a.kw, a.jahr)])
        current: list[Assignment] = []
        prev_idx: int | None = None
        for a in cells:
            idx = week_idx[(a.kw, a.jahr)]
            if current and prev_idx is not None and idx == prev_idx + 1:
                current.append(a)
            else:
                if current:
                    sortable.append(_dept_block(db, dept_id, current, week_idx))
                current = [a]
            prev_idx = idx
        if current:
            sortable.append(_dept_block(db, dept_id, current, week_idx))

    sortable.sort(key=lambda t: t[0])
    return [block for _, block in sortable]


def _overlaps(
    a_kw_von: int, a_jahr_von: int, a_kw_bis: int, a_jahr_bis: int,
    b_kw_von: int, b_jahr_von: int, b_kw_bis: int, b_jahr_bis: int,
) -> bool:
    """True, wenn sich die beiden KW-Bereiche zeitlich ueberschneiden.

    Vergleich ueber die Montags-Daten der ISO-Kalenderwochen -- das ist
    aequivalent zum Wochenindex-Vergleich innerhalb einer zusammenhaengenden
    Wochenliste, ohne dass extra ein Schuljahres-Wochenindex aufgebaut werden
    muss, und behandelt Jahreswechsel (z. B. KW52/2025 -> KW1/2026) korrekt.
    """
    a_start, a_end = kw_to_monday(a_kw_von, a_jahr_von), kw_to_monday(a_kw_bis, a_jahr_bis)
    b_start, b_end = kw_to_monday(b_kw_von, b_jahr_von), kw_to_monday(b_kw_bis, b_jahr_bis)
    return a_start <= b_end and b_start <= a_end


def partner_bogen(db: Session, bogen: FeedbackBogen) -> FeedbackBogen | None:
    """Findet den Bogen des JEWEILS ANDEREN Typs fuer denselben Trainee,
    dieselbe Abteilung und dasselbe Schuljahr mit ueberlappendem Zeitraum.

    None, wenn kein solcher Partner-Bogen existiert.
    """
    other_typ = "AZUBI" if bogen.typ == "AUSBILDER" else "AUSBILDER"
    candidates = db.exec(
        select(FeedbackBogen).where(
            FeedbackBogen.typ == other_typ,
            FeedbackBogen.trainee_id == bogen.trainee_id,
            FeedbackBogen.department_id == bogen.department_id,
            FeedbackBogen.schoolyear_id == bogen.schoolyear_id,
        )
    ).all()
    for c in candidates:
        if _overlaps(
            bogen.kw_von, bogen.jahr_von, bogen.kw_bis, bogen.jahr_bis,
            c.kw_von, c.jahr_von, c.kw_bis, c.jahr_bis,
        ):
            return c
    return None


def bogen_fuer_block(
    db: Session,
    typ: str,
    trainee_id: int,
    department_id: int,
    schoolyear_id: str,
    kw_von: int,
    jahr_von: int,
    kw_bis: int,
    jahr_bis: int,
) -> FeedbackBogen | None:
    """Findet einen bereits existierenden Bogen DESSELBEN Typs fuer diesen
    Trainee/diese Abteilung/dieses Schuljahr mit ueberlappendem Zeitraum.

    None, wenn keiner existiert.
    """
    candidates = db.exec(
        select(FeedbackBogen).where(
            FeedbackBogen.typ == typ,
            FeedbackBogen.trainee_id == trainee_id,
            FeedbackBogen.department_id == department_id,
            FeedbackBogen.schoolyear_id == schoolyear_id,
        )
    ).all()
    for c in candidates:
        if _overlaps(
            kw_von, jahr_von, kw_bis, jahr_bis,
            c.kw_von, c.jahr_von, c.kw_bis, c.jahr_bis,
        ):
            return c
    return None
