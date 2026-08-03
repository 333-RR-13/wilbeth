"""Tests fuer /feedback/ (Feedbackboegen-Staff-UI): Sichtbarkeit je Rolle,
Anlegen des AUSBILDER-Bogens, Status-Workflow und Fehlzeiten-Vorbelegung.

Login-Muster wie in test_meine_abteilung.py: settings.auth_mode per
monkeypatch auf "dev", dann POST /auth/dev-login mit rolle=ausbilder/orga/
admin. Dev-Login setzt fuer Staff-Rollen upn="dev@local"; allowed_dept_ids()
matcht Department.verantwortliche gegen diese UPN.
"""
from datetime import date, timedelta

from sqlmodel import Session, select

from app.config import settings
from app.models import (
    Abwesenheit,
    AbwesenheitQuelle,
    AbwesenheitTyp,
    Department,
    FeedbackBogen,
    Schoolyear,
    Trainee,
    TraineeRolle,
)
from app.utils.kw import kw_to_monday

SY = "2025-2026"
DEV_UPN = "dev@local"


def _dev_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "dev")


def _login(client, rolle: str):
    r = client.post("/auth/dev-login", data={"rolle": rolle}, follow_redirects=False)
    assert r.status_code == 303
    return r


def _setup(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    own_dept = Department(code="CP", name="Cloud Platform", verantwortliche=DEV_UPN)
    foreign_dept = Department(code="NW", name="Netzwerk", verantwortliche="jemand-anders@firma.de")
    session.add_all([own_dept, foreign_dept])
    session.flush()
    t = Trainee(
        vorname="Jonas", nachname="Jäger", rolle=TraineeRolle.AZUBI, aktiv=True,
        ausbildungsbeginn=date(2025, 9, 1),
    )
    session.add(t)
    session.flush()
    session.commit()
    return {"trainee": t.id, "own": own_dept.id, "foreign": foreign_dept.id}


def _make_bogen(session, typ, trainee_id, dept_id, status="entwurf"):
    b = FeedbackBogen(
        typ=typ, trainee_id=trainee_id, department_id=dept_id, schoolyear_id=SY,
        kw_von=10, jahr_von=2026, kw_bis=14, jahr_bis=2026,
        status=status, erstellt_am=date.today(),
    )
    session.add(b)
    session.commit()
    session.refresh(b)
    return b


def _neu_url(ids, **overrides) -> str:
    params = {
        "trainee_id": ids["trainee"], "department_id": ids["own"], "schoolyear_id": SY,
        "kw_von": 10, "jahr_von": 2026, "kw_bis": 14, "jahr_bis": 2026,
    }
    params.update(overrides)
    return "/feedback/neu?" + "&".join(f"{k}={v}" for k, v in params.items())


def _create_data(ids, **overrides) -> dict:
    data = {
        "trainee_id": ids["trainee"], "department_id": ids["own"], "schoolyear_id": SY,
        "kw_von": 10, "jahr_von": 2026, "kw_bis": 14, "jahr_bis": 2026,
        "einsatzart": "Ersteinsatz", "fachausbilder_name": "Trainer Tom",
        "action": "entwurf",
    }
    data.update(overrides)
    return data


def _bogen_id_from_location(location: str) -> int:
    return int(location.split("/feedback/")[1].split("?")[0])


# ── (a) Ausbilder sieht nur eigene Abteilung; fremder Bogen -> 403 ─────────

def test_ausbilder_sieht_nur_eigene_boegen(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    own_bogen = _make_bogen(session, "AUSBILDER", ids["trainee"], ids["own"])
    foreign_bogen = _make_bogen(session, "AUSBILDER", ids["trainee"], ids["foreign"])

    _login(client, "ausbilder")

    r = client.get("/feedback/")
    assert r.status_code == 200
    assert f'data-href="/feedback/{own_bogen.id}"' in r.text
    assert f'data-href="/feedback/{foreign_bogen.id}"' not in r.text

    r2 = client.get(f"/feedback/{foreign_bogen.id}")
    assert r2.status_code == 403


# ── (b) orga sieht alle Boegen ──────────────────────────────────────────────

def test_orga_sieht_alle_boegen(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    own_bogen = _make_bogen(session, "AUSBILDER", ids["trainee"], ids["own"])
    foreign_bogen = _make_bogen(session, "AUSBILDER", ids["trainee"], ids["foreign"])

    _login(client, "orga")

    r = client.get("/feedback/")
    assert r.status_code == 200
    assert f'data-href="/feedback/{own_bogen.id}"' in r.text
    assert f'data-href="/feedback/{foreign_bogen.id}"' in r.text

    r2 = client.get(f"/feedback/{foreign_bogen.id}")
    assert r2.status_code == 200


# ── (c) Anlegen fuer fremde Abteilung -> 403 ────────────────────────────────

def test_post_create_und_get_neu_foreign_department_forbidden(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)

    _login(client, "ausbilder")

    r_get = client.get(_neu_url(ids, department_id=ids["foreign"]))
    assert r_get.status_code == 403

    r_post = client.post("/feedback/", data=_create_data(ids, department_id=ids["foreign"]))
    assert r_post.status_code == 403
    assert session.exec(select(FeedbackBogen)).first() is None


# ── (d) Statusuebergaenge + Rollen-Einschraenkungen ────────────────────────

def test_status_workflow_and_role_restrictions(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)

    _login(client, "ausbilder")

    r = client.post("/feedback/", data=_create_data(ids), follow_redirects=False)
    assert r.status_code == 303
    bogen_id = _bogen_id_from_location(r.headers["location"])

    session.expire_all()
    assert session.get(FeedbackBogen, bogen_id).status == "entwurf"

    # entwurf -> abgeschlossen
    r2 = client.post(
        f"/feedback/{bogen_id}",
        data=_create_data(ids, action="abschliessen"),
        follow_redirects=False,
    )
    assert r2.status_code == 303
    session.expire_all()
    assert session.get(FeedbackBogen, bogen_id).status == "abgeschlossen"

    # abgeschlossen -> besprochen
    r3 = client.post(
        f"/feedback/{bogen_id}/besprochen",
        data={"besprochen_am": "2026-03-10"},
        follow_redirects=False,
    )
    assert r3.status_code == 303
    session.expire_all()
    bogen = session.get(FeedbackBogen, bogen_id)
    assert bogen.status == "besprochen"
    assert bogen.besprochen_am == date(2026, 3, 10)

    # reopen/loeschen als Ausbilder -> 403
    assert client.post(f"/feedback/{bogen_id}/reopen").status_code == 403
    assert client.post(f"/feedback/{bogen_id}/loeschen").status_code == 403

    # reopen als orga -> erlaubt (Korrektur)
    _login(client, "orga")
    r4 = client.post(f"/feedback/{bogen_id}/reopen", follow_redirects=False)
    assert r4.status_code == 303
    session.expire_all()
    bogen = session.get(FeedbackBogen, bogen_id)
    assert bogen.status == "entwurf"
    assert bogen.besprochen_am is None

    # loeschen als orga -> 403 (nur admin)
    assert client.post(f"/feedback/{bogen_id}/loeschen").status_code == 403

    # loeschen als admin -> erlaubt
    _login(client, "admin")
    r5 = client.post(f"/feedback/{bogen_id}/loeschen", follow_redirects=False)
    assert r5.status_code == 303
    session.expire_all()
    assert session.get(FeedbackBogen, bogen_id) is None


# ── (e) /feedback/neu uebernimmt Fehlzeiten-Vorbelegung ────────────────────

def test_neu_uebernimmt_fehlzeiten_vorbelegung(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    # Urlaub ist jetzt eine Abwesenheit (Overlay), kein Assignment mehr.
    # Volle KW 11/2026 (5 Werktage) im abgefragten Zeitraum (KW 10-14/2026).
    montag = kw_to_monday(11, 2026)
    session.add(Abwesenheit(
        trainee_id=ids["trainee"], von_datum=montag, bis_datum=montag + timedelta(days=4),
        typ=AbwesenheitTyp.URLAUB, quelle=AbwesenheitQuelle.SELBST,
    ))
    session.commit()

    _login(client, "ausbilder")

    r = client.get(_neu_url(ids))
    assert r.status_code == 200
    # Fehlzeiten jetzt in TAGEN: 1 volle Woche = 5 Werktage
    assert 'id="fehl_urlaub" name="fehl_urlaub" min="0" value="5"' in r.text


def test_neu_uebernimmt_fehlzeiten_vorbelegung_sonstige(client, session, monkeypatch):
    """fehl_sonstige wird jetzt ebenfalls aus Abwesenheiten (typ=SONSTIGES)
    in Tagen vorbelegt."""
    _dev_mode(monkeypatch)
    ids = _setup(session)
    # SONSTIGES-Abwesenheit Mo-Mi (3 Werktage) in KW 12/2026
    montag = kw_to_monday(12, 2026)
    session.add(Abwesenheit(
        trainee_id=ids["trainee"], von_datum=montag, bis_datum=montag + timedelta(days=2),
        typ=AbwesenheitTyp.SONSTIGES, quelle=AbwesenheitQuelle.PLANER,
    ))
    session.commit()

    _login(client, "ausbilder")

    r = client.get(_neu_url(ids))
    assert r.status_code == 200
    assert 'id="fehl_sonstige" name="fehl_sonstige" min="0" value="3"' in r.text


# ── (f) Update im Status abgeschlossen -> abgelehnt ────────────────────────

def test_update_im_status_abgeschlossen_wird_abgelehnt(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    bogen = _make_bogen(session, "AUSBILDER", ids["trainee"], ids["own"], status="abgeschlossen")

    _login(client, "ausbilder")

    r = client.post(
        f"/feedback/{bogen.id}",
        data=_create_data(ids, einsatzart="Folgeeinsatz", fachausbilder_name="Anderer Name"),
    )
    assert r.status_code == 400

    session.expire_all()
    unchanged = session.get(FeedbackBogen, bogen.id)
    assert unchanged.status == "abgeschlossen"
    assert unchanged.einsatzart == ""
    assert unchanged.fachausbilder_name == ""


# ── Zusatz: Anlegen mit Lernzielen + Kompetenz-Antworten (Rundlauf) ────────

def test_create_mit_lernzielen_und_antworten_rundlauf(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)

    _login(client, "ausbilder")

    data = _create_data(
        ids,
        frage_komm_ausdruck="4",
        kommentar_lernziele="Alles gut gelaufen",
        weiterer_einsatz="ja",
        zugriffe_geloescht="on",
        action="abschliessen",
    )
    data["lernziel_text"] = ["Python lernen", "Docker verstehen"]
    data["lernziel_wert"] = ["5", ""]

    r = client.post("/feedback/", data=data, follow_redirects=False)
    assert r.status_code == 303
    bogen_id = _bogen_id_from_location(r.headers["location"])

    session.expire_all()
    bogen = session.get(FeedbackBogen, bogen_id)
    assert bogen.status == "abgeschlossen"
    assert bogen.antworten == {"komm_ausdruck": 4}
    assert bogen.lernziele == [
        {"text": "Python lernen", "bewertung": 5},
        {"text": "Docker verstehen", "bewertung": None},
    ]
    assert bogen.zugriffe_geloescht is True
    assert bogen.weiterer_einsatz == "ja"
    assert bogen.freitexte.get("kommentar_lernziele") == "Alles gut gelaufen"

    r2 = client.get(f"/feedback/{bogen_id}")
    assert r2.status_code == 200
    assert "Python lernen" in r2.text
    assert "Anforderungen teilweise übertroffen" in r2.text


# ── Review-Fixes: AZUBI-Boegen gehoeren dem Azubi ───────────────────────────

def test_azubi_entwurf_fuer_staff_unsichtbar(client, session, monkeypatch):
    """AZUBI-Boegen im Status 'entwurf' sind privat: tauchen nicht in der
    Staff-Liste auf, Detail liefert 404 -- ab 'abgeschlossen' read-only
    sichtbar (symmetrisch zum AUSBILDER-Entwurf, den der Azubi nicht sieht)."""
    _dev_mode(monkeypatch)
    ids = _setup(session)
    bogen = _make_bogen(session, "AZUBI", ids["trainee"], ids["own"], status="entwurf")

    _login(client, "orga")
    r = client.get("/feedback/")
    assert r.status_code == 200
    assert f'data-href="/feedback/{bogen.id}"' not in r.text
    assert client.get(f"/feedback/{bogen.id}").status_code == 404

    bogen.status = "abgeschlossen"
    session.add(bogen)
    session.commit()
    r2 = client.get("/feedback/")
    assert f'data-href="/feedback/{bogen.id}"' in r2.text
    assert client.get(f"/feedback/{bogen.id}").status_code == 200


def test_azubi_bogen_nicht_durch_staff_bearbeitbar(client, session, monkeypatch):
    """Staff darf die Selbsteinschaetzung des Azubis NIE inhaltlich aendern
    oder in dessen Namen abschliessen -> POST /feedback/{id} ergibt 403."""
    _dev_mode(monkeypatch)
    ids = _setup(session)
    bogen = _make_bogen(session, "AZUBI", ids["trainee"], ids["own"], status="entwurf")

    _login(client, "admin")
    r = client.post(f"/feedback/{bogen.id}", data={
        "action": "abschliessen", "highlight": "vom Ausbilder untergeschoben",
    }, follow_redirects=False)
    assert r.status_code == 403

    session.expire_all()
    updated = session.get(FeedbackBogen, bogen.id)
    assert updated.status == "entwurf"
    assert updated.freitexte in (None, {})


def test_doppelanlage_ausbilder_bogen_leitet_um(client, session, monkeypatch):
    """Zweiter POST fuer denselben Block (Doppel-Submit/zweiter Ausbilder)
    legt KEINEN zweiten AUSBILDER-Bogen an, sondern leitet auf den
    bestehenden um."""
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _login(client, "ausbilder")

    r1 = client.post("/feedback/", data=_create_data(ids), follow_redirects=False)
    assert r1.status_code == 303
    erste_id = _bogen_id_from_location(r1.headers["location"])

    # Zweiter Versuch mit ueberlappendem (Teil-)Zeitraum
    r2 = client.post("/feedback/", data=_create_data(ids, kw_von=11, kw_bis=13), follow_redirects=False)
    assert r2.status_code == 303
    assert _bogen_id_from_location(r2.headers["location"]) == erste_id

    count = len(session.exec(
        select(FeedbackBogen).where(FeedbackBogen.typ == "AUSBILDER")
    ).all())
    assert count == 1
