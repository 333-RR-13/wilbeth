"""Regressionstests: konsistentes Default-Schuljahr ueberall, wo keins gewaehlt ist.

Bug: sobald ein Folgejahr angelegt ist (aber noch nicht das laufende), haben
mehrere Seiten kommentarlos das NEUESTE Jahr (years[0] bei desc-Sortierung)
als Default genommen statt das Jahr, in dem HEUTE liegt. Symptom: die
Trainee-Liste zeigte korrekt "FISI 2. LJ", das Trainee-Profil aber "FISI 3.
LJ" (weil trainees.py bereits den "aktuelles Jahr"-Fallback nutzte, die
Detailseite aber noch auf years_list[0] = neuestes Jahr griff).

Setup: zwei nicht-archivierte Schuljahre --
  - 2025-2026 enthaelt HEUTE (Default-Erwartung ueberall).
  - 2026-2027 liegt in der Zukunft (noch kein Folgejahr-Verhalten gewuenscht).
Klassen FISI 1./2./3. LJ (next_class_id verkettet), ein Trainee mit
Ausbildungsbeginn 2024-09-01 und Einstiegsklasse "FISI 1. LJ" --
klasse_fuer(..., "2025-2026") == "FISI 2. LJ" (1 Schritt), waehrend
klasse_fuer(..., "2026-2027") == "FISI 3. LJ" (2 Schritte) waere - genau der
gemeldete Bug, wenn eine Seite faelschlich das neueste Jahr nimmt.
"""
from datetime import date

from sqlmodel import Session

from app.models import (
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)

SY_AKTUELL = "2025-2026"
SY_ZUKUNFT = "2026-2027"


def _setup(session: Session) -> dict:
    sy_aktuell = Schoolyear(id=SY_AKTUELL, start_kw=36, start_year=2025, end_kw=35, end_year=2026)
    sy_zukunft = Schoolyear(id=SY_ZUKUNFT, start_kw=36, start_year=2026, end_kw=35, end_year=2027)
    session.add_all([sy_aktuell, sy_zukunft])

    k1 = TraineeClass(name="FISI 1. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    k2 = TraineeClass(name="FISI 2. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    k3 = TraineeClass(name="FISI 3. LJ", berufsschule="HHS", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add_all([k1, k2, k3])
    session.flush()
    k1.next_class_id = k2.id
    k2.next_class_id = k3.id
    session.add_all([k1, k2])

    t = Trainee(
        vorname="Max", nachname="Musterazubi", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2024, 9, 1),
    )
    session.add(t)
    session.commit()

    return {
        "trainee_id": t.id,
        "k1_id": k1.id,
        "k2_id": k2.id,
        "k3_id": k3.id,
    }


# (1) Trainee-Liste zeigt "FISI 2. LJ" -----------------------------------

def test_liste_zeigt_2_lj(client, session):
    _setup(session)
    r = client.get("/trainees/")
    assert r.status_code == 200
    assert "FISI 2. LJ" in r.text


# (2) Trainee-Detail zeigt "FISI 2. LJ", NICHT "FISI 3. LJ" ---------------

def test_detail_zeigt_2_lj_nicht_3_lj(client, session):
    ids = _setup(session)
    r = client.get(f"/trainees/{ids['trainee_id']}")
    assert r.status_code == 200
    assert "FISI 2. LJ" in r.text
    assert "FISI 3. LJ" not in r.text


# (3) /overview ohne Parameter (und ohne Cookie): 2025-2026 ist selected,
#     Trainee erscheint in der FISI-2.-LJ-Gruppe -------------------------

def test_overview_default_ohne_parameter_nutzt_aktuelles_jahr(client, session):
    ids = _setup(session)

    r = client.get("/overview")
    assert r.status_code == 200
    # Das Drag&Drop-Script bindet das tatsaechlich ausgewaehlte Jahr ein
    assert f"var schoolyearId = '{SY_AKTUELL}';" in r.text

    # Filter auf die 2.-LJ-Klasse (implizites Default-Jahr) zeigt den Trainee
    r2 = client.get("/overview", params={"klasse_id": ids["k2_id"]})
    assert r2.status_code == 200
    assert "Musterazubi" in r2.text

    # Filter auf die 3.-LJ-Klasse zeigt ihn NICHT (das waere der Bug: Berechnung
    # auf Basis des zukuenftigen statt des laufenden Jahres)
    r3 = client.get("/overview", params={"klasse_id": ids["k3_id"]})
    assert r3.status_code == 200
    assert "Musterazubi" not in r3.text


# (4) Klassen-Bearbeiten von "FISI 2. LJ" ohne Jahr-Parameter listet den
#     Trainee als Mitglied ------------------------------------------------

def test_klasse_bearbeiten_ohne_jahr_zeigt_2_lj_mitglied(client, session):
    ids = _setup(session)
    r = client.get(f"/klassen/{ids['k2_id']}/bearbeiten")
    assert r.status_code == 200
    assert f'href="/trainees/{ids["trainee_id"]}"' in r.text


# (5) DH-Semester im Detail basiert auf 2025-2026 (nicht auf dem Zukunftsjahr)

def test_dh_semester_basiert_auf_aktuellem_jahr(client, session):
    ids = _setup(session)
    dh = Trainee(
        vorname="Dana", nachname="Dahlstudent", rolle=TraineeRolle.DH_STUDENT,
        klasse_id=ids["k1_id"], ausbildungsbeginn=date(2024, 9, 1),
    )
    session.add(dh)
    session.commit()

    r = client.get(f"/trainees/{dh.id}")
    assert r.status_code == 200
    # Beginn 2024, laufendes Jahr 2025-2026 -> steps=1 -> base=2 -> "3./4. Semester"
    # (Bug waere Basis 2026-2027 -> steps=2 -> base=4 -> "5./6. Semester")
    assert "3./4. Semester" in r.text
    assert "5./6. Semester" not in r.text
