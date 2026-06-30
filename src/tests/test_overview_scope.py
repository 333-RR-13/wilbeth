"""Tests fuer (A) scrollbaren Wochen-Scope und (B) Filter-Persistenz via Cookie.

(A) Scrollbarer Scope: Alle Wochen des Lehrjahrs werden immer gerendert (kein
    Slicing). Der wochen-Parameter steuert die sichtbare Viewport-Breite per
    max-width; die Namensspalte ist sticky.

(B) Filter-Persistenz: Beim GET /overview werden die aktuellen Filter in einen
    Cookie (ov_filters, JSON) geschrieben. Ein naechster GET ohne Query-Parameter
    liest die gespeicherten Werte aus dem Cookie.
"""
import json
from urllib.parse import unquote

import pytest
from sqlmodel import Session


def _decode_cookie(raw: str) -> dict:
    """Dekodiert den vom TestClient gelieferten ov_filters-Cookie zu einem dict.

    Der Router speichert URL-encodetes JSON (percent-encoding), daher reicht
    percent-decoden + json.loads.
    """
    return json.loads(unquote(raw))

from app.models import (
    Schoolyear,
    Trainee,
    TraineeClass,
    TraineeRolle,
    UnterrichtsTyp,
)
from app.utils.kw import iter_schoolyear_weeks

SY = "2025-2026"
# Lehrjahr 2025-2026: KW 36/2025 bis KW 35/2026
START_KW, START_YEAR = 36, 2025
END_KW, END_YEAR = 35, 2026


def _setup_year(session: Session) -> None:
    session.add(Schoolyear(id=SY, start_kw=START_KW, start_year=START_YEAR,
                           end_kw=END_KW, end_year=END_YEAR))
    session.commit()


def _setup_year_with_class(session: Session) -> int:
    """Legt Lehrjahr + Klasse + 2 Trainees an; gibt klasse_id zurueck."""
    session.add(Schoolyear(id=SY, start_kw=START_KW, start_year=START_YEAR,
                           end_kw=END_KW, end_year=END_YEAR))
    klasse = TraineeClass(name="FISI 2. LJ", berufsschule="JD",
                          unterrichts_typ=UnterrichtsTyp.BLOCK_FEST)
    session.add(klasse)
    session.flush()
    session.add_all([
        Trainee(vorname="Anna", nachname="Alpha", rolle=TraineeRolle.AZUBI,
                klasse_id=klasse.id),
        Trainee(vorname="Berta", nachname="Beta", rolle=TraineeRolle.AZUBI,
                klasse_id=klasse.id),
    ])
    session.commit()
    return klasse.id


# ─────────────────────────────────────────────────────────────────────────────
# (A) Scrollbarer Scope – alle Wochen werden gerendert
# ─────────────────────────────────────────────────────────────────────────────

def test_alle_wochen_werden_gerendert(client, session):
    """Ohne wochen-Filter werden exakt alle Wochen des Lehrjahrs gerendert."""
    _setup_year(session)
    expected = sum(1 for _ in iter_schoolyear_weeks(START_KW, START_YEAR, END_KW, END_YEAR))
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    kw_headers = r.text.count("th-kw-num")
    assert kw_headers == expected, (
        f"Erwartet {expected} KW-Header (alle Lehrjahr-Wochen), gefunden: {kw_headers}"
    )


def test_wochen_filter_rendert_trotzdem_alle_wochen(client, session):
    """wochen=4 schraenkt nicht mehr die Anzahl gerenderter Spalten ein.

    Kein Slicing mehr: alle Wochen des Lehrjahrs werden gerendert,
    die sichtbare Breite wird nur per CSS max-width begrenzt.
    """
    _setup_year(session)
    expected = sum(1 for _ in iter_schoolyear_weeks(START_KW, START_YEAR, END_KW, END_YEAR))
    r = client.get("/overview", params={"schoolyear_id": SY, "wochen": "4"})
    assert r.status_code == 200
    kw_headers = r.text.count("th-kw-num")
    assert kw_headers == expected, (
        f"Erwartet alle {expected} KW-Header auch bei wochen=4, gefunden: {kw_headers}"
    )


def test_viewport_max_width_bei_wochen_4(client, session):
    """Bei wochen=4 enthaelt der matrix-scroll-Container eine max-width-Angabe."""
    _setup_year(session)
    r = client.get("/overview", params={"schoolyear_id": SY, "wochen": "4"})
    assert r.status_code == 200
    assert "calc(180px + 4 * 38px)" in r.text, (
        "Viewport-Begrenzungsformel 'calc(180px + 4 * 38px)' muss im HTML stehen"
    )
    assert "max-width" in r.text


def test_kein_viewport_max_width_ohne_wochen(client, session):
    """Ohne wochen-Parameter erscheint keine max-width fuer den Viewport-Container."""
    _setup_year(session)
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    # Kein calc(180px + ... * 38px) – der Container hat kein Limit
    assert "calc(180px +" not in r.text


def test_sticky_name_spalte_im_html(client, session):
    """Die Namensspalte hat position:sticky im eingebetteten Style-Block."""
    _setup_year(session)
    r = client.get("/overview", params={"schoolyear_id": SY})
    assert r.status_code == 200
    # Der <style>-Block im Template definiert position:sticky fuer .matrix-th-name
    assert "position: sticky" in r.text or "position:sticky" in r.text


# ─────────────────────────────────────────────────────────────────────────────
# (B) Filter-Persistenz via Cookie
# ─────────────────────────────────────────────────────────────────────────────

def test_get_setzt_filter_cookie(client, session):
    """GET /overview?klasse_id=X schreibt den ov_filters-Cookie mit klasse_id=X."""
    klasse_id = _setup_year_with_class(session)
    r = client.get("/overview", params={"schoolyear_id": SY, "klasse_id": str(klasse_id)})
    assert r.status_code == 200
    # TestClient speichert Cookies automatisch
    cookie_raw = client.cookies.get("ov_filters")
    assert cookie_raw is not None, "ov_filters-Cookie muss gesetzt sein"
    data = _decode_cookie(cookie_raw)
    assert data["klasse_id"] == str(klasse_id), (
        f"Cookie.klasse_id soll '{klasse_id}' sein, ist: {data.get('klasse_id')}"
    )


def test_cookie_persistiert_klasse_filter(client, session):
    """Nach GET mit ?klasse_id=X liefert ein folgender GET ohne klasse_id denselben Filter."""
    klasse_id = _setup_year_with_class(session)

    # 1. Erster Request setzt den Cookie
    r1 = client.get("/overview", params={"schoolyear_id": SY, "klasse_id": str(klasse_id)})
    assert r1.status_code == 200

    # 2. Zweiter Request ohne klasse_id – Cookie-Jar des TestClient uebertraegt Cookie
    r2 = client.get("/overview", params={"schoolyear_id": SY})
    assert r2.status_code == 200

    # Beide Antworten muessen denselben Trainee-Bestand zeigen
    # (nur die Klasse ist gefiltert, d. h. beide Trainees der Klasse erscheinen)
    assert "Alpha" in r2.text, "Trainee Alpha muss via Cookie-Filter sichtbar sein"
    assert "Beta" in r2.text, "Trainee Beta muss via Cookie-Filter sichtbar sein"

    # Cookie muss weiterhin klasse_id enthalten
    cookie_raw = client.cookies.get("ov_filters")
    assert cookie_raw is not None
    data = _decode_cookie(cookie_raw)
    assert data["klasse_id"] == str(klasse_id)


def test_query_param_hat_vorrang_vor_cookie(client, session):
    """Wenn ein Query-Param vorhanden ist (auch leer), hat er Vorrang vor dem Cookie."""
    klasse_id = _setup_year_with_class(session)

    # Cookie setzen mit klasse_id=X
    client.get("/overview", params={"schoolyear_id": SY, "klasse_id": str(klasse_id)})

    # Explizites klasse_id="" im Query-Param => alle Klassen (kein Filter)
    r = client.get("/overview", params={"schoolyear_id": SY, "klasse_id": ""})
    assert r.status_code == 200
    # Ohne Filter muessen ALLE Trainees erscheinen (auch wenn Cookie X hatte)
    assert "Alpha" in r.text
    assert "Beta" in r.text

    # Cookie wurde mit leerem klasse_id ueberschrieben
    cookie_raw = client.cookies.get("ov_filters")
    assert cookie_raw is not None
    data = _decode_cookie(cookie_raw)
    assert data["klasse_id"] == "", "Cookie soll leeres klasse_id speichern wenn Param=leer"


def test_wochen_cookie_persistenz(client, session):
    """wochen=8 wird via Cookie gespeichert und beim naechsten Request ohne wochen-Param genutzt."""
    _setup_year(session)

    # Setze wochen=8
    r1 = client.get("/overview", params={"schoolyear_id": SY, "wochen": "8"})
    assert r1.status_code == 200

    # Folgender Request ohne wochen: Cookie-Wert soll angewendet werden
    r2 = client.get("/overview", params={"schoolyear_id": SY})
    assert r2.status_code == 200
    # Viewport-max-width fuer n=8 muss erscheinen
    assert "calc(180px + 8 * 38px)" in r2.text, (
        "Viewport fuer wochen=8 aus Cookie soll im HTML erscheinen"
    )

    # Cookie muss wochen=8 enthalten
    cookie_raw = client.cookies.get("ov_filters")
    assert cookie_raw is not None
    data = _decode_cookie(cookie_raw)
    assert data["wochen"] == "8"
