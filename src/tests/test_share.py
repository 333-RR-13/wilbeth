"""Tests fuer den Azubi-Self-Service unter /mein-plan/{token}."""
from datetime import date

from sqlmodel import Session, select

from app.models import (
    Assignment,
    AssignmentSource,
    AssignmentTyp,
    Department,
    SchoolPlan,
    SchoolPlanWeek,
    SchoolWeekTyp,
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    TraineeWish,
    UnterrichtsTyp,
)

SY = "2025-2026"
TOKEN = "test-token-1234"


def _setup(session: Session, with_class: bool = False) -> dict:
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    cp = Department(code="CP", name="Cloud Platform")
    ba = Department(code="BA", name="Business Applications", erlaubt_mehrfachbelegung=True)
    session.add_all([cp, ba])
    klasse_id = None
    if with_class:
        klasse = TraineeClass(name="FISI 2. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
        session.add(klasse)
        session.flush()
        klasse_id = klasse.id
        plan = SchoolPlan(klasse_id=klasse_id, schoolyear_id=SY)
        session.add(plan)
        session.flush()
        session.add(SchoolPlanWeek(plan_id=plan.id, kw=41, jahr=2025, typ=SchoolWeekTyp.BERUFSSCHULE))

    t = Trainee(vorname="Anton", nachname="Altmann", rolle=TraineeRolle.AZUBI,
                klasse_id=klasse_id, share_token=TOKEN)
    session.add(t)
    session.flush()
    session.commit()
    return {"trainee": t.id, "cp": cp.id, "ba": ba.id}


# ── Zugriff / Token ──────────────────────────────────────────────

def test_my_plan_valid_token(client, session):
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}")
    assert r.status_code == 200
    assert "Anton" in r.text
    assert "Meine Einsätze" in r.text


def test_my_plan_jahr_umschalter_auch_ohne_einsaetze(client, session):
    """Der Jahr-Umschalter auf 'Meine Einsaetze' bietet ALLE Schuljahre an.

    Regression: Frueher wurden nur Jahre verlinkt, in denen der Trainee schon
    Einsaetze hatte -- bei genau einem solchen Jahr (Normalfall) verschwand der
    Umschalter komplett und kuenftige Jahre waren nicht erreichbar.
    """
    _setup(session)
    session.add(Schoolyear(id="2026-2027", start_kw=36, start_year=2026, end_kw=35, end_year=2027))
    session.commit()

    r = client.get(f"/mein-plan/{TOKEN}")
    assert r.status_code == 200
    # Beide Jahre sind als Umschalt-Link vorhanden (Trainee hat in keinem Einsaetze)
    assert f'/mein-plan/{TOKEN}?schoolyear_id={SY}' in r.text
    assert f'/mein-plan/{TOKEN}?schoolyear_id=2026-2027' in r.text

    # Und die Auswahl greift: gewaehltes Jahr ist aktiv markiert
    r2 = client.get(f"/mein-plan/{TOKEN}", params={"schoolyear_id": "2026-2027"})
    assert r2.status_code == 200
    assert 'share-year-link active">2026-2027' in r2.text


def test_my_plan_invalid_token(client, session):
    _setup(session)
    r = client.get("/mein-plan/gibt-es-nicht")
    assert r.status_code == 404


def test_my_plan_sidebar_links(client, session):
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}")
    assert r.status_code == 200
    # Linke Bar verlinkt alle Bereiche + Über Wilbeth (share-eigene Route, nicht
    # mehr /ueber-wilbeth hinter dem Planer-Auth-Guard, siehe Fix e)
    for href in [
        f"/mein-plan/{TOKEN}/klasse",
        f"/mein-plan/{TOKEN}/jahrgang",
        f"/mein-plan/{TOKEN}/urlaub",
        f"/mein-plan/{TOKEN}/wuensche",
        f"/mein-plan/{TOKEN}/ueber",
    ]:
        assert href in r.text
    # Einzeilen-Matrix mit KW-Headern
    assert "th-kw-num" in r.text


def test_urlaub_page_renders(client, session):
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/urlaub")
    assert r.status_code == 200
    assert "Urlaub" in r.text


def test_wuensche_page_renders(client, session):
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/wuensche")
    assert r.status_code == 200
    assert "Wünsche" in r.text or "Priorität" in r.text


# ── Urlaub eintragen ─────────────────────────────────────────────

def test_urlaub_create(client, session):
    ids = _setup(session)
    r = client.post(f"/mein-plan/{TOKEN}/urlaub", data={"kw": 50, "jahr": 2025}, follow_redirects=False)
    assert r.status_code == 303

    a = session.exec(select(Assignment).where(Assignment.trainee_id == ids["trainee"])).first()
    assert a is not None
    assert a.typ == AssignmentTyp.URLAUB
    assert a.source == AssignmentSource.SELBST
    assert (a.kw, a.jahr) == (50, 2025)


def test_urlaub_range(client, session):
    ids = _setup(session)
    client.post(f"/mein-plan/{TOKEN}/urlaub",
                data={"kw": 50, "jahr": 2025, "kw_end": 1, "jahr_end": 2026},
                follow_redirects=False)
    rows = session.exec(select(Assignment).where(Assignment.trainee_id == ids["trainee"])).all()
    # KW50, 51, 52 (2025) + KW1 (2026) = 4 Wochen
    assert len(rows) == 4
    assert all(a.typ == AssignmentTyp.URLAUB for a in rows)


def test_urlaub_skips_school_week(client, session):
    ids = _setup(session, with_class=True)
    # KW41/2025 ist Schulwoche -> wird uebersprungen
    client.post(f"/mein-plan/{TOKEN}/urlaub", data={"kw": 41, "jahr": 2025}, follow_redirects=False)
    rows = session.exec(select(Assignment).where(Assignment.trainee_id == ids["trainee"])).all()
    assert len(rows) == 0


def test_urlaub_delete_own(client, session):
    ids = _setup(session)
    client.post(f"/mein-plan/{TOKEN}/urlaub", data={"kw": 50, "jahr": 2025}, follow_redirects=False)
    a = session.exec(select(Assignment).where(Assignment.trainee_id == ids["trainee"])).first()
    aid = a.id

    client.post(f"/mein-plan/{TOKEN}/urlaub/loeschen", data={"assignment_id": aid}, follow_redirects=False)
    assert session.get(Assignment, aid) is None


def test_urlaub_delete_only_self_entered(client, session):
    ids = _setup(session)
    # Von der Planerin gesetzter Urlaub (source=MANUAL) darf NICHT vom Azubi geloescht werden
    a = Assignment(trainee_id=ids["trainee"], schoolyear_id=SY, kw=50, jahr=2025,
                   typ=AssignmentTyp.URLAUB, source=AssignmentSource.MANUAL)
    session.add(a)
    session.commit()
    aid = a.id

    client.post(f"/mein-plan/{TOKEN}/urlaub/loeschen", data={"assignment_id": aid}, follow_redirects=False)
    assert session.get(Assignment, aid) is not None  # bleibt erhalten


# ── Wünsche ──────────────────────────────────────────────────────

def test_save_wishes(client, session):
    ids = _setup(session)
    r = client.post(f"/mein-plan/{TOKEN}/wuensche", data={
        f"prio_{ids['cp']}": "1",
        f"prio_{ids['ba']}": "3",
        "wunsch_notiz": "CP vor der Zwischenprüfung",
    }, follow_redirects=False)
    assert r.status_code == 303

    wishes = session.exec(select(TraineeWish).where(TraineeWish.trainee_id == ids["trainee"])).all()
    prios = {w.department_id: w.prioritaet for w in wishes}
    assert prios == {ids["cp"]: 1, ids["ba"]: 3}

    t = session.get(Trainee, ids["trainee"])
    assert "Zwischenprüfung" in t.wunsch_notiz


def test_save_wishes_replaces(client, session):
    ids = _setup(session)
    client.post(f"/mein-plan/{TOKEN}/wuensche", data={f"prio_{ids['cp']}": "1"}, follow_redirects=False)
    # Zweiter Speichervorgang ersetzt die alten Wuensche
    client.post(f"/mein-plan/{TOKEN}/wuensche", data={f"prio_{ids['ba']}": "2"}, follow_redirects=False)
    wishes = session.exec(select(TraineeWish).where(TraineeWish.trainee_id == ids["trainee"])).all()
    assert len(wishes) == 1
    assert wishes[0].department_id == ids["ba"]


def test_abteilungs_zelle_hat_tooltip(client, session):
    """Auch in der Azubi-Sicht traegt die ganze Matrix-Zelle eines
    Abteilungs-Einsatzes den Abteilungsnamen als title-Tooltip."""
    ids = _setup(session)
    session.add(Assignment(trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
                           source=AssignmentSource.MANUAL))
    session.commit()
    r = client.get(f"/mein-plan/{TOKEN}")
    assert r.status_code == 200
    assert '<td class="matrix-cell" title="Cloud Platform">' in r.text


# ── ICS-Export ───────────────────────────────────────────────────

def test_ics_export(client, session):
    ids = _setup(session)
    session.add(Assignment(trainee_id=ids["trainee"], schoolyear_id=SY, kw=40, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=ids["cp"],
                           source=AssignmentSource.MANUAL))
    session.commit()

    r = client.get(f"/mein-plan/{TOKEN}/calendar.ics")
    assert r.status_code == 200
    assert "text/calendar" in r.headers["content-type"]
    body = r.text
    assert "BEGIN:VCALENDAR" in body
    assert "BEGIN:VEVENT" in body
    assert "CP" in body
    assert "DTSTART;VALUE=DATE:" in body


# ── Token-Rotation über Admin ────────────────────────────────────

def test_token_rotation_invalidates_old(client, session):
    ids = _setup(session)
    assert client.get(f"/mein-plan/{TOKEN}").status_code == 200

    # Admin erzeugt neuen Token
    client.post(f"/trainees/{ids['trainee']}/share-token", follow_redirects=False)
    session.expire_all()
    new_token = session.get(Trainee, ids["trainee"]).share_token
    assert new_token != TOKEN

    assert client.get(f"/mein-plan/{TOKEN}").status_code == 404      # alter Link tot
    assert client.get(f"/mein-plan/{new_token}").status_code == 200  # neuer Link lebt


def test_token_revoke(client, session):
    ids = _setup(session)
    client.post(f"/trainees/{ids['trainee']}/share-token/deaktivieren", follow_redirects=False)
    session.expire_all()
    assert session.get(Trainee, ids["trainee"]).share_token is None
    assert client.get(f"/mein-plan/{TOKEN}").status_code == 404


# ── Gesamtuebersicht ─────────────────────────────────────────────

def test_uebersicht_page_renders(client, session):
    """Uebersicht-Seite zeigt alle aktiven Trainees; eigener Name ist hervorgehoben."""
    ids = _setup(session, with_class=True)
    # Zweiten aktiven Trainee anlegen, damit die Gruppierung nicht trivial leer ist
    t2 = Trainee(vorname="Berta", nachname="Buehler", rolle=TraineeRolle.AZUBI, share_token="other-token")
    session.add(t2)
    session.commit()

    r = client.get(f"/mein-plan/{TOKEN}/uebersicht")
    assert r.status_code == 200
    # Eigener Name taucht auf (highlight)
    assert "Altmann" in r.text
    # Zweiter Trainee ebenfalls sichtbar
    assert "Buehler" in r.text
    # Nav-Link/Titel umbenannt (Fix Paket B, Punkt d)
    assert "Alle Azubis &amp; Studis" in r.text
    # Matrix-Kopfzeile vorhanden (KW-Header)
    assert "th-kw-num" in r.text


# ── Meine Klasse: berechnete Klasse statt Anker/Beruf (Paket B, Bugs 1+2) ──

def _setup_progression(session: Session) -> dict:
    """FISI-Klassenkette 1./2. LJ + zwei Trainees mit demselben Anker ('FISI 1. LJ')
    aber unterschiedlichem Ausbildungsbeginn:
    - 'me' (TOKEN) startete 2024 -> ist im Schuljahr 2025-2026 rechnerisch im 2. LJ.
    - 'juenger' startete erst 2025 -> ist im Schuljahr 2025-2026 noch im 1. LJ.
    Regressionsfall fuer Bug 1: die alte Route matchte Klassenkameraden ueber den
    GEMEINSAMEN Anker (trainee.klasse_id) statt ueber die berechnete Klasse und
    haette 'juenger' faelschlich als Klassenkamerad von 'me' gezeigt.
    """
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    k1 = TraineeClass(name="FISI 1. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    k2 = TraineeClass(name="FISI 2. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add_all([k1, k2])
    session.flush()

    me = Trainee(
        vorname="Anton", nachname="Altmann", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2024, 9, 1), share_token=TOKEN,
    )
    juenger = Trainee(
        vorname="Berta", nachname="Buehler", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2025, 9, 1), share_token="juenger-token",
    )
    session.add_all([me, juenger])
    session.commit()
    return {"me": me.id, "juenger": juenger.id, "k1": k1.id, "k2": k2.id}


def test_my_class_excludes_other_lj_same_beruf(client, session):
    """(i) 'Meine Klasse' zeigt NUR die berechnete eigene Klasse — ein Azubi eines
    anderen (rechnerischen) Lehrjahrs desselben Berufs, auch mit demselben Anker,
    erscheint NICHT."""
    _setup_progression(session)
    r = client.get(f"/mein-plan/{TOKEN}/klasse", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "Altmann" in r.text
    assert "Buehler" not in r.text


def test_my_class_title_shows_computed_klasse(client, session):
    """(ii) Titel/Inhalt zeigen die BERECHNETE Klasse fuers gewaehlte Jahr (Anker
    '1. LJ' + Start 2024 -> 'FISI 2. LJ' im Schuljahr 2025-2026), nicht die
    statische Anker-Einstiegsklasse."""
    _setup_progression(session)
    r = client.get(f"/mein-plan/{TOKEN}/klasse", params={"schoolyear_id": SY})
    assert r.status_code == 200
    assert "FISI 2. LJ" in r.text


def test_abteilungs_zelle_hat_tooltip_gruppenseiten(client, session):
    """Auch die gruppierten Matrizen (Mein Jahrgang / Alle Azubis & Studis,
    week_matrix_group.html) tragen den Abteilungsnamen als Zell-Tooltip."""
    ids = _setup_progression(session)
    cp = Department(code="CP", name="Cloud Platform")
    session.add(cp)
    session.flush()
    session.add(Assignment(trainee_id=ids["me"], schoolyear_id=SY, kw=40, jahr=2025,
                           typ=AssignmentTyp.ABTEILUNG, abteilung_id=cp.id,
                           source=AssignmentSource.MANUAL))
    session.commit()
    for pfad in ("jahrgang", "uebersicht"):
        r = client.get(f"/mein-plan/{TOKEN}/{pfad}", params={"schoolyear_id": SY})
        assert r.status_code == 200
        assert '<td class="matrix-cell" title="Cloud Platform">' in r.text, pfad


# ── Absolventen ausblenden (Paket B, Bug 3) ────────────────────────────────

def test_absolvent_hidden_everywhere(client, session):
    """(iii) Ein Absolvent (klasse_fuer -> None fuers gewaehlte Jahr, weil kein
    Nachfolge-Lehrjahr mehr existiert) taucht weder auf 'Meine Klasse' noch auf
    'Mein Jahrgang' oder 'Alle Azubis & Studis' auf. Ein DH-Kollege desselben
    Jahrgangs (bleibt in der letzten Klasse statt Abschluss) und ein aktiver
    Azubi bleiben sichtbar."""
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    k1 = TraineeClass(name="FISI 1. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    k2 = TraineeClass(name="FISI 2. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    k3 = TraineeClass(name="FISI 3. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add_all([k1, k2, k3])
    session.flush()

    # 3 Jahre vor Schuljahresstart 2025 -> nach 3x next_class_for() kein 4. LJ mehr -> Abschluss
    absolvent = Trainee(
        vorname="Greta", nachname="Graf", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2022, 9, 1), share_token=TOKEN,
    )
    dh_kollege = Trainee(
        vorname="Iris", nachname="Igel", rolle=TraineeRolle.DH_STUDENT,
        klasse_id=k1.id, ausbildungsbeginn=date(2022, 9, 1),  # gleicher Jahrgang, bleibt aktiv
    )
    aktiver = Trainee(
        vorname="Heiko", nachname="Hahn", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2025, 9, 1), share_token="aktiver-token-iii",
    )
    session.add_all([absolvent, dh_kollege, aktiver])
    session.commit()

    # Eigene Klasse (Absolvent selbst): fuers gewaehlte Jahr keine Klasse mehr
    r_klasse = client.get(f"/mein-plan/{TOKEN}/klasse", params={"schoolyear_id": SY})
    assert r_klasse.status_code == 200
    assert "Für das gewählte Schuljahr bist du keiner Klasse zugeordnet." in r_klasse.text

    # Mein Jahrgang (Absolvent selbst): Absolvent erscheint nicht als Zeile in der
    # Matrix (Tabellenzellen rendern "Nachname, Vorname"; der eigene Seitenkopf
    # zeigt "Vorname Nachname" der Absolventin selbstverstaendlich weiterhin an —
    # daher gezielt auf die Tabellenzeilen-Notation pruefen, nicht auf den blossen
    # Nachnamen).
    r_jahrgang = client.get(f"/mein-plan/{TOKEN}/jahrgang", params={"schoolyear_id": SY})
    assert r_jahrgang.status_code == 200
    assert "Graf, Greta" not in r_jahrgang.text
    assert "Igel, Iris" in r_jahrgang.text

    # Alle Azubis & Studis: Absolvent nicht, aktiver Azubi schon
    r_ueb = client.get(f"/mein-plan/{TOKEN}/uebersicht", params={"schoolyear_id": SY})
    assert r_ueb.status_code == 200
    assert "Graf, Greta" not in r_ueb.text
    assert "Hahn, Heiko" in r_ueb.text


# ── Mein Jahrgang (Paket B, neue Seite c) ──────────────────────────────────

def _setup_jahrgang(session: Session) -> dict:
    """Zwei Trainees desselben Startjahrgangs (2024) in unterschiedlichen Berufen
    — einer davon mit Ausbildungsbeginn 01.01.2025 (zaehlt laut Konvention zum
    Vorjahres-Jahrgang 2024) — sowie ein Trainee eines anderen Jahrgangs (2023)."""
    session.add(Schoolyear(id="2024-2025", start_kw=36, start_year=2024, end_kw=35, end_year=2025))
    fisi = TraineeClass(name="FISI 1. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    fiae = TraineeClass(name="FIAE 1. LJ", berufsschule="JD", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add_all([fisi, fiae])
    session.flush()

    ich = Trainee(
        vorname="Anton", nachname="Altmann", rolle=TraineeRolle.AZUBI,
        klasse_id=fisi.id, ausbildungsbeginn=date(2024, 9, 1), share_token=TOKEN,
    )
    januar_start = Trainee(
        vorname="Berta", nachname="Buehler", rolle=TraineeRolle.AZUBI,
        klasse_id=fiae.id, ausbildungsbeginn=date(2025, 1, 1),
    )
    anderer_jahrgang = Trainee(
        vorname="Carla", nachname="Cortes", rolle=TraineeRolle.AZUBI,
        klasse_id=fisi.id, ausbildungsbeginn=date(2023, 9, 1),
    )
    session.add_all([ich, januar_start, anderer_jahrgang])
    session.commit()
    return {"fisi": fisi.id, "fiae": fiae.id}


def test_jahrgang_cross_beruf_and_january_start(client, session):
    """(iv) 'Mein Jahrgang' zeigt denselben Startjahrgang berufsuebergreifend;
    ein anderer Jahrgang bleibt aussen vor; ein Start am 01.01. zaehlt zum
    Vorjahres-Jahrgang."""
    _setup_jahrgang(session)
    r = client.get(f"/mein-plan/{TOKEN}/jahrgang", params={"schoolyear_id": "2024-2025"})
    assert r.status_code == 200
    assert "Altmann" in r.text
    assert "Buehler" in r.text       # anderer Beruf, aber dank 01.01.-Regel gleicher Jahrgang
    assert "Cortes" not in r.text    # anderer Jahrgang (2023)


def test_jahrgang_group_headings_present(client, session):
    """(vi) Gruppen-Zwischenueberschriften (Beruf-Langname + Klassenname) sind
    vorhanden, sobald mehrere Berufe im selben Jahrgang vertreten sind."""
    _setup_jahrgang(session)
    r = client.get(f"/mein-plan/{TOKEN}/jahrgang", params={"schoolyear_id": "2024-2025"})
    assert r.status_code == 200
    assert "Fachinformatiker für Systemintegration" in r.text
    assert "Fachinformatiker für Anwendungsentwicklung" in r.text
    assert "overview-beruf-heading" in r.text
    assert "overview-klasse-heading" in r.text


# ── Über Wilbeth (Paket B, Fix e) ───────────────────────────────────────────

def test_ueber_page_renders_in_share_layout(client, session):
    """(v) /mein-plan/{token}/ueber liefert 200 im share-Layout — nicht die
    Planer-Seite /ueber-wilbeth hinter dem Auth-Guard."""
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/ueber")
    assert r.status_code == 200
    assert "Über Wilbeth" in r.text
    # Share-Layout: eigener Name erscheint im Sidebar-Header
    assert "Anton" in r.text
    assert "Altmann" in r.text
    # Inhalt ist identisch mit der Planer-Seite (gemeinsames Partial):
    # die Sage der Drei Bethen, nicht mehr der alte Kurztext
    assert "Drei Bethen" in r.text
    assert "Wilbeth ist diese App" in r.text
    # Der Abschluss-Link fuehrt auf den eigenen Plan, nicht auf /overview
    assert f'href="/mein-plan/{TOKEN}"' in r.text
    assert 'href="/overview"' not in r.text


# ── Abteilungsliste ──────────────────────────────────────────────

def test_abteilungen_page_renders(client, session):
    """Abteilungs-Seite listet Code, Name und Fallback fuer fehlende Felder."""
    ids = _setup(session)
    # Abteilung mit leerem ansprechpartner + info_text -> Fallback "-" erwartet
    r = client.get(f"/mein-plan/{TOKEN}/abteilungen")
    assert r.status_code == 200
    # Abteilungs-Codes aus _setup muessen erscheinen
    assert "CP" in r.text
    assert "BA" in r.text
    # Leere Felder zeigen "-"
    assert "–" in r.text
    # Seitenheader
    assert "Abteilungen" in r.text


def test_abteilungen_page_shows_verantwortliche(client, session):
    """Abteilungs-Seite zeigt verantwortliche an, sonst Fallback '-'."""
    session.add(Schoolyear(id=SY, start_kw=36, start_year=2025, end_kw=35, end_year=2026))
    cp = Department(code="CP", name="Cloud Platform", verantwortliche="verantwortlich@firma.de")
    ba = Department(code="BA", name="Business Applications", erlaubt_mehrfachbelegung=True)
    session.add_all([cp, ba])
    t = Trainee(vorname="Anton", nachname="Altmann", rolle=TraineeRolle.AZUBI, share_token=TOKEN)
    session.add(t)
    session.commit()

    r = client.get(f"/mein-plan/{TOKEN}/abteilungen")
    assert r.status_code == 200
    assert "verantwortlich@firma.de" in r.text
    # BA hat keine verantwortliche -> Fallback "-"
    assert "–" in r.text
