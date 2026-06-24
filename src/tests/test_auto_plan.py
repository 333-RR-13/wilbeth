"""Tests fuer app/services/auto_plan.py und die zugehoerigen Router-Endpunkte.

Abgedeckte Faelle:
  (a) Freie Wochen werden gefuellt, bestehende nicht ueberschrieben
  (b) Bloecke der Laenge N und Round-Robin ueber Prioritaeten
  (c) Doppelbelegung wird bei erlaubt_mehrfachbelegung=False vermieden
  (d) Azubi ohne Wuensche wird uebersprungen
  (e) Vorschau schreibt nichts, Apply schreibt source=AUTO
"""

from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    DepartmentKategorie,
    Schoolyear,
    Trainee,
    TraineeRolle,
    TraineeWish,
)
from app.services.auto_plan import apply_auto_plan, plan_assignments

# ── KW-Bereich fuer Tests: KW1-KW8/2026 (8 Wochen, ueberschaubar) ────────────
YEAR_ID = "2025-2026-test"
START_KW = 1
START_YEAR = 2026
END_KW = 8
END_YEAR = 2026


# ── Fixture-Helfer ────────────────────────────────────────────────────────────

def _make_year(session: Session) -> Schoolyear:
    y = Schoolyear(
        id=YEAR_ID,
        start_kw=START_KW,
        start_year=START_YEAR,
        end_kw=END_KW,
        end_year=END_YEAR,
    )
    session.add(y)
    session.flush()
    return y


def _make_trainee(session: Session, name: str = "Testee") -> Trainee:
    t = Trainee(vorname=name, nachname="Test", rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.flush()
    return t


def _make_dept(
    session: Session,
    code: str,
    multi: bool = False,
) -> Department:
    d = Department(
        code=code,
        name=f"Abt {code}",
        kategorie=DepartmentKategorie.ITO,
        erlaubt_mehrfachbelegung=multi,
    )
    session.add(d)
    session.flush()
    return d


def _add_wish(
    session: Session,
    trainee_id: int,
    dept_id: int,
    prio: int = 2,
) -> TraineeWish:
    w = TraineeWish(trainee_id=trainee_id, department_id=dept_id, prioritaet=prio)
    session.add(w)
    session.flush()
    return w


def _add_assignment(
    session: Session,
    trainee_id: int,
    kw: int,
    typ: AssignmentTyp = AssignmentTyp.ABTEILUNG,
    dept_id: int | None = None,
    source: AssignmentSource = AssignmentSource.MANUAL,
) -> Assignment:
    a = Assignment(
        trainee_id=trainee_id,
        schoolyear_id=YEAR_ID,
        kw=kw,
        jahr=START_YEAR,
        typ=typ,
        abteilung_id=dept_id,
        source=source,
    )
    session.add(a)
    session.flush()
    return a


# ── (a) Freie Wochen werden gefuellt, bestehende nicht ueberschrieben ─────────

def test_fills_free_weeks(session: Session):
    """Alle freien Wochen erhalten einen Einsatz."""
    _make_year(session)
    t = _make_trainee(session)
    d = _make_dept(session, "AA")
    _add_wish(session, t.id, d.id)

    result = plan_assignments(session, YEAR_ID, [t.id], block_length=4)

    assert len(result.planned) == 8  # alle 8 Wochen (KW1-KW8)
    assert all(e.trainee_id == t.id for e in result.planned)
    assert all(e.abteilung_id == d.id for e in result.planned)


def test_does_not_overwrite_existing_assignment(session: Session):
    """Wochen mit bestehendem Einsatz werden nicht neu verplant."""
    _make_year(session)
    t = _make_trainee(session)
    d = _make_dept(session, "AA")
    _add_wish(session, t.id, d.id)

    # KW1 und KW2 schon belegt (z. B. Berufsschule)
    _add_assignment(session, t.id, kw=1, typ=AssignmentTyp.BERUFSSCHULE)
    _add_assignment(session, t.id, kw=2, typ=AssignmentTyp.BERUFSSCHULE)

    result = plan_assignments(session, YEAR_ID, [t.id], block_length=4)

    planned_kws = {e.kw for e in result.planned}
    assert 1 not in planned_kws
    assert 2 not in planned_kws
    # Die restlichen 6 Wochen (KW3-KW8) sollen geplant worden sein
    assert len(result.planned) == 6


def test_idempotent_multiple_runs(session: Session):
    """Mehrfaches Berechnen mit denselben Parametern ist sicher (kein Ueberschreiben)."""
    _make_year(session)
    t = _make_trainee(session)
    d = _make_dept(session, "BB")
    _add_wish(session, t.id, d.id)

    # Erster Lauf: 8 geplante Wochen
    r1 = plan_assignments(session, YEAR_ID, [t.id])
    assert len(r1.planned) == 8

    # Simuliere: Einsaetze werden geschrieben
    for e in r1.planned:
        _add_assignment(session, t.id, kw=e.kw, typ=AssignmentTyp.ABTEILUNG, dept_id=e.abteilung_id, source=AssignmentSource.AUTO)

    # Zweiter Lauf: alles schon belegt -> nichts mehr geplant
    r2 = plan_assignments(session, YEAR_ID, [t.id])
    assert len(r2.planned) == 0


# ── (b) Bloecke der Laenge N und Round-Robin ──────────────────────────────────

def test_block_length_respected(session: Session):
    """Einsaetze werden in Bloecken der angegebenen Laenge zugewiesen."""
    _make_year(session)
    t = _make_trainee(session)
    d1 = _make_dept(session, "X1")
    d2 = _make_dept(session, "X2")
    _add_wish(session, t.id, d1.id, prio=1)
    _add_wish(session, t.id, d2.id, prio=2)

    result = plan_assignments(session, YEAR_ID, [t.id], block_length=4)

    # KW1-KW4: d1 (Block 1), KW5-KW8: d2 (Block 2)
    assert len(result.planned) == 8
    block1 = [e for e in result.planned if e.kw in range(1, 5)]
    block2 = [e for e in result.planned if e.kw in range(5, 9)]
    assert all(e.abteilung_id == d1.id for e in block1)
    assert all(e.abteilung_id == d2.id for e in block2)


def test_round_robin_restarts(session: Session):
    """Nach dem letzten Kandidaten startet Round-Robin von vorn."""
    _make_year(session)
    t = _make_trainee(session)
    d1 = _make_dept(session, "R1", multi=True)  # multi=True damit kein Doppelbelegugs-Stopp
    _add_wish(session, t.id, d1.id, prio=1)

    # Nur eine Abteilung -> alle Wochen bekommen d1 (Round-Robin dreht durch)
    result = plan_assignments(session, YEAR_ID, [t.id], block_length=2)
    assert len(result.planned) == 8
    assert all(e.abteilung_id == d1.id for e in result.planned)


def test_round_robin_two_depts_block2(session: Session):
    """Zwei Abteilungen, Block 2: abwechselnd d1/d2/d1/d2."""
    _make_year(session)
    t = _make_trainee(session)
    d1 = _make_dept(session, "P1", multi=True)
    d2 = _make_dept(session, "P2", multi=True)
    _add_wish(session, t.id, d1.id, prio=1)
    _add_wish(session, t.id, d2.id, prio=2)

    result = plan_assignments(session, YEAR_ID, [t.id], block_length=2)
    assert len(result.planned) == 8

    dept_sequence = [e.abteilung_id for e in sorted(result.planned, key=lambda e: e.kw)]
    # KW1-2: d1, KW3-4: d2, KW5-6: d1, KW7-8: d2
    assert dept_sequence == [d1.id, d1.id, d2.id, d2.id, d1.id, d1.id, d2.id, d2.id]


# ── (c) Doppelbelegung vermeiden ──────────────────────────────────────────────

def test_avoids_double_booking_existing(session: Session):
    """Abteilung mit erlaubt_mehrfachbelegung=False wird nicht doppelt belegt (bestehend)."""
    _make_year(session)
    t1 = _make_trainee(session, "Eins")
    t2 = _make_trainee(session, "Zwei")
    d = _make_dept(session, "SINGLE", multi=False)

    # t1 ist in KW1-KW4 bereits in d eingeplant
    for kw in range(1, 5):
        _add_assignment(session, t1.id, kw=kw, typ=AssignmentTyp.ABTEILUNG, dept_id=d.id)

    _add_wish(session, t2.id, d.id, prio=1)

    result = plan_assignments(session, YEAR_ID, [t2.id], block_length=4)

    # KW1-4 sollen NICHT fuer t2 in d geplant sein
    planned_kws = {e.kw for e in result.planned if e.trainee_id == t2.id}
    for kw in range(1, 5):
        assert kw not in planned_kws, f"KW {kw} darf nicht doppelt belegt sein"


def test_avoids_double_booking_within_run(session: Session):
    """Zwei Azubis im selben Lauf teilen sich keine nicht-multiple Abteilung in derselben KW."""
    _make_year(session)
    t1 = _make_trainee(session, "AlphaA")
    t2 = _make_trainee(session, "BetaB")
    d = _make_dept(session, "SOLO", multi=False)

    _add_wish(session, t1.id, d.id, prio=1)
    _add_wish(session, t2.id, d.id, prio=1)

    result = plan_assignments(session, YEAR_ID, [t1.id, t2.id], block_length=1)

    # Fuer jede (kw, jahr) darf maximal einer der beiden Azubis d belegen
    kw_to_trainees: dict[int, list[int]] = {}
    for e in result.planned:
        if e.abteilung_id == d.id:
            kw_to_trainees.setdefault(e.kw, []).append(e.trainee_id)

    for kw, tids in kw_to_trainees.items():
        assert len(tids) == 1, (
            f"KW {kw}: Doppelbelegung in SOLO-Abteilung durch {tids}"
        )


def test_multi_dept_allows_double_booking(session: Session):
    """Abteilung mit erlaubt_mehrfachbelegung=True kann mehrfach pro KW belegt werden."""
    _make_year(session)
    t1 = _make_trainee(session, "Multi1")
    t2 = _make_trainee(session, "Multi2")
    d = _make_dept(session, "MULTI", multi=True)

    _add_wish(session, t1.id, d.id, prio=1)
    _add_wish(session, t2.id, d.id, prio=1)

    result = plan_assignments(session, YEAR_ID, [t1.id, t2.id], block_length=8)

    # Beide Azubis sollen in d geplant sein, auch in denselben Wochen
    t1_kws = {e.kw for e in result.planned if e.trainee_id == t1.id}
    t2_kws = {e.kw for e in result.planned if e.trainee_id == t2.id}
    assert t1_kws, "t1 hat keine Eintraege"
    assert t2_kws, "t2 hat keine Eintraege"
    # Mindestens eine KW-Ueberschneidung muss erlaubt sein
    assert t1_kws & t2_kws, "Keine gemeinsamen KWs in Multi-Abteilung"


# ── (d) Azubi ohne Wuensche wird uebersprungen ────────────────────────────────

def test_trainee_without_wishes_skipped(session: Session):
    """Azubi ohne TraineeWish-Eintraege landet in der Uebersprungen-Liste."""
    _make_year(session)
    t = _make_trainee(session, "NoWish")
    # Keine Wuensche anlegen

    result = plan_assignments(session, YEAR_ID, [t.id])

    assert len(result.planned) == 0
    assert len(result.skipped) == 1
    assert result.skipped[0].trainee_id == t.id
    assert result.skipped[0].kw is None  # ganzer Azubi, nicht einzelne Woche
    assert "Wüns" in result.skipped[0].reason


def test_mix_with_and_without_wishes(session: Session):
    """Azubi mit Wuenschen wird geplant, ohne Wuensche uebersprungen."""
    _make_year(session)
    t_with = _make_trainee(session, "With")
    t_without = _make_trainee(session, "Without")
    d = _make_dept(session, "MIX")
    _add_wish(session, t_with.id, d.id)

    result = plan_assignments(session, YEAR_ID, [t_with.id, t_without.id])

    assert any(e.trainee_id == t_with.id for e in result.planned)
    assert not any(e.trainee_id == t_without.id for e in result.planned)
    assert any(s.trainee_id == t_without.id for s in result.skipped)


# ── (e) Vorschau schreibt nichts, Apply schreibt source=AUTO ─────────────────

def test_preview_does_not_write_to_db(session: Session):
    """plan_assignments() schreibt keine Datensaetze in die DB."""
    _make_year(session)
    t = _make_trainee(session)
    d = _make_dept(session, "PV")
    _add_wish(session, t.id, d.id)

    before = session.exec(select(Assignment)).all()
    result = plan_assignments(session, YEAR_ID, [t.id])
    after = session.exec(select(Assignment)).all()

    assert len(result.planned) > 0, "Sollte etwas planen"
    assert len(before) == len(after), "plan_assignments darf nichts in die DB schreiben"


def test_apply_writes_source_auto(session: Session):
    """apply_auto_plan() schreibt Assignments mit source=AUTO in die DB."""
    _make_year(session)
    t = _make_trainee(session)
    d = _make_dept(session, "AP")
    _add_wish(session, t.id, d.id)

    result = apply_auto_plan(session, YEAR_ID, [t.id])

    assert len(result.planned) > 0
    db_assignments = session.exec(
        select(Assignment).where(Assignment.trainee_id == t.id)
    ).all()
    assert len(db_assignments) == len(result.planned)
    assert all(a.source == AssignmentSource.AUTO for a in db_assignments)
    assert all(a.typ == AssignmentTyp.ABTEILUNG for a in db_assignments)


def test_apply_idempotent(session: Session):
    """Zweimaliges apply_auto_plan() erzeugt keine Duplikate (unique constraint)."""
    _make_year(session)
    t = _make_trainee(session)
    d = _make_dept(session, "IDEM", multi=True)
    _add_wish(session, t.id, d.id)

    r1 = apply_auto_plan(session, YEAR_ID, [t.id])
    n_after_first = len(session.exec(select(Assignment).where(Assignment.trainee_id == t.id)).all())

    # Zweiter Lauf: bestehende Wochen sind jetzt belegt -> nichts mehr eingefuegt
    r2 = apply_auto_plan(session, YEAR_ID, [t.id])
    n_after_second = len(session.exec(select(Assignment).where(Assignment.trainee_id == t.id)).all())

    assert r2.planned == [], "Zweiter Lauf sollte nichts planen (alles belegt)"
    assert n_after_first == n_after_second, "Keine neuen Rows im zweiten Durchlauf"


# ── Router-Integrationstests ──────────────────────────────────────────────────

def test_preview_endpoint_returns_html(client, session: Session):
    """POST /auto-plan/preview liefert HTML-Partial, kein DB-Write."""
    _make_year(session)
    t = _make_trainee(session, "PreviewTest")
    d = _make_dept(session, "PRV")
    _add_wish(session, t.id, d.id)
    session.commit()

    before = session.exec(select(Assignment)).all()
    response = client.post(
        "/auto-plan/preview",
        data={
            "schoolyear_id": YEAR_ID,
            "block_length": "4",
            "trainee_ids": str(t.id),
        },
    )
    after = session.exec(select(Assignment)).all()

    assert response.status_code == 200
    assert "Vorschau" in response.text or "Geplante" in response.text or "PRV" in response.text
    assert len(before) == len(after), "Preview darf keine DB-Aenderungen vornehmen"


def test_apply_endpoint_redirects_and_writes(client, session: Session):
    """POST /auto-plan/apply schreibt Einsaetze und leitet weiter."""
    _make_year(session)
    t = _make_trainee(session, "ApplyTest")
    d = _make_dept(session, "APL")
    _add_wish(session, t.id, d.id)
    session.commit()

    response = client.post(
        "/auto-plan/apply",
        data={
            "schoolyear_id": YEAR_ID,
            "block_length": "4",
            "trainee_ids": str(t.id),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "/auto-plan" in response.headers.get("location", "")

    # DB-Einsaetze wurden angelegt
    db_rows = session.exec(
        select(Assignment).where(
            Assignment.trainee_id == t.id,
            Assignment.source == AssignmentSource.AUTO,
        )
    ).all()
    assert len(db_rows) > 0


def test_apply_endpoint_no_trainee_ids(client, session: Session):
    """Leerer trainee_ids-Parameter fuehrt zu leerem Plan und Redirect."""
    _make_year(session)
    session.commit()

    response = client.post(
        "/auto-plan/apply",
        data={"schoolyear_id": YEAR_ID, "block_length": "4"},
        follow_redirects=False,
    )

    assert response.status_code == 303
