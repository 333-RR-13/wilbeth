"""Tests fuer /meine-abteilung/ (Ausbilder-Selbstbedienung: Bloecke bestaetigen
+ Einsatz vorschlagen) sowie den differenzierten Login-Redirect fuer Ausbilder.

Dev-Login setzt fuer Staff-Rollen upn="dev@local" (siehe app/routers/auth.py).
allowed_dept_ids() matcht Department.verantwortliche gegen die UPN.
"""
from sqlmodel import Session, select

from app.config import settings
from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    EinsatzVorschlag,
    Schoolyear,
    Trainee,
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


# ── (a) Ausbilder mit verantworteter Abteilung sieht Bloecke ────────────────

def test_ausbilder_sees_blocks_of_own_department(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _make_assignment(session, ids["trainee"], ids["own"], 40)
    _make_assignment(session, ids["trainee"], ids["own"], 41)

    _login(client, "ausbilder")

    r = client.get(f"/meine-abteilung/?schoolyear_id={SY}")
    assert r.status_code == 200
    assert "CP" in r.text
    assert "Cloud Platform" in r.text
    assert "Jäger" in r.text
    assert "KW 40/2025" in r.text
    assert "KW 41/2025" in r.text


# ── (b) POST /block bestaetigt alle Zellen des Blocks ───────────────────────

def test_post_block_bestaetigt_all_cells(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    a1 = _make_assignment(session, ids["trainee"], ids["own"], 40)
    a2 = _make_assignment(session, ids["trainee"], ids["own"], 41)

    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/block", data={
        "assignment_ids": f"{a1.id},{a2.id}",
        "aktion": "bestaetigt",
        "notiz": "Passt",
        "feedback": "",
        "schoolyear_id": SY,
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    updated1 = session.get(Assignment, a1.id)
    updated2 = session.get(Assignment, a2.id)
    assert updated1.bestaetigung == "bestaetigt"
    assert updated2.bestaetigung == "bestaetigt"
    assert updated1.notiz == "Passt"


# ── (c) fremde Abteilung -> 403 ──────────────────────────────────────────────

def test_post_block_foreign_department_forbidden(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    a = _make_assignment(session, ids["trainee"], ids["foreign"], 40)

    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/block", data={
        "assignment_ids": str(a.id),
        "aktion": "bestaetigt",
        "notiz": "",
        "feedback": "",
        "schoolyear_id": SY,
    })
    assert r.status_code == 403

    session.expire_all()
    unchanged = session.get(Assignment, a.id)
    assert unchanged.bestaetigung == "offen"


# ── (d) ohne Zuordnung -> Hinweis ────────────────────────────────────────────

def test_ausbilder_without_department_sees_hint(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    session.add(Department(code="NW", name="Netzwerk", verantwortliche="jemand-anders@firma.de"))
    session.commit()

    _login(client, "ausbilder")

    r = client.get("/meine-abteilung/")
    assert r.status_code == 200
    assert "keine Abteilung zugeordnet" in r.text
    assert DEV_UPN in r.text


# ── (e) POST /vorschlag legt Vorschlag an ────────────────────────────────────

def test_post_vorschlag_creates_einsatz_vorschlag(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)

    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/vorschlag", data={
        "trainee_id": ids["trainee"],
        "department_id": ids["own"],
        "schoolyear_id": SY,
        "von": "10,2026",
        "bis": "12,2026",
        "kommentar": "Bitte einplanen",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/meine-abteilung/?msg=created")

    rows = session.exec(select(EinsatzVorschlag)).all()
    assert len(rows) == 1
    v = rows[0]
    assert v.trainee_id == ids["trainee"]
    assert v.department_id == ids["own"]
    assert v.status == "offen"
    assert v.eingereicht_von_upn == DEV_UPN
    assert v.kommentar == "Bitte einplanen"


def test_post_vorschlag_foreign_department_forbidden(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)

    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/vorschlag", data={
        "trainee_id": ids["trainee"],
        "department_id": ids["foreign"],
        "schoolyear_id": SY,
        "von": "10,2026",
        "bis": "12,2026",
        "kommentar": "",
    })
    assert r.status_code == 403
    assert session.exec(select(EinsatzVorschlag)).first() is None


# ── (e2) Vorschlag-Formular: KW-Selects statt Handeingabe ────────────────────

def test_meine_abteilung_zeigt_kw_selects_statt_freitextfelder(client, session, monkeypatch):
    """Die frueheren Zahl-Eingabefelder (kw_von/jahr_von/kw_bis/jahr_bis) sind
    weg -- stattdessen ein Ausbildungsjahr-Select sowie 'von'/'bis'-Wochen-
    Selects, deren Optionen genau die Wochen des gewaehlten Schuljahres
    abdecken (SY 2025-2026 = KW36/2025 .. KW35/2026)."""
    _dev_mode(monkeypatch)
    _setup(session)
    _login(client, "ausbilder")

    r = client.get(f"/meine-abteilung/?schoolyear_id={SY}")
    assert r.status_code == 200
    assert 'id="vor-schoolyear"' in r.text
    assert 'id="vor-kw-von"' in r.text
    assert 'id="vor-kw-bis"' in r.text
    assert 'name="kw_von"' not in r.text
    assert 'name="jahr_von"' not in r.text
    # Erste und letzte Woche des Schuljahres sind als Option vorhanden
    assert 'value="36,2025"' in r.text
    assert 'value="35,2026"' in r.text
    assert "KW 36 / 2025" in r.text
    # Wochen aller Schuljahre stehen fuers JS-Nachladen ohne Server-Roundtrip zur Verfuegung
    assert "WEEKS_BY_YEAR" in r.text


def test_post_vorschlag_bis_vor_von_ergibt_400(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/vorschlag", data={
        "trainee_id": ids["trainee"],
        "department_id": ids["own"],
        "schoolyear_id": SY,
        "von": "12,2026",
        "bis": "10,2026",
        "kommentar": "",
    })
    assert r.status_code == 400
    assert session.exec(select(EinsatzVorschlag)).first() is None


def test_post_vorschlag_ungueltige_kw_ergibt_400_kein_500(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/vorschlag", data={
        "trainee_id": ids["trainee"],
        "department_id": ids["own"],
        "schoolyear_id": SY,
        "von": "nicht-numerisch",
        "bis": "12,2026",
        "kommentar": "",
    })
    assert r.status_code == 400
    assert session.exec(select(EinsatzVorschlag)).first() is None


# ── (f) azubi-Rolle kommt nicht auf die Seite ────────────────────────────────

def test_azubi_cannot_reach_meine_abteilung(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    t = Trainee(vorname="Anna", nachname="Azubi", rolle=TraineeRolle.AZUBI, aktiv=True)
    session.add(t)
    session.commit()
    session.refresh(t)

    _login(client, "azubi", trainee_id=str(t.id))

    r = client.get("/meine-abteilung/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/mein-plan/")


# ── (g) Login-Redirect: dev-login ausbilder -> /meine-abteilung/ ────────────

def test_dev_login_ausbilder_redirects_to_meine_abteilung(client, monkeypatch):
    _dev_mode(monkeypatch)

    r = client.post("/auth/dev-login", data={"rolle": "ausbilder"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/meine-abteilung/"


# ── (h) Infoseite pflegen (POST /meine-abteilung/infoseite) ─────────────────

def test_ausbilder_speichert_infoseite_der_eigenen_abteilung(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/infoseite", data={
        "department_id": ids["own"],
        "info_text": "Neuer Infotext fuer Azubis",
        "info_link": "https://confluence.example.com/cp",
        "schoolyear_id": SY,
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/meine-abteilung/?msg=updated")

    session.expire_all()
    dept = session.get(Department, ids["own"])
    assert dept.info_text == "Neuer Infotext fuer Azubis"
    assert dept.info_link == "https://confluence.example.com/cp"


def test_ausbilder_speichert_infoseite_fremder_abteilung_ergibt_403(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/infoseite", data={
        "department_id": ids["foreign"],
        "info_text": "Sollte nicht gespeichert werden",
        "info_link": "",
    })
    assert r.status_code == 403

    session.expire_all()
    dept = session.get(Department, ids["foreign"])
    assert dept.info_text == ""


def test_infoseite_ungueltiger_link_ergibt_400(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _login(client, "ausbilder")

    r = client.post("/meine-abteilung/infoseite", data={
        "department_id": ids["own"],
        "info_text": "",
        "info_link": "javascript:alert(1)",
    })
    assert r.status_code == 400

    session.expire_all()
    dept = session.get(Department, ids["own"])
    assert dept.info_link == ""


def test_orga_darf_infoseite_jeder_abteilung_speichern(client, session, monkeypatch):
    """Abweichend von block_action/create_vorschlag: orga/admin duerfen die
    Infoseite JEDER Abteilung pflegen, nicht nur eigene (siehe Projektauftrag)."""
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _login(client, "orga")

    r = client.post("/meine-abteilung/infoseite", data={
        "department_id": ids["foreign"],
        "info_text": "Von Orga gepflegt",
        "info_link": "",
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    dept = session.get(Department, ids["foreign"])
    assert dept.info_text == "Von Orga gepflegt"


# ── (i) Neue Seitenstruktur: Einstellungen -> Einsatzliste -> Vorschlagen ───
#        -> Meine Vorschlaege (siehe Projektauftrag Punkt 3) ────────────────

def test_meine_abteilung_reihenfolge_der_abschnitte(client, session, monkeypatch):
    """Einsatzliste (Bloecke) steht vor 'Einsatz vorschlagen' vor
    'Meine Vorschlaege'. Das fruehere Infoseiten-Formular OBEN in jeder
    Abteilungs-Karte ist weg -- es steckt jetzt im Einstellungen-Bereich vor
    den Karten."""
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _make_assignment(session, ids["trainee"], ids["own"], 40)

    _login(client, "ausbilder")

    r = client.get(f"/meine-abteilung/?schoolyear_id={SY}")
    assert r.status_code == 200
    html = r.text

    idx_einstellungen = html.index("Einstellungen")
    idx_einsatzliste = html.index("KW 40/2025")
    idx_vorschlagen = html.index("Einsatz vorschlagen")
    idx_meine_vorschlaege = html.index("Meine Vorschläge")

    assert idx_einstellungen < idx_einsatzliste < idx_vorschlagen < idx_meine_vorschlaege


def test_meine_abteilung_infotext_form_steckt_im_einstellungen_bereich(client, session, monkeypatch):
    """Das Infoseiten-Formular (Textarea + Link) liegt VOR der Einsatzliste
    (im Einstellungen-Bereich), nicht mehr in der Abteilungs-Karte selbst."""
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _make_assignment(session, ids["trainee"], ids["own"], 40)

    _login(client, "ausbilder")

    r = client.get(f"/meine-abteilung/?schoolyear_id={SY}")
    html = r.text

    idx_infotext_feld = html.index('name="info_text"')
    idx_einsatzliste = html.index("KW 40/2025")
    assert idx_infotext_feld < idx_einsatzliste


def test_meine_abteilung_einstellungen_startet_zugeklappt(client, session, monkeypatch):
    """<details> ohne 'open'-Attribut -- der Einstellungen-Bereich ist beim
    ersten Aufruf zu (kein 'display' auf .settings-body, das die native
    <details>-Ausblendung ueberschreiben wuerde -- siehe Kommentar im
    Template)."""
    _dev_mode(monkeypatch)
    ids = _setup(session)
    _make_assignment(session, ids["trainee"], ids["own"], 40)

    _login(client, "ausbilder")

    r = client.get(f"/meine-abteilung/?schoolyear_id={SY}")
    html = r.text

    assert '<details class="settings-details">' in html
    assert '<details class="settings-details" open>' not in html
    # Inhalt ist trotzdem im HTML vorhanden (kein-JS-Fallback ueber <details>) --
    # nur die native Renderlogik blendet ihn zu, solange nicht 'open' gesetzt ist.
    assert 'name="info_text"' in html


# ── (j) Kopfzeile zaehlt offene eigene Vorschlaege mit ───────────────────────

def test_kopfzeile_zeigt_offene_vorschlaege_singular(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    session.add(EinsatzVorschlag(
        trainee_id=ids["trainee"], department_id=ids["own"], schoolyear_id=SY,
        kw_von=10, jahr_von=2026, kw_bis=12, jahr_bis=2026,
        eingereicht_von_upn=DEV_UPN, eingereicht_von_name="Dev",
        status="offen", erstellt_am=None,
    ))
    session.commit()

    _login(client, "ausbilder")

    r = client.get(f"/meine-abteilung/?schoolyear_id={SY}")
    assert r.status_code == 200
    assert "1 Vorschlag offen" in r.text
    assert "Vorschläge offen" not in r.text


def test_kopfzeile_zeigt_offene_vorschlaege_plural(client, session, monkeypatch):
    _dev_mode(monkeypatch)
    ids = _setup(session)
    for kw in (10, 20):
        session.add(EinsatzVorschlag(
            trainee_id=ids["trainee"], department_id=ids["own"], schoolyear_id=SY,
            kw_von=kw, jahr_von=2026, kw_bis=kw + 1, jahr_bis=2026,
            eingereicht_von_upn=DEV_UPN, eingereicht_von_name="Dev",
            status="offen", erstellt_am=None,
        ))
    session.commit()

    _login(client, "ausbilder")

    r = client.get(f"/meine-abteilung/?schoolyear_id={SY}")
    assert r.status_code == 200
    assert "2 Vorschläge offen" in r.text


def test_kopfzeile_ohne_offene_vorschlaege_zeigt_keinen_vorschlag_teil(client, session, monkeypatch):
    """Nur bereits BEARBEITETE (angenommene/abgelehnte) eigene Vorschlaege ->
    der Vorschlags-Teil der Kopfzeile wird gar nicht erst angezeigt."""
    _dev_mode(monkeypatch)
    ids = _setup(session)
    session.add(EinsatzVorschlag(
        trainee_id=ids["trainee"], department_id=ids["own"], schoolyear_id=SY,
        kw_von=10, jahr_von=2026, kw_bis=12, jahr_bis=2026,
        eingereicht_von_upn=DEV_UPN, eingereicht_von_name="Dev",
        status="angenommen", erstellt_am=None,
    ))
    session.commit()

    _login(client, "ausbilder")

    r = client.get(f"/meine-abteilung/?schoolyear_id={SY}")
    assert r.status_code == 200
    assert "offene Blöcke insgesamt" in r.text
    assert "Vorschlag offen" not in r.text
    assert "Vorschläge offen" not in r.text
