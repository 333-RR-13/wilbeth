"""Tests fuer UI-Konsistenz: die UI zeigt nur Aktionen, die die Rolle
serverseitig auch darf (siehe app/services/auth_service.require_roles).

(a) /einsaetze/: Bulk-Delete-UI ist admin-only (orga sieht sie nicht mehr).
(b) /abteilungen/: Loeschen-Button (DELETE, admin-only) nur fuer admin.
(c) /abteilungen/: Bearbeiten/Anlegen-Buttons (orga/admin) nicht fuer ausbilder.
(d) POST /jahresabschluss/reaktivieren setzt archiviert=False; orga -> 403.
(e) Die "Archivierte Jahre"-Sektion erscheint nur, wenn archivierte Jahre da sind.

Login-Muster: settings.auth_mode per monkeypatch auf "dev" umschalten, dann
POST /auth/dev-login mit rolle=... (siehe app/routers/auth.py).
"""
from sqlmodel import Session

from app.config import settings
from app.models import Department, Schoolyear


def _login(client, monkeypatch, rolle: str) -> None:
    monkeypatch.setattr(settings, "auth_mode", "dev")
    r = client.post("/auth/dev-login", data={"rolle": rolle}, follow_redirects=False)
    assert r.status_code == 303


def _add_year(session: Session, sy_id: str, start_year: int, archiviert: bool = False) -> Schoolyear:
    y = Schoolyear(
        id=sy_id, start_kw=36, start_year=start_year, end_kw=35, end_year=start_year + 1,
        archiviert=archiviert,
    )
    session.add(y)
    session.commit()
    return y


def _add_department(session: Session, code: str = "IT", name: str = "IT-Abteilung") -> Department:
    d = Department(code=code, name=name)
    session.add(d)
    session.commit()
    return d


# ── (a) Bulk-Delete-UI: admin-only ─────────────────────────────────────────

def test_orga_sieht_keine_bulk_delete_ui(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "orga")
    r = client.get("/einsaetze/")
    assert r.status_code == 200
    assert 'id="cb-all"' not in r.text
    assert "Ausgewählte löschen" not in r.text
    assert 'class="row-cb"' not in r.text


def test_ausbilder_sieht_keine_bulk_delete_ui(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/einsaetze/")
    assert r.status_code == 200
    assert 'id="cb-all"' not in r.text
    assert "Ausgewählte löschen" not in r.text


def test_admin_sieht_bulk_delete_ui(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "admin")
    r = client.get("/einsaetze/")
    assert r.status_code == 200
    assert 'id="cb-all"' in r.text
    assert "Ausgewählte löschen" in r.text


# ── (b) Abteilungen: Loeschen-Button admin-only ────────────────────────────

def test_orga_sieht_keinen_loeschen_button_abteilungen(client, session: Session, monkeypatch):
    d = _add_department(session)
    _login(client, monkeypatch, "orga")
    r = client.get("/abteilungen/")
    assert r.status_code == 200
    assert f'hx-delete="/abteilungen/{d.id}"' not in r.text


def test_admin_sieht_loeschen_button_abteilungen(client, session: Session, monkeypatch):
    d = _add_department(session)
    _login(client, monkeypatch, "admin")
    r = client.get("/abteilungen/")
    assert r.status_code == 200
    assert f'hx-delete="/abteilungen/{d.id}"' in r.text


# ── (c) Abteilungen: Bearbeiten/Anlegen nicht fuer ausbilder ───────────────

def test_ausbilder_sieht_keinen_bearbeiten_oder_anlegen_button_abteilungen(
    client, session: Session, monkeypatch,
):
    d = _add_department(session)
    _login(client, monkeypatch, "ausbilder")
    r = client.get("/abteilungen/")
    assert r.status_code == 200
    assert "/abteilungen/neu" not in r.text
    # data-href (Zeilenklick) bleibt bewusst unangetastet (kein Server-Guard-
    # Aequivalent) - geprueft wird nur der sichtbare "Bearbeiten"-Button/-Link
    # (<a href=...>, nicht das data-href des <tr>).
    assert f'<a href="/abteilungen/{d.id}/bearbeiten"' not in r.text
    assert f'hx-delete="/abteilungen/{d.id}"' not in r.text


def test_orga_sieht_bearbeiten_und_anlegen_button_abteilungen(
    client, session: Session, monkeypatch,
):
    d = _add_department(session)
    _login(client, monkeypatch, "orga")
    r = client.get("/abteilungen/")
    assert r.status_code == 200
    assert "/abteilungen/neu" in r.text
    assert f'<a href="/abteilungen/{d.id}/bearbeiten"' in r.text


# ── (d) POST /jahresabschluss/reaktivieren ─────────────────────────────────

def test_admin_reaktiviert_archiviertes_jahr(client, session: Session, monkeypatch):
    y = _add_year(session, "2024-2025", 2024, archiviert=True)
    _login(client, monkeypatch, "admin")

    r = client.post(
        "/jahresabschluss/reaktivieren",
        data={"schoolyear_id": y.id},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=updated" in r.headers["location"]

    session.expire_all()
    updated = session.get(Schoolyear, y.id)
    assert updated.archiviert is False, "Jahr muss nach Reaktivieren archiviert=False sein"

    # Jahr taucht wieder im /overview-Dropdown auf
    r2 = client.get("/overview", params={"schoolyear_id": y.id})
    assert r2.status_code == 200
    assert y.id in r2.text


def test_reaktivieren_unbekanntes_jahr_liefert_fehler(client, session: Session, monkeypatch):
    _login(client, monkeypatch, "admin")
    r = client.post(
        "/jahresabschluss/reaktivieren",
        data={"schoolyear_id": "9999-9999"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "msg=error" in r.headers["location"]


def test_orga_reaktivieren_verboten(client, session: Session, monkeypatch):
    y = _add_year(session, "2024-2025", 2024, archiviert=True)
    _login(client, monkeypatch, "orga")

    r = client.post(
        "/jahresabschluss/reaktivieren",
        data={"schoolyear_id": y.id},
        follow_redirects=False,
    )
    assert r.status_code == 403

    session.expire_all()
    unchanged = session.get(Schoolyear, y.id)
    assert unchanged.archiviert is True, "Orga darf ein Jahr nicht reaktivieren"


# ── (e) Archivierte-Jahre-Sektion nur wenn vorhanden ───────────────────────

def test_archivierte_jahre_sektion_nicht_ohne_archivierte(client, session: Session, monkeypatch):
    _add_year(session, "2025-2026", 2025, archiviert=False)
    _login(client, monkeypatch, "admin")

    r = client.get("/jahresabschluss/")
    assert r.status_code == 200
    assert "Archivierte Jahre" not in r.text


def test_archivierte_jahre_sektion_zeigt_archivierte_jahre(client, session: Session, monkeypatch):
    _add_year(session, "2025-2026", 2025, archiviert=False)
    archiv = _add_year(session, "2023-2024", 2023, archiviert=True)
    _login(client, monkeypatch, "admin")

    r = client.get("/jahresabschluss/")
    assert r.status_code == 200
    assert "Archivierte Jahre" in r.text
    assert archiv.id in r.text
