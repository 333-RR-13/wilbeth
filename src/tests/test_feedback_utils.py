"""Tests fuer app.services.feedback_utils (Fehlzeiten-Vorbelegung,
Trainee-Bloecke ueber Abteilungen, Partner-/Block-Lookup zwischen den beiden
Feedbackbogen-Typen)."""

from datetime import date

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    FeedbackBogen,
    SchoolPlan,
    SchoolPlanWeek,
    SchoolWeekTyp,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)
from app.services.feedback_utils import (
    bogen_fuer_block,
    fehlzeiten_vorbelegung,
    partner_bogen,
    trainee_bloecke,
)

SY = "2025-2026"


def _make_assignment(session, trainee_id, kw, jahr, typ, dept_id=None):
    a = Assignment(
        trainee_id=trainee_id, schoolyear_id=SY, kw=kw, jahr=jahr,
        typ=typ, abteilung_id=dept_id, source=AssignmentSource.MANUAL,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


# ── fehlzeiten_vorbelegung ────────────────────────────────────────────────

def test_fehlzeiten_vorbelegung_urlaub_und_schulwoche_ohne_doppelzaehlung(session):
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))

    klasse = TraineeClass(
        name="FISI 2. LJ", berufsschule="BS1", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST,
    )
    session.add(klasse)
    session.flush()

    # Ausbildungsbeginn im Monat >= 8 -> global_start_year == 2025 ==
    # schoolyear.start_year -> klasse_fuer liefert direkt trainee.klasse_id
    # (steps == 0), ohne next_class_for-Verkettung.
    t = Trainee(
        vorname="Jonas", nachname="Jaeger", rolle=TraineeRolle.AZUBI, aktiv=True,
        klasse_id=klasse.id, ausbildungsbeginn=date(2025, 9, 1),
    )
    session.add(t)
    session.flush()

    plan = SchoolPlan(klasse_id=klasse.id, schoolyear_id=SY)
    session.add(plan)
    session.flush()
    # Plan-Schulwoche OHNE eigenes Assignment (kw 10/2026)
    session.add(SchoolPlanWeek(plan_id=plan.id, kw=10, jahr=2026, typ=SchoolWeekTyp.BERUFSSCHULE))
    # Plan-Schulwoche, die ZUSAETZLICH ein Assignment hat (kw 8/2026) ->
    # darf nur einmal gezaehlt werden.
    session.add(SchoolPlanWeek(plan_id=plan.id, kw=8, jahr=2026, typ=SchoolWeekTyp.BERUFSSCHULE))
    session.commit()
    session.refresh(t)

    _make_assignment(session, t.id, 8, 2026, AssignmentTyp.BERUFSSCHULE)
    _make_assignment(session, t.id, 5, 2026, AssignmentTyp.URLAUB)
    # ausserhalb des abgefragten Bereichs -- darf NICHT mitgezaehlt werden
    _make_assignment(session, t.id, 20, 2026, AssignmentTyp.URLAUB)

    result = fehlzeiten_vorbelegung(
        session, t.id, SY, kw_von=1, jahr_von=2026, kw_bis=15, jahr_bis=2026,
    )

    assert result == {"urlaub": 1, "schule": 2}


def test_fehlzeiten_vorbelegung_bereichsgrenzen_inklusive(session):
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    t = Trainee(vorname="Anna", nachname="Azubi", rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.commit()
    session.refresh(t)

    _make_assignment(session, t.id, 10, 2026, AssignmentTyp.URLAUB)  # genau kw_von
    _make_assignment(session, t.id, 12, 2026, AssignmentTyp.URLAUB)  # genau kw_bis
    _make_assignment(session, t.id, 9, 2026, AssignmentTyp.URLAUB)   # davor -> nicht zaehlen
    _make_assignment(session, t.id, 13, 2026, AssignmentTyp.URLAUB)  # danach -> nicht zaehlen

    result = fehlzeiten_vorbelegung(
        session, t.id, SY, kw_von=10, jahr_von=2026, kw_bis=12, jahr_bis=2026,
    )

    assert result == {"urlaub": 2, "schule": 0}


# ── trainee_bloecke ────────────────────────────────────────────────────────

def test_trainee_bloecke_zwei_abteilungen_luecke_und_jahreswechsel(session):
    # Schuljahr, das den Jahreswechsel abdeckt
    session.add(Schoolyear(id=SY, start_kw=48, start_year=2025, end_kw=10, end_year=2026))
    dept_a = Department(code="CP", name="Cloud Platform")
    dept_b = Department(code="NW", name="Netzwerk")
    session.add_all([dept_a, dept_b])
    session.flush()
    t = Trainee(vorname="Jonas", nachname="Jaeger", rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.commit()
    session.refresh(t)
    session.refresh(dept_a)
    session.refresh(dept_b)

    # Block 1: dept_a, KW 49-50/2025
    _make_assignment(session, t.id, 49, 2025, AssignmentTyp.ABTEILUNG, dept_a.id)
    _make_assignment(session, t.id, 50, 2025, AssignmentTyp.ABTEILUNG, dept_a.id)
    # Luecke: KW 51/2025 fehlt -> trennt Block 1 von Block 2
    # Block 2: dept_a, KW 52/2025 -> KW 1/2026 (Jahreswechsel, EIN Block)
    _make_assignment(session, t.id, 52, 2025, AssignmentTyp.ABTEILUNG, dept_a.id)
    _make_assignment(session, t.id, 1, 2026, AssignmentTyp.ABTEILUNG, dept_a.id)
    # Block 3: dept_b, KW 5/2026 (weitere Luecke davor)
    _make_assignment(session, t.id, 5, 2026, AssignmentTyp.ABTEILUNG, dept_b.id)

    bloecke = trainee_bloecke(session, t.id, SY)

    assert len(bloecke) == 3

    assert bloecke[0]["department"].id == dept_a.id
    assert bloecke[0]["kw_von"] == 49 and bloecke[0]["jahr_von"] == 2025
    assert bloecke[0]["kw_bis"] == 50 and bloecke[0]["jahr_bis"] == 2025

    assert bloecke[1]["department"].id == dept_a.id
    assert bloecke[1]["kw_von"] == 52 and bloecke[1]["jahr_von"] == 2025
    assert bloecke[1]["kw_bis"] == 1 and bloecke[1]["jahr_bis"] == 2026

    assert bloecke[2]["department"].id == dept_b.id
    assert bloecke[2]["kw_von"] == 5 and bloecke[2]["jahr_von"] == 2026
    assert bloecke[2]["kw_bis"] == 5 and bloecke[2]["jahr_bis"] == 2026


def test_trainee_bloecke_unbekanntes_schuljahr_liefert_leere_liste(session):
    assert trainee_bloecke(session, 1, "does-not-exist") == []


# ── partner_bogen ──────────────────────────────────────────────────────────

def _make_bogen(session, typ, trainee_id, dept_id, kw_von, jahr_von, kw_bis, jahr_bis):
    b = FeedbackBogen(
        typ=typ, trainee_id=trainee_id, department_id=dept_id, schoolyear_id=SY,
        kw_von=kw_von, jahr_von=jahr_von, kw_bis=kw_bis, jahr_bis=jahr_bis,
    )
    session.add(b)
    session.commit()
    session.refresh(b)
    return b


def _setup_trainee_dept(session):
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    dept = Department(code="CP", name="Cloud Platform")
    session.add(dept)
    session.flush()
    t = Trainee(vorname="Jonas", nachname="Jaeger", rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.commit()
    session.refresh(t)
    session.refresh(dept)
    return t, dept


def test_partner_bogen_ueberlappung_gefunden(session):
    t, dept = _setup_trainee_dept(session)
    ausbilder_bogen = _make_bogen(session, "AUSBILDER", t.id, dept.id, 10, 2026, 14, 2026)
    azubi_bogen = _make_bogen(session, "AZUBI", t.id, dept.id, 12, 2026, 16, 2026)

    found = partner_bogen(session, ausbilder_bogen)
    assert found is not None
    assert found.id == azubi_bogen.id

    # Symmetrisch auch andersherum
    found2 = partner_bogen(session, azubi_bogen)
    assert found2 is not None
    assert found2.id == ausbilder_bogen.id


def test_partner_bogen_keine_ueberlappung_gibt_none(session):
    t, dept = _setup_trainee_dept(session)
    ausbilder_bogen = _make_bogen(session, "AUSBILDER", t.id, dept.id, 10, 2026, 14, 2026)
    _make_bogen(session, "AZUBI", t.id, dept.id, 20, 2026, 24, 2026)

    assert partner_bogen(session, ausbilder_bogen) is None


def test_partner_bogen_ohne_partner_gibt_none(session):
    t, dept = _setup_trainee_dept(session)
    ausbilder_bogen = _make_bogen(session, "AUSBILDER", t.id, dept.id, 10, 2026, 14, 2026)

    assert partner_bogen(session, ausbilder_bogen) is None


# ── bogen_fuer_block ───────────────────────────────────────────────────────

def test_bogen_fuer_block_ueberlappender_bogen_gefunden(session):
    t, dept = _setup_trainee_dept(session)
    bogen = _make_bogen(session, "AUSBILDER", t.id, dept.id, 10, 2026, 14, 2026)

    found = bogen_fuer_block(
        session, "AUSBILDER", t.id, dept.id, SY,
        kw_von=12, jahr_von=2026, kw_bis=16, jahr_bis=2026,
    )
    assert found is not None
    assert found.id == bogen.id


def test_bogen_fuer_block_keine_ueberlappung_gibt_none(session):
    t, dept = _setup_trainee_dept(session)
    _make_bogen(session, "AUSBILDER", t.id, dept.id, 10, 2026, 14, 2026)

    found = bogen_fuer_block(
        session, "AUSBILDER", t.id, dept.id, SY,
        kw_von=20, jahr_von=2026, kw_bis=24, jahr_bis=2026,
    )
    assert found is None


def test_bogen_fuer_block_anderer_typ_wird_ignoriert(session):
    t, dept = _setup_trainee_dept(session)
    _make_bogen(session, "AZUBI", t.id, dept.id, 10, 2026, 14, 2026)

    found = bogen_fuer_block(
        session, "AUSBILDER", t.id, dept.id, SY,
        kw_von=10, jahr_von=2026, kw_bis=14, jahr_bis=2026,
    )
    assert found is None
