"""Tests fuer Sprint 6: Wochentag-Schule (TAGE_FEST), Multi-Beruf, Klassen-Matrix."""
from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)
from app.routers.assignments import _resolve_range
from app.services.conflict_checker import find_conflicts, ConflictKind
from app.utils.kw import format_weekdays, parse_weekdays

SY = "2025-2026"


# ── Wochentag-Helfer ─────────────────────────────────────────────

def test_parse_weekdays():
    assert parse_weekdays("2,3") == [2, 3]
    assert parse_weekdays("") == []
    assert parse_weekdays("1,4") == [1, 4]


def test_format_weekdays():
    assert format_weekdays("2,3") == "Di, Mi"
    assert format_weekdays("1,4", full=True) == "Montag, Donnerstag"
    assert format_weekdays("2,3", halbtag=3) == "Di, Mi (halbtags)"


# ── Setup ────────────────────────────────────────────────────────

def _tage_fest_class(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    klasse = TraineeClass(name="Büro 1. LJ", berufsschule="KS Karlsruhe",
                          unterrichts_typ=UnterrichtsTyp.TAGE_FEST,
                          schul_wochentage="2,3", halbtag_wochentag=3)
    hr = Department(code="HR", name="Human Resources")
    session.add_all([klasse, hr])
    session.flush()
    t = Trainee(vorname="Uwe", nachname="Ulmer", rolle=TraineeRolle.AZUBI, klasse_id=klasse.id)
    session.add(t)
    session.flush()
    session.commit()
    return {"klasse": klasse.id, "trainee": t.id, "hr": hr.id}


# ── Konflikt-Verhalten ───────────────────────────────────────────

def test_tage_fest_abteilung_no_schul_konflikt(session):
    """ABTEILUNG für eine TAGE_FEST-Klasse erzeugt keinen Schul-Konflikt
    (keine SchoolPlanWeek-Einträge -> Teilzeit-Schule ist der Normalfall)."""
    ids = _tage_fest_class(session)
    session.add(Assignment(trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["hr"],
                           source=AssignmentSource.MANUAL))
    session.commit()
    conflicts = find_conflicts(session, SY)
    assert not any(c.kind == ConflictKind.SCHUL_KONFLIKT for c in conflicts)


def test_tage_fest_urlaub_allowed(session):
    """Urlaub ist für Bürokaufleute immer erlaubt (keine Schulwochen-Sperre)."""
    ids = _tage_fest_class(session)
    to_create, to_override, skipped, pending = _resolve_range(
        session, ids["trainee"], SY, [(40, 2025)], AssignmentTyp.URLAUB, frozenset()
    )
    assert to_create == [(40, 2025)]
    assert not skipped


# ── Modell-Roundtrip ─────────────────────────────────────────────

def test_class_stores_weekdays(session):
    ids = _tage_fest_class(session)
    c = session.get(TraineeClass, ids["klasse"])
    assert c.unterrichts_typ == UnterrichtsTyp.TAGE_FEST
    assert c.schul_wochentage == "2,3"
    assert c.halbtag_wochentag == 3


# ── Klassen-Formular (Route) ─────────────────────────────────────

def test_create_tage_fest_class_via_form(client, session):
    r = client.post("/klassen/", data={
        "name": "Büro 3. LJ", "berufsschule": "KS Karlsruhe",
        "unterrichts_typ": "TAGE_FEST",
        "wochentag": ["1", "4"], "halbtag_wochentag": "",
    }, follow_redirects=False)
    assert r.status_code == 303
    c = session.exec(select(TraineeClass).where(TraineeClass.name == "Büro 3. LJ")).first()
    assert c is not None
    assert c.schul_wochentage == "1,4"
    assert c.halbtag_wochentag is None


def test_block_class_clears_weekdays(client, session):
    """Bei BLOCK_FEST werden versehentlich mitgesendete Wochentage verworfen."""
    r = client.post("/klassen/", data={
        "name": "FISI X", "berufsschule": "JD",
        "unterrichts_typ": "BLOCK_FEST",
        "wochentag": ["2", "3"],
    }, follow_redirects=False)
    assert r.status_code == 303
    c = session.exec(select(TraineeClass).where(TraineeClass.name == "FISI X")).first()
    assert c.schul_wochentage == ""


# ── Admin-Matrix Badge ───────────────────────────────────────────

def test_matrix_shows_school_days_badge(client, session):
    _tage_fest_class(session)
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "school-days-badge" in r.text
    assert "Di, Mi" in r.text


# ── Azubi-Klassen-Matrix ─────────────────────────────────────────

def test_my_class_matrix(client, session):
    ids = _tage_fest_class(session)
    # zweite Person in derselben Klasse + Token für die erste
    t2 = Trainee(vorname="Vera", nachname="Voigt", rolle=TraineeRolle.AZUBI, klasse_id=ids["klasse"])
    session.add(t2)
    t1 = session.get(Trainee, ids["trainee"])
    t1.share_token = "tok-klasse-1"
    session.commit()

    r = client.get("/mein-plan/tok-klasse-1/klasse")
    assert r.status_code == 200
    assert "Voigt" in r.text          # Klassenkamerad:in sichtbar
    assert "Ulmer" in r.text          # man selbst
    assert "is-self" in r.text        # eigene Zeile hervorgehoben
    assert "Schultage der Klasse" in r.text


def test_my_class_no_class(client, session):
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    t = Trainee(vorname="Karl", nachname="Ohne", rolle=TraineeRolle.PRAKTIKANT,
                klasse_id=None, share_token="tok-ohne")
    session.add(t)
    session.commit()
    r = client.get("/mein-plan/tok-ohne/klasse")
    assert r.status_code == 200
    assert "keiner Klasse zugeordnet" in r.text
