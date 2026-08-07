"""Tests fuer die neue Abteilungs-Kachel-Uebersicht (share/abteilungen.html)
und die Abteilungs-Detailseite (GET /mein-plan/{token}/abteilungen/{id})."""
from sqlmodel import Session

from app.models import Department, Trainee, TraineeRolle

TOKEN = "dept-detail-token"


def _setup(session: Session, **dept_kwargs) -> dict:
    defaults = {
        "code": "CP", "name": "Cloud Platform",
        "ansprechpartner": "Max Mustermann",
        "verantwortliche": "ausbilder@firma.de",
        "info_text": "Beschreibung der Abteilung.",
    }
    defaults.update(dept_kwargs)
    dept = Department(**defaults)
    session.add(dept)
    session.flush()
    t = Trainee(vorname="Anton", nachname="Altmann", rolle=TraineeRolle.AZUBI, share_token=TOKEN)
    session.add(t)
    session.commit()
    return {"trainee": t.id, "dept": dept.id}


# ── Kachel-Uebersicht ────────────────────────────────────────────────────────

def test_kachel_zeigt_kategorie_und_ansprechpartner(client, session):
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/abteilungen")
    assert r.status_code == 200
    assert "Max Mustermann" in r.text


def test_kachel_zeigt_verantwortliche_upn_nicht(client, session):
    """Wichtig: Azubis duerfen die Verantwortlichen-UPNs NICHT sehen."""
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/abteilungen")
    assert r.status_code == 200
    assert "ausbilder@firma.de" not in r.text


def test_kachel_zeigt_info_text_nicht(client, session):
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/abteilungen")
    assert r.status_code == 200
    assert "Beschreibung der Abteilung." not in r.text


def test_kachel_verlinkt_auf_detailseite(client, session):
    ids = _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/abteilungen")
    assert r.status_code == 200
    assert f'href="/mein-plan/{TOKEN}/abteilungen/{ids["dept"]}"' in r.text


# ── Detailseite ───────────────────────────────────────────────────────────────

def test_detailseite_zeigt_name_kuerzel_kategorie_ansprechpartner(client, session):
    ids = _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/abteilungen/{ids['dept']}")
    assert r.status_code == 200
    assert "Cloud Platform" in r.text
    assert "CP" in r.text
    assert "Max Mustermann" in r.text


def test_detailseite_rendert_info_text_und_verlinkt_url(client, session):
    ids = _setup(session, info_text="Mehr dazu: https://example.com/plan")
    r = client.get(f"/mein-plan/{TOKEN}/abteilungen/{ids['dept']}")
    assert r.status_code == 200
    assert '<a href="https://example.com/plan"' in r.text
    assert 'rel="noopener noreferrer"' in r.text


def test_detailseite_info_text_wird_nicht_als_html_interpretiert(client, session):
    ids = _setup(session, info_text="<script>alert(1)</script>")
    r = client.get(f"/mein-plan/{TOKEN}/abteilungen/{ids['dept']}")
    assert r.status_code == 200
    assert "<script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_detailseite_zeigt_info_link_button(client, session):
    ids = _setup(session, info_link="https://confluence.example.com/cp")
    r = client.get(f"/mein-plan/{TOKEN}/abteilungen/{ids['dept']}")
    assert r.status_code == 200
    assert 'href="https://confluence.example.com/cp"' in r.text
    assert "Zur Abteilungsseite" in r.text
    assert 'rel="noopener noreferrer"' in r.text
    assert 'target="_blank"' in r.text


def test_detailseite_zurueck_link(client, session):
    ids = _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/abteilungen/{ids['dept']}")
    assert r.status_code == 200
    assert f'href="/mein-plan/{TOKEN}/abteilungen"' in r.text


def test_detailseite_unbekannte_id_ergibt_404(client, session):
    _setup(session)
    r = client.get(f"/mein-plan/{TOKEN}/abteilungen/999999")
    assert r.status_code == 404


def test_detailseite_ungueltiger_token_ergibt_404(client, session):
    ids = _setup(session)
    r = client.get(f"/mein-plan/nicht-existent/abteilungen/{ids['dept']}")
    assert r.status_code == 404
