"""Tests fuer den Filter "Nur meine Abteilung" in /overview und /einsaetze/.

Schraenkt die Matrix (Uebersicht) bzw. die Zeilen (Einsatz-Liste) auf die
Abteilungen ein, fuer die der angemeldete Nutzer laut Department.verantwortliche
zustaendig ist (siehe allowed_dept_ids in app/services/auth_service.py).

Der Default-Testclient laeuft mit AUTH_MODE=off als admin mit upn="test@local"
(siehe conftest.py / app/main.py Zeile ~65) -- das reicht fuer die meisten
Faelle hier, da laut Projektauftrag admin/orga genauso als Verantwortliche
gelten koennen wie Ausbilder (die Checkbox ist nicht auf die Rolle "ausbilder"
beschraenkt, sondern auf "hat ueberhaupt eine verantwortete Abteilung").
"""
import json
from urllib.parse import unquote

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

SY = "2025-2026"
UPN = "test@local"  # Default-Testclient-UPN bei AUTH_MODE=off


def _base(session: Session) -> dict:
    """Schuljahr + 2 Abteilungen (eine eigene, eine fremde) + 2 Trainees.

    Anton hat einen Einsatz in der EIGENEN Abteilung (CP), Beate hat NUR einen
    Einsatz in der FREMDEN Abteilung (NW) -- also gar keinen eigenen Einsatz.
    """
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    own = Department(code="CP", name="Cloud Platform", verantwortliche=UPN)
    foreign = Department(code="NW", name="Netzwerk", verantwortliche="jemand-anders@firma.de")
    session.add_all([own, foreign])
    session.flush()

    anton = Trainee(vorname="Anton", nachname="Altmann", rolle=TraineeRolle.AZUBI)
    beate = Trainee(vorname="Beate", nachname="Bergmann", rolle=TraineeRolle.AZUBI)
    session.add_all([anton, beate])
    session.flush()

    session.add(Assignment(
        trainee_id=anton.id, schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=own.id, source=AssignmentSource.MANUAL,
    ))
    session.add(Assignment(
        trainee_id=beate.id, schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=foreign.id, source=AssignmentSource.MANUAL,
    ))
    session.commit()
    return {"own": own.id, "foreign": foreign.id, "anton": anton.id, "beate": beate.id}


def _base_ohne_eigene_abteilung(session: Session) -> dict:
    """Wie _base(), aber OHNE dass der Testnutzer irgendeine Abteilung verantwortet."""
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    foreign = Department(code="NW", name="Netzwerk", verantwortliche="jemand-anders@firma.de")
    session.add(foreign)
    session.flush()
    beate = Trainee(vorname="Beate", nachname="Bergmann", rolle=TraineeRolle.AZUBI)
    session.add(beate)
    session.flush()
    session.add(Assignment(
        trainee_id=beate.id, schoolyear_id=SY, kw=40, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=foreign.id, source=AssignmentSource.MANUAL,
    ))
    session.commit()
    return {"foreign": foreign.id, "beate": beate.id}


# ── Uebersicht (/overview) ───────────────────────────────────────────────────

def test_overview_ohne_haken_zeigt_fremde_abteilung(client, session):
    _base(session)
    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": ""})
    assert r.status_code == 200
    assert "Altmann" in r.text
    assert "Bergmann" in r.text


def test_overview_mit_haken_blendet_fremde_abteilung_aus(client, session):
    _base(session)
    r = client.get("/overview", params={
        "schoolyear_id": SY, "halbjahr": "", "nur_meine_abteilung": "1",
    })
    assert r.status_code == 200
    assert "Altmann" in r.text        # eigener Einsatz (CP) bleibt sichtbar
    assert "Bergmann" not in r.text   # nur fremder Einsatz (NW) -> Zeile verschwindet


def test_overview_checkbox_wird_gerendert_wenn_verantwortlich(client, session):
    _base(session)
    r = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": ""})
    assert r.status_code == 200
    assert 'name="nur_meine_abteilung"' in r.text
    assert "Nur meine Abteilung" in r.text


def test_overview_checkbox_nicht_gerendert_ohne_verantwortung(client, session):
    """Ohne verantwortete Abteilung wird die Checkbox nicht gerendert. Ein
    manuell gesetzter Query-Parameter darf trotzdem nicht zu Vollzugriff
    fuehren -- der Nutzer sieht dann nichts Eigenes (leere Auswahl)."""
    _base_ohne_eigene_abteilung(session)

    r_normal = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": ""})
    assert r_normal.status_code == 200
    assert 'name="nur_meine_abteilung"' not in r_normal.text
    assert "Bergmann" in r_normal.text  # ohne Haken ganz normal sichtbar

    r_forced = client.get("/overview", params={
        "schoolyear_id": SY, "halbjahr": "", "nur_meine_abteilung": "1",
    })
    assert r_forced.status_code == 200
    assert "Bergmann" not in r_forced.text  # erzwungener Haken -> leere Auswahl, nicht Vollzugriff


def test_overview_trainee_ohne_eigenen_einsatz_verschwindet_komplett(client, session):
    _base(session)
    r = client.get("/overview", params={
        "schoolyear_id": SY, "halbjahr": "", "nur_meine_abteilung": "1",
    })
    assert r.status_code == 200
    assert "Bergmann" not in r.text


def test_overview_filter_cookie_persistenz(client, session):
    """Filter ueberlebt einen zweiten Aufruf ohne Query-Parameter (Cookie)."""
    _base(session)
    r1 = client.get("/overview", params={
        "schoolyear_id": SY, "halbjahr": "", "nur_meine_abteilung": "1",
    })
    assert r1.status_code == 200

    cookie_raw = client.cookies.get("ov_filters")
    assert cookie_raw is not None, "ov_filters-Cookie muss gesetzt sein"
    data = json.loads(unquote(cookie_raw))
    assert data["nur_meine_abteilung"] == "1"

    r2 = client.get("/overview", params={"schoolyear_id": SY, "halbjahr": ""})
    assert r2.status_code == 200
    assert "Altmann" in r2.text
    assert "Bergmann" not in r2.text  # Cookie wirkt weiter ohne Query-Param


def test_overview_haken_kann_wirklich_entfernt_werden(client, session):
    """Regressionstest fuer das Hidden-Feld-Pattern der Checkbox: Ein Request der
    NICHT den Wert '1' enthaelt (so wie beim Absenden mit unangehakter Checkbox --
    nur der leere Hidden-Fallback-Wert kommt an) darf NICHT auf den im Cookie
    gespeicherten Haken zurueckfallen, sonst liesse sich der Filter nie wieder
    ausschalten."""
    _base(session)
    client.get("/overview", params={
        "schoolyear_id": SY, "halbjahr": "", "nur_meine_abteilung": "1",
    })
    r = client.get("/overview", params={
        "schoolyear_id": SY, "halbjahr": "", "nur_meine_abteilung": "",
    })
    assert r.status_code == 200
    assert "Bergmann" in r.text  # Filter tatsaechlich deaktiviert


def test_overview_schulwochen_bleiben_sichtbar_mit_haken(client, session):
    """Schul-/Uni-Wochen bleiben in der Matrix sichtbar, auch wenn der Haken
    gesetzt ist -- nur Abteilungs-Zellen anderer Abteilungen werden geleert."""
    ids = _base(session)
    session.add(Assignment(
        trainee_id=ids["anton"], schoolyear_id=SY, kw=41, jahr=2025,
        typ=AssignmentTyp.BERUFSSCHULE, source=AssignmentSource.MANUAL,
    ))
    session.commit()

    r = client.get("/overview", params={
        "schoolyear_id": SY, "halbjahr": "", "nur_meine_abteilung": "1",
    })
    assert r.status_code == 200
    assert "Altmann" in r.text
    assert "cell-school" in r.text  # BS-Chip (siehe _partials/chip.html) bleibt erhalten


# ── Einsatz-Liste (/einsaetze/) ──────────────────────────────────────────────
#
# Die Trainee-Namen stehen zusaetzlich immer im <select name="trainee_id">
# Dropdown (ungefiltert, alle Trainees), daher werden die Tabellenzeilen
# fuer die "sichtbar/nicht sichtbar"-Checks ueber den <tbody>-Bereich isoliert.

def _tbody(html: str) -> str:
    return html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]


def test_einsaetze_ohne_haken_zeigt_fremde_abteilung(client, session):
    _base(session)
    r = client.get("/einsaetze/", params={"schoolyear_id": SY})
    assert r.status_code == 200
    rows = _tbody(r.text)
    assert "Altmann" in rows
    assert "Bergmann" in rows


def test_einsaetze_mit_haken_zeigt_nur_eigene_abteilung(client, session):
    _base(session)
    r = client.get("/einsaetze/", params={"schoolyear_id": SY, "nur_meine_abteilung": "1"})
    assert r.status_code == 200
    rows = _tbody(r.text)
    assert "Altmann" in rows
    assert "Bergmann" not in rows


def test_einsaetze_checkbox_wird_gerendert_wenn_verantwortlich(client, session):
    _base(session)
    r = client.get("/einsaetze/", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert 'name="nur_meine_abteilung"' in r.text
    assert "Nur meine Abteilung" in r.text


def test_einsaetze_checkbox_nicht_gerendert_ohne_verantwortung(client, session):
    _base_ohne_eigene_abteilung(session)

    r_normal = client.get("/einsaetze/", params={"schoolyear_id": SY})
    assert r_normal.status_code == 200
    assert 'name="nur_meine_abteilung"' not in r_normal.text
    assert "Bergmann" in _tbody(r_normal.text)

    r_forced = client.get("/einsaetze/", params={"schoolyear_id": SY, "nur_meine_abteilung": "1"})
    assert r_forced.status_code == 200
    assert "Bergmann" not in _tbody(r_forced.text)  # erzwungener Haken -> leere Auswahl


def test_einsaetze_filter_cookie_persistenz(client, session):
    """Filter ueberlebt einen zweiten Aufruf ohne Query-Parameter (Cookie)."""
    _base(session)
    r1 = client.get("/einsaetze/", params={"schoolyear_id": SY, "nur_meine_abteilung": "1"})
    assert r1.status_code == 200

    cookie_raw = client.cookies.get("ea_filters")
    assert cookie_raw is not None, "ea_filters-Cookie muss gesetzt sein"
    data = json.loads(unquote(cookie_raw))
    assert data["nur_meine_abteilung"] == "1"

    r2 = client.get("/einsaetze/", params={"schoolyear_id": SY})
    assert r2.status_code == 200
    rows = _tbody(r2.text)
    assert "Altmann" in rows
    assert "Bergmann" not in rows


def test_einsaetze_haken_kann_wirklich_entfernt_werden(client, session):
    _base(session)
    client.get("/einsaetze/", params={"schoolyear_id": SY, "nur_meine_abteilung": "1"})
    r = client.get("/einsaetze/", params={"schoolyear_id": SY, "nur_meine_abteilung": ""})
    assert r.status_code == 200
    assert "Bergmann" in _tbody(r.text)
