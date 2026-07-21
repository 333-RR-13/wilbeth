"""Block-Bildung fuer zusammenhaengende ABTEILUNG-Einsaetze.

Fasst die einzelnen Wochen-Zellen (Assignment) eines Trainees in einer
Abteilung zu zusammenhaengenden KW-Bloecken zusammen (bezogen auf die
Wochenliste des jeweiligen Schuljahres, damit Jahreswechsel innerhalb eines
Schuljahres korrekt als "aufeinanderfolgend" erkannt werden).
"""

from sqlmodel import Session, select

from app.models.assignment import Assignment, AssignmentTyp
from app.models.schoolyear import Schoolyear
from app.models.trainee import Trainee
from app.utils.kw import iter_schoolyear_weeks


def _build_block(
    db: Session,
    trainee_id: int,
    cells: list[Assignment],
    week_idx: dict[tuple[int, int], int],
) -> tuple[int, str, dict]:
    """Baut das Block-Dict fuer eine Folge zusammenhaengender Zellen.

    Gibt zusaetzlich (erster_wochenindex, nachname) fuer die Sortierung
    zurueck.
    """
    trainee = db.get(Trainee, trainee_id)
    first, last = cells[0], cells[-1]

    statuses = {(c.bestaetigung or "offen") for c in cells}
    if statuses == {"bestaetigt"}:
        status = "bestaetigt"
    elif statuses == {"abgelehnt"}:
        status = "abgelehnt"
    else:
        status = "offen"

    notiz = next((c.notiz for c in cells if c.notiz), "")
    feedback = next((c.feedback for c in cells if c.feedback), "")

    block = {
        "trainee": trainee,
        "kw_von": first.kw,
        "jahr_von": first.jahr,
        "kw_bis": last.kw,
        "jahr_bis": last.jahr,
        "assignment_ids": [c.id for c in cells],
        "status": status,
        "notiz": notiz,
        "feedback": feedback,
    }
    nachname = trainee.nachname if trainee is not None else ""
    return week_idx[(first.kw, first.jahr)], nachname, block


def assignment_blocks(db: Session, department_id: int, schoolyear_id: str) -> list[dict]:
    """Gruppiert die ABTEILUNG-Einsaetze einer Abteilung/eines Schuljahres je
    Trainee zu zusammenhaengenden KW-Bloecken.

    Zellen zaehlen als zusammenhaengend, wenn ihre Wochenindizes (bezogen auf
    die geordnete Wochenliste des Schuljahres) direkt aufeinander folgen --
    das erfasst auch Jahreswechsel innerhalb eines Schuljahres korrekt
    (z. B. KW52/2025 -> KW1/2026).
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
            Assignment.schoolyear_id == schoolyear_id,
            Assignment.typ == AssignmentTyp.ABTEILUNG,
            Assignment.abteilung_id == department_id,
        )
    ).all()

    by_trainee: dict[int, list[Assignment]] = {}
    for a in rows:
        idx = week_idx.get((a.kw, a.jahr))
        if idx is None:
            continue  # Zelle ausserhalb der Wochenliste des Schuljahres
        by_trainee.setdefault(a.trainee_id, []).append(a)

    sortable: list[tuple[int, str, dict]] = []
    for trainee_id, cells in by_trainee.items():
        cells.sort(key=lambda a: week_idx[(a.kw, a.jahr)])
        current: list[Assignment] = []
        prev_idx: int | None = None
        for a in cells:
            idx = week_idx[(a.kw, a.jahr)]
            if current and prev_idx is not None and idx == prev_idx + 1:
                current.append(a)
            else:
                if current:
                    sortable.append(_build_block(db, trainee_id, current, week_idx))
                current = [a]
            prev_idx = idx
        if current:
            sortable.append(_build_block(db, trainee_id, current, week_idx))

    sortable.sort(key=lambda t: (t[0], t[1]))
    return [block for _, _, block in sortable]


def apply_to_block(
    db: Session,
    assignment_ids: list[int],
    bestaetigung: str | None,
    notiz: str | None,
    feedback: str | None,
) -> int:
    """Setzt die uebergebenen (nicht-None) Felder auf allen Assignments der
    Liste und committet die Aenderung.

    Felder, die None sind, bleiben unveraendert. Gibt die Anzahl der
    betroffenen Assignments zurueck.
    """
    if not assignment_ids:
        return 0
    rows = db.exec(
        select(Assignment).where(Assignment.id.in_(assignment_ids))  # type: ignore[union-attr]
    ).all()
    for a in rows:
        if bestaetigung is not None:
            a.bestaetigung = bestaetigung
        if notiz is not None:
            a.notiz = notiz
        if feedback is not None:
            a.feedback = feedback
        db.add(a)
    db.commit()
    return len(rows)
