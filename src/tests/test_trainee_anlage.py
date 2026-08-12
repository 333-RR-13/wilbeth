"""Tests fuer die Trainee-Anlage: Pflicht Ausbildungsbeginn + Beruf,
abgeleitete Einstiegsklasse, Sonderfall-Override.

(a) Ausbildungsbeginn ist Pflicht -> ohne ihn: Error-Redirect, kein Trainee.
(b) Beruf-Auswahl (Regelfall) leitet die Einstiegsklasse "<Beruf> 1. LJ" ab.
(c) Sonderfall + explizite Klasse -> genau diese Klasse wird Einstiegsklasse.
(d) DH-Kohorte (kein "n. LJ"-Muster): Beruf == Klassenname -> diese Klasse.
(e) Beruf ohne passende "<Beruf> 1. LJ"-Klasse -> Error-Redirect.
(f) Edit-Formular ist mit Beruf vorbelegt; Sonderfall vor-angehakt+aufgeklappt
    wenn die aktuelle Einstiegsklasse existiert und ihr LJ != 1 ist.
(h) Trainee-Liste zeigt den Ausbildungsbeginn als eigene Spalte (TT.MM.JJJJ).
(i) Unplausibler Ausbildungsbeginn (nicht der 1. eines ueblichen Startmonats)
    loest beim Anlegen/Bearbeiten eine Warnung aus, blockiert aber nicht.
(j) base.html und share/_base.html binden das Klartext-Echo-Skript ein.
"""
import urllib.parse
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


def test_edit_form_kein_sonderfall_bei_dh_kohorte(client, session: Session):
    """DH-Kohorte (kein 'n. LJ'-Muster, lj is None) ist ueber den Beruf
    ableitbar - KEIN Sonderfall. Edit-Formular: Checkbox nicht angehakt,
    beruf-Select mit dem Kohortennamen vorbelegt."""
    from datetime import date
    dh = _add_class(session, "DHBW Cybersecurity")
    t = Trainee(
        vorname="Doro", nachname="Dual", rolle=TraineeRolle.DH_STUDENT,
        klasse_id=dh.id, ausbildungsbeginn=date(2025, 9, 1),
    )
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}/bearbeiten")
    assert r.status_code == 200
    assert '<option value="DHBW Cybersecurity" selected>' in r.text
    checkbox_tag = r.text.split('id="sonderfall"')[1].split(">")[0]
    assert "checked" not in checkbox_tag, "DH-Kohorte darf NICHT als Sonderfall angehakt sein"
    assert "display:none;" in r.text.split("sonderfall-klasse-block")[1].split(">")[0]


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


# ── (h) Ausbildungsbeginn-Spalte in der Liste (TT.MM.JJJJ) ────────────────────

def test_liste_zeigt_ausbildungsbeginn_spalte_als_tt_mm_jjjj(client, session: Session):
    """Die Trainee-Liste zeigt den Ausbildungsbeginn als eigene Spalte im
    Format TT.MM.JJJJ (nicht ISO) -- damit ein falsch erfasstes Datum (z. B.
    durch ein Browser-Datumsfeld in MM/DD/YYYY) beim Durchsehen auffaellt."""
    k1 = _add_class(session, "FISI 1. LJ")
    t = Trainee(
        vorname="Peter", nachname="Pruefbar", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2024, 1, 9),
    )
    session.add(t)
    session.commit()

    r = client.get("/trainees/")
    assert r.status_code == 200
    zeile = r.text.split("Pruefbar")[1].split("</tr>")[0]
    assert "09.01.2024" in zeile
    assert "2024-01-09" not in zeile


# ── (i) Server-Warnung bei unplausiblem Ausbildungsbeginn ─────────────────────
# Realer Produktionsfehler: Azubis mit Start 01.09.2024 wurden ueber ein
# englisches Edge-<input type="date"> (MM/DD/YYYY) als "01/09/2024" erfasst,
# also als 9. Januar statt 1. September gespeichert. Der Datensatz soll trotzdem
# angelegt werden (Ausnahmen kommen vor) -- aber mit einem deutlichen Hinweis.

def test_create_mit_unplausiblem_ausbildungsbeginn_legt_an_und_warnt(client, session: Session):
    """9. Januar 2024 (Tageszahl != 1) -> Trainee wird trotzdem angelegt,
    Redirect enthaelt eine Warnung."""
    k1 = _add_class(session, "FISI 1. LJ")

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Warn",
            "nachname": "Fall",
            "rolle": "AZUBI",
            "sonderfall": "1",
            "klasse_id": str(k1.id),
            "ausbildungsbeginn": "2024-01-09",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" not in r.headers["location"]
    assert "warnung=" in r.headers["location"]
    assert "Ungewöhnlicher" in urllib.parse.unquote(r.headers["location"])
    assert "9. Januar 2024" in urllib.parse.unquote(r.headers["location"])

    session.expire_all()
    t = session.exec(select(Trainee).where(Trainee.nachname == "Fall")).first()
    assert t is not None
    assert t.ausbildungsbeginn == date(2024, 1, 9)


def test_create_mit_plausiblem_ausbildungsbeginn_ohne_warnung(client, session: Session):
    """1. September 2024 (Regelfall) -> Trainee wird angelegt OHNE Warnung."""
    k1 = _add_class(session, "FISI 1. LJ")

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Kein",
            "nachname": "Warnfall",
            "rolle": "AZUBI",
            "sonderfall": "1",
            "klasse_id": str(k1.id),
            "ausbildungsbeginn": "2024-09-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" not in r.headers["location"]
    assert "warnung=" not in r.headers["location"]

    session.expire_all()
    t = session.exec(select(Trainee).where(Trainee.nachname == "Warnfall")).first()
    assert t is not None


def test_create_mit_ausnahme_01_01_ohne_warnung(client, session: Session):
    """1. Januar (verkuerzte Ausbildung, dokumentierte Ausnahme) -> keine Warnung."""
    k1 = _add_class(session, "FISI 1. LJ")

    r = client.post(
        "/trainees/",
        data={
            "vorname": "Neujahr",
            "nachname": "Start",
            "rolle": "AZUBI",
            "sonderfall": "1",
            "klasse_id": str(k1.id),
            "ausbildungsbeginn": "2025-01-01",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "warnung=" not in r.headers["location"]


def test_update_mit_unplausiblem_ausbildungsbeginn_warnt(client, session: Session):
    """Auch beim Bearbeiten eines bestehenden Trainees wird gewarnt, wenn das
    neue Datum unplausibel wirkt (Tag != 1, unueblicher Monat)."""
    k1 = _add_class(session, "FISI 1. LJ")
    t = Trainee(
        vorname="Edit", nachname="Warnung", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2024, 9, 1),
    )
    session.add(t)
    session.commit()
    session.refresh(t)

    r = client.post(
        f"/trainees/{t.id}",
        data={
            "vorname": "Edit",
            "nachname": "Warnung",
            "rolle": "AZUBI",
            "sonderfall": "1",
            "klasse_id": str(k1.id),
            "ausbildungsbeginn": "2024-03-15",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=updated" in r.headers["location"]
    assert "warnung=" in r.headers["location"]


# ── (j) Klartext-Echo-Skript wird eingebunden ──────────────────────────────────

def test_base_html_bindet_date_echo_skript_ein(client, session: Session):
    """base.html (Planer-Layout) bindet /static/date-echo.js ein -- das Skript
    macht den tatsaechlich gewaehlten Wert jedes Datumsfelds als deutschen
    Klartext sichtbar (Schutz gegen Locale-Verwechslungen wie MM/DD/YYYY)."""
    r = client.get("/trainees/neu")
    assert r.status_code == 200
    assert '/static/date-echo.js' in r.text


def test_share_base_html_bindet_date_echo_skript_ein(client, session: Session):
    """share/_base.html (Azubi-Layout) bindet dasselbe Skript ein -- nicht
    zweimal kopiert, sondern dieselbe Datei wie im Planer-Layout."""
    token = "test-token-date-echo"
    t = Trainee(vorname="Echo", nachname="Test", rolle=TraineeRolle.AZUBI, share_token=token)
    session.add(t)
    session.commit()

    r = client.get(f"/mein-plan/{token}/abwesenheit")
    assert r.status_code == 200
    assert '/static/date-echo.js' in r.text
