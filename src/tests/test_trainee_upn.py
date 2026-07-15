"""Tests fuer das UPN-Feld (Entra-Anmeldename) bei Trainees.

(a) POST /trainees/ speichert die UPN (Whitespace wird getrimmt, leer -> None).
(b) POST /trainees/{id} aktualisiert die UPN.
(c) Die Detailseite zeigt die hinterlegte UPN an.
(d) Das Formular ist bei Bearbeitung mit der bestehenden UPN vorbelegt.
"""
from sqlmodel import Session, select

from app.models import Trainee, TraineeRolle

UPN = "vorname.nachname@grenke.de"


def test_create_speichert_upn(client, session: Session):
    """POST /trainees/ speichert das UPN-Feld (getrimmt)."""
    r = client.post(
        "/trainees/",
        data={
            "vorname": "Uwe",
            "nachname": "Upn",
            "rolle": "AZUBI",
            "upn": f"  {UPN}  ",
            "aktiv": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    session.expire_all()
    t = session.exec(select(Trainee).where(Trainee.vorname == "Uwe")).first()
    assert t is not None
    assert t.upn == UPN


def test_create_ohne_upn_speichert_none(client, session: Session):
    """POST /trainees/ ohne UPN (leerer String) speichert None."""
    r = client.post(
        "/trainees/",
        data={
            "vorname": "Nina",
            "nachname": "Nurname",
            "rolle": "AZUBI",
            "aktiv": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    session.expire_all()
    t = session.exec(select(Trainee).where(Trainee.vorname == "Nina")).first()
    assert t is not None
    assert t.upn is None


def test_update_aktualisiert_upn(client, session: Session):
    """POST /trainees/{id} aktualisiert das UPN-Feld."""
    t = Trainee(vorname="Udo", nachname="Update", rolle=TraineeRolle.AZUBI, upn="alt.upn@grenke.de")
    session.add(t)
    session.commit()
    tid = t.id

    r = client.post(
        f"/trainees/{tid}",
        data={
            "vorname": "Udo",
            "nachname": "Update",
            "rolle": "AZUBI",
            "upn": UPN,
            "aktiv": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    session.expire_all()
    t2 = session.get(Trainee, tid)
    assert t2.upn == UPN


def test_update_leere_upn_loescht_wert(client, session: Session):
    """POST /trainees/{id} mit leerem UPN-Feld setzt upn auf None."""
    t = Trainee(vorname="Ella", nachname="Entfernt", rolle=TraineeRolle.AZUBI, upn="alt.upn@grenke.de")
    session.add(t)
    session.commit()
    tid = t.id

    r = client.post(
        f"/trainees/{tid}",
        data={
            "vorname": "Ella",
            "nachname": "Entfernt",
            "rolle": "AZUBI",
            "upn": "",
            "aktiv": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    session.expire_all()
    t2 = session.get(Trainee, tid)
    assert t2.upn is None


def test_detail_zeigt_upn(client, session: Session):
    """Die Detailseite zeigt die hinterlegte UPN an."""
    t = Trainee(vorname="Petra", nachname="Plan", rolle=TraineeRolle.AZUBI, upn=UPN)
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert UPN in r.text
    assert "UPN" in r.text


def test_detail_ohne_upn_zeigt_platzhalter(client, session: Session):
    """Ohne UPN zeigt die Detailseite einen Platzhalter, kein Crash."""
    t = Trainee(vorname="Otto", nachname="Ohne", rolle=TraineeRolle.AZUBI)
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200


def test_form_vorbelegt_mit_upn(client, session: Session):
    """Das Bearbeiten-Formular ist mit der bestehenden UPN vorbelegt."""
    t = Trainee(vorname="Frieda", nachname="Formular", rolle=TraineeRolle.AZUBI, upn=UPN)
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}/bearbeiten")
    assert r.status_code == 200
    assert f'value="{UPN}"' in r.text


def test_form_neu_zeigt_leeres_upn_feld(client, session: Session):
    """Das Neu-Formular zeigt ein leeres UPN-Feld ohne Crash."""
    r = client.get("/trainees/neu")
    assert r.status_code == 200
    assert 'name="upn"' in r.text
