"""Tests fuer die Azubi-Seite /mein-plan/{token}/abwesenheit sowie die
Abwesenheits-Markierung in den share-Matrizen (Overlay-Modell, siehe
app.services.abwesenheit_utils und die Fachspezifikation im Aufgabentext)."""
from datetime import date

from sqlmodel import Session, select

from app.models import (
    Abwesenheit,
    AbwesenheitQuelle,
    AbwesenheitTyp,
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    Schoolyear,
    Trainee,
    TraineeRolle,
)

SY = "2025-2026"
TOKEN = "test-token-abwesenheit"


def _setup(session: Session, token: str = TOKEN, vorname: str = "Anton", nachname: str = "Altmann") -> dict:
    if session.get(Schoolyear, SY) is None:
        session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    cp = Department(code="CP", name="Cloud Platform")
    session.add(cp)
    session.flush()

    t = Trainee(vorname=vorname, nachname=nachname, rolle=TraineeRolle.AZUBI, share_token=token)
    session.add(t)
    session.flush()
    session.commit()
    return {"trainee": t.id, "cp": cp.id}


# ── (a) Anlegen ueber mehrere Wochen ────────────────────────────────────────

def test_anlegen_ueber_mehrere_wochen(client, session):
    ids = _setup(session)
    # KW50/2025 (Mo 2025-12-08) bis KW52/2025 (Fr 2025-12-26) -- drei Wochen
    r = client.post(f"/mein-plan/{TOKEN}/abwesenheit",
                     data={"von": "2025-12-08", "bis": "2025-12-26", "typ": "URLAUB",
                           "kommentar": "Weihnachtsurlaub"},
                     follow_redirects=False)
    assert r.status_code == 303

    rows = session.exec(select(Abwesenheit).where(Abwesenheit.trainee_id == ids["trainee"])).all()
    assert len(rows) == 1
    assert rows[0].von_datum == date(2025, 12, 8)
    assert rows[0].bis_datum == date(2025, 12, 26)
    assert rows[0].kommentar == "Weihnachtsurlaub"

    page = client.get(f"/mein-plan/{TOKEN}/abwesenheit")
    assert page.status_code == 200
    assert "08.12.2025" in page.text
    assert "26.12.2025" in page.text


# ── (b) bis < von -> 400 ─────────────────────────────────────────────────

def test_bis_vor_von_ergibt_400(client, session):
    _setup(session)
    r = client.post(f"/mein-plan/{TOKEN}/abwesenheit",
                     data={"von": "2026-01-10", "bis": "2026-01-05"},
                     follow_redirects=False)
    assert r.status_code == 400


def test_kaputtes_datum_ergibt_400_nicht_500(client, session):
    _setup(session)
    r = client.post(f"/mein-plan/{TOKEN}/abwesenheit",
                     data={"von": "nicht-datum", "bis": "2026-01-05"},
                     follow_redirects=False)
    assert r.status_code == 400


# ── (c) Fremde Abwesenheit loeschen -> 404 ──────────────────────────────────

def test_fremde_abwesenheit_loeschen_ergibt_404(client, session):
    ids_a = _setup(session, token=TOKEN, vorname="Anton", nachname="Altmann")
    trainee_b = Trainee(vorname="Berta", nachname="Buehler", rolle=TraineeRolle.AZUBI,
                        share_token="test-token-abwesenheit-b")
    session.add(trainee_b)
    session.commit()

    a = Abwesenheit(trainee_id=ids_a["trainee"], von_datum=date(2026, 1, 5), bis_datum=date(2026, 1, 7),
                    typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.SELBST)
    session.add(a)
    session.commit()
    aid = a.id

    # Trainee B versucht, die Abwesenheit von Trainee A ueber den eigenen Token zu loeschen
    r = client.post(f"/mein-plan/test-token-abwesenheit-b/abwesenheit/{aid}/loeschen", follow_redirects=False)
    assert r.status_code == 404
    assert session.get(Abwesenheit, aid) is not None


# ── (d) Vom Planer eingetragene Abwesenheit ist sichtbar, aber nicht loeschbar ──

def test_planer_abwesenheit_sichtbar_aber_nicht_loeschbar(client, session):
    ids = _setup(session)
    a = Abwesenheit(trainee_id=ids["trainee"], von_datum=date(2026, 2, 2), bis_datum=date(2026, 2, 4),
                    typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.PLANER,
                    erstellt_von_upn="planerin@firma.de")
    session.add(a)
    session.commit()
    aid = a.id

    page = client.get(f"/mein-plan/{TOKEN}/abwesenheit")
    assert page.status_code == 200
    assert "02.02.2026" in page.text
    assert "Planer" in page.text
    # Keine Loeschen-Aktion fuer diesen Eintrag im Markup
    assert f"/mein-plan/{TOKEN}/abwesenheit/{aid}/loeschen" not in page.text

    r = client.post(f"/mein-plan/{TOKEN}/abwesenheit/{aid}/loeschen", follow_redirects=False)
    assert r.status_code == 404
    assert session.get(Abwesenheit, aid) is not None


# ── (e) Matrix-Zelle: mc-abwesend + Abteilungs-Tooltip bleibt erhalten ──────

def test_matrix_zelle_traegt_mc_abwesend_und_dept_tooltip(client, session):
    ids = _setup(session)
    # KW40/2025: Mo 2025-09-29 .. Fr 2025-10-03 -- Abteilungseinsatz die ganze Woche
    session.add(Assignment(trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
                           source=AssignmentSource.MANUAL))
    session.commit()

    # Ueberlagernde Abwesenheit Mo-Mi derselben Woche (blockt den Einsatz NICHT)
    client.post(f"/mein-plan/{TOKEN}/abwesenheit",
                data={"von": "2025-09-29", "bis": "2025-10-01"}, follow_redirects=False)

    r = client.get(f"/mein-plan/{TOKEN}")
    assert r.status_code == 200
    assert 'class="matrix-cell mc-abwesend"' in r.text
    assert "mc-abwesend-voll" not in r.text  # nur Teilwoche (Mo-Mi)
    assert 'title="Cloud Platform — Urlaub Mo-Mi (3 Tage)"' in r.text
    # Der Abteilungseinsatz bleibt bestehen (Chip weiterhin sichtbar)
    assert ">CP<" in r.text


# ── (f) ICS enthaelt den Abwesenheits-Termin mit exklusivem DTEND ───────────

def test_ics_enthaelt_abwesenheit_mit_exklusivem_dtend(client, session):
    ids = _setup(session)
    session.add(Abwesenheit(trainee_id=ids["trainee"], von_datum=date(2026, 3, 2), bis_datum=date(2026, 3, 4),
                            typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.SELBST))
    session.commit()

    r = client.get(f"/mein-plan/{TOKEN}/calendar.ics")
    assert r.status_code == 200
    body = r.text
    assert "SUMMARY:Urlaub" in body
    assert "DTSTART;VALUE=DATE:20260302" in body
    # bis_datum (04.03.) + 1 Tag (exklusiv) = 05.03.
    assert "DTEND;VALUE=DATE:20260305" in body


def test_ics_abwesenheit_sonstiges_summary(client, session):
    ids = _setup(session)
    session.add(Abwesenheit(trainee_id=ids["trainee"], von_datum=date(2026, 4, 6), bis_datum=date(2026, 4, 6),
                            typ=AbwesenheitTyp.SONSTIGES, quelle=AbwesenheitQuelle.SELBST))
    session.commit()

    r = client.get(f"/mein-plan/{TOKEN}/calendar.ics")
    assert r.status_code == 200
    assert "SUMMARY:Abwesend" in r.text
    assert "DTSTART;VALUE=DATE:20260406" in r.text
    assert "DTEND;VALUE=DATE:20260407" in r.text


# ── (g) Befund 3: Plausibilitaetsgrenze statt 500er / Dauer-Abwesenheit ─────

def test_riesiger_zeitraum_ergibt_400_nicht_500(client, session):
    """Ohne die Plausibilitaetsgrenze laeuft von=0001-01-01/bis=9999-12-31 in
    die tageweise Schulwochen-Pruefung: bis_datum ist exakt date.max, das
    Inkrementieren am letzten Schleifendurchlauf (d += timedelta(days=1))
    wirft dort OverflowError -> HTTP 500, obwohl der Docstring 'nie einen
    500er' zusichert. Erwartet wird stattdessen ein sauberer 400er."""
    _setup(session)
    r = client.post(f"/mein-plan/{TOKEN}/abwesenheit",
                     data={"von": "0001-01-01", "bis": "9999-12-31"},
                     follow_redirects=False)
    assert r.status_code == 400
    assert session.exec(select(Abwesenheit)).first() is None


def test_zeitraum_ueber_ein_jahr_ergibt_400(client, session):
    """Auch ein 'nur' rund 200 Jahre langer Zeitraum (1900..2100) darf nicht
    kommentarlos akzeptiert werden: der Trainee waere sonst in JEDER Woche
    als voll abwesend markiert (Auto-Plan uebersprungen dauerhaft)."""
    _setup(session)
    r = client.post(f"/mein-plan/{TOKEN}/abwesenheit",
                     data={"von": "1900-01-01", "bis": "2100-12-31"},
                     follow_redirects=False)
    assert r.status_code == 400
    assert session.exec(select(Abwesenheit)).first() is None


def test_zeitraum_366_tage_wird_noch_akzeptiert(client, session):
    """Grenzfall: genau 366 Tage (Schaltjahr-Schuljahr) bleibt weiterhin ok."""
    ids = _setup(session)
    r = client.post(f"/mein-plan/{TOKEN}/abwesenheit",
                     data={"von": "2026-01-01", "bis": "2027-01-01"},
                     follow_redirects=False)
    assert r.status_code == 303
    rows = session.exec(select(Abwesenheit).where(Abwesenheit.trainee_id == ids["trainee"])).all()
    assert len(rows) == 1


# ── (h) Befund 12: fremde Abwesenheit nur generisch, eigene detailliert ─────

def test_uebersicht_zeigt_fremde_abwesenheit_nur_generisch(client, session):
    """Datenschutz: In der Gesamtuebersicht (week_matrix_group.html) duerfen
    fremde Zeilen nur den generischen Hinweis 'Abwesend' zeigen -- Typ und
    Tagesgenauigkeit (z. B. 'Sonstiges Mo-Mi (3 Tage)') bleiben der eigenen
    Zeile vorbehalten. Der Abteilungs-Tooltip (hier keiner gesetzt) bliebe
    davon unberuehrt."""
    ids = _setup(session)
    other = Trainee(vorname="Berta", nachname="Buehler", rolle=TraineeRolle.AZUBI, share_token="tok-berta-b")
    session.add(other)
    session.commit()
    session.refresh(other)

    # Fremde Abwesenheit: Mo-Mi derselben KW40/2025 -- SONSTIGES
    session.add(Abwesenheit(trainee_id=other.id, von_datum=date(2025, 9, 29), bis_datum=date(2025, 10, 1),
                            typ=AbwesenheitTyp.SONSTIGES, quelle=AbwesenheitQuelle.PLANER))
    # Eigene Abwesenheit: dieselbe Woche, URLAUB
    session.add(Abwesenheit(trainee_id=ids["trainee"], von_datum=date(2025, 9, 29), bis_datum=date(2025, 10, 1),
                            typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.SELBST))
    session.commit()

    r = client.get(f"/mein-plan/{TOKEN}/uebersicht", params={"schoolyear_id": SY})
    assert r.status_code == 200
    # Eigene Zeile: volle Details
    assert 'title="Urlaub Mo-Mi (3 Tage)"' in r.text
    # Fremde Zeile: nur der generische Hinweis, keine Typ-/Tagesangabe
    assert 'title="Abwesend"' in r.text
    assert "Sonstiges Mo-Mi" not in r.text
    assert 'title="Sonstiges Mo-Mi (3 Tage)"' not in r.text
