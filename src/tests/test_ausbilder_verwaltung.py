"""Tests fuer die Ausbilder-Verwaltung (/ausbilder-verwaltung/), seit
Migration 0017betreuung eine Personen-Verwaltung (Betreuer-Tabelle) mit ZWEI
unabhaengigen Zustaendigkeiten: Abteilungen (schreibt weiterhin
Department.verantwortliche -- app.services.auth_service.allowed_dept_ids()
bleibt unveraendert) und Berufe (Betreuer.berufe, neu).

Dev-Login setzt fuer Staff-Rollen upn="dev@local" (siehe app/routers/auth.py).
Login-Muster wie in tests/test_meine_abteilung.py / tests/test_role_guards.py.
"""
import re

from sqlmodel import Session, select

from app.config import settings
from app.models import (
    Betreuer,
    BetreuerTrainee,
    Department,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)
from app.services.auth_service import CurrentUser, allowed_dept_ids
from app.services.verantwortliche_utils import parse_verantwortliche


def _dev_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "dev")


def _login(client, rolle: str):
    r = client.post("/auth/dev-login", data={"rolle": rolle}, follow_redirects=False)
    assert r.status_code == 303
    return r


def _checkbox_checked(html: str, name: str, value) -> bool:
    m = re.search(rf'name="{name}" value="{value}"([^>]*)>', html)
    assert m, f"Checkbox {name}={value} nicht gefunden"
    return "checked" in m.group(1)


# ── Liste ────────────────────────────────────────────────────────────────

def test_liste_zeigt_betreuer_mit_funktion_abteilungen_und_status(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    d = Department(code="AI", name="AI Platform", verantwortliche="anna@firma.de")
    session.add(d)
    b1 = Betreuer(upn="anna@firma.de", name="Anna Beispiel", funktionen=["HR"], aktiv=True)
    b2 = Betreuer(upn="ben@firma.de", name="Ben Muster", funktionen=["TECHNISCH"], aktiv=False, berufe=["FISI"])
    session.add_all([b1, b2])
    session.commit()

    _login(client, "orga")
    r = client.get("/ausbilder-verwaltung/")
    assert r.status_code == 200
    assert "Anna Beispiel" in r.text
    assert "Ben Muster" in r.text
    assert "Ausbildung (HR)" in r.text
    assert "Fachlicher Ausbilder" in r.text
    assert "AI" in r.text  # Abteilungs-Chip fuer Anna
    assert "Inaktiv" in r.text
    assert "FISI" in r.text


def test_mehrere_funktionen_erscheinen_als_badges_in_liste_und_profil(client, session, monkeypatch):
    """Eine Person kann mehrere Funktionen gleichzeitig haben -- beide werden
    als eigene Badges angezeigt, sowohl in der Liste als auch auf der
    Profilseite."""
    _dev_mode(monkeypatch)
    b = Betreuer(upn="beide@firma.de", name="Beide Funktionen", funktionen=["HR", "TECHNISCH"])
    session.add(b)
    session.commit()
    session.refresh(b)

    _login(client, "orga")
    r_liste = client.get("/ausbilder-verwaltung/")
    assert r_liste.status_code == 200
    assert "Ausbildung (HR)" in r_liste.text
    assert "Fachlicher Ausbilder" in r_liste.text

    r_profil = client.get(f"/ausbilder-verwaltung/{b.id}")
    assert r_profil.status_code == 200
    assert "Ausbildung (HR)" in r_profil.text
    assert "Fachlicher Ausbilder" in r_profil.text


def test_ohne_funktion_ist_reiner_abteilungs_ausbilder(client, session, monkeypatch):
    """Eine leere Funktionsliste ist ausdruecklich erlaubt (reiner
    Abteilungs-Ausbilder ohne uebergreifende Betreuungsfunktion)."""
    _dev_mode(monkeypatch)
    b = Betreuer(upn="nurabteilung@firma.de", name="Nur Abteilung", funktionen=[])
    session.add(b)
    session.commit()
    session.refresh(b)

    _login(client, "orga")
    r_liste = client.get("/ausbilder-verwaltung/")
    assert r_liste.status_code == 200
    assert "keine" in r_liste.text

    r_profil = client.get(f"/ausbilder-verwaltung/{b.id}")
    assert r_profil.status_code == 200
    assert "nur Abteilungs-Ausbilder" in r_profil.text


# ── Anlegen ──────────────────────────────────────────────────────────────

def test_anlegen_speichert_alle_felder_und_synct_abteilung(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    d1 = Department(code="AI", name="AI Platform")
    d2 = Department(code="CP", name="Cloud Platform")
    session.add_all([d1, d2])
    session.commit()
    session.refresh(d1)
    session.refresh(d2)

    _login(client, "orga")
    r = client.post("/ausbilder-verwaltung/neu", data={
        "upn": "Neu.Person@Firma.de",
        "name": "Neu Person",
        "funktion": ["EINSATZPLANUNG", "HR"],
        "email": "neu.person@firma.de",
        "telefon": "+49 30 123",
        "notiz": "interne Notiz",
        "aktiv": "1",
        "beruf": ["FISI"],
        "abteilung_ids": [str(d1.id), str(d2.id)],
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/ausbilder-verwaltung/?msg=created"

    session.expire_all()
    betreuer = session.exec(
        select(Betreuer).where(Betreuer.upn == "Neu.Person@Firma.de")
    ).first()
    assert betreuer is not None
    assert betreuer.name == "Neu Person"
    assert betreuer.funktionen == ["EINSATZPLANUNG", "HR"]
    assert betreuer.email == "neu.person@firma.de"
    assert betreuer.aktiv is True
    assert betreuer.berufe == ["FISI"]

    d1_r = session.get(Department, d1.id)
    d2_r = session.get(Department, d2.id)
    assert "Neu.Person@Firma.de" in d1_r.verantwortliche
    assert "Neu.Person@Firma.de" in d2_r.verantwortliche


def test_anlegen_ohne_upn_kein_write(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    _login(client, "orga")
    r = client.post("/ausbilder-verwaltung/neu", data={"upn": "   "}, follow_redirects=False)
    assert r.status_code == 303
    assert "msg=error" in r.headers["location"]

    session.expire_all()
    assert session.exec(select(Betreuer)).all() == []


def test_anlegen_dublette_upn_case_insensitiv_wird_abgelehnt(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    session.add(Betreuer(upn="person@firma.de", name="Erste Person"))
    session.commit()

    _login(client, "orga")
    r = client.post("/ausbilder-verwaltung/neu", data={
        "upn": "Person@Firma.de",
        "name": "Zweite Person",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "msg=error" in r.headers["location"]

    session.expire_all()
    alle = session.exec(select(Betreuer)).all()
    assert len(alle) == 1
    assert alle[0].name == "Erste Person"


# ── Bearbeiten ───────────────────────────────────────────────────────────

def test_bearbeiten_vorschau_zeigt_aktuelle_werte_vorausgewaehlt(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    d1 = Department(code="AI", name="AI Platform", verantwortliche="person@firma.de")
    d2 = Department(code="CP", name="Cloud Platform")
    session.add_all([d1, d2])
    session.add(TraineeClass(name="FISI 1. LJ", berufsschule="X", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST))
    b = Betreuer(upn="person@firma.de", name="Person Eins", funktionen=["TECHNISCH", "HR"], berufe=["FISI"])
    session.add(b)
    session.commit()
    session.refresh(b)
    session.refresh(d1)
    session.refresh(d2)

    _login(client, "orga")
    r = client.get(f"/ausbilder-verwaltung/{b.id}/bearbeiten")
    assert r.status_code == 200
    assert 'value="Person Eins"' in r.text
    assert _checkbox_checked(r.text, "abteilung_ids", d1.id) is True
    assert _checkbox_checked(r.text, "abteilung_ids", d2.id) is False
    assert _checkbox_checked(r.text, "beruf", "FISI") is True
    assert _checkbox_checked(r.text, "funktion", "TECHNISCH") is True
    assert _checkbox_checked(r.text, "funktion", "HR") is True
    assert _checkbox_checked(r.text, "funktion", "EINSATZPLANUNG") is False


def test_bearbeiten_aendert_felder_und_abteilungen_andere_bleiben(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    d1 = Department(code="AI", name="AI Platform", verantwortliche="person.eins@firma.de, person.zwei@firma.de")
    d2 = Department(code="CP", name="Cloud Platform", verantwortliche="person.eins@firma.de")
    d3 = Department(code="NW", name="Netzwerk")
    session.add_all([d1, d2, d3])
    b = Betreuer(upn="person.eins@firma.de", name="Person Eins", funktionen=["TECHNISCH"])
    session.add(b)
    session.commit()
    session.refresh(b)
    session.refresh(d1)
    session.refresh(d2)
    session.refresh(d3)

    _login(client, "orga")
    r = client.post(f"/ausbilder-verwaltung/{b.id}/bearbeiten", data={
        "upn": "person.eins@firma.de",
        "name": "Person Eins",
        "funktion": ["HR"],
        "aktiv": "",  # Checkbox nicht gesetzt -> inaktiv
        "abteilung_ids": [str(d1.id), str(d3.id)],
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/ausbilder-verwaltung/?msg=updated"

    session.expire_all()
    b_r = session.get(Betreuer, b.id)
    assert b_r.funktionen == ["HR"]
    assert b_r.aktiv is False

    d1_r = session.get(Department, d1.id)
    d2_r = session.get(Department, d2.id)
    d3_r = session.get(Department, d3.id)
    assert "person.eins@firma.de" in d1_r.verantwortliche
    assert "person.zwei@firma.de" in d1_r.verantwortliche  # andere Person bleibt
    assert "person.eins@firma.de".lower() not in d2_r.verantwortliche.lower()  # aus d2 entfernt
    assert "person.eins@firma.de" in d3_r.verantwortliche  # neu


def test_bearbeiten_upn_aenderung_migriert_abteilungszuordnung(client, session, monkeypatch):
    """UPN-Umbenennung: alte Schreibweise wird ueberall ausgetragen, neue eingetragen."""
    _dev_mode(monkeypatch)
    d = Department(code="AI", name="AI Platform", verantwortliche="alt@firma.de")
    session.add(d)
    b = Betreuer(upn="alt@firma.de", name="Person")
    session.add(b)
    session.commit()
    session.refresh(b)
    session.refresh(d)

    _login(client, "orga")
    r = client.post(f"/ausbilder-verwaltung/{b.id}/bearbeiten", data={
        "upn": "neu@firma.de",
        "name": "Person",
        "abteilung_ids": [str(d.id)],
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    d_r = session.get(Department, d.id)
    eintraege = [e.lower() for e in parse_verantwortliche(d_r.verantwortliche)]
    assert "alt@firma.de" not in eintraege
    assert "neu@firma.de" in eintraege


def test_bearbeiten_upn_dublette_wird_abgelehnt(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    session.add(Betreuer(upn="a@firma.de", name="A"))
    b2 = Betreuer(upn="b@firma.de", name="B")
    session.add(b2)
    session.commit()
    session.refresh(b2)

    _login(client, "orga")
    r = client.post(f"/ausbilder-verwaltung/{b2.id}/bearbeiten", data={
        "upn": "A@Firma.de",
        "name": "B",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "msg=error" in r.headers["location"]

    session.expire_all()
    b2_r = session.get(Betreuer, b2.id)
    assert b2_r.upn == "b@firma.de"  # unveraendert


# ── Entfernen ────────────────────────────────────────────────────────────

def test_entfernen_loescht_betreuer_abteilungszuordnung_und_ausnahmen(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    d1 = Department(code="AI", name="AI Platform", verantwortliche="weg@firma.de, bleibt@firma.de")
    d2 = Department(code="CP", name="Cloud Platform", verantwortliche="weg@firma.de")
    session.add_all([d1, d2])
    b = Betreuer(upn="weg@firma.de", name="Weg")
    session.add(b)
    session.commit()
    session.refresh(b)
    t = Trainee(vorname="Max", nachname="Muster", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.commit()
    session.refresh(t)
    session.add(BetreuerTrainee(betreuer_id=b.id, trainee_id=t.id, modus="ZUSAETZLICH"))
    session.commit()
    session.refresh(d1)
    session.refresh(d2)

    _login(client, "orga")
    r = client.post(f"/ausbilder-verwaltung/{b.id}/entfernen", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/ausbilder-verwaltung/?msg=deleted"

    session.expire_all()
    assert session.get(Betreuer, b.id) is None
    assert session.exec(select(BetreuerTrainee).where(BetreuerTrainee.betreuer_id == b.id)).all() == []
    d1_r = session.get(Department, d1.id)
    d2_r = session.get(Department, d2.id)
    assert "weg@firma.de" not in d1_r.verantwortliche
    assert "bleibt@firma.de" in d1_r.verantwortliche
    assert d2_r.verantwortliche == ""


# ── Rollen-Guards ────────────────────────────────────────────────────────

def test_ausbilder_bekommt_403_auf_verwaltungsrouten(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    b = Betreuer(upn="x@firma.de", name="X")
    session.add(b)
    session.commit()
    session.refresh(b)

    _login(client, "ausbilder")

    assert client.get("/ausbilder-verwaltung/").status_code == 403
    assert client.get("/ausbilder-verwaltung/neu").status_code == 403
    assert client.post("/ausbilder-verwaltung/neu", data={"upn": "y@firma.de"}).status_code == 403
    assert client.get(f"/ausbilder-verwaltung/{b.id}/bearbeiten").status_code == 403
    assert client.post(f"/ausbilder-verwaltung/{b.id}/bearbeiten", data={"upn": "x@firma.de"}).status_code == 403
    assert client.post(f"/ausbilder-verwaltung/{b.id}/entfernen").status_code == 403
    assert client.post(f"/ausbilder-verwaltung/{b.id}/ausnahmen", data={"trainee_id": 1, "modus": "ZUSAETZLICH"}).status_code == 403

    session.expire_all()
    assert session.get(Betreuer, b.id) is not None  # unveraendert


def test_orga_und_admin_duerfen_zugreifen(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    b = Betreuer(upn="jemand@firma.de", name="Jemand")
    session.add(b)
    session.commit()
    session.refresh(b)

    for rolle in ("orga", "admin"):
        _login(client, rolle)
        assert client.get("/ausbilder-verwaltung/").status_code == 200
        assert client.get(f"/ausbilder-verwaltung/{b.id}/bearbeiten").status_code == 200
        assert client.get(f"/ausbilder-verwaltung/{b.id}").status_code == 200


# ── Profilseite: Zugriff der Person selbst ──────────────────────────────

def test_profilseite_person_selbst_sichtbar_aber_ohne_notiz_und_ausnahmenpflege(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    # Dev-Login setzt fuer Staff-Rollen immer upn="dev@local".
    b = Betreuer(upn="dev@local", name="Ich Selbst", notiz="geheime interne Notiz")
    session.add(b)
    session.commit()
    session.refresh(b)

    _login(client, "ausbilder")  # normalerweise 403 auf dieser Seite -- Ausnahme: eigene UPN
    r = client.get(f"/ausbilder-verwaltung/{b.id}")
    assert r.status_code == 200
    assert "geheime interne Notiz" not in r.text
    assert "Ausnahmen" not in r.text


def test_profilseite_fremde_ausbilder_bekommt_403(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    b = Betreuer(upn="andere.person@firma.de", name="Andere Person")
    session.add(b)
    session.commit()
    session.refresh(b)

    _login(client, "ausbilder")  # upn=dev@local, matcht NICHT
    r = client.get(f"/ausbilder-verwaltung/{b.id}")
    assert r.status_code == 403


def test_profilseite_orga_sieht_notiz_und_ausnahmenpflege(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    b = Betreuer(upn="person@firma.de", name="Person", notiz="interne Notiz")
    session.add(b)
    session.commit()
    session.refresh(b)

    _login(client, "orga")
    r = client.get(f"/ausbilder-verwaltung/{b.id}")
    assert r.status_code == 200
    assert "interne Notiz" in r.text
    assert "Ausnahmen" in r.text


def test_profilseite_unbekannte_id_404(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    _login(client, "orga")
    assert client.get("/ausbilder-verwaltung/999999").status_code == 404


# ── Ausnahmen (Ausnahmen-CRUD, nur orga/admin) ──────────────────────────

def test_ausnahme_anlegen_aendern_und_entfernen(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    b = Betreuer(upn="betreuer@firma.de", name="Betreuer", berufe=["FISI"])
    session.add(b)
    t = Trainee(vorname="Mia", nachname="Muster", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.commit()
    session.refresh(b)
    session.refresh(t)

    _login(client, "orga")
    r = client.post(f"/ausbilder-verwaltung/{b.id}/ausnahmen", data={
        "trainee_id": t.id, "modus": "ZUSAETZLICH",
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    rows = session.exec(select(BetreuerTrainee).where(BetreuerTrainee.betreuer_id == b.id)).all()
    assert len(rows) == 1
    assert rows[0].modus == "ZUSAETZLICH"

    # Erneutes Anlegen fuer dasselbe Paar aendert den Modus (Upsert, keine Dublette)
    r2 = client.post(f"/ausbilder-verwaltung/{b.id}/ausnahmen", data={
        "trainee_id": t.id, "modus": "AUSGENOMMEN",
    }, follow_redirects=False)
    assert r2.status_code == 303
    session.expire_all()
    rows2 = session.exec(select(BetreuerTrainee).where(BetreuerTrainee.betreuer_id == b.id)).all()
    assert len(rows2) == 1
    assert rows2[0].modus == "AUSGENOMMEN"

    ausnahme_id = rows2[0].id
    r3 = client.post(f"/ausbilder-verwaltung/{b.id}/ausnahmen/{ausnahme_id}/entfernen", follow_redirects=False)
    assert r3.status_code == 303
    session.expire_all()
    assert session.exec(select(BetreuerTrainee).where(BetreuerTrainee.betreuer_id == b.id)).all() == []


# ── Regression: allowed_dept_ids() unveraendert ─────────────────────────

def test_allowed_dept_ids_matcht_nach_zuordnung_ueber_neue_ui(client, session, monkeypatch):
    """Der abteilungsbezogene Teil der Seite muss weiterhin exakt das
    liefern, was allowed_dept_ids() (auth_service.py) fuer diese UPN als
    'eigene Abteilungen' erkennt -- UNVERAENDERT gegenueber vor Migration
    0017betreuung."""
    _dev_mode(monkeypatch)
    d1 = Department(code="AI", name="AI Platform")
    d2 = Department(code="CP", name="Cloud Platform")
    d3 = Department(code="NW", name="Netzwerk")
    session.add_all([d1, d2, d3])
    session.commit()
    session.refresh(d1)
    session.refresh(d2)
    session.refresh(d3)

    _login(client, "orga")
    r = client.post("/ausbilder-verwaltung/neu", data={
        "upn": "Ausbilder.Test@Firma.de",
        "abteilung_ids": [str(d1.id), str(d2.id)],
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    user = CurrentUser(upn="ausbilder.test@firma.de", name="Test", rolle="ausbilder")
    ids = allowed_dept_ids(session, user)
    assert ids == {d1.id, d2.id}
    assert d3.id not in ids
