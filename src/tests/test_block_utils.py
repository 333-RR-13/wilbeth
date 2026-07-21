"""Tests fuer app.services.block_utils (Block-Bildung ueber Assignments)."""
from sqlmodel import Session

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    Schoolyear,
    Trainee,
    TraineeRolle,
)
from app.services.block_utils import apply_to_block, assignment_blocks

# Schuljahr mit Jahreswechsel: KW36/2025 – KW35/2026
SY = "2025-2026"


def _setup(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    abt = Department(code="AI", name="Artificial Intelligence")
    other = Department(code="HR", name="Human Resources")
    session.add(abt)
    session.add(other)
    t1 = Trainee(vorname="Bea", nachname="Adler", rolle=TraineeRolle.AZUBI)
    t2 = Trainee(vorname="Cem", nachname="Berger", rolle=TraineeRolle.AZUBI)
    session.add(t1)
    session.add(t2)
    session.flush()
    session.commit()
    return {"abt": abt.id, "other": other.id, "t1": t1.id, "t2": t2.id}


def _assign(session, trainee_id, kw, jahr, abteilung_id, **kwargs):
    a = Assignment(
        trainee_id=trainee_id,
        schoolyear_id=SY,
        kw=kw,
        jahr=jahr,
        typ=kwargs.pop("typ", AssignmentTyp.ABTEILUNG),
        abteilung_id=abteilung_id,
        source=AssignmentSource.MANUAL,
        **kwargs,
    )
    session.add(a)
    return a


# ── (a) zusammenhaengende KWs -> ein Block, Luecke -> zwei Bloecke ─────────

def test_consecutive_weeks_form_one_block_gap_splits(session):
    ids = _setup(session)
    for kw in (8, 9, 10):
        _assign(session, ids["t1"], kw, 2026, ids["abt"])
    # Luecke bei KW11, dann weiter bei KW12/13
    for kw in (12, 13):
        _assign(session, ids["t1"], kw, 2026, ids["abt"])
    session.commit()

    blocks = assignment_blocks(session, ids["abt"], SY)
    assert len(blocks) == 2
    assert (blocks[0]["kw_von"], blocks[0]["jahr_von"]) == (8, 2026)
    assert (blocks[0]["kw_bis"], blocks[0]["jahr_bis"]) == (10, 2026)
    assert len(blocks[0]["assignment_ids"]) == 3
    assert (blocks[1]["kw_von"], blocks[1]["jahr_von"]) == (12, 2026)
    assert (blocks[1]["kw_bis"], blocks[1]["jahr_bis"]) == (13, 2026)
    assert len(blocks[1]["assignment_ids"]) == 2


# ── (b) Jahreswechsel zaehlt als zusammenhaengend ───────────────────────────

def test_year_boundary_counts_as_consecutive(session):
    ids = _setup(session)
    for kw, jahr in ((51, 2025), (52, 2025), (1, 2026), (2, 2026)):
        _assign(session, ids["t1"], kw, jahr, ids["abt"])
    session.commit()

    blocks = assignment_blocks(session, ids["abt"], SY)
    assert len(blocks) == 1
    assert (blocks[0]["kw_von"], blocks[0]["jahr_von"]) == (51, 2025)
    assert (blocks[0]["kw_bis"], blocks[0]["jahr_bis"]) == (2, 2026)
    assert len(blocks[0]["assignment_ids"]) == 4


# ── (c) Status-Aggregation ───────────────────────────────────────────────────

def test_status_aggregation_all_confirmed_vs_mixed(session):
    ids = _setup(session)
    # Trainee 1: alle Zellen bestaetigt -> Block-Status "bestaetigt"
    for kw in (8, 9):
        _assign(session, ids["t1"], kw, 2026, ids["abt"], bestaetigung="bestaetigt")
    # Trainee 2: gemischt (bestaetigt + offen) -> Block-Status "offen"
    _assign(session, ids["t2"], 8, 2026, ids["abt"], bestaetigung="bestaetigt")
    _assign(session, ids["t2"], 9, 2026, ids["abt"], bestaetigung="offen")
    session.commit()

    blocks = assignment_blocks(session, ids["abt"], SY)
    assert len(blocks) == 2
    by_trainee = {b["trainee"].id: b for b in blocks}
    assert by_trainee[ids["t1"]]["status"] == "bestaetigt"
    assert by_trainee[ids["t2"]]["status"] == "offen"


def test_status_aggregation_all_rejected(session):
    ids = _setup(session)
    for kw in (8, 9):
        _assign(session, ids["t1"], kw, 2026, ids["abt"], bestaetigung="abgelehnt")
    session.commit()

    blocks = assignment_blocks(session, ids["abt"], SY)
    assert len(blocks) == 1
    assert blocks[0]["status"] == "abgelehnt"


# ── (d) apply_to_block setzt Felder nur wenn nicht None ─────────────────────

def test_apply_to_block_only_sets_non_none_fields(session):
    ids = _setup(session)
    a1 = _assign(session, ids["t1"], 8, 2026, ids["abt"], bestaetigung="offen", notiz="alt")
    a2 = _assign(session, ids["t1"], 9, 2026, ids["abt"], bestaetigung="offen", notiz="alt")
    session.commit()
    ids_list = [a1.id, a2.id]

    # Nur bestaetigung setzen, notiz/feedback bleiben unveraendert
    count = apply_to_block(session, ids_list, bestaetigung="bestaetigt", notiz=None, feedback=None)
    assert count == 2
    session.refresh(a1)
    session.refresh(a2)
    assert a1.bestaetigung == "bestaetigt"
    assert a2.bestaetigung == "bestaetigt"
    assert a1.notiz == "alt"
    assert a1.feedback is None

    # Jetzt notiz und feedback setzen, bestaetigung bleibt unveraendert
    count2 = apply_to_block(session, ids_list, bestaetigung=None, notiz="neu", feedback="gut gemacht")
    assert count2 == 2
    session.refresh(a1)
    assert a1.bestaetigung == "bestaetigt"  # unveraendert
    assert a1.notiz == "neu"
    assert a1.feedback == "gut gemacht"


# ── (e) fremde Abteilung/BS-Zellen tauchen nicht auf ────────────────────────

def test_foreign_department_and_school_cells_excluded(session):
    ids = _setup(session)
    # Zielabteilung: eine Zelle
    _assign(session, ids["t1"], 8, 2026, ids["abt"])
    # Fremde Abteilung -> darf nicht auftauchen
    _assign(session, ids["t1"], 9, 2026, ids["other"])
    # Berufsschule (kein ABTEILUNG-Typ, keine abteilung_id) -> darf nicht auftauchen
    _assign(session, ids["t1"], 10, 2026, None, typ=AssignmentTyp.BERUFSSCHULE)
    session.commit()

    blocks = assignment_blocks(session, ids["abt"], SY)
    assert len(blocks) == 1
    assert len(blocks[0]["assignment_ids"]) == 1
    # Nur die Zelle aus der Zielabteilung ist enthalten
    only = session.get(Assignment, blocks[0]["assignment_ids"][0])
    assert only.abteilung_id == ids["abt"]
    assert only.kw == 8
