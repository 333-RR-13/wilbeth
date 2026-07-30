"""Tests fuer die Azubi-UI der Feedbackboegen unter /mein-plan/{token}/feedback."""
from datetime import date

from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    FeedbackBogen,
    Schoolyear,
    Trainee,
    TraineeRolle,
)
from app.services.feedback_def import VERSION_AZUBI

SY = "2025-2026"
TOKEN = "test-token-feedback"

# Zusammenhaengender Abteilungs-Block: KW 10..14/2026
BLOCK_KW_VON, BLOCK_JAHR_VON = 10, 2026
BLOCK_KW_BIS, BLOCK_JAHR_BIS = 14, 2026


def _setup(session: Session) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    dept = Department(code="CP", name="Cloud Platform")
    session.add(dept)
    session.flush()

    t = Trainee(vorname="Anton", nachname="Altmann", rolle=TraineeRolle.AZUBI, share_token=TOKEN)
    session.add(t)
    session.flush()

    for kw in range(BLOCK_KW_VON, BLOCK_KW_BIS + 1):
        session.add(Assignment(
            trainee_id=t.id, schoolyear_id=SY, kw=kw, jahr=BLOCK_JAHR_VON,
            typ=AssignmentTyp.ABTEILUNG, abteilung_id=dept.id,
            source=AssignmentSource.MANUAL,
        ))
    session.commit()
    session.refresh(t)
    session.refresh(dept)
    return {"trainee": t.id, "dept": dept.id}


def _make_bogen(session, typ, trainee_id, dept_id, status="entwurf", **kwargs):
    b = FeedbackBogen(
        typ=typ, trainee_id=trainee_id, department_id=dept_id, schoolyear_id=SY,
        kw_von=BLOCK_KW_VON, jahr_von=BLOCK_JAHR_VON, kw_bis=BLOCK_KW_BIS, jahr_bis=BLOCK_JAHR_BIS,
        status=status, **kwargs,
    )
    session.add(b)
    session.commit()
    session.refresh(b)
    return b


# ── (a) Uebersicht ────────────────────────────────────────────────────────

def test_overview_renders_bloecke_ohne_boegen(client, session):
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/feedback", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Cloud Platform" in r.text
    assert "Ausf" in r.text  # "Ausfüllen"-Link (kein eigener Bogen)
    # Kein Ausbilder-Bogen vorhanden -> neutraler Hinweis, keine Existenz verraten
    assert "noch nicht besprochen" in r.text


def test_overview_zeigt_status_des_eigenen_bogens(client, session):
    ids = _setup(session)
    _make_bogen(session, "AZUBI", ids["trainee"], ids["dept"], status="entwurf")
    r = client.get(f"/mein-plan/{TOKEN}/feedback", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Entwurf" in r.text
    assert "Bearbeiten" in r.text


# ── (b) AZUBI-Bogen anlegen ────────────────────────────────────────────────

def test_azubi_bogen_anlegen(client, session):
    ids = _setup(session)
    r = client.post(f"/mein-plan/{TOKEN}/feedback", data={
        "department_id": ids["dept"], "schoolyear_id": SY,
        "kw_von": BLOCK_KW_VON, "jahr_von": BLOCK_JAHR_VON,
        "kw_bis": BLOCK_KW_BIS, "jahr_bis": BLOCK_JAHR_BIS,
        "einsatzart": "Ersteinsatz",
        "aufg_kommunikation": "5",
        "unt_team": "4",
        "highlight": "Testhighlight",
        "weiterer_einsatz": "ja",
        "action": "entwurf",
    }, follow_redirects=False)
    assert r.status_code == 303

    bogen = session.exec(
        select(FeedbackBogen).where(FeedbackBogen.trainee_id == ids["trainee"])
    ).first()
    assert bogen is not None
    assert bogen.typ == "AZUBI"
    assert bogen.bogen_version == VERSION_AZUBI
    assert bogen.status == "entwurf"
    assert bogen.antworten["aufg_kommunikation"] == 5
    assert bogen.freitexte["highlight"] == "Testhighlight"
    assert bogen.weiterer_einsatz == "ja"
    assert bogen.erstellt_von_upn == f"azubi:{ids['trainee']}"
    assert bogen.erstellt_am == date.today()


def test_azubi_bogen_doppelanlage_leitet_auf_bestehenden_um(client, session):
    ids = _setup(session)
    existing = _make_bogen(session, "AZUBI", ids["trainee"], ids["dept"], status="entwurf")

    r = client.post(f"/mein-plan/{TOKEN}/feedback", data={
        "department_id": ids["dept"], "schoolyear_id": SY,
        "kw_von": BLOCK_KW_VON + 1, "jahr_von": BLOCK_JAHR_VON,
        "kw_bis": BLOCK_KW_BIS - 1, "jahr_bis": BLOCK_JAHR_BIS,
        "action": "entwurf",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith(f"/feedback/{existing.id}")

    count = len(session.exec(
        select(FeedbackBogen).where(FeedbackBogen.trainee_id == ids["trainee"])
    ).all())
    assert count == 1


# ── (c) Fremder Bogen -> 404 ───────────────────────────────────────────────

def test_fremder_bogen_ergibt_404(client, session):
    ids = _setup(session)
    other = Trainee(vorname="Berta", nachname="Buehler", rolle=TraineeRolle.AZUBI, share_token="other-token")
    session.add(other)
    session.commit()
    other_bogen = _make_bogen(session, "AZUBI", other.id, ids["dept"], status="entwurf")

    r = client.get(f"/mein-plan/{TOKEN}/feedback/{other_bogen.id}")
    assert r.status_code == 404


# ── (d) AUSBILDER-Bogen erst ab "besprochen" sichtbar ─────────────────────

def test_ausbilder_bogen_vor_besprochen_nicht_sichtbar(client, session):
    ids = _setup(session)
    ab = _make_bogen(session, "AUSBILDER", ids["trainee"], ids["dept"], status="entwurf")

    assert client.get(f"/mein-plan/{TOKEN}/feedback/{ab.id}").status_code == 404

    ab.status = "abgeschlossen"
    session.add(ab)
    session.commit()
    assert client.get(f"/mein-plan/{TOKEN}/feedback/{ab.id}").status_code == 404

    # Taucht auch in der Uebersicht nicht auf
    r = client.get(f"/mein-plan/{TOKEN}/feedback", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "noch nicht besprochen" in r.text
    assert "bitte best" not in r.text


def test_ausbilder_bogen_ab_besprochen_sichtbar(client, session):
    ids = _setup(session)
    ab = _make_bogen(session, "AUSBILDER", ids["trainee"], ids["dept"], status="besprochen",
                      besprochen_am=date(2026, 3, 1))

    r = client.get(f"/mein-plan/{TOKEN}/feedback/{ab.id}")
    assert r.status_code == 200
    assert "Zur Kenntnis genommen" in r.text

    r_overview = client.get(f"/mein-plan/{TOKEN}/feedback", params={"schoolyear_id": SY})
    assert r_overview.status_code == 200
    assert "bitte best" in r_overview.text  # Hinweis-Badge "bitte bestätigen"

    ab.status = "bestaetigt"
    session.add(ab)
    session.commit()
    r2 = client.get(f"/mein-plan/{TOKEN}/feedback/{ab.id}")
    assert r2.status_code == 200
    assert "Zur Kenntnis genommen" not in r2.text  # nur bei Status "besprochen"


# ── (e) Bestaetigen ────────────────────────────────────────────────────────

def test_bestaetigen_besprochen_zu_bestaetigt(client, session):
    ids = _setup(session)
    ab = _make_bogen(session, "AUSBILDER", ids["trainee"], ids["dept"], status="besprochen",
                      besprochen_am=date(2026, 3, 1))

    r = client.post(f"/mein-plan/{TOKEN}/feedback/{ab.id}/bestaetigen", follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    updated = session.get(FeedbackBogen, ab.id)
    assert updated.status == "bestaetigt"
    assert updated.bestaetigt_am == date.today()


def test_bestaetigen_im_status_entwurf_abgelehnt(client, session):
    ids = _setup(session)
    ab = _make_bogen(session, "AUSBILDER", ids["trainee"], ids["dept"], status="entwurf")

    r = client.post(f"/mein-plan/{TOKEN}/feedback/{ab.id}/bestaetigen", follow_redirects=False)
    assert r.status_code == 400

    session.expire_all()
    assert session.get(FeedbackBogen, ab.id).status == "entwurf"


def test_bestaetigen_fremden_bogen_ergibt_404(client, session):
    ids = _setup(session)
    other = Trainee(vorname="Berta", nachname="Buehler", rolle=TraineeRolle.AZUBI, share_token="other-token-2")
    session.add(other)
    session.commit()
    ab = _make_bogen(session, "AUSBILDER", other.id, ids["dept"], status="besprochen")

    r = client.post(f"/mein-plan/{TOKEN}/feedback/{ab.id}/bestaetigen", follow_redirects=False)
    assert r.status_code == 404


# ── (f) Lernziel-Texte aus Partner-Bogen im neu-Formular ──────────────────

def test_neu_formular_zeigt_lernziele_aus_partner_bogen(client, session):
    ids = _setup(session)
    _make_bogen(
        session, "AUSBILDER", ids["trainee"], ids["dept"], status="entwurf",
        lernziele=[
            {"text": "Python lernen", "bewertung": 4},
            {"text": "Docker verstehen", "bewertung": 3},
        ],
    )

    r = client.get(f"/mein-plan/{TOKEN}/feedback/neu", params={
        "department_id": ids["dept"], "schoolyear_id": SY,
        "kw_von": BLOCK_KW_VON, "jahr_von": BLOCK_JAHR_VON,
        "kw_bis": BLOCK_KW_BIS, "jahr_bis": BLOCK_JAHR_BIS,
    })
    assert r.status_code == 200
    assert "Python lernen" in r.text
    assert "Docker verstehen" in r.text
    # Lernziel-Texte sind read-only uebernommen
    assert 'readonly' in r.text


def test_neu_formular_ohne_partner_bogen_leer(client, session):
    ids = _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/feedback/neu", params={
        "department_id": ids["dept"], "schoolyear_id": SY,
        "kw_von": BLOCK_KW_VON, "jahr_von": BLOCK_JAHR_VON,
        "kw_bis": BLOCK_KW_BIS, "jahr_bis": BLOCK_JAHR_BIS,
    })
    assert r.status_code == 200
    assert "Zeile hinzuf" in r.text  # JS-Button zum Anlegen eigener Lernziel-Zeilen


# ── (g) Update nur im Entwurf ──────────────────────────────────────────────

def test_update_eigenen_entwurf_erfolgreich(client, session):
    ids = _setup(session)
    bogen = _make_bogen(session, "AZUBI", ids["trainee"], ids["dept"], status="entwurf")

    r = client.post(f"/mein-plan/{TOKEN}/feedback/{bogen.id}", data={
        "action": "abschliessen",
        "aufg_kommunikation": "5",
        "highlight": "Toll gelaufen",
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    updated = session.get(FeedbackBogen, bogen.id)
    assert updated.status == "abgeschlossen"
    assert updated.antworten["aufg_kommunikation"] == 5
    assert updated.freitexte["highlight"] == "Toll gelaufen"
    assert updated.aktualisiert_am == date.today()


def test_update_nach_abschliessen_abgelehnt(client, session):
    ids = _setup(session)
    bogen = _make_bogen(session, "AZUBI", ids["trainee"], ids["dept"], status="abgeschlossen")

    r = client.post(f"/mein-plan/{TOKEN}/feedback/{bogen.id}", data={"action": "entwurf"}, follow_redirects=False)
    assert r.status_code == 400

    session.expire_all()
    assert session.get(FeedbackBogen, bogen.id).status == "abgeschlossen"


def test_eigener_bogen_nach_abschluss_readonly(client, session):
    ids = _setup(session)
    bogen = _make_bogen(session, "AZUBI", ids["trainee"], ids["dept"], status="abgeschlossen")

    r = client.get(f"/mein-plan/{TOKEN}/feedback/{bogen.id}")
    assert r.status_code == 200
    assert 'value="entwurf"' not in r.text
    assert 'value="abschliessen"' not in r.text


# ── Review-Fixes ───────────────────────────────────────────────────────────

def test_partner_inhalte_leaken_nicht_ins_neu_formular(client, session):
    """Nur die Lernziel-TEXTE des (unbesprochenen) AUSBILDER-Bogens werden
    uebernommen -- Bewertungen, Antworten und Freitexte des Ausbilders duerfen
    NICHT im AZUBI-Formular auftauchen, und der Hinweistext verraet keinen
    'Bogen' (neutral: 'vorgegeben')."""
    ids = _setup(session)
    _make_bogen(
        session, "AUSBILDER", ids["trainee"], ids["dept"], status="entwurf",
        lernziele=[{"text": "Python lernen", "bewertung": 5}],
        antworten={"komm_ausdruck": 1},
        freitexte={"staerken": "GEHEIME-STAERKE-XYZ"},
    )

    r = client.get(f"/mein-plan/{TOKEN}/feedback/neu", params={
        "department_id": ids["dept"], "schoolyear_id": SY,
        "kw_von": BLOCK_KW_VON, "jahr_von": BLOCK_JAHR_VON,
        "kw_bis": BLOCK_KW_BIS, "jahr_bis": BLOCK_JAHR_BIS,
    })
    assert r.status_code == 200
    assert "Python lernen" in r.text
    # Ausbilder-Inhalte bleiben unsichtbar
    assert "GEHEIME-STAERKE-XYZ" not in r.text
    assert "frage_komm_ausdruck" not in r.text  # AUSBILDER-Frage-Keys fehlen
    # Bewertung des Ausbilders (5) ist NICHT vorausgewaehlt
    assert 'selected' not in r.text
    # Neutraler Hinweis ohne Bogen-Existenz
    assert "vorgegeben" in r.text
    assert "aus dem Bogen" not in r.text


def test_muell_post_ergibt_400_statt_500(client, session):
    """Manipulierte POSTs (kw_von='x', Bewertung='abc') duerfen keinen 500er
    ausloesen."""
    ids = _setup(session)
    r = client.post(f"/mein-plan/{TOKEN}/feedback", data={
        "department_id": ids["dept"], "schoolyear_id": SY,
        "kw_von": "x", "jahr_von": BLOCK_JAHR_VON,
        "kw_bis": BLOCK_KW_BIS, "jahr_bis": BLOCK_JAHR_BIS,
    }, follow_redirects=False)
    assert r.status_code == 400

    # Muell in Bewertungs-Feldern wird ignoriert statt zu crashen
    r2 = client.post(f"/mein-plan/{TOKEN}/feedback", data={
        "department_id": ids["dept"], "schoolyear_id": SY,
        "kw_von": BLOCK_KW_VON, "jahr_von": BLOCK_JAHR_VON,
        "kw_bis": BLOCK_KW_BIS, "jahr_bis": BLOCK_JAHR_BIS,
        "aufg_kommunikation": "abc",
        "lernziel_text": "Ziel", "lernziel_bewertung": "kaputt",
        "action": "entwurf",
    }, follow_redirects=False)
    assert r2.status_code == 303

    bogen = session.exec(
        select(FeedbackBogen).where(FeedbackBogen.trainee_id == ids["trainee"])
    ).first()
    assert bogen.antworten == {}
    assert bogen.lernziele == [{"text": "Ziel", "bewertung": None}]


def test_fantasie_block_ergibt_400(client, session):
    """Ein POST fuer einen Zeitraum ohne realen Abteilungs-Einsatz des
    Trainees wird abgelehnt (kein Datenmuell in der Staff-Liste)."""
    ids = _setup(session)
    r = client.post(f"/mein-plan/{TOKEN}/feedback", data={
        "department_id": ids["dept"], "schoolyear_id": SY,
        "kw_von": 40, "jahr_von": 2025, "kw_bis": 42, "jahr_bis": 2025,
        "action": "entwurf",
    }, follow_redirects=False)
    assert r.status_code == 400
    assert session.exec(select(FeedbackBogen)).first() is None


def test_einsatzart_kann_zurueckgesetzt_werden(client, session):
    """Eine einmal gewaehlte Einsatzart laesst sich beim Update wieder auf
    leer stellen (kein stilles Ignorieren des leeren Selects)."""
    ids = _setup(session)
    bogen = _make_bogen(session, "AZUBI", ids["trainee"], ids["dept"],
                        status="entwurf", einsatzart="Ersteinsatz")

    r = client.post(f"/mein-plan/{TOKEN}/feedback/{bogen.id}", data={
        "action": "entwurf", "einsatzart": "",
    }, follow_redirects=False)
    assert r.status_code == 303

    session.expire_all()
    assert session.get(FeedbackBogen, bogen.id).einsatzart == ""
