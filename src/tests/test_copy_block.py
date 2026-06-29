"""Tests für POST /einsaetze/copy-block (Block-Auswahl Kopieren in der Matrix)."""
from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    Schoolyear,
    Trainee,
    TraineeRolle,
)

# Lehrjahr mit Jahreswechsel: KW36/2025 – KW35/2026
SY = "2025-2026"


def _setup(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    abt1 = Department(code="AI", name="Artificial Intelligence")
    abt2 = Department(code="HR", name="Human Resources")
    session.add(abt1)
    session.add(abt2)
    src_t = Trainee(vorname="Anna", nachname="Quelle", rolle=TraineeRolle.AZUBI)
    dst_t = Trainee(vorname="Ben",  nachname="Ziel",   rolle=TraineeRolle.AZUBI)
    session.add(src_t)
    session.add(dst_t)
    session.flush()
    session.commit()
    return {"src": src_t.id, "dst": dst_t.id, "abt1": abt1.id, "abt2": abt2.id}


def _post_block(client, ids, src_weeks: str, dst_kw: int, dst_jahr: int,
                src_trainee=None, dst_trainee=None):
    return client.post("/einsaetze/copy-block", data={
        "src_trainee_id": src_trainee or ids["src"],
        "src_weeks":      src_weeks,
        "dst_trainee_id": dst_trainee or ids["dst"],
        "dst_kw":         dst_kw,
        "dst_jahr":       dst_jahr,
        "schoolyear_id":  SY,
    })


# ── 3-Wochen-Block von A → B ─────────────────────────────────────────────────

def test_block_copy_three_weeks(client, session):
    """3-Wochen-Block von Azubi A → Azubi B ab Anker: 3 Ziel-Assignments mit
    typ+abteilung der Quelle, source=MANUAL."""
    ids = _setup(session)
    for kw in (8, 9, 10):
        session.add(Assignment(
            trainee_id=ids["src"], schoolyear_id=SY,
            kw=kw, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
            abteilung_id=ids["abt1"], source=AssignmentSource.AUTO,
        ))
    session.commit()

    r = _post_block(client, ids, "8:2026,9:2026,10:2026", dst_kw=12, dst_jahr=2026)
    assert r.status_code == 200

    dst_rows = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["dst"])
        .order_by(Assignment.kw)
    ).all()
    assert len(dst_rows) == 3
    assert [a.kw for a in dst_rows] == [12, 13, 14]
    for a in dst_rows:
        assert a.jahr == 2026
        assert a.typ == AssignmentTyp.ABTEILUNG
        assert a.abteilung_id == ids["abt1"]
        assert a.source == AssignmentSource.MANUAL


# ── Jahreswechsel ─────────────────────────────────────────────────────────────

def test_block_copy_across_year_boundary(client, session):
    """Block über KW52→KW1 wird korrekt fortlaufend abgelegt."""
    ids = _setup(session)
    # Quelle: KW51, KW52 (2025), KW1 (2026)
    for kw, jahr in ((51, 2025), (52, 2025), (1, 2026)):
        session.add(Assignment(
            trainee_id=ids["src"], schoolyear_id=SY,
            kw=kw, jahr=jahr, typ=AssignmentTyp.ABTEILUNG,
            abteilung_id=ids["abt1"], source=AssignmentSource.AUTO,
        ))
    session.commit()

    # Anker: KW52/2025 → Ziel-Zellen: KW52/2025, KW1/2026, KW2/2026
    r = _post_block(client, ids, "51:2025,52:2025,1:2026", dst_kw=52, dst_jahr=2025)
    assert r.status_code == 200

    dst_rows = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["dst"])
    ).all()
    assert len(dst_rows) == 3
    result = sorted(dst_rows, key=lambda a: (a.jahr, a.kw))
    assert (result[0].kw, result[0].jahr) == (52, 2025)
    assert (result[1].kw, result[1].jahr) == (1,  2026)
    assert (result[2].kw, result[2].jahr) == (2,  2026)


# ── Leere Quell-Zelle → Ziel bleibt unverändert ──────────────────────────────

def test_block_copy_empty_source_cell_skipped(client, session):
    """Leere Quell-Zelle im Block → entsprechendes Ziel bleibt unverändert."""
    ids = _setup(session)
    # Nur KW8 und KW10 belegt, KW9 leer
    session.add(Assignment(
        trainee_id=ids["src"], schoolyear_id=SY,
        kw=8, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
        abteilung_id=ids["abt1"], source=AssignmentSource.AUTO,
    ))
    session.add(Assignment(
        trainee_id=ids["src"], schoolyear_id=SY,
        kw=10, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
        abteilung_id=ids["abt2"], source=AssignmentSource.AUTO,
    ))
    session.commit()

    r = _post_block(client, ids, "8:2026,9:2026,10:2026", dst_kw=15, dst_jahr=2026)
    assert r.status_code == 200

    dst_rows = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["dst"])
        .order_by(Assignment.kw)
    ).all()
    # KW9 leer → KW16 am Ziel soll NICHT angelegt werden
    assert len(dst_rows) == 2
    assert dst_rows[0].kw == 15  # Offset 0 → src KW8
    assert dst_rows[0].abteilung_id == ids["abt1"]
    assert dst_rows[1].kw == 17  # Offset 2 → src KW10
    assert dst_rows[1].abteilung_id == ids["abt2"]


# ── Belegtes Ziel → überschreiben, kein Duplikat ─────────────────────────────

def test_block_copy_overwrites_occupied_target(client, session):
    """Belegtes Ziel-Assignment wird überschrieben – kein Duplikat."""
    ids = _setup(session)
    session.add(Assignment(
        trainee_id=ids["src"], schoolyear_id=SY,
        kw=8, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
        abteilung_id=ids["abt1"], source=AssignmentSource.AUTO,
    ))
    # Ziel bereits belegt
    session.add(Assignment(
        trainee_id=ids["dst"], schoolyear_id=SY,
        kw=12, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
        abteilung_id=ids["abt2"], source=AssignmentSource.AUTO,
    ))
    session.commit()

    r = _post_block(client, ids, "8:2026", dst_kw=12, dst_jahr=2026)
    assert r.status_code == 200

    dst_rows = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["dst"])
    ).all()
    assert len(dst_rows) == 1  # kein Duplikat
    assert dst_rows[0].abteilung_id == ids["abt1"]   # Wert aus Quelle
    assert dst_rows[0].source == AssignmentSource.MANUAL


# ── Block über Lehrjahr-Ende → überzählige übersprungen ──────────────────────

def test_block_copy_beyond_schoolyear_end_truncated(client, session):
    """Block über Lehrjahr-Ende hinaus → überzählige werden übersprungen, kein Crash."""
    ids = _setup(session)
    # Quelle: KW33, KW34, KW35, KW36 /2026 – aber Schuljahr endet KW35/2026
    for kw in (33, 34, 35, 36):
        session.add(Assignment(
            trainee_id=ids["src"], schoolyear_id=SY,
            kw=kw, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
            abteilung_id=ids["abt1"], source=AssignmentSource.AUTO,
        ))
    session.commit()

    # Anker KW33/2026 → Offsets 0,1,2 passen; Offset 3 (KW36) ist außerhalb
    r = _post_block(client, ids, "33:2026,34:2026,35:2026,36:2026",
                    dst_kw=33, dst_jahr=2026)
    assert r.status_code == 200

    dst_rows = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["dst"])
        .order_by(Assignment.kw)
    ).all()
    # Nur KW33, KW34, KW35 angelegt (KW36 außerhalb des Schuljahrs)
    assert len(dst_rows) == 3
    assert [a.kw for a in dst_rows] == [33, 34, 35]


# ── Antwort enthält OOB-Zell-ids + Konfliktzähler ────────────────────────────

def test_block_copy_response_contains_oob_cells_and_counter(client, session):
    """Antwort enthält die Ziel-Zell-ids mit hx-swap-oob + den Konfliktzähler."""
    ids = _setup(session)
    for kw in (8, 9):
        session.add(Assignment(
            trainee_id=ids["src"], schoolyear_id=SY,
            kw=kw, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
            abteilung_id=ids["abt1"], source=AssignmentSource.AUTO,
        ))
    session.commit()

    r = _post_block(client, ids, "8:2026,9:2026", dst_kw=20, dst_jahr=2026)
    assert r.status_code == 200

    # OOB-Attribute vorhanden
    assert 'hx-swap-oob="true"' in r.text

    # Ziel-Zell-ids (KW20, KW21) im Response
    assert f'id="cell-{ids["dst"]}-20-2026"' in r.text
    assert f'id="cell-{ids["dst"]}-21-2026"' in r.text

    # Konfliktzähler-Container
    assert 'id="conflict-counter"' in r.text

    # Abteilungs-Kürzel aus den kopierten Zellen
    assert "AI" in r.text


# ── src_weeks in beliebiger Reihenfolge → sortiert nach Schuljahr ────────────

def test_block_copy_src_weeks_unsorted(client, session):
    """src_weeks in beliebiger Reihenfolge werden korrekt nach Schuljahr sortiert."""
    ids = _setup(session)
    for kw in (8, 9, 10):
        session.add(Assignment(
            trainee_id=ids["src"], schoolyear_id=SY,
            kw=kw, jahr=2026, typ=AssignmentTyp.ABTEILUNG,
            abteilung_id=ids["abt1"], source=AssignmentSource.AUTO,
        ))
    session.commit()

    # Wochen in umgekehrter Reihenfolge übergeben
    r = _post_block(client, ids, "10:2026,8:2026,9:2026", dst_kw=20, dst_jahr=2026)
    assert r.status_code == 200

    dst_rows = session.exec(
        select(Assignment).where(Assignment.trainee_id == ids["dst"])
        .order_by(Assignment.kw)
    ).all()
    assert len(dst_rows) == 3
    assert [a.kw for a in dst_rows] == [20, 21, 22]
