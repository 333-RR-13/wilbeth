"""Tests fuer die UPN-Pflege-Sammelseite (/trainees/upn-pflege).

(a) GET rendert aktive Trainees + Inputs, inaktive Trainees nicht.
(b) POST speichert UPNs (getrimmt; leerer Wert -> None).
(c) POST aendert nur gesendete Felder, andere Trainees bleiben unveraendert.
(d) list.html enthaelt den Link zur UPN-Pflege-Seite.
(e) detail.html: mit UPN ist die Share-Sektion in <details> eingeklappt, ohne UPN nicht.
Zusaetzlich: Route-Reihenfolge -- GET /trainees/upn-pflege darf nicht von der
/{trainee_id}-Route abgefangen werden (kein 404/422).
"""
from sqlmodel import Session, select

from app.models import Trainee, TraineeRolle


def _trainee(vorname: str, nachname: str = "Test", upn: str | None = None, aktiv: bool = True) -> Trainee:
    return Trainee(vorname=vorname, nachname=nachname, rolle=TraineeRolle.AZUBI, upn=upn, aktiv=aktiv)


# ── Route-Reihenfolge ──────────────────────────────────────────────────────

def test_upn_pflege_route_geht_vor_detail_route(client, session: Session):
    """GET /trainees/upn-pflege liefert 200, nicht die 404/422 der /{trainee_id}-Route."""
    r = client.get("/trainees/upn-pflege")
    assert r.status_code == 200


# ── (a) GET rendert aktive Trainees, inaktive nicht ────────────────────────

def test_get_zeigt_nur_aktive_trainees_mit_inputs(client, session: Session):
    aktiv = _trainee("Aktiver", "Anton", upn="a.anton@grenkeleasing.com")
    inaktiv = _trainee("Inaktiver", "Iwan", aktiv=False)
    session.add_all([aktiv, inaktiv])
    session.commit()

    r = client.get("/trainees/upn-pflege")
    assert r.status_code == 200
    assert f'name="upn_{aktiv.id}"' in r.text
    assert f'value="a.anton@grenkeleasing.com"' in r.text
    assert f'name="upn_{inaktiv.id}"' not in r.text
    assert "Iwan" not in r.text
    assert "Anton" in r.text


def test_get_zeigt_leeres_feld_ohne_upn(client, session: Session):
    t = _trainee("Ohne", "Ursprung")
    session.add(t)
    session.commit()

    r = client.get("/trainees/upn-pflege")
    assert r.status_code == 200
    assert f'name="upn_{t.id}" value=""' in r.text


# ── (b) POST speichert UPNs ─────────────────────────────────────────────────

def test_post_speichert_upn_getrimmt(client, session: Session):
    t = _trainee("Peter", "Post")
    session.add(t)
    session.commit()
    tid = t.id

    r = client.post(
        "/trainees/upn-pflege",
        data={f"upn_{tid}": "  p.post@grenkeleasing.com  "},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/trainees/upn-pflege?msg=updated"

    session.expire_all()
    t2 = session.get(Trainee, tid)
    assert t2.upn == "p.post@grenkeleasing.com"


def test_post_leeres_feld_setzt_upn_auf_none(client, session: Session):
    t = _trainee("Leer", "Loeschen", upn="alt.upn@grenkeleasing.com")
    session.add(t)
    session.commit()
    tid = t.id

    r = client.post(
        "/trainees/upn-pflege",
        data={f"upn_{tid}": ""},
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()
    t2 = session.get(Trainee, tid)
    assert t2.upn is None


# ── (c) POST aendert nur gesendete Felder ──────────────────────────────────

def test_post_aendert_nur_gesendete_felder(client, session: Session):
    t1 = _trainee("Erster", "Eins", upn="alt.eins@grenkeleasing.com")
    t2 = _trainee("Zweiter", "Zwei", upn="alt.zwei@grenkeleasing.com")
    session.add_all([t1, t2])
    session.commit()
    t1_id, t2_id = t1.id, t2.id

    r = client.post(
        "/trainees/upn-pflege",
        data={f"upn_{t1_id}": "neu.eins@grenkeleasing.com"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()
    assert session.get(Trainee, t1_id).upn == "neu.eins@grenkeleasing.com"
    # t2 wurde nicht im Form-Body gesendet -> unveraendert
    assert session.get(Trainee, t2_id).upn == "alt.zwei@grenkeleasing.com"


def test_post_ignoriert_inaktive_trainees(client, session: Session):
    """Ein Feld fuer einen inaktiven Trainee (theoretisch manipuliert) wird ignoriert,
    da die Route nur ueber aktive Trainees iteriert."""
    inaktiv = _trainee("Inaktiv", "Ignoriert", upn="alt@grenkeleasing.com", aktiv=False)
    session.add(inaktiv)
    session.commit()
    tid = inaktiv.id

    r = client.post(
        "/trainees/upn-pflege",
        data={f"upn_{tid}": "sollte-nicht@grenkeleasing.com"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    session.expire_all()
    assert session.get(Trainee, tid).upn == "alt@grenkeleasing.com"


# ── (d) list.html enthaelt den UPN-Pflege-Link ─────────────────────────────

def test_list_enthaelt_upn_pflege_link(client, session: Session):
    r = client.get("/trainees/")
    assert r.status_code == 200
    assert 'href="/trainees/upn-pflege"' in r.text


# ── (e) detail.html: Share-Sektion in <details> nur mit UPN ────────────────

def test_detail_mit_upn_zeigt_details_eingeklappt(client, session: Session):
    t = _trainee("Mit", "Upn", upn="mit.upn@grenkeleasing.com")
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "<details" in r.text
    assert "Share-Link (Fallback" in r.text


def test_detail_ohne_upn_zeigt_keine_details(client, session: Session):
    t = _trainee("Ohne", "Upn")
    session.add(t)
    session.commit()

    r = client.get(f"/trainees/{t.id}")
    assert r.status_code == 200
    assert "<details" not in r.text
