"""Tests fuer /vorschlaege/ (Orga/Admin nehmen von Ausbildern eingereichte
EinsatzVorschlag-Datensaetze an oder lehnen sie ab).
"""
from sqlmodel import Session, select

from app.config import settings
from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    EinsatzVorschlag,
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


def _setup(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    dept = Department(code="CP", name="Cloud Platform", verantwortliche="ausbilder@firma.de")
    session.add(dept)
    session.flush()
    t = Trainee(vorname="Jonas", nachname="Jäger", rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.flush()
    session.commit()
    return {"trainee": t.id, "dept": dept.id}


def _make_vorschlag(session: Session, ids: dict, kw_von=10, jahr_von=2026, kw_bis=12, jahr_bis=2026) -> EinsatzVorschlag:
    v = EinsatzVorschlag(
        trainee_id=ids["trainee"],
        department_id=ids["dept"],
        schoolyear_id=SY,
        kw_von=kw_von, jahr_von=jahr_von,
        kw_bis=kw_bis, jahr_bis=jahr_bis,
        kommentar="Bitte einplanen",
        eingereicht_von_upn="ausbilder@firma.de",
        eingereicht_von_name="Dev ausbilder",
        status="offen",
    )
    session.add(v)
    session.commit()
    session.refresh(v)
    return v


# ── (a) GET als orga listet offene ──────────────────────────────────────────

def test_orga_list_shows_open_vorschlag(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _make_vorschlag(session, ids)

    _login(client, "orga")

    r = client.get("/vorschlaege/")
    assert r.status_code == 200
    assert "Jäger" in r.text
    assert "Cloud Platform" in r.text
    assert "Offen" in r.text


# ── (b) annehmen legt Assignments NUR in freien Wochen an ───────────────────

def test_annehmen_skips_occupied_weeks_and_creates_confirmed_cells(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    v = _make_vorschlag(session, ids, kw_von=10, jahr_von=2026, kw_bis=12, jahr_bis=2026)

    # KW 11/2026 bereits belegt (z.B. Urlaub) -> darf nicht ueberschrieben werden
    occupied = Assignment(
        trainee_id=ids["trainee"], schoolyear_id=SY, kw=11, jahr=2026,
        typ=AssignmentTyp.URLAUB, abteilung_id=None, source=AssignmentSource.SELBST,
    )
    session.add(occupied)
    session.commit()
    session.refresh(occupied)

    _login(client, "orga")

    r = client.post(f"/vorschlaege/{v.id}/annehmen", follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()

    # KW10 und KW12 wurden neu angelegt, ABTEILUNG + bestaetigt
    row10 = session.exec(
        select(Assignment).where(
            Assignment.trainee_id == ids["trainee"], Assignment.kw == 10, Assignment.jahr == 2026
        )
    ).first()
    row12 = session.exec(
        select(Assignment).where(
            Assignment.trainee_id == ids["trainee"], Assignment.kw == 12, Assignment.jahr == 2026
        )
    ).first()
    assert row10 is not None
    assert row10.typ == AssignmentTyp.ABTEILUNG
    assert row10.abteilung_id == ids["dept"]
    assert row10.bestaetigung == "bestaetigt"
    assert row12 is not None
    assert row12.bestaetigung == "bestaetigt"

    # KW11 blieb unangetastet (weiterhin URLAUB, nicht ueberschrieben)
    row11 = session.get(Assignment, occupied.id)
    assert row11.typ == AssignmentTyp.URLAUB

    updated_v = session.get(EinsatzVorschlag, v.id)
    assert updated_v.status == "angenommen"
    assert "KW 11/2026" in updated_v.antwort_kommentar
    assert "2 Wochen angelegt" in updated_v.antwort_kommentar


def test_annehmen_no_skipped_weeks(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    v = _make_vorschlag(session, ids, kw_von=15, jahr_von=2026, kw_bis=16, jahr_bis=2026)

    _login(client, "orga")

    r = client.post(f"/vorschlaege/{v.id}/annehmen", follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    updated_v = session.get(EinsatzVorschlag, v.id)
    assert updated_v.status == "angenommen"
    assert "2 Wochen angelegt" in updated_v.antwort_kommentar
    assert "keine uebersprungen" in updated_v.antwort_kommentar


# ── (c) ablehnen setzt Status+Kommentar ──────────────────────────────────────

def test_ablehnen_sets_status_and_kommentar(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    v = _make_vorschlag(session, ids)

    _login(client, "orga")

    r = client.post(f"/vorschlaege/{v.id}/ablehnen", data={
        "kommentar": "Passt zeitlich nicht",
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    updated_v = session.get(EinsatzVorschlag, v.id)
    assert updated_v.status == "abgelehnt"
    assert updated_v.antwort_kommentar == "Passt zeitlich nicht"


# ── (d) ausbilder auf /vorschlaege/ -> 403 ──────────────────────────────────

def test_ausbilder_forbidden_on_vorschlaege(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _make_vorschlag(session, ids)

    _login(client, "ausbilder")

    r = client.get("/vorschlaege/")
    assert r.status_code == 403
