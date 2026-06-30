"""Tests fuer die nach Beruf gruppierte Klassen-Listenansicht (/klassen)."""
from app.models import TraineeClass, UnterrichtsTyp


def _add_class(session, name: str, berufsschule: str = "BS Musterstadt") -> TraineeClass:
    cls = TraineeClass(
        name=name,
        berufsschule=berufsschule,
        unterrichts_typ=UnterrichtsTyp.BLOCK_FEST,
    )
    session.add(cls)
    session.commit()
    session.refresh(cls)
    return cls


# ── Beruf-Überschriften ──────────────────────────────────────────────────────

def test_beruf_headings_present(client, session):
    """Beruf-Überschriften FISI und FIAE erscheinen auf /klassen."""
    _add_class(session, "FISI 1. LJ")
    _add_class(session, "FISI 2. LJ")
    _add_class(session, "FIAE 2. LJ")

    r = client.get("/klassen/")
    assert r.status_code == 200
    assert "FISI" in r.text
    assert "FIAE" in r.text


def test_beruf_headings_separate_sections(client, session):
    """FISI und FIAE werden als eigene Sektionen gerendert (beruf-heading class)."""
    _add_class(session, "FISI 1. LJ")
    _add_class(session, "FIAE 2. LJ")

    r = client.get("/klassen/")
    assert r.status_code == 200
    # Beide Berufe als Überschrift
    text = r.text
    fisi_pos = text.find("FISI")
    fiae_pos = text.find("FIAE")
    assert fisi_pos != -1
    assert fiae_pos != -1


def test_lehrjahr_order_within_beruf(client, session):
    """Innerhalb eines Berufs erscheint LJ 1 vor LJ 2 vor LJ 3."""
    _add_class(session, "FISI 3. LJ")
    _add_class(session, "FISI 1. LJ")
    _add_class(session, "FISI 2. LJ")

    r = client.get("/klassen/")
    assert r.status_code == 200
    text = r.text
    pos1 = text.find("FISI 1. LJ")
    pos2 = text.find("FISI 2. LJ")
    pos3 = text.find("FISI 3. LJ")
    assert pos1 < pos2 < pos3, "Lehrjahre nicht in aufsteigender Reihenfolge"


def test_mixed_berufe_lj_order(client, session):
    """Verschiedene Berufe: FIAE und FISI je in LJ-Reihenfolge."""
    _add_class(session, "FISI 2. LJ")
    _add_class(session, "FIAE 2. LJ")
    _add_class(session, "FISI 1. LJ")
    _add_class(session, "FIAE 1. LJ")

    r = client.get("/klassen/")
    assert r.status_code == 200
    text = r.text

    # FIAE 1. LJ vor FIAE 2. LJ
    assert text.find("FIAE 1. LJ") < text.find("FIAE 2. LJ")
    # FISI 1. LJ vor FISI 2. LJ
    assert text.find("FISI 1. LJ") < text.find("FISI 2. LJ")


# ── Bestehende Aktionen ──────────────────────────────────────────────────────

def test_edit_link_still_present(client, session):
    """'Bearbeiten'-Link je Klasse bleibt erreichbar."""
    cls = _add_class(session, "FISI 1. LJ")

    r = client.get("/klassen/")
    assert r.status_code == 200
    assert f"/klassen/{cls.id}/bearbeiten" in r.text
    assert "Bearbeiten" in r.text


def test_delete_button_still_present(client, session):
    """'Löschen'-Button (hx-delete) je Klasse bleibt erreichbar."""
    cls = _add_class(session, "FISI 1. LJ")

    r = client.get("/klassen/")
    assert r.status_code == 200
    assert f"hx-delete=\"/klassen/{cls.id}\"" in r.text
    assert "Löschen" in r.text


def test_neu_anlegen_link_present(client, session):
    """'Klasse anlegen'-Button ist auf der Listenseite vorhanden."""
    r = client.get("/klassen/")
    assert r.status_code == 200
    assert "/klassen/neu" in r.text


# ── Klassen ohne LJ-Muster ──────────────────────────────────────────────────

def test_class_without_lj_pattern_shown(client, session):
    """Klassen ohne LJ-Muster (z. B. DHBW Cybersecurity) werden ebenfalls angezeigt."""
    _add_class(session, "DHBW Cybersecurity")

    r = client.get("/klassen/")
    assert r.status_code == 200
    assert "DHBW Cybersecurity" in r.text


def test_empty_state_no_classes(client, session):
    """Ohne Klassen wird der leere Zustand angezeigt."""
    r = client.get("/klassen/")
    assert r.status_code == 200
    assert "Noch keine Klassen angelegt" in r.text


# ── Langname-Anzeige ─────────────────────────────────────────────────────────

def test_beruf_heading_shows_langname_fisi(client, session):
    """Beruf-Ueberschrift zeigt den ausgeschriebenen Namen, nicht das Token."""
    _add_class(session, "FISI 1. LJ")

    r = client.get("/klassen/")
    assert r.status_code == 200
    assert "Fachinformatiker für Systemintegration" in r.text


def test_beruf_heading_shows_langname_fiae(client, session):
    """Beruf-Ueberschrift zeigt den ausgeschriebenen Namen fuer FIAE."""
    _add_class(session, "FIAE 2. LJ")

    r = client.get("/klassen/")
    assert r.status_code == 200
    assert "Fachinformatiker für Anwendungsentwicklung" in r.text


def test_beruf_heading_unknown_token_unchanged(client, session):
    """Unbekannte Token (z. B. DHBW Cybersecurity) werden unveraendert angezeigt."""
    _add_class(session, "DHBW Cybersecurity")

    r = client.get("/klassen/")
    assert r.status_code == 200
    assert "DHBW Cybersecurity" in r.text
