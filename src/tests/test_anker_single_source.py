"""Tests: Klassendaten beruhen NUR auf dem Trainee-Anker (Ausbildungsbeginn +
Einstiegsklasse); Overrides (TraineeClassMembership) sind explizite, sichtbare,
loeschbare AUSNAHMEN - keine stillen Schreibpfade mehr.

(a) Repro des urspruenglichen Bugs: ein veralteter Override wird in Liste/Detail
    als "Ausnahme" sichtbar gemacht statt die Berechnung stillschweigend zu
    ueberschreiben; nach dem Loeschen der Ausnahme greift wieder die Berechnung.
(b) Normales Speichern des Edit-Formulars OHNE Ausnahme-Felder schreibt KEINEN
    Override.
(c) Explizites Hinzufuegen (Jahr+Klasse gesetzt) schreibt genau einen Override
    und laesst t.klasse_id (Anker) unveraendert.
(d) Klassen-Bearbeiten zeigt berechnete Mitglieder + Ausnahme-Badge; ein POST
    ohne mitglied-Param schreibt keine Memberships mehr.
(e) /daten/ausnahmen-loeschen loescht alle Overrides (admin); orga -> 403.
"""
from datetime import date

from sqlmodel import Session, select

from app.config import settings
from app.models import (
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeClassMembership,
    TraineeRolle,
    UnterrichtsTyp,
)

SY = "2025-2026"


# ── Hilfsfunktionen ────────────────────────────────────────────────────────

def _add_year(session: Session, sy_id: str = SY, start_year: int = 2025) -> Schoolyear:
    y = Schoolyear(id=sy_id, start_kw=36, start_year=start_year, end_kw=35, end_year=start_year + 1)
    session.add(y)
    session.flush()
    return y


def _add_class(session: Session, name: str) -> TraineeClass:
    c = TraineeClass(name=name, berufsschule="JD Schule", unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(c)
    session.flush()
    return c


def _login(client, monkeypatch, rolle: str) -> None:
    monkeypatch.setattr(settings, "auth_mode", "dev")
    r = client.post("/auth/dev-login", data={"rolle": rolle}, follow_redirects=False)
    assert r.status_code == 303


# ── (a) Repro: veralteter Override wird sichtbar statt die Berechnung stillschweigend zu ueberschreiben ──

def test_veralteter_override_zeigt_ausnahme_badge_und_loeschen_stellt_berechnung_wieder_her(
    client, session: Session,
):
    _add_year(session)
    k1 = _add_class(session, "FISI 1. LJ")
    _add_class(session, "FISI 2. LJ")
    _add_class(session, "FISI 3. LJ")

    trainee = Trainee(
        vorname="Rudi", nachname="Repro", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2024, 9, 1),
    )
    session.add(trainee)
    session.commit()

    # Veralteter Override: Wiederholung/Sonderfall aus einer frueheren Pflege,
    # zeigt noch auf die Einstiegsklasse statt der berechneten Folgeklasse.
    session.add(TraineeClassMembership(trainee_id=trainee.id, schoolyear_id=SY, klasse_id=k1.id))
    session.commit()

    # Liste: zeigt die Override-Klasse (1. LJ) MIT Ausnahme-Badge
    r = client.get("/trainees/")
    assert r.status_code == 200
    zeile = r.text.split("Repro")[1].split("</tr>")[0]
    assert "FISI 1. LJ" in zeile
    assert "Ausnahme" in zeile

    # Detail: ebenfalls Override-Klasse MIT Ausnahme-Hinweis
    r = client.get(f"/trainees/{trainee.id}")
    assert r.status_code == 200
    assert "Ausnahme" in r.text

    # Ausnahme loeschen
    r = client.post(
        f"/trainees/{trainee.id}/ausnahme-loeschen",
        data={"schoolyear_id": SY},
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()
    assert session.exec(
        select(TraineeClassMembership).where(TraineeClassMembership.trainee_id == trainee.id)
    ).first() is None

    # Liste zeigt jetzt die BERECHNETE Klasse (2. LJ), kein Badge mehr
    r = client.get("/trainees/")
    assert r.status_code == 200
    zeile = r.text.split("Repro")[1].split("</tr>")[0]
    assert "FISI 2. LJ" in zeile
    assert "Ausnahme" not in zeile

    # Detail ebenfalls
    r = client.get(f"/trainees/{trainee.id}")
    assert r.status_code == 200
    dd = r.text.split("<dt>Klasse</dt>")[1].split("</dd>")[0]
    assert "FISI 2. LJ" in dd
    assert "Ausnahme" not in dd


# ── (b) Normales Speichern schreibt KEINEN Override ───────────────────────

def test_normales_speichern_ohne_ausnahme_felder_schreibt_keinen_override(
    client, session: Session,
):
    _add_year(session)
    k1 = _add_class(session, "FISI 1. LJ")
    trainee = Trainee(
        vorname="Nora", nachname="Normal", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2025, 9, 1),
    )
    session.add(trainee)
    session.commit()

    r = client.post(
        f"/trainees/{trainee.id}",
        data={
            "vorname": "Nora",
            "nachname": "Normal",
            "rolle": "AZUBI",
            "beruf": "FISI",
            "ausbildungsbeginn": "2025-09-01",
            "klasse_id": "",
            # keine membership_year_id / membership_klasse_id gesetzt
            "notizen": "",
            "steckbrief": "",
            "aktiv": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()
    memberships = session.exec(select(TraineeClassMembership)).all()
    assert memberships == []


# ── (c) Explizite Ausnahme schreibt genau einen Override, Anker unveraendert ──

def test_explizite_ausnahme_schreibt_genau_einen_override_anker_unveraendert(
    client, session: Session,
):
    _add_year(session)
    k1 = _add_class(session, "FISI 1. LJ")
    k_sonder = _add_class(session, "Sonderklasse")
    trainee = Trainee(
        vorname="ExplA", nachname="Ausnahme", rolle=TraineeRolle.AZUBI,
        klasse_id=k1.id, ausbildungsbeginn=date(2025, 9, 1),
    )
    session.add(trainee)
    session.commit()

    r = client.post(
        f"/trainees/{trainee.id}",
        data={
            "vorname": "ExplA",
            "nachname": "Ausnahme",
            "rolle": "AZUBI",
            "beruf": "FISI",
            "ausbildungsbeginn": "2025-09-01",
            "klasse_id": "",
            "membership_year_id": SY,
            "membership_klasse_id": str(k_sonder.id),
            "notizen": "",
            "steckbrief": "",
            "aktiv": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()
    memberships = session.exec(select(TraineeClassMembership)).all()
    assert len(memberships) == 1
    assert memberships[0].trainee_id == trainee.id
    assert memberships[0].schoolyear_id == SY
    assert memberships[0].klasse_id == k_sonder.id

    t = session.get(Trainee, trainee.id)
    assert t.klasse_id == k1.id  # Anker unveraendert


# ── (d) Klassen-Bearbeiten: berechnete Mitglieder + Badge; kein mitglied-Schreibpfad ──

def test_klassen_bearbeiten_zeigt_berechnete_mitglieder_und_kein_mitglied_schreibpfad(
    client, session: Session,
):
    _add_year(session)
    cls = _add_class(session, "FISI 2. LJ")

    t_anker = Trainee(vorname="Anke", nachname="Anker", rolle=TraineeRolle.AZUBI, klasse_id=cls.id)
    t_override = Trainee(vorname="Ovi", nachname="Override", rolle=TraineeRolle.AZUBI, klasse_id=None)
    session.add_all([t_anker, t_override])
    session.commit()
    session.add(TraineeClassMembership(trainee_id=t_override.id, schoolyear_id=SY, klasse_id=cls.id))
    session.commit()

    r = client.get(f"/klassen/{cls.id}/bearbeiten?year_id={SY}")
    assert r.status_code == 200
    assert 'name="mitglied"' not in r.text
    assert "Anker" in r.text
    assert "Override" in r.text
    zeile_override = r.text.split("Override")[1].split("</div>")[0]
    assert "Ausnahme" in zeile_override

    vor = len(session.exec(select(TraineeClassMembership)).all())
    r = client.post(
        f"/klassen/{cls.id}",
        data={
            "name": "FISI 2. LJ",
            "berufsschule": "JD Schule",
            "unterrichts_typ": "BLOCK_FEST",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    session.expire_all()
    nach = len(session.exec(select(TraineeClassMembership)).all())
    assert nach == vor


# ── (e) /daten/ausnahmen-loeschen: admin loescht alles, orga -> 403 ───────

def test_ausnahmen_loeschen_als_admin_und_403_fuer_orga(client, session: Session, monkeypatch):
    _add_year(session)
    k1 = _add_class(session, "FISI 1. LJ")
    t = Trainee(vorname="Del", nachname="Etus", rolle=TraineeRolle.AZUBI, klasse_id=k1.id)
    session.add(t)
    session.commit()
    session.add(TraineeClassMembership(trainee_id=t.id, schoolyear_id=SY, klasse_id=k1.id))
    session.commit()

    _login(client, monkeypatch, "orga")
    r = client.post(
        "/daten/ausnahmen-loeschen",
        data={"bestaetigt": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 403

    session.expire_all()
    assert len(session.exec(select(TraineeClassMembership)).all()) == 1

    _login(client, monkeypatch, "admin")
    r = client.post(
        "/daten/ausnahmen-loeschen",
        data={"bestaetigt": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" not in r.headers["location"]

    session.expire_all()
    assert session.exec(select(TraineeClassMembership)).all() == []
