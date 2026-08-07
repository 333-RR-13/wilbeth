"""Tests fuer Teil C -- Ausbilder-Notizen ueber den Azubi (TraineeNotiz).

Login-Muster wie in tests/test_meine_abteilung.py (_dev_mode/_login,
DEV_UPN = "dev@local"). Deckt ab: Anlage mit/ohne Einsatz-Kontext, Rechte
(orga/admin frei, ausbilder nur mit Abteilungs-Bezug), chronologische
Sortierung im Profil-HTML, dass der Azubi-Bereich (/mein-plan/...) davon
nichts zeigt, sowie Loeschrechte (Verfasser/admin).
"""
from datetime import date

from sqlmodel import Session, select

from app.config import settings
from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    Schoolyear,
    Trainee,
    TraineeNotiz,
    TraineeRolle,
)

SY = "2025-2026"
DEV_UPN = "dev@local"


def _dev_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "dev")


def _login(client, rolle: str, trainee_id: str = ""):
    data = {"rolle": rolle}
    if trainee_id:
        data["trainee_id"] = trainee_id
    r = client.post("/auth/dev-login", data=data, follow_redirects=False)
    assert r.status_code == 303
    return r


def _setup(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    own_dept = Department(code="CP", name="Cloud Platform", verantwortliche=DEV_UPN)
    foreign_dept = Department(code="NW", name="Netzwerk", verantwortliche="jemand-anders@firma.de")
    session.add_all([own_dept, foreign_dept])
    session.flush()
    t = Trainee(vorname="Jonas", nachname="Jäger", rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.flush()
    session.commit()
    return {"trainee": t.id, "own": own_dept.id, "foreign": foreign_dept.id}


def _make_assignment(session: Session, trainee_id: int, dept_id: int, kw: int, jahr: int = 2025) -> Assignment:
    a = Assignment(
        trainee_id=trainee_id, schoolyear_id=SY, kw=kw, jahr=jahr,
        typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept_id, source=AssignmentSource.MANUAL,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


# ── POST /meine-abteilung/notiz (Block-Kontext) ─────────────────────────────

def test_post_meine_abteilung_notiz_setzt_kontext(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/notiz", data={
        "trainee_id": ids["trainee"],
        "department_id": ids["own"],
        "schoolyear_id": SY,
        "kw_von": 40,
        "jahr_von": 2025,
        "kw_bis": 42,
        "jahr_bis": 2025,
        "text": "Guter Start im Team",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/meine-abteilung/?msg=created")

    rows = session.exec(select(TraineeNotiz)).all()
    assert len(rows) == 1
    n = rows[0]
    assert n.trainee_id == ids["trainee"]
    assert n.department_id == ids["own"]
    assert n.kw_von == 40
    assert n.jahr_von == 2025
    assert n.kw_bis == 42
    assert n.jahr_bis == 2025
    assert n.text == "Guter Start im Team"
    assert n.verfasser_upn == DEV_UPN


# ── POST /trainees/{id}/notizen (Profil, ohne Kontext) ──────────────────────

def test_post_trainee_notizen_ohne_kontext(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _make_assignment(session, ids["trainee"], ids["own"], 40)
    _login(client, "ausbilder")

    r = client.post(f"/trainees/{ids['trainee']}/notizen", data={
        "text": "Direkt im Profil notiert",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/trainees/{ids['trainee']}?msg=created"

    rows = session.exec(select(TraineeNotiz)).all()
    assert len(rows) == 1
    assert rows[0].department_id is None
    assert rows[0].text == "Direkt im Profil notiert"


# ── Ausbilder ohne Abteilungs-Verbindung -> 403 (beide Routen) ──────────────

def test_ausbilder_ohne_verbindung_bekommt_403_ueber_profil_route(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    # Trainee hat NUR einen Einsatz in der fremden Abteilung
    _make_assignment(session, ids["trainee"], ids["foreign"], 40)
    _login(client, "ausbilder")

    r = client.post(f"/trainees/{ids['trainee']}/notizen", data={"text": "Verboten"})
    assert r.status_code == 403
    assert session.exec(select(TraineeNotiz)).first() is None


def test_ausbilder_fremde_department_id_bekommt_403_ueber_block_route(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/notiz", data={
        "trainee_id": ids["trainee"],
        "department_id": ids["foreign"],
        "schoolyear_id": SY,
        "kw_von": 40,
        "jahr_von": 2025,
        "kw_bis": 40,
        "jahr_bis": 2025,
        "text": "Verboten",
    })
    assert r.status_code == 403
    assert session.exec(select(TraineeNotiz)).first() is None


# ── Orga/Admin duerfen JEDEM Trainee eine Notiz anlegen ─────────────────────

def test_orga_und_admin_duerfen_ohne_abteilungsverbindung_notiz_anlegen(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    # Trainee hat KEINE Einsaetze ueberhaupt -> keine Abteilungs-Verbindung

    for rolle in ("orga", "admin"):
        _login(client, rolle)
        r = client.post(f"/trainees/{ids['trainee']}/notizen", data={
            "text": f"Notiz von {rolle}",
        }, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == f"/trainees/{ids['trainee']}?msg=created"

    rows = session.exec(select(TraineeNotiz)).all()
    assert len(rows) == 2


# ── Chronologische Sortierung im Profil-HTML ────────────────────────────────

def test_notizen_erscheinen_chronologisch_absteigend(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    session.add_all([
        TraineeNotiz(
            trainee_id=ids["trainee"], text="ALTERE_NOTIZ_TEXT",
            verfasser_upn=DEV_UPN, verfasser_name="Alt", erstellt_am=date(2025, 1, 1),
        ),
        TraineeNotiz(
            trainee_id=ids["trainee"], text="NEUERE_NOTIZ_TEXT",
            verfasser_upn=DEV_UPN, verfasser_name="Neu", erstellt_am=date(2025, 6, 1),
        ),
    ])
    session.commit()
    _login(client, "orga")

    r = client.get(f"/trainees/{ids['trainee']}")
    assert r.status_code == 200
    assert "ALTERE_NOTIZ_TEXT" in r.text
    assert "NEUERE_NOTIZ_TEXT" in r.text
    # neuere zuerst
    assert r.text.index("NEUERE_NOTIZ_TEXT") < r.text.index("ALTERE_NOTIZ_TEXT")


# ── Azubi-Sicht: Notiz-Text erscheint NIRGENDS unter /mein-plan/... ─────────

def test_azubi_sieht_notiz_text_nirgends(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    t = session.get(Trainee, ids["trainee"])
    t.share_token = "test-token-notiz-geheim"
    session.add(t)
    session.add(TraineeNotiz(
        trainee_id=ids["trainee"], text="GEHEIMER_AUSBILDER_NOTIZ_TEXT_XYZ",
        verfasser_upn=DEV_UPN, verfasser_name="Ausbilder", erstellt_am=date(2025, 6, 1),
    ))
    session.commit()

    token = t.share_token
    r1 = client.get(f"/mein-plan/{token}")
    assert r1.status_code == 200
    assert "GEHEIMER_AUSBILDER_NOTIZ_TEXT_XYZ" not in r1.text

    r2 = client.get(f"/mein-plan/{token}/klasse")
    assert r2.status_code == 200
    assert "GEHEIMER_AUSBILDER_NOTIZ_TEXT_XYZ" not in r2.text

    r3 = client.get(f"/mein-plan/{token}/wuensche")
    assert r3.status_code == 200
    assert "GEHEIMER_AUSBILDER_NOTIZ_TEXT_XYZ" not in r3.text


# ── Loeschen: nur Verfasser selbst oder admin ───────────────────────────────

def test_loeschen_nur_verfasser_oder_admin(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)

    # Verfasser (dev@local als ausbilder) legt eine eigene Notiz an
    _login(client, "ausbilder")
    session.add(TraineeNotiz(
        trainee_id=ids["trainee"], text="Eigene Notiz",
        verfasser_upn=DEV_UPN, verfasser_name="Ausbilder Eins", erstellt_am=date(2025, 6, 1),
    ))
    session.commit()
    own_notiz = session.exec(select(TraineeNotiz)).first()

    # Verfasser loescht eigene Notiz -> ok
    r = client.post(
        f"/trainees/{ids['trainee']}/notizen/{own_notiz.id}/loeschen",
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/trainees/{ids['trainee']}?msg=deleted"
    session.expire_all()
    assert session.get(TraineeNotiz, own_notiz.id) is None

    # Fremde Notiz eines ANDEREN Verfassers -> 403 fuer den (weiterhin
    # eingeloggten) Ausbilder dev@local
    fremde = TraineeNotiz(
        trainee_id=ids["trainee"], text="Fremde Notiz",
        verfasser_upn="andere.person@firma.de", verfasser_name="Andere Person",
        erstellt_am=date(2025, 6, 1),
    )
    session.add(fremde)
    session.commit()
    session.refresh(fremde)

    r2 = client.post(f"/trainees/{ids['trainee']}/notizen/{fremde.id}/loeschen")
    assert r2.status_code == 403
    session.expire_all()
    assert session.get(TraineeNotiz, fremde.id) is not None

    # admin darf jede Notiz loeschen
    _login(client, "admin")
    r3 = client.post(
        f"/trainees/{ids['trainee']}/notizen/{fremde.id}/loeschen",
        follow_redirects=False,
    )
    assert r3.status_code == 303
    session.expire_all()
    assert session.get(TraineeNotiz, fremde.id) is None


# ── Migrationsnahe Konsistenzpruefung auf Modellebene ───────────────────────

def test_trainee_mit_altem_notizen_feld_bleibt_ueber_sqlmodel_anlegbar(session):
    """Die Spalte trainee.notizen existiert im Modell weiterhin (kein Drop) --
    auch wenn UI/Router sie nicht mehr befuellen, darf ein Trainee mit
    gefuelltem notizen-Feld weiterhin ganz normal ueber SQLModel angelegt
    werden koennen (z. B. Altdaten, Import, Migrationslauf)."""
    t = Trainee(
        vorname="Bestand", nachname="Trainee", rolle=TraineeRolle.AZUBI,
        notizen="Alte Freitext-Notiz aus Stammdaten",
    )
    session.add(t)
    session.commit()
    session.refresh(t)
    assert t.notizen == "Alte Freitext-Notiz aus Stammdaten"
