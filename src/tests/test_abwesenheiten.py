"""Tests fuer /abwesenheiten/ (Staff-Seite, Overlay-Modell -- siehe
app/routers/abwesenheiten.py) sowie die Markierung in der Planer-Uebersicht
(overview.py + overview/matrix.html, UI-Vertrag siehe Aufgabenbeschreibung).

Rollen-Test-Muster: monkeypatch.setattr(settings, "auth_mode", "dev") +
POST /auth/dev-login (siehe tests/test_meine_abteilung.py). Ohne dev-mode
liefert conftest per AUTH_MODE=off einen synthetischen Admin (upn=test@local),
das reicht fuer alle orga/admin-Tests hier.
"""
from datetime import date

from sqlmodel import Session, select

from app.config import settings
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


def _dev_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "dev")


def _login(client, rolle: str):
    r = client.post("/auth/dev-login", data={"rolle": rolle}, follow_redirects=False)
    assert r.status_code == 303
    return r


def _make_trainee(session, vorname="Jonas", nachname="Jaeger") -> int:
    t = Trainee(vorname=vorname, nachname=nachname, rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.commit()
    session.refresh(t)
    return t.id


# ── (a) orga kann anlegen/aendern/loeschen ─────────────────────────────────

def test_orga_kann_abwesenheit_anlegen(client, session):
    t_id = _make_trainee(session)

    r = client.post("/abwesenheiten/", data={
        "trainee_id": t_id,
        "von_datum": "2026-03-02",
        "bis_datum": "2026-03-04",
        "typ": "URLAUB",
        "kommentar": "Familienurlaub",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/abwesenheiten/?msg=created")

    rows = session.exec(select(Abwesenheit)).all()
    assert len(rows) == 1
    a = rows[0]
    assert a.trainee_id == t_id
    assert a.von_datum == date(2026, 3, 2)
    assert a.bis_datum == date(2026, 3, 4)
    assert a.typ == AbwesenheitTyp.URLAUB
    assert a.quelle == AbwesenheitQuelle.PLANER
    assert a.erstellt_von_upn == "test@local"
    assert a.erstellt_am == date.today()
    assert a.kommentar == "Familienurlaub"


def test_orga_kann_abwesenheit_aendern(client, session):
    t_id = _make_trainee(session)
    a = Abwesenheit(
        trainee_id=t_id, von_datum=date(2026, 3, 2), bis_datum=date(2026, 3, 4),
        typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.PLANER,
    )
    session.add(a)
    session.commit()
    session.refresh(a)

    r = client.post(f"/abwesenheiten/{a.id}", data={
        "trainee_id": t_id,
        "von_datum": "2026-04-01",
        "bis_datum": "2026-04-03",
        "typ": "SONSTIGES",
        "kommentar": "Geaendert",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/abwesenheiten/?msg=updated"

    session.expire_all()
    updated = session.get(Abwesenheit, a.id)
    assert updated.von_datum == date(2026, 4, 1)
    assert updated.bis_datum == date(2026, 4, 3)
    assert updated.typ == AbwesenheitTyp.SONSTIGES
    assert updated.kommentar == "Geaendert"


def test_orga_kann_abwesenheit_loeschen(client, session):
    t_id = _make_trainee(session)
    a = Abwesenheit(
        trainee_id=t_id, von_datum=date(2026, 3, 2), bis_datum=date(2026, 3, 4),
        typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.PLANER,
    )
    session.add(a)
    session.commit()
    session.refresh(a)

    r = client.post(f"/abwesenheiten/{a.id}/loeschen", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/abwesenheiten/?msg=deleted"

    session.expire_all()
    assert session.get(Abwesenheit, a.id) is None


def test_orga_sieht_liste_mit_spalten(client, session):
    t_id = _make_trainee(session, "Anna", "Azubi")
    session.add(Abwesenheit(
        trainee_id=t_id, von_datum=date(2026, 3, 2), bis_datum=date(2026, 3, 4),
        typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.PLANER,
    ))
    session.commit()

    r = client.get("/abwesenheiten/")
    assert r.status_code == 200
    assert "Azubi, Anna" in r.text
    assert "02.03.2026" in r.text
    assert "04.03.2026" in r.text


# ── (b) ausbilder -> 403 auf Liste UND POST ─────────────────────────────────

def test_ausbilder_darf_liste_nicht_sehen(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    _login(client, "ausbilder")

    r = client.get("/abwesenheiten/")
    assert r.status_code == 403


def test_ausbilder_darf_nicht_anlegen(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    t_id = _make_trainee(session)
    _login(client, "ausbilder")

    r = client.post("/abwesenheiten/", data={
        "trainee_id": t_id,
        "von_datum": "2026-03-02",
        "bis_datum": "2026-03-04",
        "typ": "URLAUB",
        "kommentar": "",
    })
    assert r.status_code == 403
    assert session.exec(select(Abwesenheit)).first() is None


# ── (c) bis < von -> 400 ─────────────────────────────────────────────────────

def test_bis_vor_von_gibt_400(client, session):
    t_id = _make_trainee(session)

    r = client.post("/abwesenheiten/", data={
        "trainee_id": t_id,
        "von_datum": "2026-03-04",
        "bis_datum": "2026-03-02",
        "typ": "URLAUB",
        "kommentar": "",
    })
    assert r.status_code == 400
    assert session.exec(select(Abwesenheit)).first() is None


# ── (d) kaputtes Datum -> 400 statt 500 ──────────────────────────────────────

def test_kaputtes_datum_gibt_400(client, session):
    t_id = _make_trainee(session)

    r = client.post("/abwesenheiten/", data={
        "trainee_id": t_id,
        "von_datum": "nicht-ein-datum",
        "bis_datum": "2026-03-04",
        "typ": "URLAUB",
        "kommentar": "",
    })
    assert r.status_code == 400
    assert session.exec(select(Abwesenheit)).first() is None


def test_leeres_datum_gibt_400(client, session):
    t_id = _make_trainee(session)

    r = client.post("/abwesenheiten/", data={
        "trainee_id": t_id,
        "von_datum": "",
        "bis_datum": "2026-03-04",
        "typ": "URLAUB",
        "kommentar": "",
    })
    assert r.status_code == 400
    assert session.exec(select(Abwesenheit)).first() is None


# ── (e)/(f) Markierung in der Planer-Uebersicht ──────────────────────────────
# KW10/2026: Mo 2026-03-02 .. Fr 2026-03-06 / KW11/2026: Mo 2026-03-09 .. Fr 2026-03-13

def _overview_setup(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    dept = Department(code="CP", name="Cloud Platform")
    session.add(dept)
    session.flush()
    t = Trainee(vorname="Jonas", nachname="Jaeger", rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.flush()
    session.add(Assignment(
        trainee_id=t.id, schoolyear_id=SY, kw=10, jahr=2026,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept.id, source=AssignmentSource.MANUAL,
    ))
    session.add(Assignment(
        trainee_id=t.id, schoolyear_id=SY, kw=11, jahr=2026,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept.id, source=AssignmentSource.MANUAL,
    ))
    session.commit()
    return {"trainee": t.id, "dept": dept.id}


def test_teil_abwesenheit_traegt_mc_abwesend_und_beide_tooltip_teile(client, session):
    ids = _overview_setup(session)
    # KW10: Mo-Mi abwesend (Teilwoche) -- KW11 bleibt ohne Abwesenheit
    session.add(Abwesenheit(
        trainee_id=ids["trainee"], von_datum=date(2026, 3, 2), bis_datum=date(2026, 3, 4),
        typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.PLANER,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": ""})
    assert r.status_code == 200
    # Abteilungsname + Abwesenheits-Label kombiniert im Tooltip, bestehender
    # Abteilungs-Tooltip geht dabei nicht verloren
    assert 'title="Cloud Platform — Urlaub Mo-Mi (3 Tage)"' in r.text
    assert "mc-abwesend" in r.text
    # Teilwoche -> NICHT die "ganze Woche"-Klasse
    assert "mc-abwesend-voll" not in r.text


def test_ganze_woche_abwesend_traegt_mc_abwesend_voll(client, session):
    ids = _overview_setup(session)
    # KW11: komplette Woche abwesend
    session.add(Abwesenheit(
        trainee_id=ids["trainee"], von_datum=date(2026, 3, 9), bis_datum=date(2026, 3, 13),
        typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.PLANER,
    ))
    session.commit()

    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": ""})
    assert r.status_code == 200
    assert 'title="Cloud Platform — Urlaub (ganze Woche)"' in r.text
    assert "mc-abwesend mc-abwesend-voll" in r.text


def test_woche_ohne_abwesenheit_traegt_klasse_nicht(client, session):
    _overview_setup(session)

    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": ""})
    assert r.status_code == 200
    assert "mc-abwesend" not in r.text


# ── (g) Befund 3: Plausibilitaetsgrenze (Staff-Router) ──────────────────────

def test_riesiger_zeitraum_ergibt_400(client, session):
    """von=0001-01-01/bis=9999-12-31 wuerde den Trainee in JEDER Woche als
    voll abwesend markieren und die Liste muesste pro Zeile (_werktage())
    zehntausende Tage durchlaufen -- das wird jetzt mit 400 abgelehnt."""
    t_id = _make_trainee(session)

    r = client.post("/abwesenheiten/", data={
        "trainee_id": t_id,
        "von_datum": "0001-01-01",
        "bis_datum": "9999-12-31",
        "typ": "URLAUB",
        "kommentar": "",
    })
    assert r.status_code == 400
    assert session.exec(select(Abwesenheit)).first() is None


def test_zeitraum_ueber_ein_jahr_ergibt_400_staff(client, session):
    t_id = _make_trainee(session)

    r = client.post("/abwesenheiten/", data={
        "trainee_id": t_id,
        "von_datum": "1900-01-01",
        "bis_datum": "2100-12-31",
        "typ": "URLAUB",
        "kommentar": "",
    })
    assert r.status_code == 400
    assert session.exec(select(Abwesenheit)).first() is None


def test_zeitraum_366_tage_bleibt_ok_staff(client, session):
    t_id = _make_trainee(session)

    r = client.post("/abwesenheiten/", data={
        "trainee_id": t_id,
        "von_datum": "2026-01-01",
        "bis_datum": "2027-01-01",
        "typ": "URLAUB",
        "kommentar": "",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert session.exec(select(Abwesenheit)).first() is not None


# ── (h) Befund 10: Ueberschneidungspruefung auch beim Bearbeiten ────────────

def test_aendern_auf_ueberschneidenden_zeitraum_gibt_hinweis_kein_block(client, session):
    """Verschiebt der Planer eine Abwesenheit exakt auf eine bestehende,
    entsteht kommentarlos ein Doppel-Eintrag, wenn update_abwesenheit die
    Ueberschneidung nicht prueft. Erwartet: Hinweis-Flash wie beim Anlegen,
    aber weiterhin KEIN harter Block -- beide Eintraege bleiben bestehen."""
    t_id = _make_trainee(session)
    bestehend = Abwesenheit(
        trainee_id=t_id, von_datum=date(2026, 3, 2), bis_datum=date(2026, 3, 4),
        typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.PLANER,
    )
    zu_bearbeiten = Abwesenheit(
        trainee_id=t_id, von_datum=date(2026, 4, 1), bis_datum=date(2026, 4, 3),
        typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.PLANER,
    )
    session.add_all([bestehend, zu_bearbeiten])
    session.commit()
    session.refresh(zu_bearbeiten)

    r = client.post(f"/abwesenheiten/{zu_bearbeiten.id}", data={
        "trainee_id": t_id,
        "von_datum": "2026-03-02",
        "bis_datum": "2026-03-04",
        "typ": "URLAUB",
        "kommentar": "",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/abwesenheiten/?msg=updated&detail=")
    assert "ueberschneidet" in r.headers["location"]

    rows = session.exec(select(Abwesenheit)).all()
    assert len(rows) == 2  # kein harter Block -- beide Eintraege bleiben


def test_aendern_ohne_ueberschneidung_bleibt_ohne_hinweis(client, session):
    """exclude_id blendet den bearbeiteten Eintrag selbst aus: eine
    unveraenderte Bearbeitung darf sich nicht staendig selbst als
    Ueberschneidung melden."""
    t_id = _make_trainee(session)
    a = Abwesenheit(
        trainee_id=t_id, von_datum=date(2026, 3, 2), bis_datum=date(2026, 3, 4),
        typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.PLANER,
    )
    session.add(a)
    session.commit()
    session.refresh(a)

    r = client.post(f"/abwesenheiten/{a.id}", data={
        "trainee_id": t_id,
        "von_datum": "2026-03-02",
        "bis_datum": "2026-03-04",
        "typ": "URLAUB",
        "kommentar": "unveraendert",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/abwesenheiten/?msg=updated"
