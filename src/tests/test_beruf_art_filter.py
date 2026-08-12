"""Tests fuer TEIL A: Ausbildungsrichtung (Beruf) nach Rolle filtern.

(a) membership_utils.beruf_art_map leitet je Beruf-Token die Art ab
    (Mehrheitsregel, bei Gleichstand "AUSBILDUNG").
(b) Klassen-Formular: TraineeClass.art ist speicherbar (Anlegen/Bearbeiten)
    und wird in der Klassen-Liste angezeigt.
(c) Trainee-Formular liefert die Beruf->Art-Zuordnung als JSON mit.
(d) Speichern eines Azubis mit Studiengang (Art-Mismatch) legt den Trainee
    TROTZDEM an, aber mit Warn-Flash; passende Kombination warnt nicht.
    Gilt fuer create UND update; DH_STUDENT+Ausbildungsberuf ebenso.
    PRAKTIKANT/UMSCHUELER duerfen jede Art waehlen -> nie eine Warnung.
"""
import urllib.parse
from datetime import date

from sqlmodel import Session, select

from app.models import Trainee, TraineeClass, TraineeRolle, UnterrichtsTyp
from app.services.membership_utils import beruf_art_map


def _add_class(session: Session, name: str, art: str = "AUSBILDUNG") -> TraineeClass:
    c = TraineeClass(
        name=name, berufsschule="JD Schule",
        unterrichts_typ=UnterrichtsTyp.BLOCK_FEST, art=art,
    )
    session.add(c)
    session.commit()
    return c


# ── (a) beruf_art_map ─────────────────────────────────────────────────────────

def test_beruf_art_map_ausbildung(session: Session):
    _add_class(session, "FISI 1. LJ", art="AUSBILDUNG")
    _add_class(session, "FISI 2. LJ", art="AUSBILDUNG")
    classes = session.exec(select(TraineeClass)).all()
    assert beruf_art_map(classes)["FISI"] == "AUSBILDUNG"


def test_beruf_art_map_studium_dh_kohorte(session: Session):
    _add_class(session, "DHBW Cybersecurity", art="STUDIUM")
    classes = session.exec(select(TraineeClass)).all()
    assert beruf_art_map(classes)["DHBW Cybersecurity"] == "STUDIUM"


def test_beruf_art_map_mehrheitsregel(session: Session):
    """3 Klassen desselben Berufs, 2x STUDIUM, 1x AUSBILDUNG (versehentlich
    falsch gepflegt) -> Mehrheit STUDIUM gewinnt."""
    _add_class(session, "MIX 1. LJ", art="STUDIUM")
    _add_class(session, "MIX 2. LJ", art="STUDIUM")
    _add_class(session, "MIX 3. LJ", art="AUSBILDUNG")
    classes = session.exec(select(TraineeClass)).all()
    assert beruf_art_map(classes)["MIX"] == "STUDIUM"


def test_beruf_art_map_gleichstand_gewinnt_ausbildung(session: Session):
    """Gleichstand (1x AUSBILDUNG, 1x STUDIUM) -> konservativ AUSBILDUNG."""
    _add_class(session, "TIE 1. LJ", art="AUSBILDUNG")
    _add_class(session, "TIE 2. LJ", art="STUDIUM")
    classes = session.exec(select(TraineeClass)).all()
    assert beruf_art_map(classes)["TIE"] == "AUSBILDUNG"


# ── (b) Klassen-Formular: art speicherbar ─────────────────────────────────────

def test_klasse_create_stores_art_studium(client, session: Session):
    r = client.post("/klassen/", data={
        "name": "DHBW Testgang",
        "berufsschule": "DHBW",
        "unterrichts_typ": "DH_PHASEN",
        "art": "STUDIUM",
    }, follow_redirects=False)
    assert r.status_code == 303

    cls = session.exec(select(TraineeClass).where(TraineeClass.name == "DHBW Testgang")).first()
    assert cls is not None
    assert cls.art == "STUDIUM"


def test_klasse_create_default_art_ist_ausbildung(client, session: Session):
    r = client.post("/klassen/", data={
        "name": "FISI 1. LJ",
        "berufsschule": "HHS",
        "unterrichts_typ": "BLOCK_FEST",
    }, follow_redirects=False)
    assert r.status_code == 303

    cls = session.exec(select(TraineeClass).where(TraineeClass.name == "FISI 1. LJ")).first()
    assert cls is not None
    assert cls.art == "AUSBILDUNG"


def test_klasse_update_changes_art(client, session: Session):
    cls = _add_class(session, "Testklasse X", art="AUSBILDUNG")

    r = client.post(f"/klassen/{cls.id}", data={
        "name": "Testklasse X",
        "berufsschule": "JD Schule",
        "unterrichts_typ": "BLOCK_FEST",
        "art": "STUDIUM",
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    updated = session.get(TraineeClass, cls.id)
    assert updated.art == "STUDIUM"


def test_klasse_bearbeiten_form_zeigt_art_select(client, session: Session):
    cls = _add_class(session, "FIAE 2. LJ", art="AUSBILDUNG")

    r = client.get(f"/klassen/{cls.id}/bearbeiten")
    assert r.status_code == 200
    assert 'name="art"' in r.text
    assert 'value="AUSBILDUNG" selected' in r.text


def test_klassen_liste_zeigt_art_badge(client, session: Session):
    _add_class(session, "DHBW Testliste", art="STUDIUM")

    r = client.get("/klassen/")
    assert r.status_code == 200
    assert "Studium" in r.text


# ── (c) Trainee-Formular liefert Beruf->Art-Zuordnung ─────────────────────────

def test_trainee_neu_formular_enthaelt_beruf_art_map(client, session: Session):
    _add_class(session, "FISI 1. LJ", art="AUSBILDUNG")
    _add_class(session, "DHBW Cybersecurity", art="STUDIUM")

    r = client.get("/trainees/neu")
    assert r.status_code == 200
    assert '"FISI"' in r.text
    assert '"AUSBILDUNG"' in r.text
    assert '"DHBW Cybersecurity"' in r.text
    assert '"STUDIUM"' in r.text


def test_trainee_bearbeiten_formular_enthaelt_beruf_art_map(client, session: Session):
    k1 = _add_class(session, "FISI 1. LJ", art="AUSBILDUNG")
    t = Trainee(
        vorname="Formular", nachname="Test", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2025, 9, 1),
    )
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}/bearbeiten")
    assert r.status_code == 200
    assert '"FISI"' in r.text
    assert '"AUSBILDUNG"' in r.text


# ── (d) Serverseitige Warnung bei Rolle/Art-Mismatch ──────────────────────────

def test_create_azubi_mit_studiengang_legt_an_und_warnt(client, session: Session):
    """AZUBI + Studiengang (DH-Kohorte) -> wird trotzdem angelegt, aber mit
    Warn-Flash im Redirect (Ausnahmen kommen vor, kein Block)."""
    _add_class(session, "DHBW Cybersecurity", art="STUDIUM")

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Alex", "nachname": "Mismatch", "rolle": "AZUBI",
            "beruf": "DHBW Cybersecurity", "ausbildungsbeginn": "2025-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" not in r.headers["location"]
    assert "warnung=" in r.headers["location"]
    assert "Azubi" in urllib.parse.unquote(r.headers["location"])
    assert "Studiengang" in urllib.parse.unquote(r.headers["location"])

    session.expire_all()
    t = session.exec(select(Trainee).where(Trainee.nachname == "Mismatch")).first()
    assert t is not None
    assert t.rolle == TraineeRolle.AZUBI


def test_create_dh_student_mit_ausbildungsberuf_legt_an_und_warnt(client, session: Session):
    """DH_STUDENT + Ausbildungsberuf -> wird angelegt, aber mit Warnung."""
    _add_class(session, "FISI 1. LJ", art="AUSBILDUNG")

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Doro", "nachname": "Umgekehrt", "rolle": "DH_STUDENT",
            "beruf": "FISI", "ausbildungsbeginn": "2025-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" not in r.headers["location"]
    assert "warnung=" in r.headers["location"]
    assert "DH-Student" in urllib.parse.unquote(r.headers["location"])
    assert "Ausbildungsberuf" in urllib.parse.unquote(r.headers["location"])


def test_create_azubi_mit_ausbildungsberuf_warnt_nicht(client, session: Session):
    """Passende Kombination (AZUBI + Ausbildungsberuf) -> keine Warnung."""
    _add_class(session, "FISI 1. LJ", art="AUSBILDUNG")

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Passt", "nachname": "Gut", "rolle": "AZUBI",
            "beruf": "FISI", "ausbildungsbeginn": "2025-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "warnung=" not in r.headers["location"]


def test_create_dh_student_mit_studiengang_warnt_nicht(client, session: Session):
    """Passende Kombination (DH_STUDENT + Studiengang) -> keine Warnung."""
    _add_class(session, "DHBW Cybersecurity", art="STUDIUM")

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Doro", "nachname": "Dual", "rolle": "DH_STUDENT",
            "beruf": "DHBW Cybersecurity", "ausbildungsbeginn": "2025-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "warnung=" not in r.headers["location"]


def test_create_praktikant_mit_studiengang_warnt_nicht(client, session: Session):
    """PRAKTIKANT darf jede Art waehlen -> nie eine Rolle/Art-Warnung."""
    _add_class(session, "DHBW Cybersecurity", art="STUDIUM")

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Paul", "nachname": "Praktikant", "rolle": "PRAKTIKANT",
            "beruf": "DHBW Cybersecurity", "ausbildungsbeginn": "2025-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "warnung=" not in r.headers["location"]


def test_update_azubi_zu_dh_student_mit_studiengang_warnt_nicht_mehr(client, session: Session):
    """Bearbeiten: Rolle- und Beruf-Aenderung gemeinsam auf eine passende
    Kombination -> keine Warnung mehr (Regressionsschutz fuer die
    Warnungs-Kombinationslogik bei update_trainee)."""
    k1 = _add_class(session, "FISI 1. LJ", art="AUSBILDUNG")
    dh = _add_class(session, "DHBW Cybersecurity", art="STUDIUM")
    t = Trainee(
        vorname="Wechsel", nachname="Rolle", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2025, 9, 1),
    )
    session.add(t)
    session.commit()
    session.refresh(t)

    r = client.post(
        f"/trainees/{t.id}",
        data={
            "vorname": "Wechsel", "nachname": "Rolle", "rolle": "DH_STUDENT",
            "beruf": "DHBW Cybersecurity", "ausbildungsbeginn": "2025-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "warnung=" not in r.headers["location"]

    session.expire_all()
    updated = session.get(Trainee, t.id)
    assert updated.klasse_id == dh.id


def test_update_azubi_mit_studiengang_warnt(client, session: Session):
    """Bearbeiten auf eine unpassende Kombination -> Warnung erscheint."""
    k1 = _add_class(session, "FISI 1. LJ", art="AUSBILDUNG")
    _add_class(session, "DHBW Cybersecurity", art="STUDIUM")
    t = Trainee(
        vorname="Edit", nachname="Warnfall", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2025, 9, 1),
    )
    session.add(t)
    session.commit()
    session.refresh(t)

    r = client.post(
        f"/trainees/{t.id}",
        data={
            "vorname": "Edit", "nachname": "Warnfall", "rolle": "AZUBI",
            "beruf": "DHBW Cybersecurity", "ausbildungsbeginn": "2025-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "warnung=" in r.headers["location"]
