"""Tests fuer die Trainee-Anlage: Pflicht Ausbildungsbeginn + Beruf,
abgeleitete Einstiegsklasse, Sonderfall-Override.

(a) Ausbildungsbeginn ist Pflicht -> ohne ihn: Error-Redirect, kein Trainee.
(b) Beruf-Auswahl (Regelfall) leitet die Einstiegsklasse "<Beruf> 1. LJ" ab.
(c) Sonderfall + explizite Klasse -> genau diese Klasse wird Einstiegsklasse.
(d) DH-Kohorte (kein "n. LJ"-Muster): Beruf == Klassenname -> diese Klasse.
(e) Beruf ohne passende "<Beruf> 1. LJ"-Klasse -> Error-Redirect.
(f) Edit-Formular ist mit Beruf vorbelegt; Sonderfall vor-angehakt+aufgeklappt
    wenn die aktuelle Einstiegsklasse existiert und ihr LJ != 1 ist.
"""
from datetime import date

from sqlmodel import Session, select

from app.models import Trainee, TraineeClass, TraineeRolle, UnterrichtsTyp


def _add_class(session: Session, name: str) -> TraineeClass:
    c = TraineeClass(name=name, berufsschule="JD Schule", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(c)
    session.commit()
    return c


# ── (a) Ausbildungsbeginn Pflicht ─────────────────────────────────────────────

def test_create_ohne_ausbildungsbeginn_error(client, session: Session):
    """POST /trainees/ ohne ausbildungsbeginn -> Error-Redirect, kein Trainee angelegt."""
    r = client.post(
        "/trainees/",
        data={
            "vorname": "Ohne",
            "nachname": "Beginn",
            "rolle": "AZUBI",
            "beruf": "FISI",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" in r.headers["location"]

    session.expire_all()
    t = session.exec(select(Trainee).where(Trainee.nachname == "Beginn")).first()
    assert t is None


# ── (b) Beruf -> abgeleitete Einstiegsklasse (Regelfall) ──────────────────────

def test_create_mit_beruf_leitet_einstiegsklasse_ab(client, session: Session):
    """POST mit beruf=FISI + Ausbildungsbeginn -> klasse_id == 'FISI 1. LJ'."""
    k1 = _add_class(session, "FISI 1. LJ")
    _add_class(session, "FISI 2. LJ")

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Fiona",
            "nachname": "Fisi",
            "rolle": "AZUBI",
            "beruf": "FISI",
            "ausbildungsbeginn": "2025-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" not in r.headers["location"]

    session.expire_all()
    t = session.exec(select(Trainee).where(Trainee.nachname == "Fisi")).first()
    assert t is not None
    assert t.klasse_id == k1.id


# ── (c) Sonderfall + explizite Klasse ─────────────────────────────────────────

def test_create_sonderfall_setzt_explizite_klasse(client, session: Session):
    """Sonderfall + klasse_id 'FISI 2. LJ' -> genau diese Klasse als Anker."""
    _add_class(session, "FISI 1. LJ")
    k2 = _add_class(session, "FISI 2. LJ")

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Sina",
            "nachname": "Sonder",
            "rolle": "AZUBI",
            "sonderfall": "1",
            "klasse_id": str(k2.id),
            "ausbildungsbeginn": "2024-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" not in r.headers["location"]

    session.expire_all()
    t = session.exec(select(Trainee).where(Trainee.nachname == "Sonder")).first()
    assert t is not None
    assert t.klasse_id == k2.id


# ── (d) DH-Kohorte (kein LJ-Muster) ───────────────────────────────────────────

def test_create_dh_kohorte_ueber_beruf(client, session: Session):
    """DH: beruf == voller Klassenname -> diese Kohortenklasse wird Anker."""
    dh = _add_class(session, "DHBW Cybersecurity")

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Doro",
            "nachname": "Dual",
            "rolle": "DH_STUDENT",
            "beruf": "DHBW Cybersecurity",
            "ausbildungsbeginn": "2025-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" not in r.headers["location"]

    session.expire_all()
    t = session.exec(select(Trainee).where(Trainee.nachname == "Dual")).first()
    assert t is not None
    assert t.klasse_id == dh.id


# ── (e) Beruf ohne passende 1.-LJ-Klasse ──────────────────────────────────────

def test_create_beruf_ohne_klasse_error(client, session: Session):
    """beruf ohne existierende '<Beruf> 1. LJ'-Klasse -> Error-Redirect."""
    r = client.post(
        "/trainees/",
        data={
            "vorname": "Niemand",
            "nachname": "Klasse",
            "rolle": "AZUBI",
            "beruf": "UNBEKANNT",
            "ausbildungsbeginn": "2025-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" in r.headers["location"]

    session.expire_all()
    t = session.exec(select(Trainee).where(Trainee.nachname == "Klasse")).first()
    assert t is None


# ── (f) Edit-Formular: Beruf vorbelegt + Sonderfall bei LJ != 1 ───────────────

def test_edit_form_vorbelegt_beruf_und_sonderfall_bei_2lj(client, session: Session):
    """Edit-Formular ist mit dem Beruf-Token vorbelegt; Sonderfall ist
    vor-angehakt+aufgeklappt, weil die Einstiegsklasse im 2. LJ liegt."""
    _add_class(session, "FISI 1. LJ")
    k2 = _add_class(session, "FISI 2. LJ")

    from datetime import date
    t = Trainee(
        vorname="Edda", nachname="Edit", rolle=TraineeRolle.AZUBI,
        klasse_id=k2.id, ausbildungsbeginn=date(2024, 9, 1),
    )
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}/bearbeiten")
    assert r.status_code == 200
    assert '<option value="FISI" selected>' in r.text
    # Sonderfall-Checkbox ist angehakt: zwischen dem Checkbox-Tag und dem
    # naechsten '>' muss "checked" stehen.
    checkbox_tag = r.text.split('id="sonderfall"')[1].split(">")[0]
    assert "checked" in checkbox_tag
    # Der Sonderfall-Block ist aufgeklappt (kein display:none)
    assert "sonderfall-klasse-block" in r.text
    assert "display:none;" not in r.text.split("sonderfall-klasse-block")[1].split(">")[0]


def test_edit_form_kein_sonderfall_bei_1lj(client, session: Session):
    """Bei Einstiegsklasse im 1. LJ bleibt Sonderfall unangehakt+eingeklappt."""
    from datetime import date
    k1 = _add_class(session, "FISI 1. LJ")
    t = Trainee(
        vorname="Erik", nachname="Einlj", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2025, 9, 1),
    )
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}/bearbeiten")
    assert r.status_code == 200
    assert '<option value="FISI" selected>' in r.text
    checkbox_tag = r.text.split('id="sonderfall"')[1].split(">")[0]
    assert "checked" not in checkbox_tag
    assert "display:none;" in r.text.split("sonderfall-klasse-block")[1].split(">")[0]


# ── (g) Trainee-Liste zeigt die BERECHNETE Klasse (nicht den rohen Anker) ─────

def test_liste_zeigt_berechnete_klasse(client, session: Session):
    """Anker Beginn 2024 + Einstieg 'FISI 1. LJ' -> Liste zeigt die fuers
    laufende Jahr (2025-2026) berechnete Klasse 'FISI 2. LJ'."""
    from app.models import Schoolyear

    session.add(Schoolyear(id="2025-2026", start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    k1 = _add_class(session, "FISI 1. LJ")
    _add_class(session, "FISI 2. LJ")
    _add_class(session, "FISI 3. LJ")

    t = Trainee(
        vorname="Robin", nachname="Rechnet", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2024, 9, 1),
    )
    session.add(t)
    session.commit()

    r = client.get("/trainees/")
    assert r.status_code == 200
    zeile = r.text.split("Rechnet")[1].split("</tr>")[0]
    assert "FISI 2. LJ" in zeile, "Liste muss die berechnete Klasse zeigen"
    # Anker steht als Tooltip drin (Transparenz bei falschen Anker-Daten)
    assert "Einstieg: FISI 1. LJ" in zeile


def test_liste_doppelt_gezaehlter_anker_wird_sichtbar(client, session: Session):
    """Fehlerhafte Daten (Beginn 2024 + Einstieg schon '2. LJ') zeigen in der
    Liste die berechnete '3. LJ' - konsistent mit dem Jahresabschluss, statt
    den Fehler mit dem rohen Anker zu verstecken."""
    from app.models import Schoolyear

    session.add(Schoolyear(id="2025-2026", start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    _add_class(session, "FISI 1. LJ")
    k2 = _add_class(session, "FISI 2. LJ")
    _add_class(session, "FISI 3. LJ")

    t = Trainee(
        vorname="Doppelt", nachname="Gezaehlt", rolle=TraineeRolle.AZUBI,
        klasse_id=k2.id, ausbildungsbeginn=date(2024, 9, 1),
    )
    session.add(t)
    session.commit()

    r = client.get("/trainees/")
    assert r.status_code == 200
    zeile = r.text.split("Gezaehlt")[1].split("</tr>")[0]
    assert "FISI 3. LJ" in zeile
