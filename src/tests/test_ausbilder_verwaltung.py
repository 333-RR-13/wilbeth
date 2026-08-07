"""Tests fuer die zentrale Ausbilder-Verwaltung (/ausbilder-verwaltung/):
kehrt Department.verantwortliche (bisher nur pro Abteilung pflegbar) um zu
Person -> ihre Abteilungen.

Dev-Login setzt fuer Staff-Rollen upn="dev@local" (siehe app/routers/auth.py).
Login-Muster wie in tests/test_meine_abteilung.py / tests/test_role_guards.py.
"""
import re
import urllib.parse

from sqlmodel import Session

from app.config import settings
from app.models import Department
from app.services.auth_service import CurrentUser, allowed_dept_ids
from app.services.verantwortliche_utils import (
    parse_verantwortliche,
    people_by_upn,
    serialize_verantwortliche,
)


def _dev_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "dev")


def _login(client, rolle: str):
    r = client.post("/auth/dev-login", data={"rolle": rolle}, follow_redirects=False)
    assert r.status_code == 303
    return r


def _enc(upn: str) -> str:
    return urllib.parse.quote(upn, safe="")


def _checkbox_checked(html: str, dept_id: int) -> bool:
    """Prueft, ob die Checkbox fuer dept_id im gerenderten HTML 'checked' ist."""
    m = re.search(rf'value="{dept_id}"([^>]*)>', html)
    assert m, f"Checkbox fuer Abteilung {dept_id} nicht gefunden"
    return "checked" in m.group(1)


# ── Reine Helper-Unit-Tests (app/services/verantwortliche_utils.py) ────────

def test_parse_verantwortliche_ist_defensiv():
    assert parse_verantwortliche(None) == []
    assert parse_verantwortliche("") == []
    assert parse_verantwortliche("   ") == []
    # doppelte Trenner, fuehrende/folgende Leerzeichen, Leerzeilen
    assert parse_verantwortliche(" a@x.de ,, ;\n b@x.de \n\n, ,c@x.de,,") == [
        "a@x.de", "b@x.de", "c@x.de",
    ]


def test_serialize_verantwortliche():
    assert serialize_verantwortliche([]) == ""
    assert serialize_verantwortliche(["a@x.de", "b@x.de"]) == "a@x.de, b@x.de"


def test_people_by_upn_dedupliziert_case_insensitiv_und_sortiert(session: Session):
    d1 = Department(code="ZZ", name="Zulieferung", verantwortliche="Zora@Firma.de")
    d2 = Department(code="AA", name="Anfang", verantwortliche="zora@firma.de, anton@firma.de")
    session.add_all([d1, d2])
    session.commit()

    people = people_by_upn(session)
    assert list(people.keys()) == ["anton@firma.de", "zora@firma.de"]
    zora_depts = people["zora@firma.de"]
    # dedupliziert: Zora@Firma.de + zora@firma.de sind EINE Person, je Abteilung
    # nur einmal in der Liste, sortiert nach Department.code
    assert [d.code for d in zora_depts] == ["AA", "ZZ"]


# ── Zuordnung anlegen ("Person hinzufuegen") ────────────────────────────────

def test_hinzufuegen_legt_zuordnung_in_beiden_abteilungen_an(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    d1 = Department(code="AI", name="AI Platform")
    d2 = Department(code="CP", name="Cloud Platform")
    session.add_all([d1, d2])
    session.commit()
    session.refresh(d1)
    session.refresh(d2)

    _login(client, "orga")

    r = client.post("/ausbilder-verwaltung/hinzufuegen", data={
        "upn": "Neu.Ausbilder@Firma.de",
        "anzeigename": "Neu Ausbilder",
        "abteilung_ids": [str(d1.id), str(d2.id)],
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/ausbilder-verwaltung/?msg=created")

    session.expire_all()
    d1_r = session.get(Department, d1.id)
    d2_r = session.get(Department, d2.id)
    assert "Neu.Ausbilder@Firma.de" in d1_r.verantwortliche
    assert "Neu.Ausbilder@Firma.de" in d2_r.verantwortliche


def test_hinzufuegen_ohne_upn_kein_write(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    d = Department(code="AI", name="AI Platform")
    session.add(d)
    session.commit()
    session.refresh(d)

    _login(client, "orga")
    r = client.post("/ausbilder-verwaltung/hinzufuegen", data={
        "upn": "   ",
        "abteilung_ids": [str(d.id)],
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "msg=error" in r.headers["location"]

    session.expire_all()
    d_r = session.get(Department, d.id)
    assert d_r.verantwortliche == ""


# ── Zuordnung aendern ────────────────────────────────────────────────────

def test_bearbeiten_aendert_zuordnung_andere_eintraege_bleiben(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    d1 = Department(code="AI", name="AI Platform", verantwortliche="person.eins@firma.de, person.zwei@firma.de")
    d2 = Department(code="CP", name="Cloud Platform", verantwortliche="person.eins@firma.de")
    d3 = Department(code="NW", name="Netzwerk")
    session.add_all([d1, d2, d3])
    session.commit()
    session.refresh(d1)
    session.refresh(d2)
    session.refresh(d3)

    _login(client, "orga")

    # person.eins ist aktuell in d1 + d2 -> Checkbox-Auswahl aendert auf d1 + d3
    r = client.post(f"/ausbilder-verwaltung/{_enc('person.eins@firma.de')}/bearbeiten", data={
        "abteilung_ids": [str(d1.id), str(d3.id)],
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/ausbilder-verwaltung/?msg=updated"

    session.expire_all()
    d1_r = session.get(Department, d1.id)
    d2_r = session.get(Department, d2.id)
    d3_r = session.get(Department, d3.id)
    assert "person.eins@firma.de" in d1_r.verantwortliche
    # andere Person in d1 bleibt unangetastet
    assert "person.zwei@firma.de" in d1_r.verantwortliche
    # aus d2 entfernt
    assert "person.eins@firma.de".lower() not in d2_r.verantwortliche.lower()
    # neu in d3
    assert "person.eins@firma.de" in d3_r.verantwortliche


def test_bearbeiten_vorschau_zeigt_aktuelle_zuordnung_vorausgewaehlt(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    d1 = Department(code="AI", name="AI Platform", verantwortliche="person@firma.de")
    d2 = Department(code="CP", name="Cloud Platform")
    session.add_all([d1, d2])
    session.commit()
    session.refresh(d1)
    session.refresh(d2)

    _login(client, "orga")
    r = client.get(f"/ausbilder-verwaltung/{_enc('person@firma.de')}/bearbeiten")
    assert r.status_code == 200
    assert _checkbox_checked(r.text, d1.id) is True
    assert _checkbox_checked(r.text, d2.id) is False


# ── Zuordnung entfernen ──────────────────────────────────────────────────

def test_entfernen_traegt_aus_allen_abteilungen_aus_andere_bleiben(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    d1 = Department(code="AI", name="AI Platform", verantwortliche="weg@firma.de, bleibt@firma.de")
    d2 = Department(code="CP", name="Cloud Platform", verantwortliche="weg@firma.de")
    session.add_all([d1, d2])
    session.commit()
    session.refresh(d1)
    session.refresh(d2)

    _login(client, "orga")

    r = client.post(f"/ausbilder-verwaltung/{_enc('weg@firma.de')}/entfernen", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/ausbilder-verwaltung/?msg=deleted"

    session.expire_all()
    d1_r = session.get(Department, d1.id)
    d2_r = session.get(Department, d2.id)
    assert "weg@firma.de" not in d1_r.verantwortliche
    assert "bleibt@firma.de" in d1_r.verantwortliche
    assert d2_r.verantwortliche == ""


# ── Defensives Parsen bei krummen Bestandsdaten ─────────────────────────────

def test_defensives_parsen_krummes_feld_bleibt_lesbar(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    krumm = " a@firma.de ,, ;\n b@firma.de \n\n, ,c@firma.de,,"
    d = Department(code="AI", name="AI Platform", verantwortliche=krumm)
    session.add(d)
    session.commit()
    session.refresh(d)

    _login(client, "orga")
    # a@firma.de bleibt zugeordnet (schon drin) -- Schreiben durch den Router
    # muss das Feld bereinigen, ohne b/c zu verlieren.
    r = client.post(f"/ausbilder-verwaltung/{_enc('a@firma.de')}/bearbeiten", data={
        "abteilung_ids": [str(d.id)],
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    d_r = session.get(Department, d.id)
    eintraege = [e.lower() for e in parse_verantwortliche(d_r.verantwortliche)]
    assert sorted(eintraege) == ["a@firma.de", "b@firma.de", "c@firma.de"]
    assert len(eintraege) == 3  # keine leeren Eintraege, keine Duplikate


# ── Liste: Dedup + Sortierung ────────────────────────────────────────────

def test_liste_dedupliziert_case_insensitiv_und_sortiert_alphabetisch(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    d1 = Department(code="ZZ", name="Zulieferung", verantwortliche="Zora@Firma.de")
    d2 = Department(code="AA", name="Anfang", verantwortliche="zora@firma.de, anton@firma.de")
    session.add_all([d1, d2])
    session.commit()

    _login(client, "orga")
    r = client.get("/ausbilder-verwaltung/")
    assert r.status_code == 200
    # kanonisch kleingeschrieben, nur EINE Tabellenzeile (die UPN erscheint
    # je Zeile zweimal im Markup: als Anzeige + im confirm()-Text der
    # Entfernen-Aktion -- bei Dedup-Versagen waeren es zwei Zeilen = 4x)
    assert r.text.count("zora@firma.de") == 2
    # alphabetisch sortiert: anton vor zora
    pos_anton = r.text.find("anton@firma.de")
    pos_zora = r.text.find("zora@firma.de")
    assert 0 <= pos_anton < pos_zora
    # Zora ist in AA und ZZ zugeordnet -> beide Codes als Chips sichtbar
    assert "AA" in r.text
    assert "ZZ" in r.text


# ── Rollen-Guards ────────────────────────────────────────────────────────

def test_ausbilder_bekommt_403_auf_allen_routen(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    d = Department(code="AI", name="AI Platform")
    session.add(d)
    session.commit()
    session.refresh(d)

    _login(client, "ausbilder")

    assert client.get("/ausbilder-verwaltung/").status_code == 403
    assert client.get(f"/ausbilder-verwaltung/{_enc('x@firma.de')}/bearbeiten").status_code == 403
    assert client.post(
        f"/ausbilder-verwaltung/{_enc('x@firma.de')}/bearbeiten",
        data={"abteilung_ids": [str(d.id)]},
    ).status_code == 403
    assert client.post(
        "/ausbilder-verwaltung/hinzufuegen", data={"upn": "x@firma.de"},
    ).status_code == 403
    assert client.post(f"/ausbilder-verwaltung/{_enc('x@firma.de')}/entfernen").status_code == 403

    session.expire_all()
    d_r = session.get(Department, d.id)
    assert d_r.verantwortliche == ""  # kein Schreibzugriff trotz Versuch


def test_orga_und_admin_duerfen_zugreifen(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    d = Department(code="AI", name="AI Platform", verantwortliche="jemand@firma.de")
    session.add(d)
    session.commit()
    session.refresh(d)

    for rolle in ("orga", "admin"):
        _login(client, rolle)
        assert client.get("/ausbilder-verwaltung/").status_code == 200
        r = client.get(f"/ausbilder-verwaltung/{_enc('jemand@firma.de')}/bearbeiten")
        assert r.status_code == 200


# ── Integrationstest: Wirkung auf allowed_dept_ids ──────────────────────────

def test_allowed_dept_ids_matcht_nach_zuordnung(client, session, monkeypatch):
    """Der eigentliche Zweck der Seite: eine hier vergebene Zuordnung muss
    exakt das liefern, was allowed_dept_ids() (auth_service.py) fuer diese
    UPN als 'eigene Abteilungen' erkennt."""
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
    r = client.post("/ausbilder-verwaltung/hinzufuegen", data={
        "upn": "Ausbilder.Test@Firma.de",
        "abteilung_ids": [str(d1.id), str(d2.id)],
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    user = CurrentUser(upn="ausbilder.test@firma.de", name="Test", rolle="ausbilder")
    ids = allowed_dept_ids(session, user)
    assert ids == {d1.id, d2.id}
    assert d3.id not in ids
