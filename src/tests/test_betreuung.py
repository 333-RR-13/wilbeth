"""Tests fuer die Betreuer-Zustaendigkeit (Personen, die einen Trainee ueber
die gesamte Ausbildung begleiten, unabhaengig von der abteilungsbezogenen
Zustaendigkeit): app/services/betreuung_utils.py, das Trainee-Profil
(Abschnitt "Betreuung") und die Azubi-Sicht (/mein-plan -- Kontakt OHNE
interne Notiz).

klasse_fuer() faellt bei einer nicht aufloesbaren schoolyear_id (bzw. ohne
Anker/Klasse) auf trainee.klasse_id zurueck (siehe
app/services/membership_utils.py) -- ein Trainee OHNE klasse_id liefert
daher IMMER beruf_token=None ("ohne berechnete Klasse"), auch ohne eigens
angelegte Schoolyear-Zeilen. Das nutzen diese Tests, um beide Faelle
(mit/ohne berechnete Klasse) ohne Schuljahres-Fixtures abzubilden; ein
beliebiger schoolyear_id-String reicht (die statische Fallback-Regel greift
unabhaengig davon, ob dieses Schuljahr in der DB existiert).
"""
from sqlmodel import Session

from app.config import settings
from app.models import (
    Assignment,
    AssignmentTyp,
    Betreuer,
    BetreuerTrainee,
    Department,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)
from app.services.betreuung_utils import betreuer_fuer_trainee, trainees_fuer_betreuer

SY = "2025-2026"


def _dev_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "dev")


def _add_year(session: Session, sy_id: str = SY, start_year: int = 2025) -> Schoolyear:
    y = Schoolyear(id=sy_id, start_kw=36, start_year=start_year, end_kw=35, end_year=start_year + 1)
    session.add(y)
    session.flush()
    return y


def _add_class(session: Session, name: str) -> TraineeClass:
    c = TraineeClass(name=name, berufsschule="X", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(c)
    session.flush()
    return c


def _add_trainee(session: Session, vorname: str, nachname: str = "Test", klasse_id: int | None = None) -> Trainee:
    t = Trainee(vorname=vorname, nachname=nachname, rolle=TraineeRolle.AZUBI, klasse_id=klasse_id)
    session.add(t)
    session.flush()
    return t


# ── Regel: berufe-Filter ─────────────────────────────────────────────────

def test_berufe_filter_matcht_nur_passenden_beruf(session: Session):
    fisi = _add_class(session, "FISI 1. LJ")
    fiae = _add_class(session, "FIAE 1. LJ")
    t_fisi = _add_trainee(session, "Fiona", klasse_id=fisi.id)
    t_fiae = _add_trainee(session, "Finn", klasse_id=fiae.id)
    betreuer = Betreuer(upn="tech@firma.de", name="Tech", funktion="TECHNISCH", berufe=["FISI"])
    session.add(betreuer)
    session.commit()

    assert betreuer_fuer_trainee(session, t_fisi, SY) == [betreuer]
    assert betreuer_fuer_trainee(session, t_fiae, SY) == []
    assert trainees_fuer_betreuer(session, betreuer, SY) == [t_fisi]


def test_leere_berufe_liste_matcht_alle(session: Session):
    fisi = _add_class(session, "FISI 1. LJ")
    fiae = _add_class(session, "FIAE 1. LJ")
    t_fisi = _add_trainee(session, "Fiona", klasse_id=fisi.id)
    t_fiae = _add_trainee(session, "Finn", klasse_id=fiae.id)
    betreuer = Betreuer(upn="hr@firma.de", name="HR", funktion="HR", berufe=[])
    session.add(betreuer)
    session.commit()

    assert betreuer_fuer_trainee(session, t_fisi, SY) == [betreuer]
    assert betreuer_fuer_trainee(session, t_fiae, SY) == [betreuer]
    assert {t.id for t in trainees_fuer_betreuer(session, betreuer, SY)} == {t_fisi.id, t_fiae.id}


def test_inaktiver_betreuer_taucht_in_beiden_richtungen_nie_auf(session: Session):
    fisi = _add_class(session, "FISI 1. LJ")
    t = _add_trainee(session, "Fiona", klasse_id=fisi.id)
    betreuer = Betreuer(upn="inaktiv@firma.de", name="Inaktiv", berufe=[], aktiv=False)
    session.add(betreuer)
    session.commit()

    assert betreuer_fuer_trainee(session, t, SY) == []
    assert trainees_fuer_betreuer(session, betreuer, SY) == []


# ── Ausnahmen ────────────────────────────────────────────────────────────

def test_ausgenommen_entfernt_sonst_passenden_azubi(session: Session):
    fisi = _add_class(session, "FISI 1. LJ")
    t = _add_trainee(session, "Fiona", klasse_id=fisi.id)
    betreuer = Betreuer(upn="tech@firma.de", name="Tech", berufe=["FISI"])
    session.add(betreuer)
    session.commit()
    session.add(BetreuerTrainee(betreuer_id=betreuer.id, trainee_id=t.id, modus="AUSGENOMMEN"))
    session.commit()

    assert betreuer_fuer_trainee(session, t, SY) == []
    assert trainees_fuer_betreuer(session, betreuer, SY) == []


def test_zusaetzlich_nimmt_sonst_unpassenden_azubi_auf(session: Session):
    fiae = _add_class(session, "FIAE 1. LJ")
    t = _add_trainee(session, "Finn", klasse_id=fiae.id)
    betreuer = Betreuer(upn="tech@firma.de", name="Tech", berufe=["FISI"])
    session.add(betreuer)
    session.commit()
    session.add(BetreuerTrainee(betreuer_id=betreuer.id, trainee_id=t.id, modus="ZUSAETZLICH"))
    session.commit()

    assert betreuer_fuer_trainee(session, t, SY) == [betreuer]
    assert trainees_fuer_betreuer(session, betreuer, SY) == [t]


def test_trainee_ohne_berechnete_klasse_nur_ueber_zusaetzlich(session: Session):
    """Trainee ohne klasse_id -> beruf_token ist immer None (siehe
    Modul-Docstring): berufe=[] ("alle") matcht ihn TROTZDEM nicht, nur eine
    explizite ZUSAETZLICH-Ausnahme greift."""
    ohne_klasse = _add_trainee(session, "Ohne", klasse_id=None)
    betreuer_alle = Betreuer(upn="alle@firma.de", name="Alle", berufe=[])
    session.add(betreuer_alle)
    session.commit()

    assert betreuer_fuer_trainee(session, ohne_klasse, SY) == []
    assert trainees_fuer_betreuer(session, betreuer_alle, SY) == []

    session.add(BetreuerTrainee(betreuer_id=betreuer_alle.id, trainee_id=ohne_klasse.id, modus="ZUSAETZLICH"))
    session.commit()

    assert betreuer_fuer_trainee(session, ohne_klasse, SY) == [betreuer_alle]
    assert trainees_fuer_betreuer(session, betreuer_alle, SY) == [ohne_klasse]


# ── Sortierung ───────────────────────────────────────────────────────────

def test_sortierung_nach_funktion_dann_name(session: Session):
    fisi = _add_class(session, "FISI 1. LJ")
    t = _add_trainee(session, "Fiona", klasse_id=fisi.id)
    b_sonstiges = Betreuer(upn="z@firma.de", name="Zeta", funktion="SONSTIGES", berufe=[])
    b_hr = Betreuer(upn="a@firma.de", name="Alpha HR", funktion="HR", berufe=[])
    b_technisch = Betreuer(upn="b@firma.de", name="Beta Technik", funktion="TECHNISCH", berufe=[])
    b_planung = Betreuer(upn="c@firma.de", name="Charlie Planung", funktion="EINSATZPLANUNG", berufe=[])
    session.add_all([b_sonstiges, b_hr, b_technisch, b_planung])
    session.commit()

    ergebnis = betreuer_fuer_trainee(session, t, SY)
    assert [b.funktion for b in ergebnis] == ["HR", "TECHNISCH", "EINSATZPLANUNG", "SONSTIGES"]


# ── UI: Trainee-Profil zeigt Betreuung, Azubi-Sicht ohne Notiz ──────────

def test_trainee_profil_zeigt_betreuer(client, session):
    _add_year(session)
    fisi = _add_class(session, "FISI 1. LJ")
    t = _add_trainee(session, "Fiona", klasse_id=fisi.id)
    session.add(Betreuer(upn="tech@firma.de", name="Frau Fachausbilderin", funktion="TECHNISCH", berufe=["FISI"]))
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "Frau Fachausbilderin" in r.text
    assert "Fachlicher Ausbilder" in r.text


def test_azubi_sicht_zeigt_kontakt_aber_nicht_die_interne_notiz(client, session, monkeypatch):
    """Die Betreuung ist eine eigene Seite (/mein-plan/{token}/betreuer,
    TEIL 1) -- kein Abschnitt mehr auf 'Meine Einsaetze'."""
    _dev_mode(monkeypatch)
    _add_year(session)
    fisi = _add_class(session, "FISI 1. LJ")
    t = _add_trainee(session, "Fiona", klasse_id=fisi.id)
    session.add(Betreuer(
        upn="tech@firma.de", name="Frau Fachausbilderin", funktion="TECHNISCH",
        email="fachausbilderin@firma.de", telefon="+49 30 999",
        notiz="GEHEIME INTERNE NOTIZ", berufe=["FISI"],
    ))
    session.commit()

    r = client.post("/auth/dev-login", data={"rolle": "azubi", "trainee_id": t.id}, follow_redirects=False)
    token = r.headers["location"].rsplit("/", 1)[-1]

    r2 = client.get(f"/mein-plan/{token}/betreuer")
    assert r2.status_code == 200
    assert "Frau Fachausbilderin" in r2.text
    assert "Fachlicher Ausbilder" in r2.text
    assert "fachausbilderin@firma.de" in r2.text
    assert "+49 30 999" in r2.text
    assert "GEHEIME INTERNE NOTIZ" not in r2.text


def test_azubi_sicht_ohne_zustaendigen_betreuer_zeigt_hinweis(client, session, monkeypatch):
    """Kein zustaendiger Betreuer -> Block 1 zeigt den freundlichen
    Platzhaltertext statt (fremder) Namen. 'Meine Betreuer' als Nav-Text
    erscheint jetzt auf JEDER share-Seite (eigener Nav-Eintrag) und ist daher
    kein taugliches Ausschlusskriterium mehr, s. share/_base.html."""
    _dev_mode(monkeypatch)
    _add_year(session)
    fiae = _add_class(session, "FIAE 1. LJ")
    t = _add_trainee(session, "Finn", klasse_id=fiae.id)
    session.add(Betreuer(upn="tech@firma.de", name="Nur FISI", funktion="TECHNISCH", berufe=["FISI"]))
    session.commit()

    r = client.post("/auth/dev-login", data={"rolle": "azubi", "trainee_id": t.id}, follow_redirects=False)
    token = r.headers["location"].rsplit("/", 1)[-1]

    r2 = client.get(f"/mein-plan/{token}/betreuer")
    assert r2.status_code == 200
    assert "Nur FISI" not in r2.text
    assert "Aktuell sind dir keine Ansprechpartner zugeordnet." in r2.text

    # Der bisherige Abschnitt auf "Meine Einsaetze" ist weg, nur noch ein Link.
    plan = client.get(f"/mein-plan/{token}")
    assert plan.status_code == 200
    assert f'href="/mein-plan/{token}/betreuer"' in plan.text


# ── TEIL 1: eigene Seite "Meine Betreuer" (Block 1 + Block 2) ──────────────

def test_betreuer_seite_zeigt_beide_bloecke_in_funktions_reihenfolge(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    _add_year(session)
    fisi = _add_class(session, "FISI 1. LJ")
    t = _add_trainee(session, "Fiona", klasse_id=fisi.id)
    session.add_all([
        Betreuer(upn="sonstiges@firma.de", name="Sina Sonstiges", funktion="SONSTIGES", berufe=[]),
        Betreuer(upn="hr@firma.de", name="Hanna HR", funktion="HR", berufe=[]),
        Betreuer(upn="plan@firma.de", name="Petra Planung", funktion="EINSATZPLANUNG", berufe=[]),
        Betreuer(upn="tech@firma.de", name="Tobias Technik", funktion="TECHNISCH", berufe=["FISI"]),
    ])
    session.commit()

    r = client.post("/auth/dev-login", data={"rolle": "azubi", "trainee_id": t.id}, follow_redirects=False)
    token = r.headers["location"].rsplit("/", 1)[-1]

    r2 = client.get(f"/mein-plan/{token}/betreuer")
    assert r2.status_code == 200
    assert "Deine Ansprechpartner in der Ausbildung" in r2.text
    assert "Ansprechpartner in den Abteilungen" in r2.text

    # Funktions-Reihenfolge: HR, TECHNISCH, EINSATZPLANUNG, SONSTIGES
    pos_hr = r2.text.index("Hanna HR")
    pos_tech = r2.text.index("Tobias Technik")
    pos_plan = r2.text.index("Petra Planung")
    pos_sonst = r2.text.index("Sina Sonstiges")
    assert pos_hr < pos_tech < pos_plan < pos_sonst


def test_betreuer_seite_abteilungsblock_zeigt_klarname_statt_upn(client, session, monkeypatch):
    """Existiert zur UPN in Department.verantwortliche ein Betreuer-
    Datensatz, wird Klarname+Kontakt statt der nackten UPN gezeigt; eine
    zweite UPN ohne Betreuer-Datensatz bleibt als rohe UPN sichtbar."""
    _dev_mode(monkeypatch)
    _add_year(session)
    fisi = _add_class(session, "FISI 1. LJ")
    t = _add_trainee(session, "Fiona", klasse_id=fisi.id)
    dept = Department(
        code="CP", name="Cloud Platform",
        verantwortliche="bekannt@firma.de, unbekannt@firma.de",
        ansprechpartner="Fachliche Ansprechperson XY",
    )
    session.add(dept)
    session.add(Betreuer(upn="bekannt@firma.de", name="Klarname Bekannt", email="bekannt@firma.de"))
    session.commit()
    session.add(Assignment(
        trainee_id=t.id, schoolyear_id=SY, kw=10, jahr=2025,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept.id,
    ))
    session.commit()

    r = client.post("/auth/dev-login", data={"rolle": "azubi", "trainee_id": t.id}, follow_redirects=False)
    token = r.headers["location"].rsplit("/", 1)[-1]

    r2 = client.get(f"/mein-plan/{token}/betreuer")
    assert r2.status_code == 200
    assert "CP" in r2.text and "Cloud Platform" in r2.text
    assert "Klarname Bekannt" in r2.text
    assert "unbekannt@firma.de" in r2.text
    assert "Fachliche Ansprechperson XY" in r2.text


def test_betreuer_seite_ohne_einsaetze_zeigt_hinweis(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    _add_year(session)
    fisi = _add_class(session, "FISI 1. LJ")
    t = _add_trainee(session, "Fiona", klasse_id=fisi.id)
    session.commit()

    r = client.post("/auth/dev-login", data={"rolle": "azubi", "trainee_id": t.id}, follow_redirects=False)
    token = r.headers["location"].rsplit("/", 1)[-1]

    r2 = client.get(f"/mein-plan/{token}/betreuer")
    assert r2.status_code == 200
    assert "Du hattest noch keine Einsätze" in r2.text


def test_nav_link_meine_betreuer_vorhanden(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    _add_year(session)
    fisi = _add_class(session, "FISI 1. LJ")
    t = _add_trainee(session, "Fiona", klasse_id=fisi.id)
    session.commit()

    r = client.post("/auth/dev-login", data={"rolle": "azubi", "trainee_id": t.id}, follow_redirects=False)
    token = r.headers["location"].rsplit("/", 1)[-1]

    r2 = client.get(f"/mein-plan/{token}")
    assert r2.status_code == 200
    assert f'href="/mein-plan/{token}/betreuer"' in r2.text


# ── Konsistenz beider Richtungen (Integrationstest ueber mehrere Faelle) ──

def test_beide_richtungen_konsistent(session: Session):
    fisi = _add_class(session, "FISI 1. LJ")
    fiae = _add_class(session, "FIAE 1. LJ")
    t1 = _add_trainee(session, "Fiona", klasse_id=fisi.id)
    t2 = _add_trainee(session, "Finn", klasse_id=fiae.id)
    t3 = _add_trainee(session, "Ohne", klasse_id=None)
    b1 = Betreuer(upn="b1@firma.de", name="B1", berufe=["FISI"])
    b2 = Betreuer(upn="b2@firma.de", name="B2", berufe=[])
    session.add_all([b1, b2])
    session.commit()
    session.add(BetreuerTrainee(betreuer_id=b1.id, trainee_id=t3.id, modus="ZUSAETZLICH"))
    session.add(BetreuerTrainee(betreuer_id=b2.id, trainee_id=t1.id, modus="AUSGENOMMEN"))
    session.commit()

    alle_trainees = [t1, t2, t3]
    alle_betreuer = [b1, b2]

    for betreuer in alle_betreuer:
        via_trainees = {t.id for t in trainees_fuer_betreuer(session, betreuer, SY)}
        via_betreuer = {
            t.id for t in alle_trainees
            if betreuer in betreuer_fuer_trainee(session, t, SY)
        }
        assert via_trainees == via_betreuer, f"inkonsistent fuer {betreuer.upn}"
