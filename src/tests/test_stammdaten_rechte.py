"""Tests fuer Teil A: Rechte-Nachzug auf den Stammdaten-Routen.

Vorher konnte ein Ausbilder alle Stammdaten-Seiten (Listen + Bearbeiten-
Formulare) OEFFNEN, nur das Speichern scheiterte. Jetzt sind alle GET-Routen
der Stammdaten-Router (Klassen, Abteilungen, Schulplaene, Schulferien,
Lehrjahre, Trainees) auf orga/admin beschraenkt. Ausnahme: das einzelne
Trainee-Profil (GET /trainees/{id}, read-only) bleibt fuer Ausbilder
erreichbar, aber nur fuer Azubis mit einem Abteilungs-Einsatz (typ=ABTEILUNG,
irgendwann: vergangen/laufend/geplant) in einer vom Ausbilder verantworteten
Abteilung (Department.verantwortliche).

Zusaetzlich: Loeschen in den Stammdaten (vorher admin-only) ist jetzt fuer
orga+admin erlaubt, ebenso der Jahresabschluss.

Login-Muster wie in test_meine_abteilung.py / test_role_guards.py:
settings.auth_mode per monkeypatch auf "dev", dann POST /auth/dev-login mit
rolle=.... Dev-Login setzt fuer Staff-Rollen upn="dev@local" (siehe
app/routers/auth.py).
"""
from sqlmodel import Session

from app.config import settings
from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    SchoolHoliday,
    SchoolPlan,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)

SY = "2025-2026"
DEV_UPN = "dev@local"


def _login(client, monkeypatch, rolle: str) -> None:
    monkeypatch.setattr(settings, "auth_mode", "dev")
    r = client.post("/auth/dev-login", data={"rolle": rolle}, follow_redirects=False)
    assert r.status_code == 303


def _add_year(session: Session, sy_id: str = SY, start_year: int = 2025) -> Schoolyear:
    y = Schoolyear(id=sy_id, start_kw=36, start_year=start_year, end_kw=35, end_year=start_year + 1)
    session.add(y)
    session.commit()
    return y


def _add_class(session: Session, name: str = "FISI 1. LJ") -> TraineeClass:
    c = TraineeClass(name=name, berufsschule="JD Schule", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(c)
    session.commit()
    return c


def _add_department(session: Session, code: str = "IT", verantwortliche: str = "") -> Department:
    d = Department(code=code, name=f"{code}-Abteilung", verantwortliche=verantwortliche)
    session.add(d)
    session.commit()
    return d


def _add_holiday(session: Session, sy_id: str = SY) -> SchoolHoliday:
    h = SchoolHoliday(
        schoolyear_id=sy_id, name="Sommerferien",
        start_kw=30, start_year=2026, end_kw=32, end_year=2026,
    )
    session.add(h)
    session.commit()
    return h


def _add_plan(session: Session, klasse_id: int, sy_id: str = SY) -> SchoolPlan:
    p = SchoolPlan(klasse_id=klasse_id, schoolyear_id=sy_id)
    session.add(p)
    session.commit()
    return p


def _add_trainee(session: Session, vorname: str = "Test", nachname: str = "Azubi") -> Trainee:
    t = Trainee(vorname=vorname, nachname=nachname, rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.commit()
    return t


def _add_assignment(
    session: Session, trainee_id: int, dept_id: int,
    kw: int = 40, jahr: int = 2025, sy_id: str = SY,
) -> Assignment:
    a = Assignment(
        trainee_id=trainee_id, schoolyear_id=sy_id, kw=kw, jahr=jahr,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept_id, source=AssignmentSource.MANUAL,
    )
    session.add(a)
    session.commit()
    return a


# ── (1) Ausbilder: 403 auf GET-Listen + GET-Bearbeiten-Formulare ──────────

def test_ausbilder_klassen_liste_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/klassen/")
    assert r.status_code == 403


def test_ausbilder_klassen_bearbeiten_verboten(client, session: Session, monkeypatch):
    c = _add_class(session)
    _login(client, monkeypatch, "ausbilder")
    r = client.get(f"/klassen/{c.id}/bearbeiten")
    assert r.status_code == 403


def test_ausbilder_abteilungen_liste_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/abteilungen/")
    assert r.status_code == 403


def test_ausbilder_abteilungen_bearbeiten_verboten(client, session: Session, monkeypatch):
    d = _add_department(session)
    _login(client, monkeypatch, "ausbilder")
    r = client.get(f"/abteilungen/{d.id}/bearbeiten")
    assert r.status_code == 403


def test_ausbilder_schulplaene_liste_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/schulplaene/")
    assert r.status_code == 403


def test_ausbilder_schulplaene_detail_verboten(client, session: Session, monkeypatch):
    _add_year(session)
    c = _add_class(session)
    p = _add_plan(session, c.id)
    _login(client, monkeypatch, "ausbilder")
    r = client.get(f"/schulplaene/{p.id}")
    assert r.status_code == 403


def test_ausbilder_schulferien_liste_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/schulferien/")
    assert r.status_code == 403


def test_ausbilder_schulferien_bearbeiten_verboten(client, session: Session, monkeypatch):
    _add_year(session)
    h = _add_holiday(session)
    _login(client, monkeypatch, "ausbilder")
    r = client.get(f"/schulferien/{h.id}/bearbeiten")
    assert r.status_code == 403


def test_ausbilder_lehrjahre_liste_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/lehrjahre/")
    assert r.status_code == 403


def test_ausbilder_lehrjahre_bearbeiten_verboten(client, session: Session, monkeypatch):
    y = _add_year(session)
    _login(client, monkeypatch, "ausbilder")
    r = client.get(f"/lehrjahre/{y.id}/bearbeiten")
    assert r.status_code == 403


def test_ausbilder_trainees_liste_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/trainees/")
    assert r.status_code == 403


def test_ausbilder_trainees_neu_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/trainees/neu")
    assert r.status_code == 403


def test_ausbilder_trainees_upn_pflege_verboten(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/trainees/upn-pflege")
    assert r.status_code == 403


def test_ausbilder_trainees_bearbeiten_verboten(client, session: Session, monkeypatch):
    t = _add_trainee(session)
    _login(client, monkeypatch, "ausbilder")
    r = client.get(f"/trainees/{t.id}/bearbeiten")
    assert r.status_code == 403


# ── (2) Trainee-Profil: Ausbilder nur mit Abteilungs-Einsatz in eigener Abt. ──

def test_ausbilder_profil_mit_einsatz_in_eigener_abteilung_erlaubt(client, session: Session, monkeypatch):
    _add_year(session)
    dept = _add_department(session, code="CP", verantwortliche=DEV_UPN)
    t = _add_trainee(session)
    _add_assignment(session, t.id, dept.id)

    _login(client, monkeypatch, "ausbilder")
    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200


def test_ausbilder_profil_ohne_einsatz_verboten(client, session: Session, monkeypatch):
    """Kein Einsatz ueberhaupt -> keine Schnittmenge -> 403."""
    t = _add_trainee(session)
    _login(client, monkeypatch, "ausbilder")
    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 403


def test_ausbilder_profil_nur_fremde_abteilung_verboten(client, session: Session, monkeypatch):
    """Einsatz existiert, aber nur in einer Abteilung, fuer die der Ausbilder
    nicht verantwortlich ist -> 403."""
    _add_year(session)
    foreign = _add_department(session, code="NW", verantwortliche="jemand-anders@firma.de")
    t = _add_trainee(session)
    _add_assignment(session, t.id, foreign.id)

    _login(client, monkeypatch, "ausbilder")
    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 403


def test_orga_profil_ohne_einsatz_erlaubt(client, session: Session, monkeypatch):
    """orga darf jedes Profil oeffnen, unabhaengig von Abteilungs-Einsaetzen."""
    t = _add_trainee(session)
    _login(client, monkeypatch, "orga")
    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200


def test_admin_profil_ohne_einsatz_erlaubt(client, session: Session, monkeypatch):
    t = _add_trainee(session)
    _login(client, monkeypatch, "admin")
    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200


# ── (3) Profil-HTML: Bearbeiten-Link nur fuer orga/admin ──────────────────

def test_profil_zeigt_bearbeiten_link_nicht_fuer_ausbilder(client, session: Session, monkeypatch):
    _add_year(session)
    dept = _add_department(session, code="CP", verantwortliche=DEV_UPN)
    t = _add_trainee(session)
    _add_assignment(session, t.id, dept.id)

    _login(client, monkeypatch, "ausbilder")
    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert f'href="/trainees/{t.id}/bearbeiten"' not in r.text


def test_profil_zeigt_bearbeiten_link_fuer_orga(client, session: Session, monkeypatch):
    t = _add_trainee(session)
    _login(client, monkeypatch, "orga")
    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert f'href="/trainees/{t.id}/bearbeiten"' in r.text


# ── (4) Orga darf loeschen + Jahresabschluss ausfuehren ────────────────────

def test_orga_delete_department_erlaubt(client, session: Session, monkeypatch):
    d = _add_department(session, code="DEL")
    _login(client, monkeypatch, "orga")
    r = client.delete(f"/abteilungen/{d.id}")
    assert r.status_code == 200


def test_orga_jahresabschluss_get_und_post_erlaubt(client, session: Session, monkeypatch):
    _add_year(session)
    _login(client, monkeypatch, "orga")

    r_get = client.get("/jahresabschluss/")
    assert r_get.status_code == 200

    r_post = client.post(
        "/jahresabschluss/abschliessen",
        data={"schoolyear_id": SY},
        follow_redirects=False,
    )
    assert r_post.status_code == 303


# ── (5) Sidebar: "Stammdaten" nicht fuer Ausbilder, aber fuer orga ─────────

def test_sidebar_zeigt_keine_stammdaten_fuer_ausbilder(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/einsaetze/")
    assert r.status_code == 200
    assert "Stammdaten" not in r.text


def test_sidebar_zeigt_stammdaten_fuer_orga(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "orga")
    r = client.get("/einsaetze/")
    assert r.status_code == 200
    assert "Stammdaten" in r.text
